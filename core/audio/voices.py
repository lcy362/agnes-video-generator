"""core.audio.voices — 音色目录与兼容性

基于 edge_tts.list_voices() 动态加载全部可用音色，按项目 13 种 i18n 语言分组，
并内置跨语言兼容性矩阵与「文本脚本 → 兼容性」检测，供后端 /api/voices* 接口与
任务创建时的 voice/text 校验复用。

设计背景见 docs/plans/v4.0/voice_selector_design_DONE.md。核心结论：
- 同一文字体系内互通，跨体系基本不通（CJK→en 是唯一例外）。
- edge-tts 跨体系调用直接抛异常，无降级，因此必须前置校验。
"""

import asyncio
import logging
import re

import edge_tts

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# 项目语言定义
# ═══════════════════════════════════════════════════

# code -> (展示名, 文字体系)
# 文字体系: cjk / latin / cyrillic
PROJECT_LANGUAGES = {
    "zh": {"label": "中文", "script": "cjk"},
    "en": {"label": "English", "script": "latin"},
    "ja": {"label": "日本語", "script": "cjk"},
    "ko": {"label": "한국어", "script": "cjk"},
    "ru": {"label": "Русский", "script": "cyrillic"},
    "de": {"label": "Deutsch", "script": "latin"},
    "fr": {"label": "Français", "script": "latin"},
    "nl": {"label": "Nederlands", "script": "latin"},
    "es": {"label": "Español", "script": "latin"},
    "pt": {"label": "Português", "script": "latin"},
    "it": {"label": "Italiano", "script": "latin"},
    "id": {"label": "Bahasa Indonesia", "script": "latin"},
    "ms": {"label": "Bahasa Melayu", "script": "latin"},
    "ar": {"label": "العربية", "script": "arabic"},
}

# 拉丁体系包含的全部项目语言（彼此完全互通）
_LATIN_LANGS = [c for c, v in PROJECT_LANGUAGES.items() if v["script"] == "latin"]

# ═══════════════════════════════════════════════════
# 预设试听文本（与音色语言严格匹配）
# ═══════════════════════════════════════════════════

VOICE_PREVIEW_TEXTS = {
    "zh": "你好，我是{name}，这是一段音色试听。",
    "en": "Hello, I'm {name}, this is a voice preview sample.",
    "ja": "こんにちは、{name}です。これはボイスプレビューです。",
    "ko": "안녕하세요, 저는 {name}입니다. 이것은 음성 미리보기입니다.",
    "ru": "Здравствуйте, я {name}, это образец голоса.",
    "de": "Hallo, ich bin {name}, dies ist eine Sprachvorschau.",
    "fr": "Bonjour, je suis {name}, ceci est un aperçu vocal.",
    "nl": "Hallo, ik ben {name}, dit is een stemvoorbeeld.",
    "es": "Hola, soy {name}, esta es una muestra de voz.",
    "pt": "Olá, eu sou {name}, esta é uma amostra de voz.",
    "it": "Ciao, sono {name}, questo è un esempio vocale.",
    "id": "Halo, saya {name}, ini adalah sampel suara.",
    "ms": "Helo, saya {name}, ini adalah sampel suara.",
    "ar": "مرحبًا، أنا {name}، هذا نموذج صوتي تجريبي.",
}

# 阿拉伯语按地区方言的试听文案覆盖（locale 如 "ar-SY"）。
# 阿拉伯语音色的地域口音差异很大，标准阿拉伯语（فصحى）试听无法体现方言特色，
# 因此对已适配的地区使用地道方言问候语；未覆盖的地区回退到 VOICE_PREVIEW_TEXTS["ar"]。
VOICE_PREVIEW_TEXTS_BY_LOCALE = {
    "ar-SY": "أهلين، أنا {name}، هاد مثال عن صوتي.",
}

# ═══════════════════════════════════════════════════
# 兼容性矩阵（语言级）
# ═══════════════════════════════════════════════════
# 每个语言可读的目标语言集合（实测结论见设计文档 2.2 节）。
# 拉丁体系 9 种语言完全互通，故共享同一集合。

