"""
Agnes Video Generator v2.0 — FastAPI 服务层

三种任务类型的路由集成：
- POST /api/tasks/simple      — 简单视频生成
- POST /api/tasks/creative    — 创意长视频生成
- POST /api/tasks/manuscript  — 稿件长视频生成
- POST /api/tasks             — 向后兼容（映射到 creative）

所有类型共享 WebSocket 进度推送、任务列表、任务详情、视频下载等端点。
resume 端点根据 task_type 自动选择对应的 Pipeline。
"""

import asyncio
import json
import logging
import os
import re
import signal
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Optional, Union

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from core.config import get_api_key, set_api_key, get_working_dir, AVAILABLE_VOICES, DURATION_FRAME_MAP
from core.pipelines import (
    BasePipeline,
    PipelineShutdown,
    SimpleVideoPipeline,
    CreativeVideoPipeline,
    ManuscriptVideoPipeline,
)
from core.task_manager import TaskManager
from models.task import (
    AudioConfig,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    SimpleVideoTask,
    StepStatus,
    SubtitleStyle,
    TaskType,
    VideoMode,
)


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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Suppress noisy WebSocket heartbeat / protocol logs from uvicorn and websockets
logging.getLogger("uvicorn.protocols.websockets").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

active_connections: Dict[str, WebSocket] = {}
active_pipelines: Dict[str, BasePipeline] = {}
shutdown_event = asyncio.Event()


def _find_dir_name(task_id: str) -> str:
    """Find the directory name for a task_id. Falls back to task_id for legacy tasks."""
    tm = TaskManager("_")
    for t in tm.list_tasks():
        if t["task_id"] == task_id:
            return t.get("dir_name", task_id)
    return task_id


# ═══════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(get_working_dir(), exist_ok=True)
    upload_dir = os.path.join(get_working_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    working_dir = get_working_dir()
    if os.path.exists(working_dir):
        for name in os.listdir(working_dir):
            task_file = os.path.join(working_dir, name, "task_state.json")
            if os.path.exists(task_file):
                try:
                    with open(task_file, "r") as f:
                        data = json.load(f)
                    if data.get("status") == "running":
                        data["status"] = "pending"
                        with open(task_file, "w") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        logger.info(f"[Startup] Reset stale running task {name} -> pending")
                except Exception:
                    pass

    yield


app = FastAPI(title="Agnes Video Generator", lifespan=lifespan)

UPLOAD_DIR = os.path.join(get_working_dir(), "uploads")


# ═══════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════


@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await websocket.accept()
    logger.info(f"[WS] Client connected for task {task_id}")
    active_connections[task_id] = websocket

    async def progress_callback(step: str, status: str, message: str, progress: float, data: dict):
        try:
            await websocket.send_json({
                "type": "progress",
                "task_id": task_id,
                "step": step,
                "status": status,
                "message": message,
                "progress": progress,
                "data": data,
            })
        except Exception:
            pass

    if task_id in active_pipelines:
        logger.info(f"[WS] Binding existing pipeline for task {task_id}")
        active_pipelines[task_id].progress_callback = progress_callback

    try:
        while True:
            msg = await websocket.receive_text()
            if not msg or msg.strip().lower() in ("ping", "pong"):
                continue
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected for task {task_id}")
    except Exception as e:
        logger.warning(f"[WS] Error for task {task_id}: {e}")
    finally:
        if task_id in active_connections:
            del active_connections[task_id]


# ═══════════════════════════════════════════════════
# Static files + Root
# ═══════════════════════════════════════════════════


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Agnes Video Generator API"}


# ═══════════════════════════════════════════════════
# API Key 配置
# ═══════════════════════════════════════════════════


@app.get("/api/config")
async def get_config():
    key = get_api_key()
    data = {"api_key": key[:8] + "..." if key else ""}
    return data


@app.post("/api/config")
async def save_config(api_key: str = Form(...)):
    set_api_key(api_key)
    return {"ok": True}


@app.get("/api/voices")
async def get_voices():
    """返回可选 TTS 语音角色列表。"""
    return {"voices": AVAILABLE_VOICES}


# ═══════════════════════════════════════════════════
# 任务列表 + 详情 + 视频下载
# ═══════════════════════════════════════════════════


@app.get("/api/tasks")
async def list_tasks():
    tm = TaskManager("_")
    tasks = tm.list_tasks()
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
            # 简单视频
            elif isinstance(state, SimpleVideoTask):
                t["prompt"] = state.prompt[:100] if state.prompt else ""
                t["mode"] = state.mode
    return {"tasks": tasks}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")
    data = state.model_dump()
    data["dir_name"] = dir_name
    return data


@app.get("/api/video/{task_id}")
async def serve_video(task_id: str):
    dir_name = _find_dir_name(task_id)
    task_dir = os.path.join(get_working_dir(), dir_name)
    video_path = os.path.join(task_dir, "final_video.mp4")
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path, media_type="video/mp4")


