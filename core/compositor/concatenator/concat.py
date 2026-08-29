"""core.compositor.concatenator.concat — 纯拼接 + 字幕 clip 解析（v5.0 Batch 4 / 4.3 拆分）

ConcatMixin：concat_videos / 位置解析 / SRT→TextClip / 时长 / ffmpeg；
模块级常量 _AUDIO_CODEC.._VIDEO_FPS 供 audio_overlay 复用。"""
import logging
import os
import shutil
import subprocess
import re as _re
from typing import List, Optional

import srt as srt_lib
from moviepy import VideoFileClip, concatenate_videoclips

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)


# ── 视频输出常量（对齐 MoneyPrinterTurbo，确保播放器兼容性）──
_AUDIO_CODEC = "aac"
_AUDIO_BITRATE = "192k"
_AUDIO_FPS = 44100
_VIDEO_FPS = 30

class ConcatMixin:
    """纯拼接与字幕 clip 解析方法，v5.0 Batch 4（4.3）拆分。"""

    @staticmethod
    def concat_videos(video_paths: List[str], output_path: str) -> str:
        """纯视频拼接（无音频处理）。

        Args:
            video_paths: 视频文件路径列表
            output_path: 输出文件路径

        Returns:
            输出文件路径
        """
        logger.info(f"[Compositor] Concatenating {len(video_paths)} videos → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not video_paths:
            raise RuntimeError("No videos to concatenate")

        if len(video_paths) == 1:
            shutil.copy2(video_paths[0], output_path)
            logger.info("[Compositor] Single video, copied directly")
            return output_path

        clips = [VideoFileClip(p) for p in video_paths]
        # L7: 统一缩放到第一个视频的分辨率，避免 compose 模式 pad 黑边
        target_w, target_h = clips[0].w, clips[0].h
        resized_clips = []
        for c in clips:
            if c.w != target_w or c.h != target_h:
                resized_clips.append(c.resized((target_w, target_h)))
            else:
                resized_clips.append(c)
        final = None
        try:
            final = concatenate_videoclips(resized_clips, method="compose")
            final.write_videofile(
                output_path,
                codec="libx264",
                audio_codec=_AUDIO_CODEC,
                audio_bitrate=_AUDIO_BITRATE,
                audio_fps=_AUDIO_FPS,
                fps=_VIDEO_FPS,
                logger="bar",
            )
        finally:
            # P6: 关闭所有资源（clips + resized_clips + final）
            # 注意：不要用 `if c not in clips` 来去重 —— moviepy 2.x 的
            # Clip.__eq__ 逐帧比较，write_videofile 后 readers 处于已消费
            # 状态会抛 AttributeError。close() 本身是幂等的，直接全量关闭。
            for c in clips:
                try:
                    c.close()
                except Exception:
                    pass
            for c in resized_clips:
                try:
                    c.close()
                except Exception:
                    pass
            if final is not None:
                try:
                    final.close()
                except Exception:
                    pass

        logger.info(f"[Compositor] Concatenation complete: {output_path}")
        return output_path

    @staticmethod
    def _resolve_subtitle_position(
        pos, default=("center", "bottom"), video_height: int = 0, video_width: int = 1920,
    ) -> tuple:
        """将字幕位置配置归一化为 (horizontal, vertical) 元组。

        支持格式：
          - 标准四角: "top-left", "top-right", "bottom-left", "bottom-right"
          - 偏移: "bottom-80", "top+20", "left+10", "right-30"
          - 百分比: ("50%", "30%")
          - 像素坐标: ("center", 200)
          - 传统: ("center", "bottom"), ("left", "top")
          - 纯字符串: "center", "top", "bottom", "top-left" 等

        复用 SubtitleGenerator.resolve_position 的核心逻辑。
        """
        from core.audio.subtitle import SubtitleGenerator
        return SubtitleGenerator.resolve_position(
            pos, video_width or 1920, video_height or 1080,
        )

    @staticmethod
    def _shape_bidi_text(text: str) -> str:
        """阿拉伯文字母连写 + 双向重排（Pillow/moviepy 不做复杂文本排版，需手动处理）。

        非阿拉伯文文本原样返回；多行文本逐行处理，保留行序。
        """
        from core.audio.voices import _ARABIC_RE

        if not _ARABIC_RE.search(text):
            return text

        import arabic_reshaper
        from bidi.algorithm import get_display

        lines = text.split("\n")
        return "\n".join(get_display(arabic_reshaper.reshape(line)) for line in lines)

    @staticmethod
    def _parse_srt_to_clips(
        srt_path: str,
        subtitle_style: SubtitleStyle,
        video_width: int,
        video_height: int = 0,
        video_duration: float = 0.0,
        subtitle_styles: Optional[list] = None,
    ) -> list:
        """逐条解析 SRT，返回 TextClip 列表（支持多行自动换行 + 逐条样式覆盖）。

        Args:
            srt_path: SRT 文件路径。
            subtitle_style: 全局字幕样式（作为默认值/回退）。
            video_width: 视频宽度。
            video_height: 视频高度。
            video_duration: 视频总时长（用于钳位）。
            subtitle_styles: 逐条样式列表（Phase 2：LLM 生成），
                每项含 index, position, color, fontsize。
                未指定的字段回退到 subtitle_style 的全局值。
        """
        from moviepy import TextClip as MpTextClip
        from core.config import resolve_font_path, DEFAULT_ARABIC_FONT
        from core.audio.subtitle import SubtitleGenerator
        from core.audio.voices import _ARABIC_RE

        font_path = resolve_font_path(subtitle_style.font)
        # 项目内置字体均不含阿拉伯语字形；配置的字体若不支持阿拉伯文会渲染为方块（tofu）。
        # 逐条按文本内容检测并强制回退到内置阿拉伯语字体，而非依赖用户手填正确字体名。
        arabic_font_path = resolve_font_path(DEFAULT_ARABIC_FONT)

        # 兼容旧格式 bg_color 字符串
        bg = subtitle_style.bg_color
        if isinstance(bg, str):
            if "@" in bg:
                parts = bg.split("@", 1)
                rgb = {"black": (0, 0, 0), "white": (255, 255, 255)}.get(parts[0].strip().lower(), (0, 0, 0))
                bg = (*rgb, int(float(parts[1]) * 255))
            else:
                bg = (0, 0, 0, 128)

        # 构建逐条样式查找表
        style_map: dict[int, dict] = {}
        if subtitle_styles:
            for s in subtitle_styles:
                idx = s.get("index", 0)
                if idx > 0:
                    style_map[idx] = s

        # 根据视频宽度动态计算每行最大字符数（与 subtitle.py 一致）
        available_w = video_width - 40

        # 位置冲突时的备选位置池（循环取用，确保重叠字幕不在同一位置）
        _FALLBACK_POSITIONS = [
            ("center", "top+80"),
            ("center", "center"),
            ("center", "bottom-100"),
            ("left", "center"),
            ("right", "center"),
            ("left", "top+60"),
            ("right", "bottom-120"),
            ("center", "top+120"),
            ("left", "bottom-80"),
            ("right", "top+80"),
        ]

        subs_clips = []
        _clip_registry: list[tuple[float, float, tuple]] = []  # (start, end, position)
        with open(srt_path, "r", encoding="utf-8") as f:
            for sub in srt_lib.parse(f):
                txt = sub.content
                start_s = sub.start.total_seconds()
                end_s = sub.end.total_seconds()
                dur = end_s - start_s
                idx = sub.index

                # ═ 逐条样式覆盖 ═
                entry_style = style_map.get(idx, {})
                fs = entry_style.get("fontsize", subtitle_style.fontsize)
                color = entry_style.get("color", subtitle_style.color)
                pos = entry_style.get("position", subtitle_style.position)

                # 每行字符数随字号动态调整
                cjk_max_chars = max(8, available_w // fs) if fs > 0 else 14

                # 长文本自动拆为多行，避免单行溢出屏幕
                wrapped = SubtitleGenerator._split_long_text(txt, cjk_max_chars)
                wrapped = VideoConcatenator._shape_bidi_text(wrapped)
                entry_font = arabic_font_path if _ARABIC_RE.search(txt) else font_path

                clip = MpTextClip(
                    text=wrapped,
                    font=entry_font,
                    font_size=fs,
                    color=color,
                    stroke_color=subtitle_style.stroke_color,
                    stroke_width=subtitle_style.stroke_width,
                    bg_color=bg,
                    method="caption",
                    size=(available_w, None),
                    text_align="center",
                )
                # M10: 钳位字幕结束时间不超过视频时长
                if video_duration > 0:
                    end_s = min(end_s, video_duration - 0.01)
                    if end_s <= start_s:
                        continue
                    dur = end_s - start_s

                clip = (
                    clip.with_start(start_s)
                    .with_end(end_s)
                    .with_duration(dur)
                )
                pos_resolved = VideoConcatenator._resolve_subtitle_position(
                    pos, video_height=video_height, video_width=video_width,
                )
                h_part, v_part = pos_resolved
                # clamp horizontal pixel: keep text box (width=available_w) within frame
                if isinstance(h_part, (int, float)):
                    max_x = video_width - available_w
                    h_part = max(20, min(h_part, max(20, max_x)))
                # clamp vertical pixel: ~100px safe zone at bottom for 2-line text
                if isinstance(v_part, (int, float)):
                    v_part = max(20, min(v_part, video_height - 100))
                pos_tuple = (h_part, v_part)

                # ── 位置去重：与现有字幕时间重叠且位置相同 → 自动错开 ──
                for es, ee, ep in _clip_registry:
                    if start_s < ee and es < end_s and ep == pos_tuple:
                        for alt_pos in _FALLBACK_POSITIONS:
                            alt_resolved = VideoConcatenator._resolve_subtitle_position(
                                alt_pos, video_height=video_height, video_width=video_width,
                            )
                            if isinstance(alt_resolved[0], (int, float)):
                                max_x = video_width - available_w
                                alt_resolved = (max(20, min(alt_resolved[0], max(20, max_x))), alt_resolved[1])
                            if isinstance(alt_resolved[1], (int, float)):
                                alt_resolved = (alt_resolved[0], max(20, min(alt_resolved[1], video_height - 100)))
                            conflict = any(
                                start_s < ee2 and es2 < end_s and alt_resolved == ep2
                                for es2, ee2, ep2 in _clip_registry
                            )
                            if not conflict:
                                pos_tuple = alt_resolved
                                break
                        break

                clip = clip.with_position(pos_tuple)
                _clip_registry.append((start_s, end_s, pos_tuple))
                subs_clips.append(clip)
        return subs_clips

    @staticmethod
    def _get_duration(path: str) -> float:
        """用 ffprobe 获取媒体文件时长（秒）。"""
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=15,
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    @staticmethod
    def _run_ffmpeg(cmd: list, desc: str = "") -> None:
        """执行 ffmpeg 命令，失败时抛 RuntimeError。"""
        logger.info(f"[Compositor] ffmpeg: {desc}")
        try:
            r = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=600,
            )
            if r.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg {desc} failed (code {r.returncode}): "
                    f"{r.stderr[:500]}"
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ffmpeg {desc} timed out")