_LATIN_COMPAT = list(_LATIN_LANGS)  # 自身 + 其他 8 种拉丁语言

LANG_COMPAT = {
    "zh": ["zh", "en"],
    "en": list(_LATIN_COMPAT),
    "ja": ["ja", "zh", "en"],
    "ko": ["ko", "zh", "en"],
    "ru": ["ru"],
    "de": list(_LATIN_COMPAT),
    "fr": list(_LATIN_COMPAT),
    "nl": list(_LATIN_COMPAT),
    "es": list(_LATIN_COMPAT),
    "pt": list(_LATIN_COMPAT),
    "it": list(_LATIN_COMPAT),
    "id": list(_LATIN_COMPAT),
    "ms": list(_LATIN_COMPAT),
    "ar": ["ar"],
}


# ═══════════════════════════════════════════════════
# 文本脚本检测（用于任务提交时校验任意文本）
# ═══════════════════════════════════════════════════

# 各文字体系对应的可读 voice 语言集合
_SCRIPT_COMPAT_VOICES = {
    "zh": {"zh", "ja", "ko"},          # 汉字 → 中/日/韩音色
    "ja": {"ja"},                       # 假名 → 仅日语音色
    "ko": {"ko"},                       # 谚文 → 仅韩语音色
    "latin": set(_LATIN_LANGS) | {"zh", "ja", "ko"},  # 拉丁字母 → 全部拉丁 + CJK(均可读英文)
    "ru": {"ru"},                       # 西里尔 → 仅俄文
    "arabic": {"ar"},                   # 阿拉伯字母 → 仅阿拉伯语音色
}

# 阿拉伯字母及常见附加区块（含波斯语/乌尔都语共用字符、阿拉伯语标点、表现形式）
_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def detect_text_script(text: str) -> str:
    """粗略判断文本的 dominant 文字体系。

    Returns: 'zh' | 'ja' | 'ko' | 'latin' | 'ru' | 'arabic' | 'unknown'
    """
    if not text or not text.strip():
        return "unknown"
    # 优先级：谚文 > 假名 > 汉字 > 西里尔 > 阿拉伯文 > 拉丁
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[Ѐ-ӿ]", text):
        return "ru"
    if _ARABIC_RE.search(text):
        return "arabic"
    if re.search(r"[A-Za-z]", text):
        return "latin"
    return "unknown"


# ═══════════════════════════════════════════════════
# voice id 解析
# ═══════════════════════════════════════════════════

def get_voice_lang(voice_id: str):
    """从 voice id（如 zh-CN-XiaoxiaoNeural）解析项目语言 code。

    返回 PROJECT_LANGUAGES 中的 code，无法识别时返回 None。
    """
    if not voice_id:
        return None
    lang_part = voice_id.split("-")[0].lower()
    return lang_part if lang_part in PROJECT_LANGUAGES else None


# ═══════════════════════════════════════════════════
# 兼容性判定
# ═══════════════════════════════════════════════════

def is_voice_compatible(voice_id: str, target_lang: str) -> bool:
    """语言级兼容性：voice 能否朗读 target_lang 语言的内容。"""
    vlang = get_voice_lang(voice_id)
    if vlang is None or target_lang not in PROJECT_LANGUAGES:
        # 未知 voice 或未知目标语言：仅当完全相同时视为兼容
        return vlang == target_lang
    supported = LANG_COMPAT.get(vlang, [vlang])
    return target_lang in supported


def is_voice_compatible_with_text(voice_id: str, text: str) -> bool:
    """文本级兼容性：voice 能否朗读给定文本的 dominant 文字体系。

    用于任务提交时校验（稿件正文已知，创意/诗歌等由 LLM 按页面语言生成）。
    """
    vlang = get_voice_lang(voice_id)
    if vlang is None:
        return True  # 未知音色不阻断
    script = detect_text_script(text)
    allowed = _SCRIPT_COMPAT_VOICES.get(script)
    if allowed is None:
        return True  # unknown 脚本不阻断
    return vlang in allowed


# ═══════════════════════════════════════════════════
# 离线 fallback 目录（edge_tts 不可用时使用）
# ═══════════════════════════════════════════════════

