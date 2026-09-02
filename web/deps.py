"""Web 层共享依赖（Batch 1 从 server.py 拆出）。

Pipeline 工厂与执行器：任务创建 / resume 端点共同依赖的
「按 task_type 构建 Pipeline」与「并发受控的后台执行」逻辑。
"""
from __future__ import annotations

import asyncio
import logging

from core.config import get_selected_models
from core.pipelines import (
    AnchorPipeline,
    BasePipeline,
    CreativeVideoPipeline,
    ManuscriptVideoPipeline,
    PipelineShutdown,
    PoetryVideoPipeline,
    SimpleVideoPipeline,
)
from core.task_manager import TaskManager
from models.task import BaseTaskState, StepStatus, TaskType
from web import app_state

logger = logging.getLogger(__name__)


def create_pipeline_for_type(
    task_type: TaskType,
    api_key: str,
    task_id: str,
    dir_name: str,
) -> BasePipeline:
    """根据任务类型创建对应的 Pipeline 实例。

    从配置读取选中的模型（文本/图像/视频），注入各 Pipeline，
    使界面选择的模型生效。
    """
    models = get_selected_models()
    text_model = models["text"]
    image_model = models["image"]
    video_model = models["video"]
    shutdown_event = app_state.shutdown_event

    if task_type == TaskType.SIMPLE:
        return SimpleVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.MANUSCRIPT:
        return ManuscriptVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.ANCHOR:
        return AnchorPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.POETRY:
        return PoetryVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )
    else:
        # CREATIVE（默认）
        return CreativeVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            chat_model=text_model,
            image_model=image_model,
            video_model=video_model,
            shutdown_event=shutdown_event,
        )


def _refresh_task_manifests(state: BaseTaskState, pipeline: BasePipeline) -> None:
    """落盘产物清单 manifest.json + MANIFEST.md（v5.x 产物规范前置工作）。

    在任务运行开始与结束时调用；失败不阻断主流程（清单为辅助产物）。
    """
    try:
        from core.artifacts import write_task_manifests
        write_task_manifests(state, pipeline.working_dir)
    except Exception as e:
        logger.warning(f"[Artifacts] manifest refresh failed for {pipeline.task_id}: {e}")


def mark_task_queued(task_manager: TaskManager) -> None:
    """创建任务后立即落盘为排队状态（status=queued + 排队消息）。

    创建端点同步落盘（而非等后台协程异步置位），保证前端在响应返回后
    打开任务详情页时能立即识别为「排队中」并启动轮询，避免进度卡在
    「0% / 待启动」。
    """
    task_manager.update_state(
        status=StepStatus.QUEUED,
        current_step="init",
        current_status="running",
        current_message="任务排队中...",
        current_progress=0.0,
    )


async def run_pipeline(pipeline: BasePipeline, state: BaseTaskState):
    """通用 Pipeline 执行包装器。"""
    # v6.1 二期：进入流水线执行上下文即登记 task_id，供 error_collector 落盘关联（诊断端点用）
    from core.api.error_collector import set_error_task_id

    set_error_task_id(pipeline.task_id)
    try:
        logger.info(f"[Pipeline] Starting run for task {pipeline.task_id}, type={state.task_type}")
        _refresh_task_manifests(state, pipeline)  # 初始产物清单
        await pipeline.run(state)
        logger.info(f"[Pipeline] Completed run for task {pipeline.task_id}")
    except PipelineShutdown:
        logger.info(f"[Pipeline] Task {pipeline.task_id} stopped by user")
    except Exception as e:
        logger.error(f"[Pipeline] Task {pipeline.task_id} failed: {e}", exc_info=True)
    finally:
        _refresh_task_manifests(state, pipeline)  # 最终产物清单
        # 身份比对：仅当字典里仍是当前 pipeline 时才删除。
        # 否则快速 resume→stop 会让旧 pipeline 的 finally 误删新 pipeline。
        if app_state.active_pipelines.get(pipeline.task_id) is pipeline:
            del app_state.active_pipelines[pipeline.task_id]


