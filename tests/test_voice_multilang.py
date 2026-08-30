"""tests.test_voice_multilang — PR #32 阿语后续优化（多语言补齐）测试

锁定 core.audio.voices 对 tr/vi/th/tl/hi/fa/bn/ur 共 8 种新增语言的支撑：
    1. A 节：_ARABIC_RE 排除 U+FEFF（BOM），含 BOM 文本不误判为阿语
    2. 脚本检测：泰文/天城文/孟加拉文 + 阿语（fa/ur 复用）+ 拉丁（tr/vi/tl）
    3. voice id 归一：fil → tl
    4. 兼容性矩阵：新语言自身兼容、跨体系不兼容
    5. 本地姓名映射：非拉丁语音色试听文案用本地姓名

注意：本文件位于 tests/ 顶层，不受 tests/mock_regression/conftest.py 影响。
"""

import asyncio
import os

import pytest

from core.audio.voices import (
    _VOICE_NATIVE_NAMES,
    LANG_COMPAT,
    PROJECT_LANGUAGES,
    detect_text_script,
    get_voice_lang,
    is_voice_compatible,
    is_voice_compatible_with_text,
    load_voice_catalog,
)
from core.compositor.concatenator.audio_overlay import AudioOverlayMixin
from models.task import SubtitleStyle

_MULTI_SCRIPT_SRT = """1
00:00:00,000 --> 00:00:02,000
สวัสดีครับ

2
00:00:02,000 --> 00:00:04,000
नमस्ते दुनिया

3
00:00:04,000 --> 00:00:06,000
বাংলা ভাষা

4
00:00:06,000 --> 00:00:08,000
سلام دنیا
"""


def _multi_script_srt_path(tmp_path) -> str:
    p = os.path.join(str(tmp_path), "multi.srt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(_MULTI_SCRIPT_SRT)
    return p


def _style() -> SubtitleStyle:
    return SubtitleStyle(
        font="STHeitiMedium.ttc",
        color="white",
        position=("center", "bottom-80"),
        fontsize=48,
        stroke_color="black",
        stroke_width=2,
        bg_color=(0, 0, 0, 140),
    )

# ══════════════════════════════════════════════════════════════════════
# A 节：_ARABIC_RE 排除 U+FEFF（BOM）
# ══════════════════════════════════════════════════════════════════════

def test_bom_not_detected_as_arabic():
    """含 U+FEFF（BOM）的文本不应被误判为阿拉伯文。"""
    assert detect_text_script("\ufeffمرحبا") == "arabic", "BOM+阿语正文仍应判为 arabic"
    assert detect_text_script("\ufeffHello") == "latin", "BOM+拉丁正文应判为 latin，不因 BOM 判 arabic"
    # 纯 BOM 不应判为阿拉伯文
    assert detect_text_script("\ufeff") != "arabic"


# ══════════════════════════════════════════════════════════════════════
# 脚本检测：新增文字体系
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Merhaba", "latin"),              # tr（土耳其语，拉丁）
        ("Xin chào", "latin"),             # vi（越南语，拉丁）
        ("Kumusta", "latin"),              # tl（他加禄语，拉丁）
        ("สวัสดี", "thai"),                 # th（泰文）
        ("नमस्ते", "devanagari"),           # hi（印地语，天城文）
        ("বাংলা", "bengali"),               # bn（孟加拉文）
        ("سلام", "arabic"),                # fa（波斯语，阿文）
        ("اردو", "arabic"),                # ur（乌尔都语，阿文）
        ("مرحبا", "arabic"),               # ar（阿拉伯语）
    ],
)
def test_detect_text_script_new_langs(text, expected):
    assert detect_text_script(text) == expected


