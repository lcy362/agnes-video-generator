"""core.audio.subtitle — SRT 字幕生成 + moviepy 叠加

将 edge_tts SubMaker cues 转换为 SRT 格式，并通过 moviepy SubtitlesClip 叠加到视频。

v2.1: 支持细粒度字幕分割，避免 5 秒视频只有 1 条字幕的问题。
"""

import datetime
import logging
import os
from typing import List, Optional, Tuple

import srt
from moviepy import VideoFileClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)

# ── 细粒度字幕分割参数 ──
# 每条字幕最大持续时长（秒）
_MAX_SUB_DURATION = 2.5
# 每条字幕最大字符数（中文场景）
_MAX_SUB_CHARS = 18
# 最少字数字幕阈值：如果词级 cues 太少（如只有 3 个 cues for 14s），
# 说明 edge_tts 本身提供的粒度已足够，不需要额外细化（避免空洞字幕）
_MIN_WORD_CUES_FOR_FINE = 6


class SubtitleGenerator:
    """字幕生成器：cues → SRT + moviepy 叠加。"""

    @staticmethod
    def _split_long_text(txt: str, max_chars_per_line: int = 14) -> str:
        """将过长的字幕文本拆分为多行，避免单行溢出屏幕。

        对 CJK 文本按字符数拆分，对非 CJK 文本按单词边界拆分。
        最多拆为 2 行，尽量等长分配。

        Args:
            txt: 原始字幕文本
            max_chars_per_line: 每行最大字符数（CJK）或单词数（非 CJK）

        Returns:
            可能含 \\n 的文本
        """
        if not txt or "\n" in txt:
            return txt

        has_cjk = any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf' for ch in txt)

        if has_cjk:
            if len(txt) <= max_chars_per_line:
                return txt
            # 拆为 2 行，尽量等长
            mid = len(txt) // 2
            # 在中间附近找标点或自然断点
            for offset in range(min(4, mid)):
                for candidate in (mid + offset, mid - offset):
                    if 0 < candidate < len(txt) and txt[candidate - 1] in '，。、；！？,. ;!?':
                        return txt[:candidate] + "\n" + txt[candidate:]
            return txt[:mid] + "\n" + txt[mid:]
        else:
            words = txt.split()
            if len(words) <= max_chars_per_line:
                return txt
            mid = len(words) // 2
            return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])

    @staticmethod
    def cue_to_srt_time(seconds: float) -> str:
        """将秒数转换为 SRT 时间格式 HH:MM:SS,mmm。"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _cue_total_seconds(td) -> float:
        """将 timedelta 转为秒数（兼容 srt.Subtitle 的 start/end 字段）。"""
        if isinstance(td, datetime.timedelta):
            return td.total_seconds()
        return float(td)

    @staticmethod
    def _generate_fine_srt_from_word_cues(
        word_cues: list,
        max_duration: float = _MAX_SUB_DURATION,
        max_chars: int = _MAX_SUB_CHARS,
    ) -> str:
        """从词级 cues 生成细粒度 SRT。

        将 edge_tts SubMaker.cues（词级时间戳列表）分组为短字幕段落，
        每组不超过 max_duration 秒和 max_chars 字符，优先在较长停顿处断开。

        Args:
            word_cues: edge_tts SubMaker.cues 列表（srt.Subtitle 对象）
            max_duration: 每条字幕最大持续时长（秒）
            max_chars: 每条字幕最大字符数

        Returns:
            SRT 格式字符串
        """
        if not word_cues:
            return ""

        # 将 cues 转为 (start_s, end_s, text) 三元组
        items = []
        for cue in word_cues:
            start_s = SubtitleGenerator._cue_total_seconds(cue.start)
            end_s = SubtitleGenerator._cue_total_seconds(cue.end)
            text = cue.content.strip()
            if text:
                items.append((start_s, end_s, text))

        if not items:
            return ""

        # 计算词间停顿（gap），用于决定在哪里断开字幕组
        gaps = []
        for i in range(1, len(items)):
            gap = items[i][0] - items[i - 1][1]
            gaps.append(max(gap, 0.0))

        # 贪心分组：按 max_duration 和 max_chars 约束
        groups = []
        group_start_s = items[0][0]
        group_end_s = items[0][1]
        group_text_parts = [items[0][2]]
        group_chars = len(items[0][2])

        for i in range(1, len(items)):
            s_s, e_s, txt = items[i]
            gap = gaps[i - 1]

            prospective_dur = e_s - group_start_s
            prospective_chars = group_chars + len(txt)

            # 决定是否断开：满足任一条件则断开
            # 1. 持续时长超限
            # 2. 字符数超限
            # 3. 前一个词之间有较大停顿（>0.4s），且当前组已积累了一些内容
            should_break = (
                prospective_dur > max_duration
                or prospective_chars > max_chars
                or (gap > 0.4 and group_chars > 4 and len(items) > 8)
            )

            if should_break and group_text_parts:
                groups.append((group_start_s, group_end_s, "".join(group_text_parts)))
                group_start_s = s_s
                group_end_s = e_s
                group_text_parts = [txt]
                group_chars = len(txt)
            else:
                group_end_s = e_s
                group_text_parts.append(txt)
                group_chars += len(txt)

        # 最后剩余组
        if group_text_parts:
            groups.append((group_start_s, group_end_s, "".join(group_text_parts)))

        # 后处理：合并过短的尾部组
        # 只在合并后不会导致前一组过长时才合并
        while len(groups) >= 2:
            last_dur = groups[-1][1] - groups[-1][0]
            last_chars = len(groups[-1][2])
            prev_dur = groups[-2][1] - groups[-2][0]
            prev_chars = len(groups[-2][2])
            merged_dur = groups[-1][1] - groups[-2][0]
            merged_chars = prev_chars + last_chars
            # 条件：尾部太短 且 合并后不超限
            if (last_dur < 0.8
                    and merged_dur <= max_duration * 1.2
                    and merged_chars <= max_chars * 1.5):
                merged_start = groups[-2][0]
                merged_end = groups[-1][1]
                merged_text = groups[-2][2] + groups[-1][2]
                groups[-2] = (merged_start, merged_end, merged_text)
                groups.pop()
            else:
                break

        # 生成 SRT
        entries = []
        for idx, (s_s, e_s, txt) in enumerate(groups, 1):
            # 确保每组至少 0.3 秒
            if e_s - s_s < 0.3:
                e_s = s_s + 0.3
            # 确保字幕之间不重叠（end 不超过下一个 start）
            if idx < len(groups):
                next_start = groups[idx][0]
                if e_s > next_start:
                    e_s = next_start - 0.05

            start_time = SubtitleGenerator.cue_to_srt_time(s_s)
            end_time = SubtitleGenerator.cue_to_srt_time(e_s)
            entries.append(f"{idx}\n{start_time} --> {end_time}\n{txt}\n")

        return "\n".join(entries)

    @staticmethod
    def cues_to_srt(cues, output_path: str) -> str:
        """将 edge_tts SubMaker cues 转换为 SRT 文件。

        优先使用词级 cues（edge_tts 7.x 的 SubMaker.cues）进行细粒度分割，
        确保每 2-3 秒至少有一条字幕，避免出现 5 秒视频只有 1 条字幕的问题。

        对于 edge_tts 6.x，回退到 WebVTT 解析方式。

        Args:
            cues: edge_tts SubMaker 实例或空 dict
            output_path: SRT 文件输出路径

        Returns:
            SRT 文件路径
        """
        logger.info(f"[Subtitle] Converting cues to SRT: {output_path}")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        srt_content = ""
        subtitles_count = 0
        used_fine_grained = False

        # ── 策略 1: 使用词级 cues 做细粒度 SRT（推荐）──
        # edge_tts 7.x 的 SubMaker.cues 包含 WordBoundary 词级时间戳
        raw_word_cues = getattr(cues, "cues", None)
        if raw_word_cues and isinstance(raw_word_cues, list) and len(raw_word_cues) >= _MIN_WORD_CUES_FOR_FINE:
            try:
                srt_content = SubtitleGenerator._generate_fine_srt_from_word_cues(raw_word_cues)
                if srt_content.strip():
                    subtitles_count = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else (
                        1 if srt_content.strip() else 0
                    )
                    used_fine_grained = True
                    logger.info(f"[Subtitle] Fine-grained SRT generated from {len(raw_word_cues)} word cues")
            except Exception as e:
                logger.warning(f"[Subtitle] Fine-grained SRT generation failed: {e}, falling back")

        # ── 策略 2: 回退到 edge_tts 默认 SRT 生成 ──
        if not srt_content.strip():
            try:
                if hasattr(cues, "get_srt"):
                    srt_content = cues.get_srt()
                    subtitles_count = srt_content.count("\n\n") + 1 if srt_content.strip() else 0
                elif hasattr(cues, "generate_subs"):
                    vtt_content = cues.generate_subs()
                    subtitles = SubtitleGenerator._parse_vtt_to_srt(vtt_content)
                    srt_content = srt.compose(subtitles)
                    subtitles_count = len(subtitles)
                else:
                    subtitles_count = 0
            except Exception as e:
                # edge_tts 7.x + 某些 srt 库版本的 Subtitle 对象结构不兼容
                # (proprietary 字段冲突)，回退到手动从 raw_cues 构造 SRT
                logger.warning(f"[Subtitle] Default SRT generation failed: {e}, "
                               f"falling back to raw cues")
                if raw_word_cues and isinstance(raw_word_cues, list) and len(raw_word_cues) > 0:
                    try:
                        srt_content = SubtitleGenerator._generate_fine_srt_from_word_cues(
                            raw_word_cues,
                            max_duration=10.0,  # 放宽限制，因为这是最后的手段
                            max_chars=60,
                        )
                        if srt_content.strip():
                            subtitles_count = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 1
                            logger.info(f"[Subtitle] Fallback SRT from raw cues: {subtitles_count} entries")
                    except Exception as e2:
                        logger.error(f"[Subtitle] Raw cues fallback also failed: {e2}")
                        subtitles_count = 0
                else:
                    subtitles_count = 0

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        method_tag = "fine-grained" if used_fine_grained else "default"
        logger.info(f"[Subtitle] SRT saved: {output_path} ({subtitles_count} entries, {method_tag})")
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
                # 长文本自动拆为多行
                wrapped = SubtitleGenerator._split_long_text(txt, cjk_max_chars)
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

            # 根据 position 设置字幕位置
            pos = style.position
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                h, v = pos[0], pos[1]
                if isinstance(v, str):
                    v_lower = v.strip().lower()
                    if "top" in v_lower:
                        position = (h, "top")
                    elif "bottom" in v_lower:
                        position = (h, "bottom")
                    else:
                        position = (h, v)
                else:
                    position = (h, v)
            else:
                position = ("center", "bottom")

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
            logger.error(f"[Subtitle] Overlay failed: {e}, falling back to copy")
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path
