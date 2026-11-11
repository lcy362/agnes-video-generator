"""视频下载 + 中间产物管理路由。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.api.agnes_image import AgnesImageAPI
from core.api.chat_providers import get_or_build_text_chat_client
from core.artifacts import (
    apply_cascade_plan,
    build_checkpoint_manifest,
    get_cascade_plan,
    list_artifacts,
    resolve_artifact,
    write_checkpoint_manifest,
)
from core.async_io import read_text, write_bytes
from core.config import api_key_missing_msg, get_api_key, get_working_dir
from core.dependency_graph import get_dependency_graph
from core.i18n_backend import translate
from core.path_security import UnsafePathError, safe_join
from core.task_manager import TaskManager
from models.task import StepStatus
from utils.image import normalize_external_image
from utils.network import describe_network_error
from utils.video import normalize_external_video, probe_media
from web import app_state, helpers
from web.log_safe import safe_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["video", "artifacts"])

# 产物类别 → MIME 类型映射
_ARTIFACT_MEDIA_TYPES = {
    "image": "image/png",
    "video": "video/mp4",
    "audio": "audio/mpeg",
    "text": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "subtitle": "text/plain; charset=utf-8",
}


@router.get("/api/video/{task_id}")
async def serve_video(task_id: str):
    dir_name = helpers.find_dir_name(task_id)
    try:
        task_dir = safe_join(get_working_dir(), dir_name)
    except UnsafePathError:
        raise HTTPException(status_code=404, detail="Video not found")
    video_path = os.path.join(task_dir, "final_video.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path, media_type="video/mp4")


@router.get("/api/tasks/{task_id}/artifacts")
async def list_task_artifacts(task_id: str):
    """列举任务的所有中间产物（含存在性检测）。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifacts = list_artifacts(state, tm.task_dir)
    return {
        "ok": True,
        "task_type": state.task_type.value,
        "task_status": state.status.value if state.status else "pending",
        "dir_name": dir_name,
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "step_key": a.step_key,
                "label_key": a.label_key,
                "category": a.category,
                "scope": a.scope,
                "scope_index": a.scope_index,
                "exists": a.exists,
                "size": a.size,
                "deletable": a.deletable,
                # v5.x 产物规范前置：暴露相对路径 / 字段说明 / 预览 URL
                "file_relpath": a.file_relpath,
                "schema_hint": a.schema_hint,
                "preview_url": (
                    f"/api/tasks/{task_id}/artifacts/{a.artifact_id}/file"
                    if a.file_relpath else ""
                ),
            }
            for a in artifacts
        ],
    }