# ═══════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════


def _parse_duration(user_requirement: str) -> int:
    match = re.search(r'(?:每个场景|每段|每节|每)(?:约)?(\d+)\s*(?:秒|s)', user_requirement)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d+)\s*(?:秒|s)\s*(?:每|/)', user_requirement)
    if match:
        return int(match.group(1))
    return 5


def _make_progress_callback(task_id: str, ws: Optional[WebSocket] = None):
    """创建进度回调函数。优先使用传入的 ws，否则查找 active_connections。"""
    async def progress_callback(step: str, status: str, message: str, progress: float, data: dict):
        try:
            target_ws = ws or active_connections.get(task_id)
            if target_ws:
                await target_ws.send_json({
                    "type": "progress",
                    "task_id": task_id,
                    "step": step,
                    "status": status,
                    "message": message,
                    "progress": progress,
                    "data": data,
                })
        except Exception:
            pass
    return progress_callback


def _create_pipeline_for_type(
    task_type: TaskType,
    api_key: str,
    task_id: str,
    dir_name: str,
) -> BasePipeline:
    """根据任务类型创建对应的 Pipeline 实例。"""
    if task_type == TaskType.SIMPLE:
        return SimpleVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    elif task_type == TaskType.MANUSCRIPT:
        return ManuscriptVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )
    else:
        # CREATIVE（默认）
        return CreativeVideoPipeline(
            api_key=api_key,
            task_id=task_id,
            dir_name=dir_name,
            shutdown_event=shutdown_event,
        )


async def _run_pipeline(pipeline: BasePipeline, state: BaseTaskState):
    """通用 Pipeline 执行包装器。"""
    try:
        logger.info(f"[Pipeline] Starting run for task {pipeline.task_id}, type={state.task_type}")
        await pipeline.run(state)
        logger.info(f"[Pipeline] Completed run for task {pipeline.task_id}")
    except PipelineShutdown:
        logger.info(f"[Pipeline] Task {pipeline.task_id} stopped by user")
    except Exception as e:
        logger.error(f"[Pipeline] Task {pipeline.task_id} failed: {e}", exc_info=True)
    finally:
        if pipeline.task_id in active_pipelines:
            del active_pipelines[pipeline.task_id]


