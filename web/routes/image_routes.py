"""简单图片生成路由（任务 + working_dir 持久化）。"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.api.agnes_image import AgnesImageAPI
from core.config import API_KEY_MISSING_MSG, get_api_key
from core.task_manager import TaskManager
from models.task import SimpleImageTask, StepStatus
from web import helpers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["image"])

_VALID_SIZES = {
    "1024x1024", "768x1152", "1152x768", "768x1344",
    "1344x768", "1792x1024", "1024x1792",
}


@router.post("/api/image/generate")
async def generate_image(
    prompt: str = Form(...),
    size: str = Form("1024x1024"),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_image: UploadFile = File(None),
):
    """简单图片生成：创建任务 → 直调 Agnes Image API → 保存到任务目录。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    if len(prompt) > 5000:
        raise HTTPException(status_code=422, detail="prompt 最多 5000 字符")
    if not prompt.strip():
        raise HTTPException(status_code=422, detail="prompt 不能为空")
    if size not in _VALID_SIZES:
        raise HTTPException(status_code=422, detail=f"size 必须为 {_VALID_SIZES} 之一")

    task_id = uuid.uuid4().hex[:12]
    name = f"image_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    state = SimpleImageTask(
        task_id=task_id,
        creative_name=name,
        prompt=prompt.strip(),
        size=size,
        negative_prompt=negative_prompt or "",
        system_prompt=system_prompt,
    )

    # 先用 PENDING 创建任务目录和状态文件
    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)

    image_api = AgnesImageAPI(api_key=api_key)

    ref_paths = []
    if reference_image and reference_image.filename:
        ext = os.path.splitext(reference_image.filename)[1] or ".png"
        upload_dir = helpers.get_upload_dir()
        os.makedirs(upload_dir, exist_ok=True)
        ref_path = os.path.join(upload_dir, f"img_ref_{uuid.uuid4().hex[:8]}{ext}")
        with open(ref_path, "wb") as f:
            f.write(await reference_image.read())
        ref_paths.append(ref_path)

    try:
        state.status = StepStatus.RUNNING
        tm.update_state(status=StepStatus.RUNNING)

        full_prompt = helpers._build_encrypted_image_prompt(system_prompt, prompt) if system_prompt.strip() else prompt
        output = await image_api.generate_single_image(
            prompt=full_prompt,
            reference_image_paths=ref_paths,
            size=size,
            negative_prompt=negative_prompt,
        )
    except Exception as e:
        state.status = StepStatus.FAILED
        tm.update_state(status=StepStatus.FAILED)
        logger.error(f"[Image] Task {task_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    img_filename = "final_image.png"
    img_path = os.path.join(tm.task_dir, img_filename)
    try:
        await output.save(img_path)
    except Exception as e:
        state.status = StepStatus.FAILED
        tm.update_state(status=StepStatus.FAILED)
        logger.error(f"[Image] Task {task_id} save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"图片保存失败: {e}")

    state.status = StepStatus.COMPLETED
    state.final_video_file = img_path
    tm.update_state(status=StepStatus.COMPLETED, final_video_file=img_path)

    logger.info(f"[Image] Task {task_id} completed: {img_path}, prompt={prompt[:60]}...")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.get("/api/image/{task_id}")
async def serve_image(task_id: str):
    """返回已生成的图片文件。"""
    dir_name = helpers.find_dir_name(task_id)
    tm = TaskManager(task_id, dir_name=dir_name)
    state = tm.load()
    if not state or not state.final_video_file:
        raise HTTPException(status_code=404, detail="Image not found")
    if not os.path.exists(state.final_video_file):
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(state.final_video_file)
