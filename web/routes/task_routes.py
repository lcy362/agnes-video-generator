"""任务路由：列表 / 详情 / 恢复 / 停止 / 并发状态。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException

from core.config import API_KEY_MISSING_MSG, get_api_key
from core.pipelines import ALL_CHECKPOINTS, compute_current_checkpoint
from core.task_manager import TaskManager
from models.task import (
    AnchorVideoTask,
    CreativeVideoTask,
    ManuscriptVideoTask,
    PoetryVideoTask,
    SimpleImageTask,
    SimpleVideoTask,
    StepStatus,
    TaskType,
)
from web import app_state, deps, helpers
from web.log_safe import safe_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks")
async def list_tasks(limit: int = 0, offset: int = 0, status: str = ""):
    """任务列表（优化路线图 1.4：状态过滤 + 分页）。

    Args:
        limit: 每页条数；0 表示不分页（返回全部）
        offset: 跳过前 N 条
        status: 逗号分隔的状态过滤（如 ``running,queued,pending``）；空为不过滤
    """
    tm = TaskManager("_")
    tasks = tm.list_tasks()
    # 1.4：状态过滤 + 分页在轻量字段阶段完成，避免为被过滤/截断的任务
    # 做完整状态加载（此前列表对每个任务都做一次 Pydantic 完整校验）
    if status:
        statuses = {s.strip() for s in status.split(",") if s.strip()}
        tasks = [t for t in tasks if t.get("status") in statuses]
    total = len(tasks)
    if offset:
        tasks = tasks[offset:]
    if limit > 0:
        tasks = tasks[:limit]

    for t in tasks:
        task_tm = TaskManager(t["task_id"], dir_name=t.get("dir_name"))
        state = task_tm.load()
        if state:
            t["final_video_file"] = state.final_video_file
            t["task_type"] = state.task_type
            # 创意视频特有字段
            if isinstance(state, CreativeVideoTask):
                t["scene_count"] = state.scene_count
                t["idea"] = state.idea[:100] if state.idea else ""
            # 稿件视频特有字段
            elif isinstance(state, ManuscriptVideoTask):
                t["paragraph_count"] = len(state.paragraphs)
                t["manuscript_text"] = state.manuscript_text[:100] if state.manuscript_text else ""
            # 数字人口播
            elif isinstance(state, AnchorVideoTask):
                t["script_text"] = state.script_text[:100] if state.script_text else ""
                t["anchor_prompt"] = state.anchor_prompt[:100] if state.anchor_prompt else ""
                t["paragraph_count"] = len(state.paragraphs)
            # 简单视频
            elif isinstance(state, SimpleVideoTask):
                t["prompt"] = state.prompt[:100] if state.prompt else ""
                t["mode"] = state.mode
            # 诗歌视频
            elif isinstance(state, PoetryVideoTask):
                t["poem_text"] = state.poem_text[:100] if state.poem_text else ""
            # 简单图片
            elif isinstance(state, SimpleImageTask):
                t["prompt"] = state.prompt[:100] if state.prompt else ""
                t["size"] = state.size

            # v6.0 手动模式：列表徽标判断（PENDING + current_checkpoint 非空 = 等待你操作）
            mc = getattr(state, "manual_config", None)
            t["current_mode"] = "manual" if (mc and mc.enabled) else "auto"
            t["current_checkpoint"] = (mc.current_checkpoint if mc else "") or ""
            t["awaiting_user"] = bool(
                t["current_mode"] == "manual"
                and state.status == StepStatus.PENDING
                and t["current_checkpoint"]
            )
    # 1.4：total 为过滤后的总数（分页前），供前端做分页控件
    return {"tasks": tasks, "total": total}


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    data = state.model_dump()
    data["dir_name"] = dir_name
    # 后台是否有活跃 pipeline（v6.1）：前端据此区分「运行中/排队中」与
    # 「服务重启后遗留的 pending/queued（需点击续传）」，避免误导用户。
    data["active"] = task_id in app_state.active_pipelines
    return data


# ── v6.1 二期：任务诊断端点 ──
_ERROR_LOG_MAX_MESSAGE = 800  # 错误消息截断长度（诊断报告用，不含 prompt 全文与 response_body）
# v6.2.2：完整 traceback 截断长度（相对长，供定位环境级异常如 [WinError 2]）
_ERROR_TRACEBACK_MAX = 6000

# 需要从 error log 暴露给前端的字段（敏感字段：prompt / system_prompt / response_body / extra 一律不返回）
_DIAG_LOG_FIELDS = (
    "timestamp",
    "task_id",
    "model_type",
    "api_method",
    "error_type",
    "status_code",
    "error_message",
    "retry_count",
)


def _find_error_log_dir() -> Path:
    """定位 error_logs 目录（与 error_collector 一致：激活工作空间根 / server 目录）。"""
    from core.api.error_collector import _get_log_dir

    return _get_log_dir()


def _iter_error_logs() -> list[dict]:
    """读取 error_logs/ 下全部 JSON 日志，非法/损坏条目跳过。"""
    log_dir = _find_error_log_dir()
    if not log_dir.exists():
        return []
    logs = []
    for p in sorted(log_dir.glob("*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                logs.append(json.load(f))
        except Exception:
            continue
    return logs


def _sanitize_log(log: dict) -> dict:
    """仅暴露诊断所需字段，杜绝 prompt / response_body / extra 泄漏。"""
    out = {}
    for k in _DIAG_LOG_FIELDS:
        v = log.get(k, "")
        if k == "error_message":
            v = (v or "")[: _ERROR_LOG_MAX_MESSAGE]
        out[k] = v
    return out


@router.get("/api/tasks/{task_id}/diagnostics")
async def get_task_diagnostics(task_id: str):
    """返回任务摘要 + 该任务关联的模型调用错误详情（v6.1 二期，PRD FR9）。

    任务摘要：status / current_step / current_message / 时间戳。
    错误列表：优先 ``task_id`` 精确匹配；不足时按任务时间窗口（created_at ~ updated_at
    + 2h 余量）兜底，避免串入无关任务的旧日志。字段不含 prompt 全文与 response_body，
    error_message 截断。

    前端在 FeedbackPanel 展开时拉取；端点失败 / 404 时前端静默降级为纯前端版报告。
    """
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    summary = {
        "task_id": task_id,
        "task_type": state.task_type,
        "status": state.status,
        "current_step": state.current_step,
        "current_message": (state.current_message or "")[:_ERROR_LOG_MAX_MESSAGE],
        "error_traceback": (state.error_traceback or "")[:_ERROR_TRACEBACK_MAX],
        "created_at": state.created_at or "",
        "updated_at": state.updated_at or "",
    }

    # 精确匹配优先：error log 中 task_id == 本任务
    logs = _iter_error_logs()
    exact = [log for log in logs if log.get("task_id") == task_id]

    # 时间窗口兜底：created_at ~ updated_at（+ 2h 余量），且未在精确集合中
    windowed = []
    if len(exact) < 1:
        start = _parse_ts(state.created_at)
        end = _parse_ts(state.updated_at)
        if start or end:
            if end is None:
                end = start + timedelta(hours=2)
            else:
                end = end + timedelta(hours=2)
            windowed = [
                log for log in logs
                if log.get("task_id") != task_id and _in_window(log.get("timestamp"), start, end)
            ]

    matched = (exact + windowed)[:20]
    logger.info(f"[Diagnostics] Task {task_id}: {len(exact)} exact + {len(windowed)} windowed matches")
    return {
        "ok": True,
        "task_id": task_id,
        "summary": summary,
        "match_source": "exact" if exact else ("window" if windowed else "none"),
        "error_logs": [_sanitize_log(log) for log in matched],
    }


def _parse_ts(value: str) -> datetime | None:
    """解析 ISO 时间戳；失败返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _in_window(ts_value: str, start: datetime | None, end: datetime | None) -> bool:
    """判断时间戳是否落在 [start, end] 窗口内。"""
    ts = _parse_ts(ts_value)
    if ts is None:
        return False
    if start and ts < start:
        return False
    if end and ts > end:
        return False
    return True


