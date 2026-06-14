"""core.audio.subtitle — SRT 字幕生成 + moviepy 叠加

将 edge_tts SubMaker cues 转换为 SRT 格式，并通过 moviepy SubtitlesClip 叠加到视频。
"""

import logging
import os
from typing import List, Optional, Tuple

import srt
from moviepy import VideoFileClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)


class SubtitleGenerator:
    """字幕生成器：cues → SRT + moviepy 叠加。"""

    @staticmethod
    def cue_to_srt_time(seconds: float) -> str:
        """将秒数转换为 SRT 时间格式 HH:MM:SS,mmm。"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def cues_to_srt(cues: list, output_path: str) -> str:
        """将 edge_tts SubMaker cues 转换为 SRT 文件。

        edge_tts SubMaker 的 generate_subs() 方法返回 WebVTT 格式字符串，
        这里将其解析并转为标准 SRT 格式。

        Args:
            cues: edge_tts SubMaker 实例（调用 generate_subs()）
            output_path: SRT 文件输出路径

        Returns:
            SRT 文件路径
        """
        logger.info(f"[Subtitle] Converting cues to SRT: {output_path}")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # edge_tts SubMaker.generate_subs() 返回 WebVTT 格式
        # 我们手动解析 cues 来构建 SRT
        if hasattr(cues, "generate_subs"):
            vtt_content = cues.generate_subs()
            subtitles = SubtitleGenerator._parse_vtt_to_srt(vtt_content)
        else:
            # 空 cues 或 dict 类型（SilentTTSEngine）
            subtitles = []

        srt_content = srt.compose(subtitles)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"[Subtitle] SRT saved: {output_path} ({len(subtitles)} entries)")
        return output_path

    @staticmethod
    def _parse_vtt_to_srt(vtt_content: str) -> list:
        """解析 WebVTT 内容为 srt.Subtitle 列表。"""
        subtitles = []
        lines = vtt_content.strip().split("\n")
        idx = 0

        # 跳过 WEBVTT 头部
        i = 0
        while i < len(lines) and (lines[i].strip().startswith("WEBVTT") or lines[i].strip() == ""):
            i += 1

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # 时间轴行：00:00:00.000 --> 00:00:02.500
            if "-->" in line:
                parts = line.split("-->")
                if len(parts) == 2:
                    start_str = parts[0].strip().replace(".", ",")
                    end_str = parts[1].strip().replace(".", ",")

                    # 收集文本行
                    text_lines = []
                    i += 1
                    while i < len(lines) and lines[i].strip():
                        text_lines.append(lines[i].strip())
                        i += 1

                    text = " ".join(text_lines)
                    if text:
                        idx += 1
                        # 解析时间
                        start = SubtitleGenerator._parse_time(start_str)
                        end = SubtitleGenerator._parse_time(end_str)
                        subtitles.append(srt.Subtitle(index=idx, start=start, end=end, content=text))
                    continue
            i += 1

        return subtitles

    @staticmethod
    def _parse_time(time_str: str) -> "datetime.timedelta":
        """解析 SRT/VTT 时间字符串为 timedelta。"""
        import datetime

        time_str = time_str.strip()
        # 支持 HH:MM:SS,mmm 或 HH:MM:SS.mmm 或 MM:SS.mmm 格式
        if "," in time_str:
            time_str = time_str.replace(",", ".")
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            total_seconds = int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            total_seconds = int(m) * 60 + float(s)
        else:
            total_seconds = float(parts[0])

        return datetime.timedelta(seconds=total_seconds)

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

            # moviepy 的 SubtitlesClip 读取 SRT 文件
            def make_text_clip(txt):
                from moviepy import TextClip
                return TextClip(
                    text=txt,
                    font=style.font,
                    font_size=style.fontsize,
                    color=style.color,
                    stroke_color=style.stroke_color,
                    stroke_width=style.stroke_width,
                    bg_color=style.bg_color,
                    method="label",
                    size=(video_clip.w - 40, None),
                    text_align="center",
                )

            subtitles_clip = SubtitlesClip(srt_path, make_text_clip)

            # 根据 position 设置字幕位置
            pos = style.position
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                position = pos
            else:
                position = ("center", "bottom")

            final = CompositeVideoClip([video_clip, subtitles_clip.with_position(position)])
            final.write_videofile(output_path, logger="bar")

            video_clip.close()
            final.close()

            logger.info(f"[Subtitle] Overlay complete: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"[Subtitle] Overlay failed: {e}, falling back to copy")
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path
