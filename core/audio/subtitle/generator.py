"""core.audio.subtitle.generator — SRT 生成方法（v5.0 Batch 4 / 4.3 拆分）

SubtitleSrtMixin：文本拆分/分块/词级细粒度/场景感知/解析等纯 SRT 生成逻辑；
全部为 @staticmethod，经 MRO 组合回 SubtitleGenerator。"""
import datetime
import itertools
import logging
import os
import re as _re
from typing import List, Optional, Tuple

import srt

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
# 单段词级字幕的重叠缓冲（仅视觉缓冲，不再掩盖不同步）
_FINE_OVERLAP_SEC = 0.12

class SubtitleSrtMixin:
    """SRT 生成方法（cues → SRT 文本），v5.0 Batch 4（4.3）拆分。"""

    @staticmethod
    def _split_long_text(txt: str, max_chars_per_line: int = 14,
                         video_width: int = None, fontsize: int = None) -> str:
        """将过长的字幕文本拆分为多行，避免单行溢出屏幕。

        对 CJK 文本按字符数拆分，对非 CJK 文本按单词边界拆分。最多拆为 2 行，
        并尽量让每行在目标视频宽度 / 字号下不超过一行（宽度感知）。

        Args:
            txt: 原始字幕文本
            max_chars_per_line: 每行最大字符数（CJK）或单词数（非 CJK）的旧式预算；
                当提供 video_width + fontsize 时，将以宽度感知预算覆盖此值。
            video_width: 视频宽度（用于估算每行可容纳字符数）
            fontsize: 字幕字号（用于估算每行可容纳字符数）

        Returns:
            可能含 \\n 的文本
        """
        if not txt or "\n" in txt:
            return txt

        has_cjk = any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf' for ch in txt)

        # 宽度感知：根据视频宽度与字号计算每行可容纳字符数（参考中文短字幕规范）
        if video_width and fontsize:
            available_w = max(80, int(video_width) - 40)
            if has_cjk:
                per_line = max(8, available_w // fontsize)
            else:
                # 拉丁字符宽约为字号的 0.5 倍，留出安全系数 0.52
                per_line = max(12, int(available_w / (fontsize * 0.52)))
        else:
            per_line = max_chars_per_line

        if has_cjk:
            if len(txt) <= per_line:
                return txt
            # 拆为 2 行，尽量等长，在中间附近找标点或自然断点
            mid = len(txt) // 2
            for offset in range(min(4, mid)):
                for candidate in (mid + offset, mid - offset):
                    if 0 < candidate < len(txt) and txt[candidate - 1] in '，。、；！？,. ;!?':
                        return txt[:candidate] + "\n" + txt[candidate:]
            return txt[:mid] + "\n" + txt[mid:]
        else:
            words = txt.split()
            if len(txt) <= per_line:
                return txt
            # 按字符预算分两行（每行不超过 per_line 字符），优先在词边界断开
            taken = []
            cur = 0
            for w in words:
                add = len(w) + (1 if cur else 0)
                if cur == 0 or cur + add <= per_line:
                    taken.append(w)
                    cur += add
                else:
                    break
            if not taken:
                taken = [words[0]]
            line1 = " ".join(taken)
            line2 = " ".join(words[len(taken):])
            if not line2:
                return line1
            return line1 + "\n" + line2

    @staticmethod
    def _chunk_text(text: str, max_entry: int, has_cjk: bool) -> List[str]:
        """将一段字幕文本切分为若干 ≤ max_entry 字符的块（用于强制 ≤2 行）。

        CJK 按字符贪心切分（尽量在标点处断开）；非 CJK 按单词贪心切分。
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= max_entry:
            return [text]
        if has_cjk:
            chunks = []
            cur = ""
            for ch in text:
                if len(cur) + 1 <= max_entry:
                    cur += ch
                else:
                    chunks.append(cur)
                    cur = ch
            if cur:
                chunks.append(cur)
            return chunks
        words = text.split()
        chunks = []
        cur = ""
        for w in words:
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= max_entry:
                cur += " " + w
            else:
                chunks.append(cur)
                cur = w
        if cur:
            chunks.append(cur)
        return chunks

    @staticmethod
    def enforce_max_lines(srt_content: str, max_lines: int = 2,
                          video_width: int = 768, fontsize: int = 42) -> str:
        """确保每条字幕（SRT entry）渲染后不超过 max_lines 行，适配所有语言。

        参考中文短字幕规范：将过长的字幕块按目标视频宽度 / 字号估算的「每行字符数」
        上限切分为多个更短的块，并在原时间区间内按块长度比例重新分配时间。
        这样无论 CJK 还是拉丁 / 西里尔等文字体系，单条字幕都不会溢出成多行。

        Args:
            srt_content: 原始 SRT 文本
            max_lines: 每条字幕允许的最大行数（默认 2）
            video_width: 视频宽度（像素）
            fontsize: 字幕字号（像素）

        Returns:
            处理后的 SRT 文本（条目数可能增加，但每条均 ≤ max_lines 行）
        """
        import srt as _srt

        if not srt_content or not srt_content.strip():
            return srt_content
        try:
            subs = list(_srt.parse(srt_content))
        except Exception:
            return srt_content
        if not subs:
            return srt_content

        available_w = max(80, int(video_width or 768) - 40)
        fs = int(fontsize or 42)
        new_subs = []

        for sub in subs:
            text = (sub.content or "").strip()
            if not text:
                new_subs.append(sub)
                continue
            has_cjk = any('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf' for ch in text)
            if has_cjk:
                per_line = max(8, available_w // fs)
            else:
                per_line = max(12, int(available_w / (fs * 0.52)))
            max_entry = per_line * max_lines

            if len(text) <= max_entry:
                new_subs.append(sub)
                continue

            chunks = SubtitleGenerator._chunk_text(text, max_entry, has_cjk)
            if len(chunks) <= 1:
                new_subs.append(sub)
                continue

            total = sum(len(c) for c in chunks) or 1
            start = sub.start
            end = sub.end
            dur = (end - start).total_seconds()
            cursor = start
            for c in chunks:
                frac = len(c) / total
                c_dur = dur * frac
                c_end = cursor + datetime.timedelta(seconds=c_dur)
                new_subs.append(_srt.Subtitle(index=0, start=cursor, end=c_end, content=c))
                cursor = c_end

        for i, s in enumerate(new_subs, 1):
            s.index = i
        return _srt.compose(new_subs)

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

        # 复用统一分组逻辑（多段路径 generate_cue_aware_srt 也调用同一方法，保证一致性）
        return SubtitleGenerator._group_items_to_srt(
            items, max_duration=max_duration, max_chars=max_chars,
            overlap_sec=_FINE_OVERLAP_SEC,
        )

    @staticmethod
    def _group_items_to_srt(
        items: List[Tuple[float, float, str]],
        max_duration: float = _MAX_SUB_DURATION,
        max_chars: int = _MAX_SUB_CHARS,
        overlap_sec: float = 0.12,
    ) -> str:
        """将 [(start_s, end_s, text), ...] 贪心分组为可读字幕段（SRT 字符串）。

        从 _generate_fine_srt_from_word_cues 抽出，单段/多段共用。
        分组约束：≤ max_duration 秒、≤ max_chars 字符、词间停顿 >0.4s 断句。
        保留尾部合并与突出时长加成逻辑。
        """
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
        while len(groups) >= 2:
            last_dur = groups[-1][1] - groups[-1][0]
            last_chars = len(groups[-1][2])
            prev_chars = len(groups[-2][2])
            merged_dur = groups[-1][1] - groups[-2][0]
            merged_chars = prev_chars + last_chars
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

        # 突出时长加成
        if groups:
            for gi, (s_s, e_s, txt) in enumerate(groups):
                multiplier = SubtitleGenerator._detect_prominence(txt)
                if multiplier > 1.0:
                    new_dur = (e_s - s_s) * multiplier
                    e_s = s_s + new_dur
                    if gi + 1 < len(groups):
                        e_s = min(e_s, groups[gi + 1][1])
                    groups[gi] = (s_s, e_s, txt)

        # 前后段重叠：每条字幕结束时间向后延伸 overlap_sec（仅视觉缓冲）
        for gi in range(len(groups) - 1):
            s_s, e_s, txt = groups[gi]
            next_e = groups[gi + 1][1]
            new_e = min(e_s + overlap_sec, next_e)
            if new_e > e_s:
                groups[gi] = (s_s, new_e, txt)

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
        overlap_sec: float = 0.12,
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
    def _scene_char_ranges(segment_texts: List[str]) -> "Optional[list]":
        """计算各场景在「归一化整段文本」中的字符区间 [c_start, c_end)。

        归一化：去除空白与所有非「单词字符/中日韩汉字」的符号，仅保留读音文本，
        使 cues 的累计归一化字符位置能与场景文本对齐（免疫 TTS 插入的停顿/标点漂移）。

        Returns:
            每场景的 (c_start, c_end) 列表；segment_texts 为空时返回 None。
        """
        if not segment_texts:
            return None
        def norm_len(x):
            return len(_re.sub(r"\s+|[^\w\u4e00-\u9fff]", "", x))
        ranges = []
        cum = 0
        for t in segment_texts:
            n = norm_len(t)
            if n == 0:
                ranges.append((cum, cum))
            else:
                ranges.append((cum, cum + n))
                cum += n
        return ranges

    @staticmethod
    def generate_cue_aware_srt(
        word_cues: object,
        segment_texts: List[str],
        scene_start_times: "Optional[list]" = None,
        scene_durations: "Optional[list]" = None,
        max_duration: float = _MAX_SUB_DURATION,
        max_chars: int = _MAX_SUB_CHARS,
        overlap_sec: float = 0.12,
        audio_duration: "Optional[float]" = None,
    ) -> str:
        """基于 edge_tts 词级 cues 的精确时间线对齐字幕生成（替代 _generate_scene_aware_srt）。

        原理：cues 是合成音频的源头时间线（音频从 t=0 连续播放，最终成片时间轴 =
        音频时间轴），因此每个 cue 的时间即其在成片中的显示时间，无需额外偏移。
        本方法仅负责「按场景归属 + 段内分组」，使字幕断句与场景切换对齐，且每句
        时间戳贴合真实朗读位置。

        场景归属两种策略：
          - 策略 A（默认，文本锚定）：按各场景归一化字符区间归属 cues，免疫 TTS 在
            场景间插入的停顿漂移。
          - 策略 B（兜底，时间区间）：当 segment_texts 无法还原整段文本时，用
            scene_start_times / scene_durations 累加得到的时间区间归属。

        Args:
            word_cues: edge_tts SubMaker（含 .cues）。
            segment_texts: 各场景旁白文本（有序）。
            scene_start_times: 各场景在成片时间轴的起始秒（策略 B 用）。
            scene_durations: 各场景时长（策略 B 用，未给 scene_start_times 时累加）。
            max_duration / max_chars: 段内分组约束。
            overlap_sec: 段间重叠缓冲（仅视觉）。
            audio_duration: 实际音频时长，用于把最后一条 cue 钳制到音频尾部（残余归一化）。

        Returns:
            SRT 字符串；cues 不足时返回空串，由调用方回退 legacy。
        """
        raw_cues = getattr(word_cues, "cues", None) or []
        if not raw_cues:
            return ""

        # 1) cues → (start, end, text) 三元组（音频时间轴）
        items = []
        for cue in raw_cues:
            s = SubtitleGenerator._cue_total_seconds(cue.start)
            e = SubtitleGenerator._cue_total_seconds(cue.end)
            t = (cue.content or "").strip()
            if t:
                items.append((s, e, t))
        if not items:
            return ""

        # 残余归一化：把最后一条 cue 的 end 钳到实际音频时长（避免尾差留白未覆盖）
        if audio_duration and audio_duration > 0 and items[-1][1] > audio_duration:
            items[-1] = (items[-1][0], audio_duration, items[-1][2])

        n = len(segment_texts)
        if n == 0:
            return ""

        # 2) 场景归属
        scene_char_ranges = SubtitleGenerator._scene_char_ranges(segment_texts)
        if scene_char_ranges is not None:
            # 策略 A：文本锚定。累计归一化字符位置，定位每个 cue 所属场景。
            def norm_len(x):
                return len(_re.sub(r"\s+|[^\w\u4e00-\u9fff]", "", x))
            cue_char_pos = []
            run = 0
            for _, _, t in items:
                run += norm_len(t)
                cue_char_pos.append(run)
            scene_cue_idx = [[] for _ in range(n)]
            for ci, cp in enumerate(cue_char_pos):
                for si in range(n):
                    c0, c1 = scene_char_ranges[si]
                    if c0 <= cp <= c1:
                        scene_cue_idx[si].append(ci)
                        break
                else:
                    # 落在场景间隙（理论极少）：归属到累计位置最近的场景
                    best = 0
                    best_diff = abs(scene_char_ranges[0][1] - cp)
                    for si in range(n):
                        diff = abs((scene_char_ranges[si][0] + scene_char_ranges[si][1]) / 2 - cp)
                        if diff < best_diff:
                            best_diff = diff
                            best = si
                    scene_cue_idx[best].append(ci)
        else:
            # 策略 B：时间区间兜底
            if scene_start_times is not None:
                starts = list(scene_start_times)
            elif scene_durations is not None:
                starts = list(itertools.accumulate(scene_durations, initial=0.0))[:-1]
            else:
                starts = [0.0] * n
            scene_cue_idx = [[] for _ in range(n)]
            for ci, (s, _, _) in enumerate(items):
                placed = False
                for si in range(n):
                    s0 = starts[si]
                    s1 = starts[si + 1] if si + 1 < len(starts) else items[-1][1] + 1.0
                    if s0 <= s < s1:
                        scene_cue_idx[si].append(ci)
                        placed = True
                        break
                if not placed:
                    scene_cue_idx[-1].append(ci)

        # 3) 逐场景：取 cues 子集（保持时间序）→ 段内分组 → 直接沿用 cues 时间（offset=0）
        entries = []
        global_idx = 1
        for si in range(n):
            idxs = scene_cue_idx[si]
            if not idxs:
                continue
            scene_items = [items[ci] for ci in idxs]
            local_srt = SubtitleGenerator._group_items_to_srt(
                scene_items, max_duration=max_duration, max_chars=max_chars,
                overlap_sec=overlap_sec,
            )
            try:
                subs = list(srt.parse(local_srt))
            except Exception:
                subs = []
            for sub in subs:
                entries.append((global_idx, sub.start, sub.end, sub.content))
                global_idx += 1

        # 残余归一化：把所有字幕时间钳到实际音频时长内，
        # 覆盖「突出时长加成」可能把末句 end 拉出音频尾部的情况
        if audio_duration and audio_duration > 0:
            ad = datetime.timedelta(seconds=audio_duration)
            clamped = []
            for idx, s, e, t in entries:
                s = min(s, ad)
                e = min(e, ad)
                if e <= s:
                    e = s + datetime.timedelta(seconds=0.3)
                clamped.append((idx, s, e, t))
            entries = clamped

        entries.sort(key=lambda x: x[1])
        return "\n".join(
            f"{idx}\n{SubtitleGenerator.cue_to_srt_time(s.total_seconds())} --> "
            f"{SubtitleGenerator.cue_to_srt_time(e.total_seconds())}\n{t}\n"
            for idx, s, e, t in entries
        )

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