@router.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    # 关键段串行化：check 与 insert 之间存在多个 await 让出点，快速重复 resume
    # 会让两次请求都通过 "task not in active_pipelines" 检查并各自启动 pipeline，
    # 导致同任务双重运行、状态文件交叉写入。
    async with app_state.get_pipeline_lock(task_id):
        if task_id in app_state.active_pipelines:
            existing = app_state.active_pipelines[task_id]
            if existing._stop_event.is_set():
                logger.info("[Resume] Replacing stopped pipeline for task %s",
                            safe_log(task_id))
                del app_state.active_pipelines[task_id]
            else:
                raise HTTPException(status_code=400, detail="Task is already running")

        dir_name = helpers.find_dir_name(task_id)
        tm = TaskManager(task_id, dir_name=dir_name)
        state = tm.load()
        if not state:
            raise HTTPException(status_code=404, detail="Task not found")

        if state.status == StepStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Task is already completed")

        logger.info("[Resume] Starting resume for task %s, type=%s, status=%s",
                    safe_log(task_id), state.task_type, state.status)

        # v2.0：根据 task_type 选择对应的 Pipeline
        pipeline = deps.create_pipeline_for_type(state.task_type, api_key, task_id, dir_name)
        app_state.active_pipelines[task_id] = pipeline

        app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    if task_id not in app_state.active_pipelines and task_id not in app_state._queued_tasks:
        raise HTTPException(status_code=400, detail="Task is not running")

    # 停止运行中的 pipeline
    if task_id in app_state.active_pipelines:
        pipeline = app_state.active_pipelines[task_id]
        pipeline.stop()

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if state and state.status in (StepStatus.RUNNING, StepStatus.QUEUED):
        tm.update_state(status=StepStatus.PENDING)
        logger.info("[Stop] Task %s status -> pending", safe_log(task_id))

    logger.info("[Stop] Task %s stop requested", safe_log(task_id))
    return {"ok": True, "task_id": task_id}


