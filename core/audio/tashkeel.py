"""阿拉伯语变音符号（tashkeel/harakat）自动标注，供 TTS 更准确地朗读。

使用 mishkal（基于规则的阿拉伯语形态分析库）而非 LLM 来生成变音符号：
LLM 方案实测不可靠——即使明确要求"只加符号、不改字母"，模型仍会偶发替换
借词拼写（如 فيديو -> ويديو）或替换同义连词（如 إذا -> إن），这对旁白配音
是不可接受的（读出的内容会与原文不同）。mishkal 只做形态学标注，天然不会
引入新字母，因此改用"取 mishkal 的变音符号 + 保留原文逐字符结构"的合并算法，
以程序方式保证结果与原文在去除变音符号后完全一致。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_ARABIC_LETTER_RE = re.compile(r"[ء-ي]")
_DIACRITIC_RE = re.compile(r"[ً-ْٰ]")

_vocalizer = None


def _get_vocalizer():
    global _vocalizer
    if _vocalizer is None:
        from mishkal.tashkeel import TashkeelClass

        _vocalizer = TashkeelClass()
    return _vocalizer


def _merge_tashkeel(original: str, diacritized: str) -> str:
    """按原文逐字符重建结果：阿拉伯字母取自 mishkal 输出（含其变音符号），
    其余字符（标点、空格、数字等）严格保留原文，不采用 mishkal 对它们的改写。
    """
    d_tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(diacritized):
        ch = diacritized[i]
        if _ARABIC_LETTER_RE.match(ch):
            j = i + 1
            diac = ""
            while j < len(diacritized) and _DIACRITIC_RE.match(diacritized[j]):
                diac += diacritized[j]
                j += 1
            d_tokens.append((ch, diac))
            i = j
        else:
            i += 1

    out = []
    ti = 0
    for ch in original:
        if _ARABIC_LETTER_RE.match(ch):
            if ti < len(d_tokens):
                letter, diac = d_tokens[ti]
                out.append(letter + diac)
                ti += 1
            else:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def add_tashkeel_safe(text: str) -> str:
    """为阿拉伯文文本添加变音符号，失败或校验不通过时原样返回。

    校验：合并结果去除变音符号后必须与输入（同样去除变音符号后）逐字符相等，
    否则说明 mishkal 内部出现异常输出，这种情况下放弃标注、返回原文，
    避免把错误内容送入 TTS。
    """
    if not text or not _ARABIC_LETTER_RE.search(text):
        return text

    base_text = _DIACRITIC_RE.sub("", text)
    try:
        vocalizer = _get_vocalizer()
        raw_result = vocalizer.tashkeel(base_text)
    except Exception as e:
        logger.warning(f"[Tashkeel] mishkal failed, returning original text: {e}")
        return text

    merged = _merge_tashkeel(base_text, raw_result)
    if _DIACRITIC_RE.sub("", merged) != base_text:
        logger.warning("[Tashkeel] validation failed (letters changed), returning original text")
        return text
    return merged
