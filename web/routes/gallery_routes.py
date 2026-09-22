"""产物画廊路由（P1）— 纯只读展示。

对每个任务复用 ``TaskManager.list_tasks()`` 的轻扫描 + 读取 state 顶层
``final_video_file`` 字段推导 media url，**不读 manifest/checkpoint 实体**，
**不向任何任务目录写入文件**，也**不暴露任何删除端点**。

画廊数据完全由现有目录扫描 + 成片路径逻辑聚合而来，满足「以现有目录结构为
基础、通过逻辑实现功能」与「只读不删」的核心约束。
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from core.task_manager import TaskManager
from models.task import StepStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gallery"])

_MEDIA_KIND_IMAGE = "image"
_MEDIA_KIND_VIDEO = "video"

# 各任务类型的描述字段（按优先级取第一个非空，作为卡片简介）
_DESC_FIELDS = (
    "idea",
    "manuscript_text",
    "script_text",
    "poem_text",
    "prompt",
)


def _derive_media(task: dict) -> dict:
    """由任务轻字段推导媒体 kind 与访问 URL（纯逻辑，不落盘新文件）。

    - 图片任务（task_type == image）→ ``GET /api/image/{task_id}``（已有端点）
    - 其它任务 → 复用产物 preview_url 拼接规则
      ``/api/tasks/{id}/artifacts/{task_type}:final_video/file``
      （与 ``core.artifacts.build_manifest`` 的 artifact_id 一致）
    """
    task_id = task["task_id"]
    task_type = task["task_type"]
    if task_type == "image":
        return {_MEDIA_KIND_IMAGE: task_id, "is_image": True}
    kind = _MEDIA_KIND_VIDEO
    artifact_id = f"{task_type}:final_video"
    return {"kind": kind, "is_image": False, "artifact_id": artifact_id}


@router.get("/api/gallery")
async def gallery(filter: str = "all", status: str = "all"):
    """画廊数据聚合（只读）。

    Args:
        filter: all | video | image — 按媒体类型过滤。
        status: all | completed | failed — 按任务状态过滤。

    Returns:
        ``{"ok": True, "items": [{task_id, dir_name, task_type, status, kind,
          description, media_url}], "total": int}``
    """
    tm = TaskManager("_")
    tasks = tm.list_tasks()

    items = []
    for t in tasks:
        # 跳过无状态字段的保护性兜底
        task_type = t.get("task_type") or "creative"
        task_status = t.get("status") or "pending"

        # 状态过滤
        if status != "all" and task_status != status:
            continue

        task_tm = TaskManager(t["task_id"], dir_name=t.get("dir_name"))
        state = task_tm.load()
        if not state:
            continue
        final_file = getattr(state, "final_video_file", None)
        # 只有真正产出终版的产物才进画廊（无产物 or 文件已不存在则跳过）
        if not final_file or not os.path.isfile(final_file):
            continue

        # 类型过滤（在推导 kind 后，用 kind 判断视频/图片）
        derived = _derive_media(t)

        # 描述摘要
        description = ""
        for field in _DESC_FIELDS:
            val = getattr(state, field, "") or ""
            if isinstance(val, str) and val.strip():
                description = val.strip()[:120]
                break

        # media url
        if task_type == "image":
            media_url = f"/api/image/{t['task_id']}"
        else:
            media_url = (
                f"/api/tasks/{t['task_id']}/artifacts/"
                f"{derived['artifact_id']}/file"
            )

        if filter != "all":
            kind = "image" if derived["is_image"] else "video"
            if kind != filter:
                continue

        items.append({
            "task_id": t["task_id"],
            "dir_name": t.get("dir_name", ""),
            "task_type": task_type,
            "status": task_status,
            "kind": "image" if derived["is_image"] else "video",
            "description": description,
            "title": t.get("creative_name") or t["task_id"],
            "media_url": media_url,
        })

    return {"ok": True, "items": items, "total": len(items)}