@router.post("/api/tasks/{task_id}/mode")
async def switch_task_mode(task_id: str, mode: str = Form(...)):
    """运行时切换执行模式（v6.0 手动模式）。

    ``mode=manual``（自动变手动）：
        - simple / simple_image 无检查点，返回 400；
        - 复用现有 stop 链路挂起流水线（pipeline.stop() → 下一安全点
          PipelineShutdown 正常落盘），落盘 ``enabled=true`` +
          ``current_checkpoint=最近完成边界`` + ``status=PENDING``；
        - 恢复后保持手动模式，在下一个命中检查点再次暂停（不主动切回则一直是手动）。

    ``mode=auto``（手动变自动，**切换即继续**）：
        - 清空 ``pause_points``（永不暂停）；
        - 若任务正暂停在检查点 → 立即走现有 resume 继续跑完。

    Args:
        mode: "auto" | "manual"。
    """
    if mode not in ("auto", "manual"):
        raise HTTPException(status_code=422, detail="mode 必须为 auto 或 manual")

    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    mc = state.manual_config

    if mode == "manual":
        # simple / simple_image 无检查点，不支持手动模式（PRD §4.3）
        if state.task_type in (TaskType.SIMPLE, TaskType.IMAGE):
            raise HTTPException(status_code=400, detail="该任务类型不支持手动模式")

        # 幂等：已是手动模式且处于暂停态 → 直接返回
        if mc.enabled and state.status == StepStatus.PENDING and mc.current_checkpoint:
            return {"ok": True, "task_id": task_id, "mode": "manual",
                    "current_checkpoint": mc.current_checkpoint, "changed": False}

        # 复用 stop 链路挂起流水线（若正在运行/排队）
        if task_id in app_state.active_pipelines:
            app_state.active_pipelines[task_id].stop()
        elif task_id in app_state._queued_tasks:
            logger.info("[Mode] Task %s queued, will skip on slot acquire",
                        safe_log(task_id))
        else:
            logger.info("[Mode] Task %s not running, marking manual only",
                        safe_log(task_id))

        # 计算当前检查点边界 + 落盘
        checkpoint = compute_current_checkpoint(state)
        mc.enabled = True
        if not mc.pause_points:
            mc.pause_points = list(ALL_CHECKPOINTS)  # 默认全部检查点暂停
        mc.current_checkpoint = checkpoint
        tm.update_state(
            status=StepStatus.PENDING,
            manual_config=mc,
            current_step=checkpoint or state.current_step,
            current_status="awaiting_user",
            current_message=(
                f"已切换为手动模式，等待你在检查点 '{checkpoint}' 确认或修改产物"
                if checkpoint else "已切换为手动模式"
            ),
        )
        logger.info("[Mode] Task %s switched to manual (checkpoint=%s)",
                    safe_log(task_id), safe_log(checkpoint))
        return {"ok": True, "task_id": task_id, "mode": "manual",
                "current_checkpoint": checkpoint, "changed": True}

    # ── mode == "auto"：手动变自动，切换即继续 ──
    was_paused = mc.enabled and state.status == StepStatus.PENDING and bool(mc.current_checkpoint)
    mc.pause_points = []
    mc.current_checkpoint = ""
    tm.update_state(
        manual_config=mc,
        current_status="resumed",
        current_message="已切换为自动模式",
    )
    logger.info("[Mode] Task %s switched to auto (was_paused=%s)",
                safe_log(task_id), was_paused)

    if was_paused:
        # 切换即继续：立即走现有 resume 逻辑跑完
        return await resume_task(task_id)

    return {"ok": True, "task_id": task_id, "mode": "auto", "changed": True}


