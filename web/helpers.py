"""Web 层纯工具函数（Batch 1 从 server.py 拆出）。

全部为无路由装饰器的函数：字幕样式解析、音色试听/兼容校验、
时长提取、图片 prompt 构建、任务目录查找、原生目录选择。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import re
import subprocess
import tempfile

import edge_tts
from fastapi import HTTPException

from core.audio.voices import (
    LANG_COMPAT,
    PROJECT_LANGUAGES,
    VOICE_PREVIEW_TEXTS,
    get_voice_lang,
    is_voice_compatible,
    is_voice_compatible_with_text,
)
from core.config import get_working_dir
from core.task_manager import TaskManager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 字幕样式解析
# ═══════════════════════════════════════════════════

def _parse_bg_color(raw: str) -> tuple:
    """将 bg_color 字符串解析为 moviepy 2.x 兼容的 RGBA 元组。"""
    if isinstance(raw, tuple):
        return raw
    if isinstance(raw, str):
        if raw.startswith("(") and raw.endswith(")"):
            return tuple(int(x.strip()) for x in raw[1:-1].split(","))
        if "@" in raw:
            parts = raw.split("@", 1)
            color_name = parts[0].strip().lower()
            alpha_pct = float(parts[1])
            rgb = {"black": (0, 0, 0), "white": (255, 255, 255),
                   "red": (255, 0, 0), "blue": (0, 0, 255),
                   "yellow": (255, 255, 0)}.get(color_name, (0, 0, 0))
            return (*rgb, int(alpha_pct * 255))
        if raw.lower() in ("none", "transparent", ""):
            return None
    return (0, 0, 0, 128)


def _build_position(subtitle_position: str) -> tuple:
    """将 'bottom'/'top' 转为 moviepy 兼容的位置元组。"""
    if subtitle_position == "top":
        return ("center", "top")
    return ("center", "bottom")


# ═══════════════════════════════════════════════════
# 音色试听缓存 + 兼容性校验
# ═══════════════════════════════════════════════════

# 试听音频缓存目录（系统临时目录，重启后自动清理）
VOICE_PREVIEW_CACHE_DIR = os.path.join(tempfile.gettempdir(), "agnes-voice-previews")
os.makedirs(VOICE_PREVIEW_CACHE_DIR, exist_ok=True)


def _preview_cache_key(voice_id: str, text: str) -> str:
    """生成试听缓存文件名：{md5(voice_id)}__{md5(text)}.mp3

    对 voice_id 一并做哈希，避免用户可控的 voice_id（可能含路径分隔符 / ``..``）
    流入缓存文件路径造成路径穿越。
    """
    voice_hash = hashlib.md5(voice_id.encode("utf-8")).hexdigest()
    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    return f"{voice_hash}__{text_hash}"


async def _get_or_generate_preview(voice_id: str, text: str) -> str:
    """获取试听音频：缓存命中直接返回路径，否则调用 edge_tts 生成后缓存。

    写入使用 .tmp + os.replace 原子替换，避免并发读到半成品。
    """
    cache_key = _preview_cache_key(voice_id, text)
    cache_path = os.path.join(VOICE_PREVIEW_CACHE_DIR, cache_key + ".mp3")
    if os.path.exists(cache_path):
        return cache_path  # 缓存命中

    tmp_path = cache_path + ".tmp"
    communicate = edge_tts.Communicate(text, voice=voice_id)
    await communicate.save(tmp_path)
    os.replace(tmp_path, cache_path)  # 原子替换
    return cache_path


def _resolve_preview_text(voice_id: str, text: str) -> str:
    """解析试听文本：显式传入优先，否则用该音色语言的预设试听句。"""
    if text:
        return text
    vlang = get_voice_lang(voice_id) or "zh"
    name = voice_id.split("-")[-1].replace("Neural", "")
    return VOICE_PREVIEW_TEXTS.get(vlang, VOICE_PREVIEW_TEXTS["zh"]).format(name=name)


def _validate_voice_compat(audio_voice: str, target_lang: str, text: str = None):
    """校验 voice 与目标任务语言的兼容性，不兼容时抛出 422。

    - target_lang: 页面语言（创意/诗歌/主播等由 LLM 按页面语言生成文本）
    - text: 稿件正文（manuscript），已知文本时做更精确的脚本级检测
    """
    if not audio_voice:
        return
    if text is not None and text.strip():
        if not is_voice_compatible_with_text(audio_voice, text):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"所选音色 {audio_voice} 不支持当前稿件语言的朗读"
                    f"（跨文字体系无法朗读，任务将失败）。请更换为匹配语言的音色。"
                ),
            )
        return
    if target_lang and not is_voice_compatible(audio_voice, target_lang):
        lang_label = PROJECT_LANGUAGES.get(target_lang, {}).get("label", target_lang)
        supported = LANG_COMPAT.get(get_voice_lang(audio_voice) or "", [])
        supported_labels = [PROJECT_LANGUAGES.get(c, {}).get("label", c) for c in supported]
        raise HTTPException(
            status_code=422,
            detail=(
                f"所选音色 {audio_voice} 不支持「{lang_label}」语言的视频生成"
                f"（仅支持：{', '.join(supported_labels)}）。请更换音色或语言。"
            ),
        )


def get_upload_dir() -> str:
    """返回当前激活工作目录下的 uploads 子目录。"""
    return os.path.join(get_working_dir(), "uploads")


# ═══════════════════════════════════════════════════
# 时长提取（支持 7 种语言）
# ═══════════════════════════════════════════════════

_DURATION_PATTERNS = [
    # 中文
    r'(?:每个场景|每段|每节|每个|每)(?:约)?(\d+)\s*(?:秒|s)',
    r'(\d+)\s*(?:秒|s)\s*(?:每|/)',
    # 日文
    r'各\s*(\d+)\s*秒',
    # 英文
    r'(\d+)\s*(?:seconds?|secs?|s)\s*(?:each|per)',
    r'(?:each|per)\s*(?:scene)?\s*(\d+)\s*(?:seconds?|secs?|s)',
    # 韩文
    r'각\s*(\d+)\s*초',
    # 俄文
    r'по\s*(\d+)\s*секунд',
    # 马来/印尼
    r'(\d+)\s*(?:saat|detik)\s*(?:setiap|masing)',
    r'(?:setiap|masing)\s*(?:satu\s+)?(\d+)\s*(?:saat|detik)',
    # 通用回退
    r'(\d+)\s*(?:秒|seconds?|secs?|초|секунд|saat|detik|s)\b',
]


def _parse_duration(user_requirement: str) -> int:
    """从 user_requirement 中提取时长。支持 7 种语言。"""
    for pattern in _DURATION_PATTERNS:
        match = re.search(pattern, user_requirement, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 5


def _has_explicit_duration(user_requirement: str) -> bool:
    """检查 user_requirement 中是否显式提到了时长。支持 7 种语言。"""
    for pattern in _DURATION_PATTERNS:
        if re.search(pattern, user_requirement, re.IGNORECASE):
            return True
    return False


# ═══════════════════════════════════════════════════
# 图片 prompt 构建 + 任务目录查找
# ═══════════════════════════════════════════════════

def _build_encrypted_image_prompt(system_prompt: str, user_prompt: str) -> str:
    """Base64 加密图片描述，在系统提示词末尾写明解密方法。"""
    import base64
    encoded = base64.b64encode(user_prompt.encode("utf-8")).decode("ascii")
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', system_prompt))
    if has_chinese:
        decryption = (
            "解密方法：以下图片描述为 base64 编码。"
            "请先进行 base64 解码以获取实际描述，"
            "然后根据解码后的描述生成图片。"
            "不要直接根据编码文本生成图片。\n\n"
            f"加密描述：\n{encoded}"
        )
    else:
        decryption = (
            "Decryption method: The image description below is base64-encoded. "
            "Base64-decode it to get the actual description, "
            "then generate the image based on the decoded description. "
            "Do NOT generate based on the encoded text itself.\n\n"
            f"Encrypted description:\n{encoded}"
        )
    return f"{system_prompt}\n\n{decryption}"


def find_dir_name(task_id: str) -> str:
    """Find the directory name for a task_id. Falls back to task_id for legacy tasks."""
    tm = TaskManager("_")
    for t in tm.list_tasks():
        if t["task_id"] == task_id:
            return t.get("dir_name", task_id)
    return task_id


# ═══════════════════════════════════════════════════
# 原生目录选择（macOS / Windows / Linux）
# ═══════════════════════════════════════════════════

def _pick_directory_native() -> str:
    """同步调用系统原生目录选择器，返回路径或空字符串。"""
    system = platform.system()
    try:
        if system == "Darwin":
            script = (
                'set chosenFolder to choose folder with prompt "选择工作目录"'
                "\nreturn POSIX path of chosenFolder"
            )
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        elif system == "Windows":
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        else:
            for cmd in (["zenity", "--file-selection", "--directory"],
                        ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout.strip()
                    break
                except FileNotFoundError:
                    continue
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(f"[Workspace] Directory picker failed: {e}")
    return ""


async def pick_directory():
    """弹出操作系统原生目录选择框，返回所选目录路径。

    跨平台实现：
    - macOS: osascript
    - Linux: zenity（若不可用回退 kdialog）
    - Windows: PowerShell Forms.FolderBrowserDialog
    """
    path = await asyncio.to_thread(_pick_directory_native)
    if not path:
        return {"ok": False, "path": ""}
    return {"ok": True, "path": path}
