"""core/gallery_cache.py — 产物画廊缩略图缓存（P1 v1.x，可选增强）。

缩略图放**独立缓存目录** ``.agnes_config/gallery_cache/``，**不在任务目录内，
不破坏任务目录结构**。惰性生成：首次访问时对未缓存的成片用 ffmpeg 抽单帧，
缓存后复用。该目录属可重建 Cache，而非任务产物；画廊仍**纯只读**，不触碰删除。
"""
from __future__ import annotations

import logging
import os
import subprocess

from core.compositor.ffmpeg_tool import resolve_binary
from core.config import CONFIG_DIR

logger = logging.getLogger(__name__)

_THUMB_DIR = os.path.join(CONFIG_DIR, "gallery_cache")
_THUMB_EXT = ".jpg"


def _thumb_path(task_id: str) -> str:
    return os.path.join(_THUMB_DIR, task_id + _THUMB_EXT)


def has_thumb(task_id: str) -> bool:
    return os.path.isfile(_thumb_path(task_id))


def ensure_thumb(task_id: str, final_video_file: str) -> str | None:
    """确保指定视频成片的缩略图存在，缺失时惰性抽帧生成。

    Args:
        task_id: 任务 id（用作缓存文件名，天然唯一）。
        final_video_file: 成片绝对路径。

    Returns:
        缩略图路径；若成片不存在或抽帧失败返回 None（前端回退原生首帧）。
    """
    out = _thumb_path(task_id)
    if os.path.isfile(out):
        return out
    if not final_video_file or not os.path.isfile(final_video_file):
        return None
    try:
        os.makedirs(_THUMB_DIR, exist_ok=True)
        # 抽成片 1s 处一帧作封面，宽高限制到 480p 以控制体积
        subprocess.run([
            resolve_binary("ffmpeg"), "-y",
            "-ss", "1",
            "-i", final_video_file,
            "-frames:v", "1",
            "-vf", "scale=480:-2",
            "-q:v", "4",
            out,
        ], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)
        return out
    except Exception as e:
        logger.warning("[GalleryCache] Failed to build thumbnail for %s: %s", task_id, e)
        return None