@router.post("/api/tasks/sweep")
async def sweep_stale_tasks_endpoint(age_days: int = 7, protect: str = ""):
    """手动触发僵尸任务清理（v5.0 Batch 5 / 5.1，1.5 参数化）。

    清理工作区中状态文件超龄且非活跃的任务目录；活跃 pipeline 中的任务一律跳过。

    Args:
        age_days: 任务状态文件超龄阈值（天），默认 7
        protect: 额外保护的状态集合（逗号分隔，如 ``running,queued,pending``；
                 为空时使用默认保护集 ``{running, queued, pending}``；
                 传 ``none`` 表示仅保护活跃 pipeline，允许清理所有超龄静态任务）
    """
    from core.artifacts import _DEFAULT_PROTECT_STATUSES, sweep_stale_tasks

    # 活跃 pipeline 保护：即使状态文件超龄也不允许清理
    active_ids = set(app_state.active_pipelines.keys()) | set(app_state._queued_tasks)
    protect_set = set(_DEFAULT_PROTECT_STATUSES)
    if protect.strip():
        if protect.strip().lower() == "none":
            protect_set = set()
        else:
            protect_set = {
                StepStatus(s.strip()) for s in protect.split(",") if s.strip()
            }
    result = sweep_stale_tasks(age_days=age_days, protect_statuses=protect_set)
    result["swept"] = [d for d in result["swept"] if d not in active_ids]
    result["protected"] = result["protected"] + sorted(active_ids)
    logger.info(f"[Cleanup] Sweep finished: swept={result['swept']}, "
                f"protected={len(result['protected'])}, errors={len(result['errors'])}")
    return {"ok": True, **result}


@router.get("/api/concurrency")
async def get_concurrency_status():
    """返回当前并发控制状态：已用权重、上限、排队任务列表。"""
    running_tasks = []
    for tid, pl in app_state.active_pipelines.items():
        if tid not in app_state._queued_tasks:
            # 真正在运行的（已获取信号量）
            running_tasks.append({
                "task_id": tid,
                "type": getattr(pl, '_task_type', 'unknown'),
            })

    queued = [
        {"task_id": tid, "weight": w}
        for tid, w in app_state._queued_tasks.items()
    ]

    semaphore = app_state.get_semaphore()
    return {
        "ok": True,
        "max_weight": semaphore.max_weight,
        "current_weight": semaphore.current,
        "utilization": round(semaphore.utilization, 2),
        "running_count": len(running_tasks),
        "queued_count": len(queued),
        "queued_tasks": queued,
        "rate_limit_per_min": app_state.get_rate_limit(),
        "task_weights": {k.value: v for k, v in app_state.TASK_TYPE_WEIGHTS.items()},
    }
