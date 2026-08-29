"""core.audio.subtitle.renderer — moviepy 字幕叠加（v5.0 Batch 4 / 4.3 拆分）

SubtitleRenderMixin：位置解析 + SubtitlesClip 叠加渲染；全部为 @staticmethod。"""
import logging
import os
import re as _re

from moviepy import CompositeVideoClip, VideoFileClip
from moviepy.video.tools.subtitles import SubtitlesClip

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)


class SubtitleRenderMixin:
    """moviepy 字幕叠加方法，v5.0 Batch 4（4.3）拆分。"""

    @staticmethod
    def resolve_position(
        pos,
        video_width: int,
        video_height: int,
        safe_margin_x: int = 40,
        safe_margin_y: int = 80,
    ) -> tuple:
        """将各种格式的字幕位置解析为 moviepy (h, v) 坐标。

        支持格式：
          - 标准: ("center", "bottom"), ("left", "top"), ("right", "center")
          - 偏移: ("center", "bottom-80"), ("left+20", "top+10"), ("right-30", "bottom-50")
          - 百分比: ("50%", "30%") — 表示水平 50%, 垂直 30%
          - 像素坐标: ("center", 200) — 垂直 200px
          - 四角: "top-left", "top-right", "bottom-left", "bottom-right"
          - 纯字符串: "center", "top", "bottom", "top-left" 等

        Args:
            safe_margin_x: 水平方向像素边界留白，防止大字号字幕溢出。
            safe_margin_y: 垂直方向像素边界留白。
        """
        default = ("center", "bottom")

        # ── 字符串格式（如 "top-left", "center"）──
        if isinstance(pos, str):
            p = pos.strip().lower()
            corner_map = {
                "top-left": ("left", "top"), "top-right": ("right", "top"),
                "bottom-left": ("left", "bottom"), "bottom-right": ("right", "bottom"),
                "center": ("center", "center"), "middle": ("center", "center"),
                "top": ("center", "top"), "bottom": ("center", "bottom"),
                "left": ("left", "center"), "right": ("right", "center"),
            }
            if p in corner_map:
                return corner_map[p]
            # 尝试解析 "bottom-80" 纯字符串
            m_bot = _re.match(r'^bottom\s*[-–]\s*(\d+)$', p)
            if m_bot and video_height > 0:
                offset = int(m_bot.group(1))
                return ("center", max(video_height - offset, 0))
            m_top = _re.match(r'^top\s*\+\s*(\d+)$', p)
            if m_top:
                offset = int(m_top.group(1))
                return ("center", offset)
            return default

        # ── 二元组 ──
        if not isinstance(pos, (list, tuple)) or len(pos) != 2:
            return default

        h_raw, v_raw = pos[0], pos[1]

        # 解析水平位置
        def resolve_h(h_val) -> str:
            if isinstance(h_val, (int, float)):
                return h_val
            hs = str(h_val).strip().lower()
            if hs.endswith("%"):
                pct = float(hs.replace("%", ""))
                return int(video_width * pct / 100)
            # left+N / right-N
            m_l = _re.match(r'^left\s*\+\s*(\d+)$', hs)
            if m_l:
                return int(m_l.group(1))
            m_r = _re.match(r'^right\s*[-–]\s*(\d+)$', hs)
            if m_r:
                return max(video_width - int(m_r.group(1)), 0)
            if hs in ("left", "right", "center"):
                return hs
            return "center"

        def resolve_v(v_val) -> str:
            if isinstance(v_val, (int, float)):
                return v_val
            vs = str(v_val).strip().lower()
            if vs.endswith("%"):
                pct = float(vs.replace("%", ""))
                return int(video_height * pct / 100)
            m_bot = _re.match(r'^bottom\s*[-–]\s*(\d+)$', vs)
            if m_bot and video_height > 0:
                offset = int(m_bot.group(1))
                return max(video_height - offset, 0)
            m_top = _re.match(r'^top\s*\+\s*(\d+)$', vs)
            if m_top:
                return int(m_top.group(1))
            if vs in ("top", "bottom", "center"):
                return vs
            return "bottom"

        h_resolved = resolve_h(h_raw)
        v_resolved = resolve_v(v_raw)

        # safe-margin clamping for pixel positions
        if isinstance(h_resolved, (int, float)):
            h_resolved = max(safe_margin_x, min(h_resolved, video_width - safe_margin_x))
        if isinstance(v_resolved, (int, float)):
            v_resolved = max(safe_margin_y, min(v_resolved, video_height - safe_margin_y))

        return (h_resolved, v_resolved)

    @staticmethod
    def overlay_subtitles_to_video(
        video_path: str,
        srt_path: str,
        style: SubtitleStyle,
        output_path: str,
    ) -> str:
        """将 SRT 字幕叠加到视频文件。

        Args:
            video_path: 输入视频路径
            srt_path: SRT 字幕文件路径
            style: SubtitleStyle 字幕样式配置
            output_path: 输出视频路径

        Returns:
            输出视频路径
        """
        logger.info(f"[Subtitle] Overlaying subtitles: {video_path} + {srt_path} → {output_path}")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            video_clip = VideoFileClip(video_path)

            # 解析字体路径
            from core.config import resolve_font_path
            font_path = resolve_font_path(style.font)

            # 兼容旧格式 bg_color 字符串（如 "black@0.5"）
            bg = style.bg_color
            if isinstance(bg, str):
                if "@" in bg:
                    parts = bg.split("@", 1)
                    rgb = {"black": (0, 0, 0), "white": (255, 255, 255)}.get(parts[0].strip().lower(), (0, 0, 0))
                    bg = (*rgb, int(float(parts[1]) * 255))
                else:
                    bg = (0, 0, 0, 128)

            # 根据视频宽度动态计算每行最大字符数
            available_w = video_clip.w - 40
            # 粗略估算：CJK 字符宽 ≈ fontsize，latin 字符宽 ≈ fontsize * 0.5
            cjk_max_chars = max(8, available_w // style.fontsize)

            # moviepy 的 SubtitlesClip 读取 SRT 文件
            def make_text_clip(txt):
                from moviepy import TextClip
                # 长文本自动拆为多行（宽度感知：参考中文短字幕规范，适配所有语言）
                wrapped = SubtitleGenerator._split_long_text(
                    txt, cjk_max_chars,
                    video_width=video_clip.w, fontsize=style.fontsize,
                )
                return TextClip(
                    text=wrapped,
                    font=font_path,
                    font_size=style.fontsize,
                    color=style.color,
                    stroke_color=style.stroke_color,
                    stroke_width=style.stroke_width,
                    bg_color=bg,
                    method="caption",
                    size=(available_w, None),
                    text_align="center",
                )

            subtitles_clip = SubtitlesClip(srt_path, make_textclip=make_text_clip)

            # 使用新的解析器支持任意位置
            position = SubtitleGenerator.resolve_position(
                style.position, video_clip.w, video_clip.h
            )

            final = CompositeVideoClip([video_clip, subtitles_clip.with_position(position)])
            final.write_videofile(
                output_path,
                codec="libx264",
                audio_codec="aac",
                audio_bitrate="192k",
                audio_fps=44100,
                fps=30,
                logger="bar",
            )

            video_clip.close()
            final.close()

            logger.info(f"[Subtitle] Overlay complete: {output_path}")
            return output_path

        except Exception as e:
            # P10: 不再静默降级复制原视频，向上抛异常让调用方决定
            logger.error(f"[Subtitle] Overlay failed: {e}")
            raise
