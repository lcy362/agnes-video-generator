"""core/gallery_cache.py — 产物画廊缩略图缓存（P1 v1.x，可选增强）。

缩略图放**独立缓存目录** ``.agnes_config/gallery_cache/``，**不在任务目录内，
不破坏任务目录结构**。惰性生成：首次访问时对未缓存的成片用 ffmpeg 抽单帧，
缓存后复用。该目录属可重建 Cache，而非任务产物；画廊仍**纯只读**，不触碰删除。

安全约定：缓存文件名由 ``task_id`` 派生，而 ``task_id`` 最终来自 URL 路径参数，
属不可信输入。故本模块对 ``task_id`` 做**文件名形态白名单校验**，并用
``safe_join`` 保证 realpath 规范化后仍被限制在缓存目录内，杜绝路径穿越；
送入 ffmpeg 的成片路径同样经 ``safe_workspace_path`` 规范化，杜绝参数注入。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess

from core.compositor.ffmpeg_tool import resolve_binary
from core.config import CONFIG_DIR
from core.path_security import UnsafePathError, safe_join, safe_workspace_path

logger = logging.getLogger(__name__)

_THUMB_DIR = os.path.join(CONFIG_DIR, "gallery_cache")
_THUMB_EXT = ".jpg"

# task_id 白名单形态：仅字母 / 数字 / 下划线 / 点 / 连字符，长度 1~64。
# 不含路径分隔符即无法拼出穿越片段，也不会被解析成命令行选项（防参数注入）。
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _thumb_path(task_id: str) -> str | None:
    """由 task_id 派生缓存文件绝对路径；形态非法时返回 None。

    两步收敛不可信输入：① 白名单形态校验；② ``safe_join`` 做 realpath
    规范化 + 缓存目录 containment 校验（越界抛 ``UnsafePathError``）。
    """
    if not _TASK_ID_RE.fullmatch(task_id or ""):
        return None
    try:
        return safe_join(_THUMB_DIR, task_id + _THUMB_EXT)
    except UnsafePathError:
        return None


def has_thumb(task_id: str) -> bool:
    """判断某任务是否已有缓存缩略图（task_id 非法或未缓存均为 False）。"""
    path = _thumb_path(task_id)
    return bool(path) and os.path.isfile(path)


def ensure_thumb(task_id: str, final_video_file: str) -> str | None:
    """确保指定视频成片的缩略图存在，缺失时惰性抽帧生成。

    Args:
        task_id: 任务 id（用作缓存文件名，天然唯一）。
        final_video_file: 成片绝对路径。

    Returns:
        缩略图路径；若成片不存在或抽帧失败返回 None（前端回退原生首帧）。
    """
    out = _thumb_path(task_id)
    if not out:
        logger.warning("[GalleryCache] Rejected invalid task id for thumbnail cache")
        return None
    if os.path.isfile(out):
        return out
    if not final_video_file or not os.path.isfile(final_video_file):
        return None
    try:
        # realpath 规范化 + 受信任根 containment：中和成片路径注入
        source = safe_workspace_path(final_video_file)
    except UnsafePathError:
        logger.warning("[GalleryCache] Rejected unsafe source video path for thumbnail")
        return None
    try:
        os.makedirs(_THUMB_DIR, exist_ok=True)
        # 抽成片 1s 处一帧作封面，宽高限制到 480p 以控制体积
        subprocess.run([
            resolve_binary("ffmpeg"), "-y",
            "-ss", "1",
            "-i", source,
            "-frames:v", "1",
            "-vf", "scale=480:-2",
            "-q:v", "4",
            out,
        ], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)
        return out
    except Exception as e:
        logger.warning("[GalleryCache] Failed to build thumbnail for %s: %s", task_id, e)
        return None