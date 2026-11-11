"""简单图片生成路由（任务 + working_dir 持久化）。"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.api.agnes_image import AgnesImageAPI
from core.config import api_key_missing_msg, get_api_key, get_max_ref_images
from core.i18n_backend import get_current_lang, translate
from core.task_manager import TaskManager
from models.task import SimpleImageTask, StepStatus
from utils.network import describe_network_error
from web import helpers
from web.log_safe import safe_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["image"])

_VALID_SIZES = {
    "1024x1024", "768x1152", "1152x768", "768x1344",
    "1344x768", "1792x1024", "1024x1792",
}

# 参考图上传允许的扩展名白名单（拒绝任意后缀，杜绝路径穿越/异常文件）

@router.post("/api/image/generate")
async def generate_image(
    prompt: str = Form(...),
    size: str = Form("1024x1024"),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    # v8.1：i2i 多参考图（上游 extra_body.image 本就是数组）。
    # 旧 ``reference_image`` 单数字段保留兼容，两边都传时以前的为准并集。
    reference_images: List[UploadFile] = File([]),
    reference_image: UploadFile = File(None),
):
    """简单图片生成：创建任务 → 直调 Agnes Image API → 保存到任务目录。"""
    api_key = get_api_key()
    if not api_key:
        # v7.0（issue #64）：按请求 UI 语言返回中/英文提示，避免英文界面看到中文报错
        raise HTTPException(status_code=400, detail=api_key_missing_msg())

    if len(prompt) > 5000:
        # validation.prompt_too_long 由另一分片定义（跨分片复用，仅调用）
        raise HTTPException(status_code=422, detail=translate("validation.prompt_too_long"))
    if not prompt.strip():
        raise HTTPException(status_code=422, detail=translate("validation.prompt_empty"))
    if size not in _VALID_SIZES:
        raise HTTPException(
            status_code=422, detail=translate("image.size_invalid", opts=_VALID_SIZES),
        )

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
        # v7.0：从 LangContextMiddleware 写入的 ContextVar 里取用户 UI 语言，
        # 落盘到任务状态，保证后续异步失败消息与用户界面语言一致
        ui_language=get_current_lang(),
    )

    # 先用 PENDING 创建任务目录和状态文件
    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)

    image_api = AgnesImageAPI(api_key=api_key)

    # v8.1：多参考图（上限唯一来源 core.config.get_max_ref_images）
    uploads = [f for f in (reference_images if isinstance(reference_images, (list, tuple)) else [])
               if f and getattr(f, "filename", "")]
    if reference_image is not None and getattr(reference_image, "filename", ""):
        uploads.append(reference_image)
    max_refs = get_max_ref_images(media="image")
    if len(uploads) > max_refs:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.too_many_ref_images", None,
                             max=max_refs, current=len(uploads)),
        )

    ref_paths = []
    if uploads:
        # 复用任务创建侧的落盘逻辑（扩展名白名单 / 大小上限 / 可解码校验 / 防穿越），
        # 避免图片侧再维护一套「后缀撒谎 + 无大小上限」的旧逻辑。
        from web.routes.task_creation_routes import _save_upload_file

        upload_dir = helpers.get_upload_dir()
        os.makedirs(upload_dir, exist_ok=True)
        batch = uuid.uuid4().hex[:8]
        for idx, upload in enumerate(uploads):
            ref_paths.append(await _save_upload_file(
                upload, upload_dir, f"img_ref_{batch}_{idx}",
            ))
        # 参考图落盘路径写回状态（诊断 / 续传 / 产物登记需要）
        state.reference_images = ref_paths
        tm.update_state(reference_images=ref_paths)

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
        # v7.0（issue #64）：按任务落盘的 ui_language 生成双语网络诊断
        message = describe_network_error(e, lang=state.ui_language) or str(e)
        state.status = StepStatus.FAILED
        tm.update_state(
            status=StepStatus.FAILED,
            current_step="generate",
            current_status="failed",
            current_message=message,
        )
        logger.error(f"[Image] Task {task_id} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=message)

    img_filename = "final_image.png"
    img_path = os.path.join(tm.task_dir, img_filename)
    try:
        await output.save(img_path)
    except Exception as e:
        message = describe_network_error(e, lang=state.ui_language) or str(e)
        # 图片保存失败提示按 ui_language 本地化
        save_failed = translate("image.save_failed", state.ui_language, reason=message)
        state.status = StepStatus.FAILED
        tm.update_state(
            status=StepStatus.FAILED,
            current_step="save",
            current_status="failed",
            current_message=save_failed,
        )
        logger.error(f"[Image] Task {task_id} save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=save_failed)

    state.status = StepStatus.COMPLETED
    state.final_video_file = img_path
    tm.update_state(status=StepStatus.COMPLETED, final_video_file=img_path)

    logger.info("[Image] Task %s completed: %s, prompt=%s...",
                safe_log(task_id), img_path, safe_log(prompt[:60]))
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