_FALLBACK_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao", "local_name": "晓晓",
     "region": "普通话", "region_code": "zh-CN", "gender": "female",
     "style_tags": ["Warm"], "preview_text": "你好，我是晓晓，这是一段音色试听。", "lang": "zh"},
    {"id": "zh-CN-YunyangNeural", "name": "Yunyang", "local_name": "云扬",
     "region": "普通话", "region_code": "zh-CN", "gender": "male",
     "style_tags": ["Professional"], "preview_text": "你好，我是云扬，这是一段音色试听。", "lang": "zh"},
    {"id": "zh-CN-XiaoyiNeural", "name": "Xiaoyi", "local_name": "小艺",
     "region": "普通话", "region_code": "zh-CN", "gender": "female",
     "style_tags": ["Lively"], "preview_text": "你好，我是小艺，这是一段音色试听。", "lang": "zh"},
    {"id": "zh-CN-YunxiNeural", "name": "Yunxi", "local_name": "云希",
     "region": "普通话", "region_code": "zh-CN", "gender": "male",
     "style_tags": ["Sunshine"], "preview_text": "你好，我是云希，这是一段音色试听。", "lang": "zh"},
]


def _build_fallback_catalog() -> dict:
    return {
        "languages": [
            {"code": "zh", "label": "中文", "count": len(_FALLBACK_VOICES), "voices": _FALLBACK_VOICES}
        ],
        "compat_hint": LANG_COMPAT,
        "fallback": True,
    }


# ═══════════════════════════════════════════════════
# 阿拉伯语音色姓名本地化
# ═══════════════════════════════════════════════════
# edge-tts 不提供阿拉伯语音色的本地文字姓名（仅拉丁转写，如 "Hamed"）。
# 试听文案若直接把拉丁姓名嵌入阿拉伯语句子朗读，阿语音色会按外语拼读，
# 发音明显错误。此处手工维护全部 32 个阿拉伯语音色的正确阿拉伯语姓名，
# 用于试听文案与搜索，而非拉丁转写。
ARABIC_VOICE_NAMES = {
    "Fatima": "فاطمة", "Hamdan": "حمدان",
    "Ali": "علي", "Laila": "ليلى",
    "Amina": "أمينة", "Ismael": "إسماعيل",
    "Salma": "سلمى", "Shakir": "شاكر",
    "Bassel": "باسل", "Rana": "رنا",
    "Sana": "سناء", "Taim": "تيم",
    "Fahed": "فهد", "Noura": "نورة",
    "Layla": "ليلى", "Rami": "رامي",
    "Iman": "إيمان", "Omar": "عمر",
    "Jamal": "جمال", "Mouna": "منى",
    "Abdullah": "عبدالله", "Aysha": "عائشة",
    "Amal": "أمل", "Moaz": "معاذ",
    "Hamed": "حامد", "Zariyah": "زارية",
    "Amany": "أماني", "Laith": "ليث",
    "Hedi": "هادي", "Reem": "ريم",
    "Maryam": "مريم", "Saleh": "صالح",
}


# ═══════════════════════════════════════════════════
# 目录构建
# ═══════════════════════════════════════════════════

def _region_label(locale: str, lang: str) -> str:
    """生成 region 展示名。"""
    if lang == "zh":
        if locale.startswith("zh-HK"):
            return "粤语"
        if locale.startswith("zh-TW"):
            return "台湾"
        return "普通话"
    # 其它语言直接用 locale 代码（如 en-US / es-MX），准确且无歧义
    return locale