def test_project_languages_covers_22():
    """PROJECT_LANGUAGES 覆盖前端 22 种 UI 语言，且新增 8 种脚本标注正确。"""
    for code in ("tr", "vi", "th", "tl", "hi", "fa", "bn", "ur"):
        assert code in PROJECT_LANGUAGES, f"缺失语言 {code}"
    assert PROJECT_LANGUAGES["tr"]["script"] == "latin"
    assert PROJECT_LANGUAGES["th"]["script"] == "thai"
    assert PROJECT_LANGUAGES["hi"]["script"] == "devanagari"
    assert PROJECT_LANGUAGES["bn"]["script"] == "bengali"
    assert PROJECT_LANGUAGES["fa"]["script"] == "arabic"
    assert PROJECT_LANGUAGES["ur"]["script"] == "arabic"


# ══════════════════════════════════════════════════════════════════════
# voice id 归一：fil → tl
# ══════════════════════════════════════════════════════════════════════

def test_get_voice_lang_fil_maps_to_tl():
    """edge-tts 的 Tagalog 音色前缀为 fil，应归一为项目语言 tl。"""
    assert get_voice_lang("fil-PH-AngeloNeural") == "tl"
    assert get_voice_lang("fil-PH-BlessicaNeural") == "tl"


@pytest.mark.parametrize(
    "voice_id,expected",
    [
        ("tr-TR-EmelNeural", "tr"),
        ("vi-VN-HoaiMyNeural", "vi"),
        ("th-TH-NiwatNeural", "th"),
        ("hi-IN-SwaraNeural", "hi"),
        ("fa-IR-FaridNeural", "fa"),
        ("bn-IN-BashkarNeural", "bn"),
        ("ur-PK-AsadNeural", "ur"),
        ("ar-SA-HamedNeural", "ar"),
        ("zh-CN-XiaoxiaoNeural", "zh"),
        (None, None),
        ("", None),
        ("xx-YY-UnknownNeural", None),
    ],
)
def test_get_voice_lang_known_voices(voice_id, expected):
    assert get_voice_lang(voice_id) == expected


# ══════════════════════════════════════════════════════════════════════
# 兼容性矩阵
# ══════════════════════════════════════════════════════════════════════

def test_new_langs_in_compat():
    """8 种新语言均进入 LANG_COMPAT，且拉丁三语共享集合。"""
    for code in ("tr", "vi", "th", "tl", "hi", "fa", "bn", "ur"):
        assert code in LANG_COMPAT, f"缺失 LANG_COMPAT[{code}]"
    # 拉丁三语应与其它拉丁语言互通
    for latin in ("tr", "vi", "tl"):
        assert "en" in LANG_COMPAT[latin]
        assert "fr" in LANG_COMPAT[latin]
    # 独立文字体系只与自身互通
    for solo in ("th", "hi", "bn", "fa", "ur"):
        assert LANG_COMPAT[solo] == [solo]


def test_voice_compatible_same_script():
    """新语言音色朗读同脚本语言内容兼容。"""
    assert is_voice_compatible("th-TH-NiwatNeural", "th") is True
    assert is_voice_compatible("hi-IN-SwaraNeural", "hi") is True
    assert is_voice_compatible("bn-IN-BashkarNeural", "bn") is True
    # 拉丁音色互相兼容
    assert is_voice_compatible("tr-TR-EmelNeural", "en") is True


def test_voice_compatible_cross_script_incompatible():
    """跨文字体系不兼容（泰→英 false）。"""
    assert is_voice_compatible("th-TH-NiwatNeural", "en") is False
    assert is_voice_compatible("hi-IN-SwaraNeural", "en") is False


def test_voice_compatible_with_text_new_scripts():
    """文本级兼容：voice 语言须在对应脚本的可读集合内。"""
    assert is_voice_compatible_with_text("th-TH-NiwatNeural", "สวัสดี") is True
    assert is_voice_compatible_with_text("hi-IN-SwaraNeural", "नमस्ते") is True
    assert is_voice_compatible_with_text("bn-IN-BashkarNeural", "বাংলা") is True
    # 阿语脚本：fa/ur/ar 音色均可读（阿文字母共用语系）
    assert is_voice_compatible_with_text("fa-IR-FaridNeural", "سلام") is True
    assert is_voice_compatible_with_text("ur-PK-AsadNeural", "اردو") is True
    # 跨体系：泰音色读拉丁文本 false
    assert is_voice_compatible_with_text("th-TH-NiwatNeural", "Hello") is False


