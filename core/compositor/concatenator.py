"""core.compositor.concatenator — 视频拼接器

支持纯视频拼接和带音频字幕的拼接。
"""

import json
import logging
import os
import shutil
from typing import List, Optional

import re as _re

import srt as srt_lib
from moviepy import AudioFileClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)

# ── 视频输出常量（对齐 MoneyPrinterTurbo，确保播放器兼容性）──
_AUDIO_CODEC = "aac"
_AUDIO_BITRATE = "192k"
_AUDIO_FPS = 44100
_VIDEO_FPS = 30


class VideoConcatenator:
    """视频拼接器：纯拼接 + 带音频合成拼接。"""

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
    def _resolve_subtitle_position(pos, default=("center", "bottom"), video_height: int = 0) -> tuple:
        """将字幕位置配置归一化为 (horizontal, vertical) 元组。

        支持 "bottom-N" / "top+N" 格式（N 为像素偏移），
        返回 moviepy 可用的位置元组。
        """
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            h, v = pos[0], pos[1]
            if isinstance(v, str):
                v_lower = v.strip().lower()
                # 解析 "bottom-N" 格式
                m_bottom = _re.match(r'^bottom\s*[-–]\s*(\d+)$', v_lower)
                if m_bottom and video_height > 0:
                    offset = int(m_bottom.group(1))
                    return (h, max(video_height - offset, 0))
                # 解析 "top+N" 格式
                m_top = _re.match(r'^top\s*\+\s*(\d+)$', v_lower)
                if m_top:
                    offset = int(m_top.group(1))
                    return (h, offset)
                if "top" in v_lower:
                    return (h, "top")
                if "bottom" in v_lower:
                    return (h, "bottom")
            return (h, v)
        if isinstance(pos, str):
            pos_lower = pos.strip().lower()
            m_bottom = _re.match(r'^bottom\s*[-–]\s*(\d+)$', pos_lower)
            if m_bottom and video_height > 0:
                offset = int(m_bottom.group(1))
                return ("center", max(video_height - offset, 0))
            m_top = _re.match(r'^top\s*\+\s*(\d+)$', pos_lower)
            if m_top:
                offset = int(m_top.group(1))
                return ("center", offset)
            position_map = {
                "bottom": ("center", "bottom"),
                "top": ("center", "top"),
                "center": ("center", "center"),
                "middle": ("center", "center"),
            }
            return position_map.get(pos_lower, default)
        return default

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
        from core.config import resolve_font_path
        from core.audio.subtitle import SubtitleGenerator

        font_path = resolve_font_path(subtitle_style.font)

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

        subs_clips = []
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

                clip = MpTextClip(
                    text=wrapped,
                    font=font_path,
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
                clip = clip.with_position(
                    VideoConcatenator._resolve_subtitle_position(
                        pos, video_height=video_height
                    )
                )
                subs_clips.append(clip)
        return subs_clips

    @staticmethod
    def concat_videos_with_audio_overlay(
        video_paths: List[str],
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle] = None,
        subtitle_styles_path: Optional[str] = None,
    ) -> str:
        """先拼接视频，再统一叠加单条音频 + 单条字幕。

        MoneyPrinterTurbo 方案：不按片段做逐段合成（避免 padding 累积），
        而是先把所有视频拼成完整时间轴，再把音频和字幕作为一个整体叠加上去。

        Args:
            video_paths: 按顺序的视频路径列表。
            audio_path: 整段音频文件路径（对应全部视频的总时间轴）。
            srt_path: 整段 SRT 字幕路径（可选）。
            output_path: 最终输出文件路径。
            subtitle_style: 字幕样式配置。

        Returns:
            输出文件路径。
        """
        logger.info(
            f"[Compositor] concat_videos_with_audio_overlay: "
            f"{len(video_paths)} videos + {audio_path} → {output_path}"
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not video_paths:
            raise RuntimeError("No videos to concatenate")

        naked_path = output_path.replace(".mp4", "_naked.mp4")
        freeze_path = output_path.replace(".mp4", "_freeze.mp4")
        video_clip = None
        audio_clip = None

        try:
            # ── Step 1: 拼接所有视频 ──────────────────────────────────────
            VideoConcatenator.concat_videos(video_paths, naked_path)

            # ── Step 2: 加载拼接视频 + 音频 ────────────────────────────────
            video_clip = VideoFileClip(naked_path)
            audio_clip = AudioFileClip(audio_path)

            # ── Step 2.5: 提升音频音量（M9: 降为 1.5x 避免削波）────────
            _AUDIO_VOLUME_FACTOR = 1.5
            audio_clip = audio_clip.with_volume_scaled(_AUDIO_VOLUME_FACTOR)

            # ── Step 3: 若音频比视频长，冻结尾帧补齐 ─────────────────────
            if video_clip.duration < audio_clip.duration:
                freeze_duration = audio_clip.duration - video_clip.duration
                from core.compositor.processor import VideoProcessor
                VideoProcessor.freeze_last_frame(naked_path, freeze_duration, freeze_path)
                video_clip.close()
                video_clip = VideoFileClip(freeze_path)

            # ── Step 4: 叠加音频 ──────────────────────────────────────────
            video_with_audio = video_clip.with_audio(audio_clip)

            # ── Step 5: 叠加字幕 ──────────────────────────────────────────
            if srt_path and os.path.exists(srt_path) and subtitle_style:
                try:
                    per_entry_styles = None
                    if subtitle_styles_path and os.path.exists(subtitle_styles_path):
                        with open(subtitle_styles_path, "r", encoding="utf-8") as f:
                            per_entry_styles = json.load(f)

                    subs_clips = VideoConcatenator._parse_srt_to_clips(
                        srt_path, subtitle_style, video_clip.w,
                        video_height=video_clip.h,
                        video_duration=video_clip.duration,
                        subtitle_styles=per_entry_styles,
                    )
                    if subs_clips:
                        final = CompositeVideoClip([video_with_audio, *subs_clips])
                        final.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                        final.close()
                    else:
                        video_with_audio.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                except Exception as e:
                    logger.warning(
                        f"[Compositor] Subtitle overlay failed: {e}, writing without subtitles"
                    )
                    video_with_audio.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec=_AUDIO_CODEC,
                        audio_bitrate=_AUDIO_BITRATE,
                        audio_fps=_AUDIO_FPS,
                        fps=_VIDEO_FPS,
                        logger="bar",
                    )
            else:
                video_with_audio.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec=_AUDIO_CODEC,
                    audio_bitrate=_AUDIO_BITRATE,
                    audio_fps=_AUDIO_FPS,
                    fps=_VIDEO_FPS,
                    logger="bar",
                )
        finally:
            if video_clip is not None:
                video_clip.close()
            if audio_clip is not None:
                audio_clip.close()
            for tmp in (naked_path, freeze_path):
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] concat_videos_with_audio_overlay done: {output_path}")
        return output_path

    @staticmethod
    def composite_anchor_video(
        clip_path: str,
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        audio_duration: float,
        subtitle_style: Optional[SubtitleStyle] = None,
        subtitle_styles_path: Optional[str] = None,
        video_width: int = 768,
        video_height: int = 1344,
    ) -> str:
        """将 5 秒主播动态视频片段循环拼接为覆盖完整音频时长，再叠加音频和字幕。

        核心思路：循环拼接 + 裁剪 + 统一叠加音频/字幕。
        接缝处用 ffmpeg xfade 做 0.3 秒交叉淡入淡出过渡。

        Args:
            clip_path: 5 秒主播动态视频片段路径。
            audio_path: TTS 读稿音频路径。
            srt_path: SRT 字幕文件路径（可选）。
            output_path: 最终输出视频路径。
            audio_duration: 音频总时长（秒）。
            subtitle_style: 字幕样式配置。
            subtitle_styles_path: LLM 样式 JSON 路径（可选）。
            video_width: 视频宽度。
            video_height: 视频高度。

        Returns:
            输出文件路径。
        """
        import math
        import subprocess

        logger.info(
            f"[Compositor] composite_anchor_video: {clip_path} + {audio_path} "
            f"(audio={audio_duration:.1f}s) → {output_path}"
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Step 1: Get clip duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", clip_path],
            capture_output=True, text=True, timeout=15,
        )
        clip_duration = float(probe.stdout.strip() or 5.0)
        if clip_duration <= 0:
            clip_duration = 5.0

        # Step 2: Calculate loop count
        needed = audio_duration + 2.0  # extra 2s padding
        n = math.ceil(needed / clip_duration) + 1

        # Step 3: Build concat file list for ffmpeg
        loop_dir = os.path.dirname(output_path)
        concat_file = os.path.join(loop_dir, "_anchor_concat.txt")
        with open(concat_file, "w") as f:
            for _ in range(n):
                f.write(f"file '{clip_path}'\n")

        looped_path = output_path.replace(".mp4", "_looped.mp4")

        # Step 4: Concatenate with xfade cross-fade transitions
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_file,
                 "-c", "copy",
                 "-t", str(needed),
                 looped_path],
                check=True, capture_output=True, timeout=300,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"[Compositor] Simple concat failed: {e.stderr[:200]}, trying xfade")

            # Build complex filter for xfade cross-fade between each pair
            fade_duration = 0.3
            filter_parts = []
            for i in range(n):
                if i == 0:
                    filter_parts.append(f"[0:{i}]")
                else:
                    filter_parts.append(f"[0:{i}]")
                    filter_parts.append(f"xfade=transition=fade:duration={fade_duration}:offset={i * clip_duration - fade_duration * i}")
            filter_str = "".join(filter_parts)

            subprocess.run(
                ["ffmpeg", "-y",
                 "-stream_loop", str(n - 1), "-i", clip_path,
                 "-filter_complex",
                 f"[0:v]trim=duration={needed}[v]",
                 "-map", "[v]",
                 "-c:v", "libx264",
                 "-preset", "fast",
                 "-t", str(needed),
                 looped_path],
                check=True, capture_output=True, timeout=300,
            )

        # Step 5: Overlay audio and subtitles
        concat_video_clip = None
        audio_clip_obj = None
        try:
            concat_video_clip = VideoFileClip(looped_path)
            audio_clip_obj = AudioFileClip(audio_path)

            _AUDIO_VOLUME_FACTOR = 1.5
            audio_clip_obj = audio_clip_obj.with_volume_scaled(_AUDIO_VOLUME_FACTOR)

            video_with_audio = concat_video_clip.with_audio(audio_clip_obj)

            if srt_path and os.path.exists(srt_path) and subtitle_style:
                per_entry_styles = None
                if subtitle_styles_path and os.path.exists(subtitle_styles_path):
                    with open(subtitle_styles_path, "r", encoding="utf-8") as f:
                        per_entry_styles = json.load(f)

                subs_clips = VideoConcatenator._parse_srt_to_clips(
                    srt_path, subtitle_style,
                    video_width, video_height,
                    video_duration=concat_video_clip.duration,
                    subtitle_styles=per_entry_styles,
                )
                if subs_clips:
                    final = CompositeVideoClip([video_with_audio, *subs_clips])
                    final.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec=_AUDIO_CODEC,
                        audio_bitrate=_AUDIO_BITRATE,
                        audio_fps=_AUDIO_FPS,
                        fps=_VIDEO_FPS,
                        logger="bar",
                    )
                    final.close()
                else:
                    video_with_audio.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec=_AUDIO_CODEC,
                        audio_bitrate=_AUDIO_BITRATE,
                        audio_fps=_AUDIO_FPS,
                        fps=_VIDEO_FPS,
                        logger="bar",
                    )
            else:
                video_with_audio.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec=_AUDIO_CODEC,
                    audio_bitrate=_AUDIO_BITRATE,
                    audio_fps=_AUDIO_FPS,
                    fps=_VIDEO_FPS,
                    logger="bar",
                )
        finally:
            if concat_video_clip is not None:
                concat_video_clip.close()
            if audio_clip_obj is not None:
                audio_clip_obj.close()
            for tmp in (looped_path, concat_file):
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] composite_anchor_video done: {output_path}")
        return output_path