async def run_pipeline_with_concurrency(
    pipeline: BasePipeline,
    state: BaseTaskState,
    task_manager: TaskManager,
):
    """带并发控制的 Pipeline 执行包装器。

    复用回归流程的加权信号量逻辑：
    1. 先将任务标记为 queued（排队中）
    2. 等待加权信号量（总并发权重 ≤ MAX_CONCURRENT_WEIGHT）
    3. 获取到信号量后启动 pipeline
    4. pipeline 结束后释放信号量
    """
    weight = app_state.TASK_TYPE_WEIGHTS.get(state.task_type, 1)
    task_id = pipeline.task_id
    semaphore = app_state.get_semaphore()
    app_state._queued_tasks[task_id] = weight

    logger.info(
        f"[Concurrency] Task {task_id} queued (weight={weight}, "
        f"current={semaphore.current}/{semaphore.max_weight})"
    )

    # 标记排队状态
    task_manager.update_state(status=StepStatus.QUEUED)

    # 排队时持久化进度消息（前端轮询可读取）
    task_manager.update_state(
        current_step="init", current_status="running",
        current_message="任务排队中...", current_progress=0.0,
    )

    # 优化路线图 0.4：权重超过并发上限时直接落盘 FAILED 并给出可读原因。
    # 此前该场景由 semaphore.acquire 抛 ValueError，异常被后台任务静默吞掉，
    # 任务永远卡在 QUEUED 且无任何提示。
    if weight > semaphore.max_weight:
        reason = (
            f"任务权重 {weight} 超过并发上限 {semaphore.max_weight}"
            f"（AGNES_RATE_LIMIT={app_state.get_rate_limit()}，"
            f"请调高该值或配置多个 API Key）"
        )
        logger.error(f"[Concurrency] Task {task_id} rejected: {reason}")
        app_state._queued_tasks.pop(task_id, None)
        task_manager.update_state(
            status=StepStatus.FAILED,
            current_step="init",
            current_status="failed",
            current_message=reason,
        )
        return

    acquired = False
    try:
        # 等待并发槽位
        await semaphore.acquire(weight)
        acquired = True
        # 已获取槽位，从排队列表移除
        app_state._queued_tasks.pop(task_id, None)

        logger.info(
            f"[Concurrency] Task {task_id} acquired slot (weight={weight}, "
            f"current={semaphore.current}/{semaphore.max_weight})"
        )

        # 检查是否在排队期间被 stop
        if getattr(pipeline, '_stop_event', None) and pipeline._stop_event.is_set():
            logger.info(f"[Concurrency] Task {task_id} was stopped while queued, skipping")
            return

        # 启动 pipeline
        await run_pipeline(pipeline, state)
    except asyncio.CancelledError:
        # 任务被取消（如 stop 操作）：清理后必须重新抛出，
        # 否则取消信号被吞掉，上层无法感知（S7497）。
        app_state._queued_tasks.pop(task_id, None)
        logger.info(f"[Concurrency] Task {task_id} cancelled while queued")
        raise
    except Exception as e:
        # 0.4：获取槽位阶段的异常不再静默吞掉，落盘为 FAILED 供用户查看
        logger.error(
            f"[Concurrency] Task {task_id} failed before run: {e}", exc_info=True
        )
        app_state._queued_tasks.pop(task_id, None)
        task_manager.update_state(
            status=StepStatus.FAILED,
            current_step="init",
            current_status="failed",
            current_message=f"任务启动失败：{e}",
        )
    finally:
        # 0.4：仅当确实获取到槽位时才释放。此前 finally 无条件释放，若 acquire
        # 失败或排队中被取消，会让 semaphore.current 变负、并发控制永久失效。
        if acquired:
            try:
                await semaphore.release(weight)
                logger.info(
                    f"[Concurrency] Task {task_id} released slot (weight={weight}, "
                    f"current={semaphore.current}/{semaphore.max_weight})"
                )
            except Exception:
                pass
        app_state._queued_tasks.pop(task_id, None)


# 下划线别名：兼容旧代码 ``from server import _create_pipeline_for_type`` 等导入
_create_pipeline_for_type = create_pipeline_for_type
_run_pipeline = run_pipeline
_run_pipeline_with_concurrency = run_pipeline_with_concurrency