# ══════════════════════════════════════════════════════════════════════
# 本地姓名映射
# ══════════════════════════════════════════════════════════════════════

def test_native_name_mapping_covers_new_voices():
    """非拉丁新语言的 edge-tts 音色均有本地姓名映射。"""
    assert _VOICE_NATIVE_NAMES["fa"]["Dilara"] == "دلارا"
    assert _VOICE_NATIVE_NAMES["ur"]["Asad"] == "اسد"
    assert _VOICE_NATIVE_NAMES["th"]["Niwat"] == "นิวัฒน์"
    assert _VOICE_NATIVE_NAMES["hi"]["Swara"] == "स्वरा"
    assert _VOICE_NATIVE_NAMES["bn"]["Nabanita"] == "নবনীতা"
    # 兼容别名仍保留
    assert _VOICE_NATIVE_NAMES["ar"]["Hamed"] == "حامد"


# ══════════════════════════════════════════════════════════════════════
# 目录加载：8 种新语言进入分组
# ══════════════════════════════════════════════════════════════════════

def _run_catalog():
    return asyncio.run(load_voice_catalog(force=True))


def test_catalog_groups_new_langs():
    """目录含 8 种新语言分组，且泰/印地/孟加拉音色使用本地姓名试听。"""
    cat = _run_catalog()
    codes = {g["code"] for g in cat["languages"]}
    for code in ("tr", "vi", "th", "tl", "hi", "fa", "bn", "ur"):
        assert code in codes, f"目录缺失语言分组 {code}"
    # th 音色试听用本地姓名（泰文）
    th_group = next(g for g in cat["languages"] if g["code"] == "th")
    for v in th_group["voices"]:
        assert any(ord(c) > 0x0E00 for c in v["preview_text"]), "泰语试听应含泰文字符"


def test_catalog_tl_uses_fil_voices():
    """tl 分组来自 fil-PH 音色，试听文案为他加禄语。"""
    cat = _run_catalog()
    tl_group = next(g for g in cat["languages"] if g["code"] == "tl")
    assert len(tl_group["voices"]) == 2
    assert all(v["id"].startswith("fil-PH-") for v in tl_group["voices"])
    assert all("Kumusta" in v["preview_text"] for v in tl_group["voices"])


# ══════════════════════════════════════════════════════════════════════
# 字幕字体回退：ASS 路径逐条脚本回退
# ══════════════════════════════════════════════════════════════════════

def test_srt_to_ass_script_font_fallback(tmp_path):
    """泰/印地/孟加拉/阿文条目在 ASS 中逐条回退对应内置字体（\fn 覆盖）。"""
    srt = _multi_script_srt_path(tmp_path)
    result = AudioOverlayMixin._srt_to_ass(srt, _style(), 768, 1152)
    assert result is not None
    ass_path, _ = result
    with open(ass_path, "r", encoding="utf-8") as f:
        content = f.read()
    # 全局样式默认仍为配置字体，逐条通过 \fn 覆盖
    assert "Style: Default,STHeitiMedium,48" in content
    assert "{\\fnNotoSansThai-Regular}สวัสดีครับ" in content
    assert "{\\fnNotoSansDevanagari-Regular}नमस्ते दुनिया" in content
    assert "{\\fnNotoSansBengali-Regular}বাংলা ভাষা" in content
    # 阿文（fa/ur 共用阿文字母）回退 NotoNaskhArabicUI
    assert "{\\fnNotoNaskhArabicUI}سلام دنیا" in content
