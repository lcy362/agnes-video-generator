"""
core/config.py — Agnes Video Generator v2.0 配置模块

包含 API Key 管理、工作目录、音频/字幕默认配置工厂函数。
"""

import json
import logging
import os

from models.task import AudioConfig, SubtitleStyle

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agnes_config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def font_dir() -> str:
    """返回项目内置字体目录。"""
    return os.path.join(_PROJECT_ROOT, "resource", "fonts")


# 默认中文字体文件名（需位于 resource/fonts/ 下）
DEFAULT_CHINESE_FONT = "STHeitiMedium.ttc"

# 不支持 CJK 字符的常见字体名（用于向后兼容旧任务）
# 这些字体在 moviepy/pillow TextClip 中无法正确渲染中文，
# 检测到后自动回退到 DEFAULT_CHINESE_FONT。
_NON_CJK_FONTS = frozenset({
    "arial", "arial bold", "arial italic", "arial black",
    "helvetica", "times", "times new roman", "courier",
    "courier new", "verdana", "tahoma", "georgia", "trebuchet ms",
    "impact", "comic sans ms", "lucida console",
})


def resolve_font_path(font: str) -> str:
    """将字体名称解析为 moviepy TextClip 可用的路径。

    优先级：
    1. 绝对路径且文件存在 → 直接返回
    2. 文件名（含扩展名）→ 在 resource/fonts/ 目录下查找
    3. 已知的非 CJK 字体名 → 回退到 DEFAULT_CHINESE_FONT（兼容旧任务）
    4. 其他系统字体名 → 直接返回
    """
    # 已经是绝对路径，直接返回
    if os.path.isabs(font) and os.path.exists(font):
        return font

    # 看起来像文件名（含扩展名），尝试在项目字体目录查找
    if "." in font and "/" not in font and "\\" not in font:
        candidate = os.path.join(font_dir(), font)
        if os.path.exists(candidate):
            return candidate

    # 检查是否为已知的非 CJK 字体（向后兼容：旧任务的 font 可能仍为 "Arial"）
    if font.strip().lower() in _NON_CJK_FONTS:
        fallback = os.path.join(font_dir(), DEFAULT_CHINESE_FONT)
        if os.path.exists(fallback):
            logger.warning(
                f"Font '{font}' does not support CJK characters, "
                f"falling back to {DEFAULT_CHINESE_FONT}"
            )
            return fallback

    # 当作系统字体名称返回
    return font


# ═══════════════════════════════════════════════════
# API Key 管理（保持现有逻辑）
# ═══════════════════════════════════════════════════


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config() -> dict:
    _ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    _ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_api_key() -> str:
    env_key = os.environ.get("AGNES_API_KEY", "")
    if env_key:
        return env_key
    config = load_config()
    return config.get("api_key", "")


def set_api_key(key: str):
    config = load_config()
    config["api_key"] = key
    save_config(config)


def delete_api_key() -> bool:
    """Remove the API key from the config file.

    Returns:
        True if a key was removed, False if no key existed.

    Note:
        This does NOT affect the AGNES_API_KEY environment variable.
        If the env var is set, get_api_key() will still return it.
    """
    config = load_config()
    if "api_key" in config:
        del config["api_key"]
        save_config(config)
        return True
    return False


def get_api_key_source() -> str:
    """Return the source of the current API key.

    Returns:
        'env' if from AGNES_API_KEY environment variable,
        'config' if from the config file,
        'none' if no key is configured.
    """
    if os.environ.get("AGNES_API_KEY", ""):
        return "env"
    config = load_config()
    if config.get("api_key"):
        return "config"
    return "none"


def get_working_dir() -> str:
    return os.path.join(os.getcwd(), ".working_dir")


# ═══════════════════════════════════════════════════
# v2.0 新增：音频 / 字幕默认配置
# ═══════════════════════════════════════════════════

# D3：默认语音角色
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# D3：可选中文语音角色列表
AVAILABLE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "label": "Xiaoxiao（温柔女声）"},
    {"id": "zh-CN-YunyangNeural", "label": "Yunyang（沉稳男声）"},
    {"id": "zh-CN-XiaoyiNeural", "label": "Xiaoyi（活泼女声）"},
    {"id": "zh-CN-YunxiNeural", "label": "Yunxi（年轻男声）"},
]


def get_default_subtitle_style() -> SubtitleStyle:
    """返回默认字幕样式配置（D4）。"""
    return SubtitleStyle(
        font=DEFAULT_CHINESE_FONT,
        color="white",
        position=("center", "bottom-80"),
        fontsize=48,
        stroke_color="black",
        stroke_width=2,
        bg_color=(0, 0, 0, 128),
    )


def get_default_audio_config() -> AudioConfig:
    """返回默认音频配置（含字幕样式）（D3）。"""
    return AudioConfig(
        enabled=True,
        voice=DEFAULT_VOICE,
        rate="+0%",
        subtitle_style=get_default_subtitle_style(),
    )


# ═══════════════════════════════════════════════════
# 视频参数预设（D7）
# ═══════════════════════════════════════════════════

VIDEO_RESOLUTION_PRESETS = {
    "portrait": {"width": 768, "height": 1152, "label": "竖屏 9:16"},
    "landscape": {"width": 1152, "height": 768, "label": "横屏 16:9"},
    "square": {"width": 1024, "height": 1024, "label": "方形 1:1"},
}

# 时长 → (num_frames, frame_rate) 映射
DURATION_FRAME_MAP = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (441, 24),
    20: (441, 22),
}
