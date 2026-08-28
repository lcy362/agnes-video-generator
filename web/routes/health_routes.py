"""3.2 可观测与运维：/api/health（探活）+ /api/metrics（运行指标）。

- ``GET /api/health``：轻量探活（Docker HEALTHCHECK / compose 健康检查用），
  不带业务语义、不触达任何外部依赖。
- ``GET /api/metrics``：限速器统计、并发信号量利用率、活跃/排队任务分布。
"""
import logging

from fastapi import APIRouter

from web import app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/health")
async def health():
    """轻量探活端点。"""
    return {"ok": True, "service": "agnes-video-generator", "status": "healthy"}


@router.get("/api/metrics")
async def metrics():
    """运行指标（限速器统计 + 并发利用率 + 活跃任务分布）。"""
    limiter_stats: dict = {}
    video_limiter_stats: dict = {}
    try:
        from core.api.rate_limiter import get_rate_limiter, get_video_submit_limiter
        limiter_stats = get_rate_limiter().stats
        video_limiter_stats = get_video_submit_limiter().stats
    except Exception as e:
        logger.warning(f"[Metrics] limiter stats unavailable: {e}")

    sem = app_state.get_semaphore()
    return {
        "ok": True,
        "rate_limiter": limiter_stats,
        "video_limiter": video_limiter_stats,
        "concurrency": {
            "current_weight": sem.current,
            "max_weight": sem.max_weight,
            "usage_pct": (
                round(sem.current / sem.max_weight * 100, 1)
                if sem.max_weight
                else 0.0
            ),
        },
        "tasks": {
            "active": len(app_state.active_pipelines),
            "queued": len(app_state._queued_tasks),
            "active_ids": sorted(app_state.active_pipelines.keys()),
        },
    }