@router.get("/api/tasks/{task_id}/artifacts/{artifact_id}/file")
async def serve_artifact_file(task_id: str, artifact_id: str):
    """安全地服务中间产物文件。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact or not artifact.file_relpath:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact.exists:
        raise HTTPException(status_code=404, detail="Artifact file not found")

    abs_path = os.path.join(tm.task_dir, artifact.file_relpath)
    # 路径穿越防护
    real_task_dir = os.path.realpath(tm.task_dir)
    real_abs_path = os.path.realpath(abs_path)
    if not real_abs_path.startswith(real_task_dir + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")

    media_type = _ARTIFACT_MEDIA_TYPES.get(artifact.category, "application/octet-stream")
    return FileResponse(real_abs_path, media_type=media_type)


@router.get("/api/tasks/{task_id}/manifest")
async def get_task_manifest(task_id: str):
    """返回任务产物清单（manifest.json）。

    清单由流水线运行开始/结束时自动落盘；若不存在（如排队中或旧任务）
    则现场构建并写盘。包含结构化产物（path/schema_hint/preview_url）
    与通用文件树两部分，是 v6.0 手动模式 checkpoint 的数据基础。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    from core.artifacts import build_manifest, write_manifest

    manifest_path = os.path.join(tm.task_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        write_manifest(state, tm.task_dir)
    try:
        manifest = json.loads(await read_text(manifest_path))
    except (OSError, ValueError):
        # 清单损坏/不可读 → 现场重建
        manifest = build_manifest(state, tm.task_dir)
    return {"ok": True, **manifest}


@router.get("/api/tasks/{task_id}/manifest.md")
async def get_task_manifest_md(task_id: str):
    """返回任务目录说明文件 MANIFEST.md（供用户与外部 Agent 阅读）。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    from core.artifacts import write_manifest_md

    md_path = os.path.join(tm.task_dir, "MANIFEST.md")
    if not os.path.exists(md_path):
        write_manifest_md(state, tm.task_dir)
    if not os.path.exists(md_path):
        raise HTTPException(status_code=404, detail="Manifest not available")
    return FileResponse(md_path, media_type="text/markdown; charset=utf-8")


@router.get("/api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview")
async def preview_artifact_cascade(task_id: str, artifact_id: str):
    """预览删除产物的级联计划（不执行删除）。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    plan = get_cascade_plan(artifact_id, state, tm.task_dir)
    if not plan:
        raise HTTPException(status_code=400, detail="Cannot compute cascade plan")

    # 只返回存在的文件
    existing_files = []
    for f in plan.files_to_delete:
        abs_path = os.path.join(tm.task_dir, f)
        if os.path.exists(abs_path):
            existing_files.append(f)

    return {
        "ok": True,
        "artifact_id": artifact_id,
        "files_to_delete": existing_files,
        "steps_to_reset": plan.steps_to_reset,
    }


@router.delete("/api/tasks/{task_id}/artifacts/{artifact_id}")
async def delete_task_artifact(task_id: str, artifact_id: str):
    """删除指定中间产物（含级联删除后续产物 + 状态回退）。"""
    # 运行中任务保护（已停止的 pipeline 允许删除产物）
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        if not pipeline._stop_event.is_set():
            raise HTTPException(status_code=409, detail="Task is running, please stop it first")

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    plan = get_cascade_plan(artifact_id, state, tm.task_dir)
    if not plan:
        raise HTTPException(status_code=400, detail="Cannot compute cascade plan")

    # 1. 删除文件
    deleted_files = []
    real_task_dir = os.path.realpath(tm.task_dir)
    for f in plan.files_to_delete:
        abs_path = os.path.join(tm.task_dir, f)
        real_abs_path = os.path.realpath(abs_path)
        # 路径穿越防护
        if not real_abs_path.startswith(real_task_dir + os.sep):
            continue
        if os.path.exists(abs_path) and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                deleted_files.append(f)
            except OSError as e:
                logger.warning(f"[Artifacts] Failed to delete {f}: {e}")

    # 2. 应用级联计划到 state
    update_kwargs = apply_cascade_plan(state, plan)

    # 3. 持久化
    tm.update_state(**update_kwargs)

    logger.info(
        "[Artifacts] Deleted %d files for task %s, artifact=%s, reset_steps=%s",
        len(deleted_files), safe_log(task_id), safe_log(artifact_id),
        plan.steps_to_reset,
    )

    return {
        "ok": True,
        "deleted_files": deleted_files,
        "reset_steps": plan.steps_to_reset,
        "task_status": state.status.value if state.status else "pending",
    }


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务及其磁盘上全部生成文件（优化 3）。

    运行中/排队中任务拒绝删除。删除范围：任务工作目录（含状态文件、全部产物、
    上传文件）。删除后任务从任务列表消失，不可恢复。
    """
    # 1. 运行中保护（含排队中）
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines.get(task_id)
        if pipeline is not None and not getattr(pipeline, "_stop_event", None).is_set():
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a running task. Stop it first.",
            )
    if task_id in app_state._queued_tasks:
        raise HTTPException(
            status_code=400,
            detail="Task is queued. Stop it before deleting.",
        )

    # 2. 定位任务工作目录
    dir_name = helpers.find_dir_name(task_id)
    removed_dir = False
    if dir_name:
        # 路径穿越防护：先经 realpath 解析，确认目录位于工作目录内才允许删除
        real_root = os.path.realpath(get_working_dir())
        real_task_dir = os.path.realpath(os.path.join(get_working_dir(), dir_name))
        if real_task_dir != real_root and real_task_dir.startswith(real_root + os.sep):
            if os.path.exists(real_task_dir):
                shutil.rmtree(real_task_dir, ignore_errors=True)
                removed_dir = True
                logger.info("[Delete] Task %s directory removed: %s",
                            safe_log(task_id), real_task_dir)
        else:
            logger.warning("[Delete] Unsafe task dir for %s, skipped: %s",
                           safe_log(task_id), safe_log(dir_name))

    # 3. 从活动注册表 / 排队列表摘除
    app_state.active_pipelines.pop(task_id, None)
    app_state._queued_tasks.pop(task_id, None)
    app_state.release_pipeline_lock(task_id)
    # GA 埋点：同步清理上游报错内存聚合（防缓慢增长）
    try:
        from core.api.error_collector import clear_task_upstream_errors

        clear_task_upstream_errors(task_id)
    except Exception:
        pass

    if not removed_dir and not _task_exists(task_id):
        # 任务目录不存在且任务已不在列表中：视为不存在
        raise HTTPException(status_code=404, detail="Task not found")

    return {"ok": True, "task_id": task_id, "message": "Task deleted", "removed_dir": removed_dir}


def _task_exists(task_id: str) -> bool:
    """检查任务是否仍存在于任务列表（状态文件存在）。"""
    from core.task_manager import TaskManager

    tm = TaskManager("_")
    for t in tm.list_tasks():
        if t["task_id"] == task_id:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# v6.0 手动模式：检查点 + 影响预计算 + 产物回填 + 确认/重生成
# ═══════════════════════════════════════════════════════════════


@router.get("/api/tasks/{task_id}/checkpoints")
async def list_task_checkpoints(task_id: str):
    """返回任务按检查点分组的产物清单（checkpoint.json 数据）。

    供手动模式检查点等待页使用；若 checkpoint.json 未落盘则现场构建。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    ckpt_path = os.path.join(tm.task_dir, "checkpoint.json")
    if not os.path.exists(ckpt_path):
        write_checkpoint_manifest(state, tm.task_dir)
    try:
        data = json.loads(await read_text(ckpt_path))
    except (OSError, ValueError):
        data = build_checkpoint_manifest(state, tm.task_dir)

    # 补充当前检查点（实时读取状态，避免 checkpoint.json 过期）
    mc = getattr(state, "manual_config", None)
    data["current_checkpoint"] = (mc.current_checkpoint if mc else "") or ""
    return {"ok": True, **data}


@router.get("/api/tasks/{task_id}/checkpoints/{checkpoint}")
async def get_task_checkpoint(task_id: str, checkpoint: str):
    """返回单个检查点的产物列表与状态。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    data = build_checkpoint_manifest(state, tm.task_dir)
    groups = data.get("checkpoints", {})
    if checkpoint not in groups:
        raise HTTPException(status_code=404, detail=f"Checkpoint '{checkpoint}' not found")

    # 补产物绝对路径 + 任务目录（供通道 2/3 展示产物路径）
    group = groups[checkpoint]
    for a in group.get("artifacts", []):
        rel = a.get("path") or ""
        a["abs_path"] = os.path.join(tm.task_dir, rel) if rel else ""
    # v8.1：references 检查点额外下发逐段摘要（供「逐段补图」面板渲染）。
    # 只回显序号 / 文本片段 / 已有参考图数量，不暴露服务器绝对路径。
    scene_items = []
    if checkpoint == "references":
        for idx, scene in enumerate(getattr(state, "scenes", None) or []):
            refs = [p for p in (getattr(scene, "ref_images", None) or []) if p]
            scene_items.append({
                "index": idx,
                "text": (
                    getattr(scene, "narration_text", "")
                    or getattr(scene, "scene_prompt", "")
                    or ""
                )[:160],
                "ref_count": len(refs),
                "ref_files": [os.path.basename(p) for p in refs],
            })

    return {
        "ok": True,
        "checkpoint": checkpoint,
        "working_dir": tm.task_dir,
        "external_hint": _build_external_hint(state, checkpoint, tm.task_dir),
        "scenes": scene_items,
        **group,
    }


def _build_external_hint(state, checkpoint: str, working_dir: str):
    """构建外部素材模式检查点提示（v7.6）；非外部任务返回 None。

    Returns:
        ``{provider:{id,name,name_key,icon,url,experimental,guide_path,faq_path},
        prompt, fill_guide, notes, notes_key}``
        或 None（非 external / 该工具未定义此检查点提示词）。

    ``provider.experimental`` / ``guide_path`` / ``faq_path`` 驱动前端「试验中」
    气泡与官网说明链接（路径不含语言前缀，由前端按 UI 语言拼接）。
    """
    mc = getattr(state, "manual_config", None)
    if mc is None or getattr(mc, "execution_mode", "auto") != "external":
        return None
    from core.providers import get_provider, render_prompt

    p = get_provider(getattr(mc, "provider", "") or "")
    if checkpoint not in p.checkpoint_prompts and checkpoint not in p.fill_guide:
        return None
    durations = getattr(state, "scene_durations", None) or []
    scene_count = getattr(state, "scene_count", 0) or len(durations)
    extra = {
        "scene_count": scene_count,
        "total_duration": sum(d for d in durations if isinstance(d, (int, float))),
    }
    # v7.6：`videos` 检查点给的是「用户直接粘贴到即梦」的视频生成提示词（分镜脚本
    # 本身），而非操作流程说明；其余检查点仍用声明的协作模板。
    if checkpoint == "videos":
        prompt = build_external_video_prompts(state, working_dir)
    else:
        prompt = render_prompt(p.id, checkpoint, working_dir, extra)
    return {
        "provider": {
            "id": p.id, "name": p.name, "name_key": p.name_key, "icon": p.icon,
            "url": p.url,
            # 试验阶段标记 + 官网说明页路径（前端拼上 UI 语言前缀后渲染）
            "experimental": p.experimental,
            "guide_path": p.guide_path,
            "faq_path": p.faq_path,
        },
        "prompt": prompt,
        "fill_guide": p.fill_guide.get(checkpoint, ""),
        "notes": p.notes,
        "notes_key": p.notes_key,
    }


_SCENE_PROMPT_KEYS = ("scene_prompt", "description", "prompt", "text")


def _scene_prompt_of(item) -> str:
    """从分镜条目提取可用作即梦提示词的画面描述。

    容忍三种形态：``SceneTask`` / ``Paragraph`` 等模型对象（读属性）、
    ``dict``（读键）、纯字符串（原样返回）。**不得**把非字符串对象
    ``str()`` 化——那会把模型 repr 当成提示词下发。
    """
    if isinstance(item, dict):
        candidates = (item.get(k) for k in _SCENE_PROMPT_KEYS)
    elif isinstance(item, str):
        return item.strip()
    else:
        candidates = (getattr(item, k, None) for k in _SCENE_PROMPT_KEYS)
    for v in candidates:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def build_external_video_prompts(state, working_dir: str) -> str:
    """按场景组装「可直接粘贴到即梦」的视频生成提示词（v7.6）。

    数据来源按优先级：``state.scenes[].scene_prompt``（poetry / manuscript /
    已登记场景）→ 分镜脚本文件 ``state.script_file``（creative：分镜描述落在
    ``script.json``，``scenes[].scene_prompt`` 为空）→ ``state.paragraphs``
    （稿件兜底）。每个场景附「场景序号 / 总时长」，便于用户逐段生成。

    Returns:
        已就绪的提示词文本；无可用分镜数据时返回空串。
    """
    texts = [_scene_prompt_of(s) for s in (getattr(state, "scenes", None) or [])]
    if not any(texts):
        script_file = getattr(state, "script_file", "") or ""
        if script_file:
            path = script_file if os.path.isabs(script_file) else os.path.join(working_dir, script_file)
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        texts = [_scene_prompt_of(it) for it in data]
                except (OSError, ValueError):
                    logger.warning("[Diagnostics] external videos: failed to read %s", path)
    if not any(texts):
        texts = [_scene_prompt_of(p) for p in (getattr(state, "paragraphs", None) or [])]

    texts = [t for t in texts if t]
    if not texts:
        return ""
    # v7.6 外部素材模式 · 对白字幕来源：各场景台词附在提示词末尾，
    # 便于用户在外部工具生成视频时同步产出画面内对白。
    dialogues: list = []
    mc = getattr(state, "manual_config", None)
    if (
        mc
        and getattr(mc, "execution_mode", "auto") == "external"
        and getattr(mc, "subtitle_source", "narration") == "dialogue"
    ):
        dialogues = [
            getattr(s, "dialogue", "") or ""
            for s in (getattr(state, "scenes", None) or [])
        ]

    durations = getattr(state, "scene_durations", None) or []
    total = len(texts)
    blocks = []
    for i, txt in enumerate(texts):
        dur = durations[i] if i < len(durations) else ""
        header = f"【场景 {i + 1}/{total}" + (f" · {dur}s" if dur else "") + "】"
        block = f"{header}\n{txt}"
        dlg = dialogues[i] if i < len(dialogues) else ""
        if dlg:
            block += f"\n台词（对白）：{dlg}"
        blocks.append(block)
    return "\n\n".join(blocks)


@router.get("/api/tasks/{task_id}/checkpoints/{checkpoint}/impact")
async def preview_checkpoint_impact(
    task_id: str,
    checkpoint: str,
    modified_artifact_ids: str = "",
    param_updates: str = "",
):
    """影响预计算（PRD §4.5 / §5.2）：只计算不落盘。

    query 参数（JSON 字符串）：
        modified_artifact_ids: ["creative:script:scene_prompt"] 或 ["creative:video:2"]
        param_updates: {"resolution": "768x1152"}

    返回 ImpactPlan{affected, retained, steps_to_reset, affected_checkpoints}，
    供前端「修改前提示」弹窗展示将删除重跑的产物。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        modified = json.loads(modified_artifact_ids) if modified_artifact_ids else []
        params = json.loads(param_updates) if param_updates else None
    except ValueError:
        raise HTTPException(status_code=422, detail=translate("checkpoint.json_required"))

    if not isinstance(modified, list):
        raise HTTPException(status_code=422, detail=translate("checkpoint.artifact_ids_not_array"))

    graph = get_dependency_graph(state.task_type)
    plan = graph.compute_impact(state, modified, params)
    return {"ok": True, "checkpoint": checkpoint, **plan.to_dict()}


@router.post("/api/tasks/{task_id}/artifacts/{artifact_id}/upload")
async def upload_task_artifact(
    task_id: str,
    artifact_id: str,
    file: UploadFile = File(...),
):
    """覆盖回填产物（PRD §4.4 / 通道2）。

    仅允许在任务暂停（PENDING + current_checkpoint）或未运行时回填；
    写入前校验路径穿越 + 覆盖后落盘 manifest / checkpoint。
    """
    # 运行中保护
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        if not pipeline._stop_event.is_set():
            raise HTTPException(status_code=409, detail="Task is running, please stop/pause it first")

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact or not artifact.file_relpath:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact.deletable:
        raise HTTPException(status_code=400, detail="Artifact is not editable")

    # 路径穿越防护
    real_task_dir = os.path.realpath(tm.task_dir)
    abs_path = os.path.join(tm.task_dir, artifact.file_relpath)
    real_abs_path = os.path.realpath(abs_path)
    if not real_abs_path.startswith(real_task_dir + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")

    os.makedirs(os.path.dirname(real_abs_path), exist_ok=True)
    content = await file.read()
    await write_bytes(real_abs_path, content)

    # 标记脏：记录回填产物 id（手动模式）
    mc = getattr(state, "manual_config", None)
    if mc is not None:
        if artifact_id not in mc.modified_artifacts:
            mc.modified_artifacts.append(artifact_id)
        tm.update_state(manual_config=mc)

    # 刷新清单
    write_checkpoint_manifest(state, tm.task_dir)

    logger.info("[Artifacts] Uploaded %s for task %s (%d bytes)",
                safe_log(artifact_id), safe_log(task_id), len(content))
    return {"ok": True, "artifact_id": artifact_id, "size": len(content)}


# ═══════════════════════════════════════════════════════════════
# v7.6 外部素材模式：批量导入 + 探针
# ═══════════════════════════════════════════════════════════════

# 场景/段落子目录名（scene_0 / para_1 …）
_SCENE_DIR_RE = re.compile(r"^(?:scene|para)_\d+$")
# 段落型流水线（稿件）的子目录前缀；其余为 scene
_PARA_PREFIX_TASKS = {"manuscript"}


def _first_number(text: str) -> Optional[int]:
    """取字符串中第一个连续数字（``scene_3.mp4`` → 3），无则 None。"""
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


def _resolve_scene_target(
    task_type: str, kind: str, mapping: dict, filename: str, pos: int, scene_count: int = 0
) -> str:
    """把上传文件解析为任务目录下的目标相对路径（v7.6 外部素材导入）。

    优先级：
      1. ``scene_map`` 显式指定（值形如 ``scene_2`` / ``para_1``）；
      2. 文件名（去扩展名）首个数字 N → ``{prefix}_{N-1}``
         （即梦常导出 scene_1.mp4 表示第 1 段）；仅当 ``1 ≤ N ≤ scene_count`` 时才采用
         （``scene_count`` ≤ 0 时不限），避免把文件名里的年份/时间戳（如
         ``20261015.mp4`` → 2026）误当场景序号而落到 ``scene_2025/``；
      3. 兜底按上传顺序 → ``{prefix}_{pos}``。

    ``video`` → ``{dir}/video.mp4``；``image`` → ``{dir}/ref.png``。
    数字人（anchor）无逐场景目录：``video`` → ``clip/clip.mp4``、``image`` → ``anchor.png``。
    """
    if task_type == "anchor":
        return "clip/clip.mp4" if kind == "video" else "anchor.png"

    stem = os.path.splitext(filename)[0]
    num = _first_number(stem)
    if num is not None and scene_count > 0 and not (1 <= num <= scene_count):
        num = None
    prefix = "para" if task_type in _PARA_PREFIX_TASKS else "scene"
    scene_dir = ""
    if mapping:
        candidates = [str(pos + 1)] + ([str(num)] if num is not None else [])
        for key in candidates:
            val = str(mapping.get(key, "") or "")
            if _SCENE_DIR_RE.match(val):
                scene_dir = val
                break
    if not scene_dir:
        scene_dir = f"{prefix}_{num - 1}" if num and num >= 1 else f"{prefix}_{pos}"

    return os.path.join(scene_dir, "video.mp4" if kind == "video" else "ref.png")


@router.post("/api/tasks/{task_id}/artifacts/import")
async def import_task_artifacts(
    task_id: str,
    files: List[UploadFile] = File(...),
    kind: str = Form("video"),
    scene_map: str = Form(""),
):
    """批量导入外部工具（即梦）导出的分镜素材（v7.6）。

    归一化到任务目标分辨率/帧率/编码后落盘，并回显 ffprobe 探针信息
    （时长/分辨率/帧率/有无音轨/编码）。

    - ``kind``：``video``（→ ``{scene_i}/video.mp4``）或 ``image``（→ ``{scene_i}/ref.png``）；
    - ``scene_map``：可选 JSON，``{"1":"scene_0"}`` 显式指定映射；缺省按文件名序号/上传顺序。

    仅允许在任务暂停或未运行时导入（运行中返回 409）。
    """
    if kind not in ("image", "video"):
        raise HTTPException(status_code=422, detail=translate("validation.import_kind_invalid"))
    if not files:
        raise HTTPException(status_code=400, detail=translate("artifacts.import_no_files"))

    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        if not pipeline._stop_event.is_set():
            raise HTTPException(status_code=409, detail="Task is running, please stop/pause it first")

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    mapping: dict = {}
    if scene_map.strip():
        try:
            mapping = json.loads(scene_map)
        except ValueError:
            raise HTTPException(status_code=422, detail=translate("validation.import_scene_map_invalid"))
        if not isinstance(mapping, dict):
            raise HTTPException(status_code=422, detail=translate("validation.import_scene_map_invalid"))

    task_type = str(getattr(state.task_type, "value", state.task_type))
    width = int(getattr(state, "video_width", 0) or 0)
    height = int(getattr(state, "video_height", 0) or 0)
    scene_count = int(getattr(state, "scene_count", 0) or 0) or len(
        getattr(state, "scenes", None) or []
    )
    real_task_dir = os.path.realpath(tm.task_dir)

    results: list[dict] = []
    refs = list(getattr(state, "scene_reference_images", []) or [])
    refs_dirty = False

    for pos, upload in enumerate(files):
        filename = os.path.basename(upload.filename or f"upload_{pos}")
        entry: dict = {"filename": filename, "target": "", "ok": False, "error": "", "probe": None}
        try:
            relpath = _resolve_scene_target(task_type, kind, mapping, filename, pos, scene_count)
            abs_path = os.path.realpath(os.path.join(tm.task_dir, relpath))
            if not abs_path.startswith(real_task_dir + os.sep):
                raise ValueError("Access denied")
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            content = await upload.read()
            fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1] or ".bin")
            try:
                os.write(fd, content)
                os.close(fd)
                if kind == "video":
                    await asyncio.to_thread(normalize_external_video, tmp_path, abs_path, width, height)
                else:
                    await asyncio.to_thread(normalize_external_image, tmp_path, abs_path, width, height)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

            entry["ok"] = True
            entry["target"] = relpath
            entry["probe"] = await asyncio.to_thread(probe_media, abs_path)

            # 分镜参考图（creative）：登记到 scene_reference_images，
            # 使流水线在该场景以导入图为参考（跳过 AI 分镜图生成）。
            if kind == "image" and task_type == "creative":
                while len(refs) < pos + 1:
                    refs.append("")
                refs[pos] = abs_path
                refs_dirty = True
        except Exception as e:  # noqa: BLE001 — 逐文件隔离，单个失败不影响其余
            # 异常原文只进服务端日志（含绝对路径/ffmpeg 命令等实现细节），
            # 回给前端的固定为多语言通用文案（CWE-209 / CodeQL py/stack-trace-exposure）
            entry["error"] = translate("artifacts.import_failed")
            logger.warning(
                "[External] Import failed for %s: %s", safe_log(filename), safe_log(e),
            )
        results.append(entry)

    if refs_dirty:
        state.scene_reference_images = refs
        tm.update_state(scene_reference_images=refs)

    write_checkpoint_manifest(state, tm.task_dir)

    imported = sum(1 for r in results if r["ok"])
    failed = len(results) - imported
    logger.info("[External] Imported %d/%d %s artifacts for task %s",
                imported, len(results), safe_log(kind), safe_log(task_id))
    return {
        "ok": imported > 0,
        "task_id": task_id,
        "kind": kind,
        "results": results,
        "imported": imported,
        "failed": failed,
    }


