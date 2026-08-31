"""
Agnes Video Generator — FastAPI 服务层（Batch 1 模块化后）。

路由已拆分到 ``web/routes/``（8 个 APIRouter 模块），本文件仅保留：
- app 组装（include_router 汇总）+ 静态资源挂载
- lifespan 生命周期（初始化运行时状态 + 预加载音色目录）
- 启动入口（uvicorn + 优雅退出）
- 兼容 re-export（供旧代码 / 测试从 ``server`` 导入）

任务类型路由（见 web/routes/task_creation_routes.py）：
- POST /api/tasks/simple      — 简单视频生成
- POST /api/tasks/creative    — 创意长视频生成
- POST /api/tasks/manuscript  — 稿件长视频生成
- POST /api/tasks/poetry     — 诗词视频生成
- POST /api/tasks/anchor     — 数字人口播生成
- POST /api/tasks             — 向后兼容（映射到 creative）
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.audio.voices import load_voice_catalog
from web import app_state  # noqa: F401 兼容 re-export：旧代码 from server import app_state
from web.app_state import init_runtime_state
from web.routes import (
    config_routes,
    health_routes,
    image_routes,
    preview_routes,
    task_creation_routes,
    task_routes,
    utility_routes,
    video_routes,
    voice_routes,
    workspace_routes,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化工作目录 / uploads / 错误收集根路径，并重置上次异常退出的遗留任务
    init_runtime_state()

    # 3.2：可选文件日志（AGNES_LOG_FILE 设置后启用，10MB 轮转 × 5 份）
    from core.config import get_settings as _settings
    log_file = _settings().agnes_log_file.strip()
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler
            fh = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
            )
            fh.setLevel(logging.INFO)
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            ))
            logging.getLogger().addHandler(fh)
            logger.info(f"[Startup] File logging enabled → {log_file}")
        except Exception as e:
            logger.warning(f"[Startup] File logging setup failed: {e}")

    # v4.0: 预加载音色目录（edge_tts.list_voices）。
    # edge_tts.list_voices() 是网络调用，若网络慢/不可达会阻塞 lifespan 的 yield，
    # 导致服务启动后数秒内不可用。这里限时等待 3 秒：
    # - 正常网络（1~2s）：目录在对外服务前就绪，/api/voices 无回退闪烁
    # - 慢网络：超过 3s 立即对外服务，剩余加载转入后台，完成后自动切换完整目录
    async def _load_voice_catalog_bg():
        try:
            await load_voice_catalog()
            logger.info("[Startup] Voice catalog loaded")
        except Exception as e:
            logger.warning(f"[Startup] Voice catalog load failed ({e}); will use fallback")

    try:
        await asyncio.wait_for(load_voice_catalog(), timeout=3.0)
        logger.info("[Startup] Voice catalog loaded")
    except asyncio.TimeoutError:
        logger.warning("[Startup] Voice catalog load timed out (>3s); continuing in background")
        asyncio.create_task(_load_voice_catalog_bg())
    except Exception as e:
        logger.warning(f"[Startup] Voice catalog load failed ({e}); will use fallback")

    # v5.0 (5.1): 可选启动时僵尸任务清理（AGNES_SWEEP_AGE_DAYS 设置后启用，失败不阻断）
    sweep_days = _settings().agnes_sweep_age_days
    if sweep_days and sweep_days > 0:
        try:
            from core.artifacts import sweep_stale_tasks
            result = sweep_stale_tasks(age_days=sweep_days)
            logger.info(f"[Startup] Stale task sweep: "
                        f"swept={result['swept']}, protected={len(result['protected'])}")
        except Exception as e:
            logger.warning(f"[Startup] Stale task sweep failed ({e})")

    # ffmpeg 启动检测（非阻断）：解析一次并打印来源；缺失仅告警、不阻止启动。
    try:
        from core.compositor.ffmpeg_tool import resolve_binary
        ffmpeg_bin = resolve_binary("ffmpeg")
        if ffmpeg_bin:
            logger.info(f"[Compositor] ffmpeg resolved: {ffmpeg_bin}")
        else:
            logger.warning(
                "[Compositor] ffmpeg NOT found (no system PATH nor builtin "
                "imageio-ffmpeg). Video/audio composition will fail later; "
                "install ffmpeg or verify imageio-ffmpeg dependency."
            )
    except Exception as e:
        logger.warning(f"[Compositor] ffmpeg detection failed: {e}")

    yield


app = FastAPI(
    title="Agnes Video Generator",
    description=(
        "完全免费的 AI 视频生成服务。官网：https://video.lichuanyang.top ｜ "
        "API 文档：https://video.lichuanyang.top/api-docs ｜ "
        "调用指南：https://video.lichuanyang.top/api-docs"
    ),
    lifespan=lifespan,
)


# Phase 2（PR #33 吸收）：可配置 CORS 白名单——取代原 PR 硬编码的 :8787。
# 空（默认）→ 不启用中间件（攻击面不变）；设置 AGNES_CORS_ORIGINS 后仅允许
# 列出的源跨源调用。认证走显式 API Key（请求头），不使用 Cookie，因此
# allow_credentials=False 始终安全。
from core.config import get_settings as _settings  # noqa: E402 就地导入

_cors_settings = _settings()
_cors_origins = [
    o.strip() for o in (_cors_settings.agnes_cors_origins or "").split(",") if o.strip()
]
_cors_enabled = _cors_settings.agnes_cors_enabled
if _cors_enabled is None:
    _cors_enabled = bool(_cors_origins)
if _cors_enabled and _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    logger.info(f"[Startup] CORS enabled for origins: {_cors_origins}")
elif _cors_settings.agnes_cors_origins:
    logger.warning(
        "[Startup] CORS origins set but AGNES_CORS_ENABLED=false, "
        "middleware disabled",
    )


# ═══════════════════════════════════════════════════
# Static files
# ═══════════════════════════════════════════════════

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _serve_static_file(filename: str, media_type: str):
    """返回 static 目录中的文件；不存在时 404（与挂载目录行为一致）。"""
    path = os.path.join(static_dir, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type=media_type)
    raise HTTPException(status_code=404, detail=f"{filename} not found")


# 根路径图标：HTML 虽声明 /static/favicon.ico，但 Safari 等客户端
# 仍会额外探测根路径 /favicon.ico（及 /icon.png），无路由时每次打开页面
# 产生一次短暂 404，这里显式补上。
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return _serve_static_file("favicon.ico", "image/x-icon")


@app.get("/icon.png", include_in_schema=False)
async def icon():
    return _serve_static_file("icon.png", "image/png")


# ═══════════════════════════════════════════════════
# 路由汇总（Batch 1 拆分）
# ═══════════════════════════════════════════════════

app.include_router(utility_routes.router)
app.include_router(health_routes.router)
app.include_router(config_routes.router)
app.include_router(workspace_routes.router)
app.include_router(voice_routes.router)
app.include_router(image_routes.router)
app.include_router(video_routes.router)
app.include_router(task_routes.router)
app.include_router(task_creation_routes.router)
app.include_router(preview_routes.router)


# ═══════════════════════════════════════════════════
# 兼容 re-export（旧代码 / tests/test_core.py 从 server 导入）
# ═══════════════════════════════════════════════════

from web.helpers import (  # noqa: E402,F401,I001 兼容 re-export，勿删
    _build_position,
    _has_explicit_duration,
    _parse_bg_color,
    _parse_duration,
    get_upload_dir,
)
from web.app_state import (  # noqa: E402,F401,I001 兼容 re-export，勿删
    MAX_CONCURRENT_WEIGHT,
    TASK_TYPE_WEIGHTS,
    WeightedSemaphore,
    _AGNES_RATE_LIMIT,
    _pipeline_semaphore,
    _queued_tasks,
    active_pipelines,
    background_tasks,
    shutdown_event,
)
from web.deps import (  # noqa: E402,F401,I001 兼容 re-export，勿删
    _create_pipeline_for_type,
    _run_pipeline,
    _run_pipeline_with_concurrency,
)


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    # 允许通过环境变量覆盖监听地址/端口（npm 启动器 free-short-video 会注入）
    # 默认值保持向后兼容：0.0.0.0:8765（3.5 经 RuntimeSettings 收敛）
    from core.config import get_settings as _settings
    _HOST = _settings().host
    _PORT = _settings().port
    config = uvicorn.Config(app, host=_HOST, port=_PORT, log_level="info")
    server = uvicorn.Server(config)

    original_handle_exit = server.handle_exit

    def _handle_exit(sig, frame):
        if shutdown_event.is_set():
            logger.warning("Force exiting...")
            os._exit(1)
        logger.info("Shutting down gracefully (Ctrl+C again to force)...")
        shutdown_event.set()
        if callable(original_handle_exit):
            original_handle_exit(sig, frame)

    server.handle_exit = _handle_exit
    server.run()
