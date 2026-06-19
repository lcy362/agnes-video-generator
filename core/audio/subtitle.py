"""core.audio.subtitle — SRT 字幕生成 + moviepy 叠加

将 edge_tts SubMaker cues 转换为 SRT 格式，并通过 moviepy SubtitlesClip 叠加到视频。

v2.1: 支持细粒度字幕分割，避免 5 秒视频只有 1 条字幕的问题。
v3.0: 支持任意位置（四角/百分比/坐标）、逐场景精拆分、突出字幕时⻓加成。
"""

import datetime
import logging
import math
import os
from typing import List, Optional, Tuple

import re as _re
import srt
from moviepy import VideoFileClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)

# ── 细粒度字幕分割参数 ──
# 每条字幕最大持续时长（秒）— v3.0 降至 1.8 以支持更细拆分
_MAX_SUB_DURATION = 1.8
# 每条字幕最大字符数（中文场景）— v3.0 降至 14 以支持更细拆分
_MAX_SUB_CHARS = 14
# 最少字数字幕阈值：如果词级 cues 太少（如只有 3 个 cues for 14s），
# 说明 edge_tts 本身提供的粒度已足够，不需要额外细化（避免空洞字幕）
_MIN_WORD_CUES_FOR_FINE = 6
# 突出字幕时长倍率
_PROMINENT_DURATION_MULTIPLIER = 1.4
# 突出检测：文本长度 ≤ 此值时视为"短句突出"
_PROMINENT_MAX_CHARS = 12


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

        # ── 应用突出时长加成 ──
        if groups:
            for gi, (s_s, e_s, txt) in enumerate(groups):
                multiplier = SubtitleGenerator._detect_prominence(txt)
                if multiplier > 1.0:
                    new_dur = (e_s - s_s) * multiplier
                    e_s = s_s + new_dur
                    # 不超过下一个字幕的 end（容许突出字幕和后段重叠）
                    if gi + 1 < len(groups):
                        e_s = min(e_s, groups[gi + 1][1])
                    groups[gi] = (s_s, e_s, txt)

        # ── 前后段重叠：每条字幕结束时间向后延伸 overlap_sec ──
        _OVERLAP_SEC = 0.8
        for gi in range(len(groups) - 1):
            s_s, e_s, txt = groups[gi]
            next_e = groups[gi + 1][1]
            new_e = min(e_s + _OVERLAP_SEC, next_e)
            if new_e > e_s:
                groups[gi] = (s_s, new_e, txt)

        # 生成 SRT
        entries = []
        for idx, (s_s, e_s, txt) in enumerate(groups, 1):
            if e_s - s_s < 0.3:
                e_s = s_s + 0.3

            start_time = SubtitleGenerator.cue_to_srt_time(s_s)
            end_time = SubtitleGenerator.cue_to_srt_time(e_s)
            entries.append(f"{idx}\n{start_time} --> {end_time}\n{txt}\n")

        return "\n".join(entries)

    @staticmethod
    def _detect_prominence(text: str) -> float:
        """检测字幕文本是否"突出"，返回时长倍率（≥1.0）。

        突出规则：
          - 短句（≤ _PROMINENT_MAX_CHARS 字）且以！？?! 结尾 → 1.5x
          - 短句（≤ _PROMINENT_MAX_CHARS 字）→ 1.3x
          - 包含"注意、重要、关键、突然、竟然、原来"等关键词 → 1.3x
          - 其他 → 1.0x（正常）
        """
        t = text.strip()
        if not t:
            return 1.0
        low = t.lower()
        key_words = {"注意", "重要", "关键", "突然", "竟然", "原来",
                     "attention", "important", "suddenly", "finally", "warning"}
        if len(t) <= _PROMINENT_MAX_CHARS:
            if t[-1] in "！？!?":
                return 1.5
            return 1.3
        if any(kw in low for kw in key_words):
            return 1.3
        return 1.0

    @staticmethod
    def _generate_scene_aware_srt(
        scene_texts: List[str],
        scene_durations: List[float],
        word_cues: object = None,
        max_chars_per_group: int = _MAX_SUB_CHARS,
        scene_start_times: Optional[List[float]] = None,
        overlap_sec: float = 0.8,
    ) -> str:
        """为每个场景/段落生成细粒度 SRT，支持场景内再拆分为子段。

        策略（无需 TTS cues 也能工作）：
          1. 每个场景的文本按句子（。！？.!?）拆分为候选句
          2. 在场景时长内均匀分布各句
          3. 检测突出文本并赋予更长显示时间
          4. 合并为全量 SRT（偏移到场景在时间轴上的位置）

        Args:
            scene_texts: 每个场景的旁白文本列表。
            scene_durations: 每个场景的时长（秒）。
            word_cues: 可选 TTS SubMaker cues，如有则从中推导精确时间。
            max_chars_per_group: 每组最大字符数。
            scene_start_times: 每个场景在时间轴上的起始时间（秒）。
                若未提供则按 scene_durations 累积计算。
            overlap_sec: 前后段字幕重叠时长，同时展示多条降低音画不同步影响。

        Returns:
            SRT 格式字符串。
        """
        if not scene_texts or not scene_durations:
            return ""

        if scene_start_times is None:
            scene_start_times = []
            acc = 0.0
            for d in scene_durations:
                scene_start_times.append(acc)
                acc += d

        entries = []
        global_idx = 1

        for si, text in enumerate(scene_texts):
            if not text.strip():
                continue
            scene_dur = scene_durations[si]
            scene_start = scene_start_times[si]
            scene_end = scene_start + scene_dur

            # 按句子拆分
            sentences = [s.strip() for s in _re.split(r'(?<=[。！？.!?])', text) if s.strip()]
            if not sentences:
                sentences = [text.strip()]
            if not sentences:
                continue

            # 进一步将长句拆为子段（按逗号/分号）
            all_segments = []
            for sent in sentences:
                if len(sent) > max_chars_per_group:
                    sub_parts = _re.split(r'(?<=[，、；,;])', sent)
                    temp = ""
                    for part in sub_parts:
                        if not part.strip():
                            continue
                        if not temp or len(temp) + len(part) <= max_chars_per_group:
                            temp += part
                        else:
                            if temp.strip():
                                all_segments.append(temp.strip())
                            temp = part
                    if temp.strip():
                        all_segments.append(temp.strip())
                else:
                    all_segments.append(sent.strip())

            if not all_segments:
                continue

            # 在场景时长内均匀分配各子段
            seg_count = len(all_segments)
            # 保留 10% padding 让最后一段有呼吸感
            usable_dur = scene_dur * 0.9
            base_dur = usable_dur / seg_count

            # Pass 1: 计算各段起始/结束时间（无重叠）
            raw_segments: list[tuple[float, float, str]] = []
            current_time = scene_start
            for idx, seg in enumerate(all_segments):
                seg_dur = base_dur

                mult = SubtitleGenerator._detect_prominence(seg)
                if mult > 1.0 and idx > 0:
                    borrowed = seg_dur * 0.2
                    seg_dur += borrowed
                elif mult > 1.0:
                    seg_dur *= mult

                seg_start = current_time
                seg_end = min(seg_start + seg_dur, scene_end - 0.05)
                if seg_end <= seg_start:
                    seg_end = seg_start + 0.3

                raw_segments.append((seg_start, seg_end, seg))
                current_time = seg_end + 0.05

            # Pass 2: 前后段重叠 — 每条字幕结束时间向后延伸 overlap_sec
            # 使用 next 段的 end 而非 start 作为上限，确保可见重叠
            for si in range(len(raw_segments) - 1):
                s_s, e_s, txt = raw_segments[si]
                next_e = raw_segments[si + 1][1]
                new_e = min(e_s + overlap_sec, next_e)
                if new_e > e_s:
                    raw_segments[si] = (s_s, new_e, txt)

            for seg_start, seg_end, seg in raw_segments:
                start_srt = SubtitleGenerator.cue_to_srt_time(seg_start)
                end_srt = SubtitleGenerator.cue_to_srt_time(seg_end)
                entries.append(f"{global_idx}\n{start_srt} --> {end_srt}\n{seg}\n")
                global_idx += 1

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
    def text_to_srt(text: str, output_path: str, duration_sec: float, chars_per_sec: float = 4.0) -> str:
        """从纯文本生成 SRT（不依赖 TTS SubMaker cues）。

        当旁白关闭但字幕开启时使用。文本时长由字符数估算，
        字幕按固定间隔均匀分布。

        Args:
            text: 纯文本内容
            output_path: SRT 文件输出路径
            duration_sec: 总时长（秒）
            chars_per_sec: 朗读速度（字符/秒），默认 4.0

        Returns:
            SRT 文件路径
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not text.strip() or duration_sec <= 0:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("")
            return output_path

        # 按句号/问号/感叹号拆分句子
        sentences = []
        for part in _re.split(r'(?<=[。！？.!?])', text):
            part = part.strip()
            if part:
                sentences.append(part)

        if not sentences:
            sentences = [text.strip()]

        # 估算每个句子的时长
        total_chars = len(text)
        total_duration = max(duration_sec, 1.0)

        entries = []
        current_time = 0.0

        for idx, sentence in enumerate(sentences):
            sentence_duration = max(len(sentence) / chars_per_sec, 1.0)
            # 均匀缩放使所有句子总时长匹配 duration_sec
            sentence_duration = sentence_duration / (total_chars / chars_per_sec) * total_duration

            start_s = current_time
            end_s = min(start_s + sentence_duration, total_duration - 0.01)
            if end_s <= start_s:
                break

            start_time = SubtitleGenerator.cue_to_srt_time(start_s)
            end_time = SubtitleGenerator.cue_to_srt_time(end_s)
            entries.append(f"{idx + 1}\n{start_time} --> {end_time}\n{sentence}\n")
            current_time = end_s

        srt_content = "\n".join(entries)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"[Subtitle] text_to_srt: {output_path} ({len(entries)} entries, {duration_sec:.1f}s)")
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