@router.get("/api/tasks/{task_id}/artifacts/probe")
async def probe_task_artifact(task_id: str, relpath: str):
    """单文件探针（v7.6）：返回时长/分辨率/帧率/有无音轨/编码。

    ``relpath`` 为相对于任务目录的路径，经 ``safe_join`` 防路径穿越。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        abs_path = safe_join(tm.task_dir, relpath)
    except UnsafePathError:
        raise HTTPException(status_code=404, detail=translate("artifacts.probe_missing"))
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail=translate("artifacts.probe_missing"))
    info = await asyncio.to_thread(probe_media, abs_path)
    return {"ok": True, "relpath": relpath, **info}


def _validate_external_videos(state) -> None:
    """外部素材模式确认 ``videos`` 检查点前的磁盘校验（v7.6）。

    逐个场景按 :func:`_resolve_scene_target` 算出期望视频的相对路径，校验文件
    已导入；任一缺失即抛 ``HTTPException(422)``，避免「未导入却被放行」。
    视频是否含音轨由用户自行负责，不在此拦截。

    Args:
        state: 任务状态（含 ``manual_config`` / ``scene_count`` / ``scenes``）。

    Raises:
        HTTPException: 有场景视频缺失（422）。
    """
    mc = getattr(state, "manual_config", None)
    if not mc or getattr(mc, "execution_mode", "auto") != "external":
        return

    scene_count = int(getattr(state, "scene_count", 0) or 0) or len(
        getattr(state, "scenes", None) or []
    )
    if scene_count <= 0:
        return

    task_type = getattr(getattr(state, "task_type", None), "value", "") or str(
        getattr(state, "task_type", "")
    )
    tm = TaskManager(state.task_id, dir_name=helpers.find_dir_name(state.task_id))

    relpaths: list[str] = []
    seen: set[str] = set()
    for i in range(scene_count):
        rel = _resolve_scene_target(task_type, "video", {}, "", i)
        if rel not in seen:
            seen.add(rel)
            relpaths.append(rel)

    missing = [
        i + 1 for i, rel in enumerate(relpaths)
        if not os.path.isfile(os.path.join(tm.task_dir, rel))
    ]
    ui_lang = getattr(state, "ui_language", "") or None
    if missing:
        raise HTTPException(
            status_code=422,
            detail=translate(
                "checkpoint.approve.missing_videos",
                ui_lang,
                scenes=", ".join(str(n) for n in missing),
            ),
        )


@router.post("/api/tasks/{task_id}/checkpoints/{checkpoint}/approve")
async def approve_checkpoint(task_id: str, checkpoint: str,
                             modified_artifact_ids: str = Form(""),
                             param_updates: str = Form(""),
                             confirmed: bool = Form(False)):
    """确认产物并继续（PRD §5.2）。

    - 不传 ``confirmed``（或 false）：仅计算影响计划返回，不落盘（等价 impact 预计算）。
    - ``confirmed=true``：落盘删除受影响产物 + 重置步骤 + 标记检查点已确认，
      然后走现有 resume 恢复执行。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        modified = json.loads(modified_artifact_ids) if modified_artifact_ids else []
        params = json.loads(param_updates) if param_updates else None
    except ValueError:
        raise HTTPException(status_code=422, detail=translate("checkpoint.json_required"))

    graph = get_dependency_graph(state.task_type)
    plan = graph.compute_impact(state, modified, params)

    if not confirmed:
        # 仅预计算返回，不落盘（前端可据此展示"修改前提示"弹窗）
        return {"ok": True, "checkpoint": checkpoint, "confirmed": False, **plan.to_dict()}

    # ── 确认落盘 ──
    # v7.6 外部素材模式：确认 videos 检查点前先校验素材已导入（缺失 → 422）
    if checkpoint == "videos":
        _validate_external_videos(state)

    # 1. 删除受影响产物文件 + 应用级联计划到 state
    deleted_files: list[str] = []
    real_task_dir = os.path.realpath(tm.task_dir)
    for aid in plan.affected:
        artifact = resolve_artifact(aid, state, tm.task_dir)
        if artifact and artifact.file_relpath:
            abs_path = os.path.join(tm.task_dir, artifact.file_relpath)
            real_abs_path = os.path.realpath(abs_path)
            if real_abs_path.startswith(real_task_dir + os.sep) and os.path.exists(abs_path) and os.path.isfile(abs_path):
                try:
                    os.remove(abs_path)
                    deleted_files.append(artifact.file_relpath)
                except OSError as e:
                    logger.warning("[Artifacts] Failed to delete %s: %s", artifact.file_relpath, e)

    # 2. 重置受影响步骤状态 + 任务置 PENDING
    update_kwargs: dict = {}
    for step_field in plan.steps_to_reset:
        if hasattr(state, step_field):
            setattr(state, step_field, StepStatus.PENDING)
            update_kwargs[step_field] = StepStatus.PENDING

    # 3. 标记检查点已确认 + 清空 current_checkpoint
    mc = getattr(state, "manual_config", None)
    if mc is not None:
        if checkpoint not in mc.approved_checkpoints:
            mc.approved_checkpoints.append(checkpoint)
        mc.current_checkpoint = ""
        if modified:
            for m in modified:
                if m not in mc.modified_artifacts:
                    mc.modified_artifacts.append(m)
        update_kwargs["manual_config"] = mc
    update_kwargs["status"] = StepStatus.PENDING
    state.status = StepStatus.PENDING

    # 4. 持久化
    tm.update_state(**update_kwargs)

    # 5. 刷新清单
    write_checkpoint_manifest(state, tm.task_dir)

    logger.info(
        "[Approve] Task %s checkpoint '%s' approved, deleted=%d, reset=%s",
        safe_log(task_id), safe_log(checkpoint),
        len(deleted_files), plan.steps_to_reset,
    )

    # 6. 走现有 resume 恢复执行
    from web.routes.task_routes import resume_task

    return await resume_task(task_id)


