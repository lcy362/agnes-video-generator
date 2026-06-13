import asyncio
import json
import logging
import os
import signal
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from core.config import get_api_key, set_api_key, get_working_dir
from core.pipeline import VideoPipeline, PipelineShutdown
from core.task_manager import TaskManager
from models.task import TaskState, CreateTaskRequest, StepStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Suppress noisy WebSocket heartbeat / protocol logs from uvicorn and websockets
logging.getLogger("uvicorn.protocols.websockets").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

active_connections: Dict[str, WebSocket] = {}
active_pipelines: Dict[str, VideoPipeline] = {}
shutdown_event = asyncio.Event()


def _find_dir_name(task_id: str) -> str:
    """Find the directory name for a task_id. Falls back to task_id for legacy tasks."""
    tm = TaskManager("_")
    for t in tm.list_tasks():
        if t["task_id"] == task_id:
            return t.get("dir_name", task_id)
    return task_id


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
            # Filter out browser heartbeat / ping-pong frames
            if not msg or msg.strip().lower() in ("ping", "pong"):
                continue
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected for task {task_id}")
    except Exception as e:
        logger.warning(f"[WS] Error for task {task_id}: {e}")
    finally:
        if task_id in active_connections:
            del active_connections[task_id]


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Agnes Video Generator API"}


@app.get("/api/config")
async def get_config():
    return {"api_key": get_api_key()[:8] + "..." if get_api_key() else ""}


@app.post("/api/config")
async def save_config(api_key: str = Form(...)):
    set_api_key(api_key)
    return {"ok": True}


@app.get("/api/tasks")
async def list_tasks():
    tm = TaskManager("_")
    tasks = tm.list_tasks()
    for t in tasks:
        task_tm = TaskManager(t["task_id"], dir_name=t.get("dir_name"))
        state = task_tm.load()
        if state:
            t["final_video_file"] = state.final_video_file
            t["scene_count"] = state.scene_count
            t["idea"] = state.idea[:100] if state.idea else ""
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

    logger.info(f"[Resume] Starting resume for task {task_id}, status={state.status}")
    logger.info(f"[Resume] Steps: image_analysis={state.step_image_analysis}, story={state.step_story}, "
                f"character_ref={state.step_character_ref}, script={state.step_script}, "
                f"end_frame_prompts={state.step_end_frame_prompts}, "
                f"end_frame_gen={state.step_end_frame_generation}, "
                f"video_gen={state.step_video_generation}, concat={state.step_concatenation}")

    pipeline = VideoPipeline(api_key=api_key, task_id=task_id, dir_name=dir_name, shutdown_event=shutdown_event)
    active_pipelines[task_id] = pipeline

    if task_id in active_connections:
        logger.info(f"[Resume] Binding existing WebSocket for task {task_id}")
        ws = active_connections[task_id]

        async def progress_callback(step: str, status: str, message: str, progress: float, data: dict):
            try:
                await ws.send_json({
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

        pipeline.progress_callback = progress_callback

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


@app.post("/api/tasks")
async def create_task(
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
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先配置 API Key")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"video_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    state = TaskState(
        task_id=task_id,
        creative_name=name,
        idea=idea,
        user_requirement=user_requirement,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
    )

    if reference_image:
        upload_path = os.path.join(UPLOAD_DIR, f"{task_id}_ref_{reference_image.filename}")
        with open(upload_path, "wb") as f:
            f.write(await reference_image.read())
        state.reference_image = upload_path

    pipeline = VideoPipeline(api_key=api_key, task_id=task_id, dir_name=dir_name, shutdown_event=shutdown_event)
    active_pipelines[task_id] = pipeline

    asyncio.create_task(_run_pipeline(pipeline, state))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


async def _run_pipeline(pipeline: VideoPipeline, state: TaskState):
    try:
        logger.info(f"[Pipeline] Starting run for task {pipeline.task_id}")
        await pipeline.run(state)
        logger.info(f"[Pipeline] Completed run for task {pipeline.task_id}")
    except PipelineShutdown:
        logger.info(f"[Pipeline] Task {pipeline.task_id} stopped by user")
    except Exception as e:
        logger.error(f"[Pipeline] Task {pipeline.task_id} failed: {e}", exc_info=True)
    finally:
        if pipeline.task_id in active_pipelines:
            del active_pipelines[pipeline.task_id]


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