def _voice_to_dict(v: dict) -> dict | None:
    """将 edge_tts 单条 voice 转为目录条目，非项目语言返回 None。"""
    short = v.get("ShortName", "")
    if not short:
        return None
    lang_part = short.split("-")[0].lower()
    if lang_part not in PROJECT_LANGUAGES:
        return None  # 跳过非项目语言（如 ar/fa/hi 等）

    locale = v.get("Locale", "")
    gender = "female" if str(v.get("Gender", "")).lower() == "female" else "male"
    name = short.split("-")[-1].replace("Neural", "")
    region_label = _region_label(locale, lang_part)

    tag = v.get("VoiceTag", {}) or {}
    personalities = list(tag.get("VoicePersonalities", []) or [])
    categories = list(tag.get("ContentCategories", []) or [])
    style_tags = personalities + categories

    # 阿拉伯语音色：试听文案用真实阿拉伯语姓名朗读，而非拉丁转写
    local_name = ARABIC_VOICE_NAMES.get(name, name) if lang_part == "ar" else name

    preview_template = (
        VOICE_PREVIEW_TEXTS_BY_LOCALE.get(locale)
        or VOICE_PREVIEW_TEXTS.get(lang_part, VOICE_PREVIEW_TEXTS["zh"])
    )
    preview = preview_template.format(name=local_name)

    return {
        "id": short,
        "name": name,
        "local_name": local_name,
        "region": region_label,
        "region_code": locale,
        "gender": gender,
        "style_tags": style_tags,
        "preview_text": preview,
        "lang": lang_part,
    }


async def load_voice_catalog(force: bool = False) -> dict:
    """异步加载并构建分组音色目录，结果缓存到模块级变量。"""
    global _VOICE_CATALOG, _VOICE_INDEX
    if _VOICE_CATALOG is not None and not force:
        return _VOICE_CATALOG

    try:
        raw = await edge_tts.list_voices()
    except Exception as e:
        logger.warning(f"[Voices] edge_tts.list_voices failed ({e}); using fallback catalog")
        _VOICE_CATALOG = _build_fallback_catalog()
        _VOICE_INDEX = {v["id"]: v for v in _FALLBACK_VOICES}
        return _VOICE_CATALOG

    if not raw:
        _VOICE_CATALOG = _build_fallback_catalog()
        _VOICE_INDEX = {v["id"]: v for v in _FALLBACK_VOICES}
        return _VOICE_CATALOG

    # 按语言分组
    groups: dict[str, list] = {code: [] for code in PROJECT_LANGUAGES}
    index: dict[str, dict] = {}
    for v in raw:
        entry = _voice_to_dict(v)
        if entry is None:
            continue
        groups[entry["lang"]].append(entry)
        index[entry["id"]] = entry

    languages = []
    for code, voices in groups.items():
        if not voices:
            continue
        # 同语言内按 gender 再按 name 排序，体验更一致
        voices.sort(key=lambda x: (x["gender"] != "female", x["name"].lower()))
        languages.append({
            "code": code,
            "label": PROJECT_LANGUAGES[code]["label"],
            "count": len(voices),
            "voices": voices,
        })

    # 保持设计文档约定的高频语言顺序
    _order = ["zh", "en", "ja", "ko", "ru", "es", "fr", "de", "nl", "pt", "it", "id", "ms"]
    languages.sort(key=lambda g: _order.index(g["code"]) if g["code"] in _order else 99)

    _VOICE_CATALOG = {
        "languages": languages,
        "compat_hint": LANG_COMPAT,
        "fallback": False,
    }
    _VOICE_INDEX = index
    logger.info(f"[Voices] Loaded catalog: {sum(g['count'] for g in languages)} voices across {len(languages)} languages")
    return _VOICE_CATALOG


def get_voice_catalog() -> dict:
    """同步获取目录（已在服务启动时加载；未加载时返回 fallback 避免崩溃）。"""
    if _VOICE_CATALOG is None:
        logger.warning("[Voices] Catalog not loaded yet; returning fallback")
        return _build_fallback_catalog()
    return _VOICE_CATALOG


def get_voice_by_id(voice_id: str) -> dict | None:
    """按 id 查询单个音色条目。"""
    if _VOICE_INDEX is None:
        get_voice_catalog()
    return _VOICE_INDEX.get(voice_id)


# 模块级缓存
_VOICE_CATALOG: dict | None = None
_VOICE_INDEX: dict | None = None


def warmup_voice_catalog():
    """在同步上下文（如程序导入时）预加载目录。失败不抛异常。"""
    try:
        asyncio.run(load_voice_catalog())
    except Exception as e:
        logger.warning(f"[Voices] warmup failed ({e}); will use fallback")