@router.post("/api/tasks/{task_id}/checkpoints/{checkpoint}/regen")
async def regen_checkpoint(task_id: str, checkpoint: str):
    """重新生成当前检查点（PRD §5.2）。

    等价于 approve(modified_artifact_ids=[该检查点全部产物], confirmed=true)：
    重置本检查点全部产物 + 下游，然后 resume 重新生成。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    data = build_checkpoint_manifest(state, tm.task_dir)
    groups = data.get("checkpoints", {})
    if checkpoint not in groups:
        raise HTTPException(status_code=404, detail=f"Checkpoint '{checkpoint}' not found")

    # 该检查点全部产物 id
    modified = [a["artifact_id"] for a in groups[checkpoint]["artifacts"]]
    return await approve_checkpoint(
        task_id, checkpoint,
        modified_artifact_ids=json.dumps(modified),
        param_updates="",
        confirmed=True,
    )


_TEXT_CATEGORIES = {"json", "subtitle", "text"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _text_diff_summary(old: str, new: str, lang: str = "zh") -> str:
    """轻量文本改动摘要（行级差量 + 字符数变化），不依赖外部 diff 库。

    Args:
        old: 原文本。
        new: 新文本。
        lang: UI 语言（v7.0，issue #64），决定摘要文案语种。
    """
    old_lines = [line for line in old.splitlines() if line.strip()]
    new_lines = [line for line in new.splitlines() if line.strip()]
    if old_lines == new_lines:
        if old != new:
            return translate(
                "ai_modify.diff_char_only", lang,
                old_len=len(old), new_len=len(new),
            )
        return translate("ai_modify.diff_no_change", lang)
    added = sum(1 for line in new_lines if line not in set(old_lines))
    removed = sum(1 for line in old_lines if line not in set(new_lines))
    return translate(
        "ai_modify.diff_summary", lang,
        added=added, removed=removed, old_len=len(old), new_len=len(new),
    )


def _read_file_b64(path: str) -> str:
    """同步读取文件并返回 base64 文本（供 to_thread 在线程池执行）。"""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def _image_output_to_data_url(output) -> str:
    """将 ImageOutput 转为 base64 data URL（url / b64 两种 fmt 兼备）。"""
    ext = (getattr(output, "ext", None) or "png").lower()
    mime = mimetypes.guess_type(f"x.{ext}")[0] or "image/png"
    if getattr(output, "fmt", None) == "b64":
        raw = output.data
        if "," in raw:
            raw = raw.split(",", 1)[1]
        return f"data:{mime};base64,{raw}"
    # fmt == "url"：下载到临时文件再读回 base64
    fd, tmp = tempfile.mkstemp(suffix=f".{ext}")
    os.close(fd)
    try:
        await output.save(tmp)
        b64 = await asyncio.to_thread(_read_file_b64, tmp)
        return f"data:{mime};base64,{b64}"
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@router.post("/api/tasks/{task_id}/checkpoints/{checkpoint}/ai-modify")
async def ai_modify_artifact(
    task_id: str,
    checkpoint: str,
    artifact_id: str = Form(...),
    user_request: str = Form(...),
):
    """通道 1：页内 AI 修改（文本 / 图片产物，PRD §5.2 / §4.7）。

    读取目标产物 → 按类型调模型改写 → 返回新内容（**不落盘、不改 state**）；
    前端预览 / 微调后经 ``upload`` 落盘，再走 ``approve`` 重置下游并恢复执行。
    视频 / 音频产物暂不支持，返回 400。
    """
    if not user_request.strip():
        raise HTTPException(status_code=422, detail=translate("ai_modify.user_request_empty"))

    # 运行中保护
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        if not pipeline._stop_event.is_set():
            raise HTTPException(status_code=409, detail="Task is running, please stop/pause it first")

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    artifact = resolve_artifact(artifact_id, state, tm.task_dir)
    if not artifact or not artifact.file_relpath:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact.deletable:
        raise HTTPException(status_code=400, detail="Artifact is not editable")

    # 路径穿越防护
    real_task_dir = os.path.realpath(tm.task_dir)
    abs_path = os.path.join(tm.task_dir, artifact.file_relpath)
    real_abs_path = os.path.realpath(abs_path)
    if not real_abs_path.startswith(real_task_dir + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(real_abs_path) or not os.path.isfile(real_abs_path):
        raise HTTPException(status_code=404, detail="Artifact file not found")

    api_key = get_api_key()
    if not api_key:
        # v7.0（issue #64）：按任务落盘 ui_language 本地化，避免英文界面看到中文报错
        raise HTTPException(status_code=400, detail=api_key_missing_msg(state.ui_language))

    ui_lang = getattr(state, "ui_language", "") or "zh"
    category = artifact.category
    try:
        if category in _TEXT_CATEGORIES:
            raw = await read_text(real_abs_path)
            chat_api = get_or_build_text_chat_client(api_key=api_key)
            if category == "json":
                parsed = await asyncio.to_thread(
                    chat_api.chat_json,
                    "你是资深视频分镜/编剧编辑器。必须严格保持 JSON 结构与既有字段，"
                    "只按用户要求修改目标字段，禁止新增/删除顶层字段，禁止破坏 JSON 合法性。",
                    f"以下是现有 JSON：\n{raw}\n\n用户要求：{user_request}\n请直接输出修改后的完整 JSON。",
                )
                new_content = json.dumps(parsed, ensure_ascii=False, indent=2)
            else:
                new_content = await asyncio.to_thread(
                    chat_api.chat,
                    "你是资深视频文案/字幕编辑器。保持原格式（SRT 序号与时间轴格式不变、"
                    "文本分段不变），只按用户要求修改内容，输出完整改写结果。",
                    f"以下是现有内容：\n{raw}\n\n用户要求：{user_request}\n请直接输出修改后的完整内容。",
                )
            diff_summary = _text_diff_summary(raw, new_content, lang=ui_lang)
        elif os.path.splitext(artifact.file_relpath)[1].lower() in _IMAGE_EXTS:
            chat_api = get_or_build_text_chat_client(api_key=api_key)
            edit_prompt = await asyncio.to_thread(
                chat_api.chat_multimodal,
                "你是资深图像编辑。基于用户意见，输出一条简洁的中文改写要求，"
                "用于图像编辑模型基于该图重生成。只输出修改要求本身，不超过 150 字。",
                f"用户希望修改这幅图：{user_request}\n请输出修改要求本身。",
                [real_abs_path],
            )
            image_api = AgnesImageAPI(api_key=api_key)
            output = await image_api.generate_single_image(
                prompt=edit_prompt.strip(),
                reference_image_paths=[real_abs_path],
            )
            new_content = await _image_output_to_data_url(output)
            diff_summary = translate(
                "ai_modify.image_regenerated", ui_lang,
                prompt=edit_prompt.strip()[:120],
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=translate(
                    "ai_modify.unsupported_category", ui_lang, category=category,
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        # v7.0（issue #64）：网络诊断按 ui_language 输出中/英文
        message = describe_network_error(e, lang=ui_lang) or translate(
            "ai_modify.failed", ui_lang, reason=str(e),
        )
        raise HTTPException(status_code=502, detail=message)

    logger.info("[AiModify] %s task %s checkpoint '%s' (category=%s)",
                safe_log(artifact_id), safe_log(task_id), safe_log(checkpoint), category)
    return {
        "ok": True,
        "artifact_id": artifact_id,
        "category": category,
        "new_content": new_content,
        "diff_summary": diff_summary,
    }