# ═══════════════════════════════════════════════════
# 任务创建端点 — 三种类型
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/simple")
async def create_simple_task(
    prompt: str = Form(...),
    mode: str = Form("t2v"),
    duration: int = Form(5),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    seed: Optional[int] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    reference_image: UploadFile = File(None),
    end_frame_image: UploadFile = File(None),
):
    """创建简单视频任务（类型 1）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    task_id = uuid.uuid4().hex[:12]
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 映射模式
    video_mode = VideoMode.T2V
    if mode in ("i2v", "ti2vid"):
        video_mode = VideoMode.I2V if mode == "i2v" else VideoMode.TI2VID
    elif mode == "keyframes":
        video_mode = VideoMode.KEYFRAMES

    state = SimpleVideoTask(
        task_id=task_id,
        creative_name=f"simple_{task_id}",
        prompt=prompt,
        mode=video_mode,
        duration=duration,
        video_width=video_width,
        video_height=video_height,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    # 处理参考图上传
    if reference_image and reference_image.filename:
        upload_path = os.path.join(UPLOAD_DIR, f"{task_id}_ref_{reference_image.filename}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    # 处理尾帧图上传（keyframes 模式）
    if end_frame_image and end_frame_image.filename:
        upload_path = os.path.join(UPLOAD_DIR, f"{task_id}_end_{end_frame_image.filename}")
        with open(upload_path, "wb") as f:
            f.write(await end_frame_image.read())
        state.end_frame_image = upload_path

    pipeline = _create_pipeline_for_type(TaskType.SIMPLE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    asyncio.create_task(_run_pipeline(pipeline, state))
    logger.info(f"[Simple] Task created: {task_id}, mode={mode}, duration={duration}s")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/creative")
async def create_creative_task(
    idea: str = Form(...),
    creative_name: str = Form(""),
    user_requirement: str = Form("3个场景，每个场景10秒，电影质感"),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(5),
    reference_image: UploadFile = File(None),
    end_frame_images: list = None,
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(False),
    # v2.0 音频配置
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建创意长视频任务（类型 2）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"video_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 解析时长
    parsed_duration = _parse_duration(user_requirement)

    # 构建音频配置
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
    )
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
        subtitle_style=subtitle_style,
    )

    state = CreativeVideoTask(
        task_id=task_id,
        creative_name=name,
        idea=idea,
        user_requirement=user_requirement,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        video_duration=parsed_duration,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        audio_config=audio_config,
    )

    logger.info(f"[Pipeline] Parsed video_duration={parsed_duration}s from user_requirement={user_requirement!r}")

    # 处理参考图上传
    if reference_image and reference_image.filename:
        upload_path = os.path.join(UPLOAD_DIR, f"{task_id}_ref_{reference_image.filename}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    pipeline = _create_pipeline_for_type(TaskType.CREATIVE, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    asyncio.create_task(_run_pipeline(pipeline, state))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/manuscript")
async def create_manuscript_task(
    manuscript_text: str = Form(...),
    creative_name: str = Form(""),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(10),
    # v2.0 音频配置
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
):
    """创建稿件长视频任务（类型 3）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    if not manuscript_text.strip():
        raise HTTPException(status_code=400, detail="稿件内容不能为空")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"manuscript_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=_build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=_parse_bg_color(subtitle_bg_color),
    )
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
        subtitle_style=subtitle_style,
    )

    state = ManuscriptVideoTask(
        task_id=task_id,
        creative_name=name,
        manuscript_text=manuscript_text.strip(),
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        audio_config=audio_config,
    )

    pipeline = _create_pipeline_for_type(TaskType.MANUSCRIPT, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        pipeline.progress_callback = _make_progress_callback(task_id)

    asyncio.create_task(_run_pipeline(pipeline, state))
    logger.info(f"[Manuscript] Task created: {task_id}, text_len={len(manuscript_text)}")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


# ═══════════════════════════════════════════════════
# 向后兼容：旧的 POST /api/tasks → 映射到 creative
# ═══════════════════════════════════════════════════


@app.post("/api/tasks")
async def create_task_legacy(
    idea: str = Form(...),
    creative_name: str = Form(""),
    user_requirement: str = Form("3个场景，每个场景10秒，电影质感"),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    reference_image: UploadFile = File(None),
    end_frame_images: list = None,
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(False),
):
    """向后兼容旧端点，映射到 create_creative_task。"""
    return await create_creative_task(
        idea=idea,
        creative_name=creative_name,
        user_requirement=user_requirement,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        reference_image=reference_image,
        end_frame_images=end_frame_images,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        # 提供音频/字幕默认值（旧端点不传这些参数）
        audio_enabled=True,
        audio_voice="zh-CN-XiaoxiaoNeural",
        audio_rate="+0%",
        subtitle_font="STHeitiMedium.ttc",
        subtitle_color="white",
        subtitle_fontsize=48,
        subtitle_position="bottom",
        subtitle_stroke_color="black",
        subtitle_stroke_width=2,
        subtitle_bg_color="black@0.5",
    )


# ═══════════════════════════════════════════════════
# 任务恢复 + 停止
# ═══════════════════════════════════════════════════


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    if task_id in active_pipelines:
        existing = active_pipelines[task_id]
        if existing._stop_event.is_set():
            logger.info(f"[Resume] Replacing stopped pipeline for task {task_id}")
            del active_pipelines[task_id]
        else:
            raise HTTPException(status_code=400, detail="Task is already running")

    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state:
        raise HTTPException(status_code=404, detail="Task not found")

    if state.status == StepStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Task is already completed")

    logger.info(f"[Resume] Starting resume for task {task_id}, type={state.task_type}, status={state.status}")

    # v2.0：根据 task_type 选择对应的 Pipeline
    pipeline = _create_pipeline_for_type(state.task_type, api_key, task_id, dir_name)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        logger.info(f"[Resume] Binding existing WebSocket for task {task_id}")
        pipeline.progress_callback = _make_progress_callback(task_id)

    asyncio.create_task(_run_pipeline(pipeline, state))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    if task_id not in active_pipelines:
        raise HTTPException(status_code=400, detail="Task is not running")

    pipeline = active_pipelines[task_id]
    pipeline.stop()

    dir_name = _find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if state and state.status == StepStatus.RUNNING:
        tm.update_state(status=StepStatus.PENDING)
        logger.info(f"[Stop] Task {task_id} status -> pending")

    logger.info(f"[Stop] Task {task_id} stop requested")
    return {"ok": True, "task_id": task_id}


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════


if __name__ == "__main__":
    import uvicorn

    config = uvicorn.Config(app, host="0.0.0.0", port=8765, log_level="info")
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
