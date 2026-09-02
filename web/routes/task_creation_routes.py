"""任务创建路由：simple / creative / manuscript / poetry / anchor + 向后兼容旧端点。"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.async_io import write_bytes
from core.config import (
    API_KEY_MISSING_MSG,
    DURATION_FRAME_MAP,
    VIDEO_25_DURATIONS,
    get_api_key,
    get_selected_models,
    is_v25_video_model,
)
from core.path_security import safe_join
from core.pipelines import ALL_CHECKPOINTS
from core.pipelines.poetry_video import POETRY_SUBTITLE_STYLE
from core.screenwriter import build_poetry_scene_prompt
from core.task_manager import TaskManager
from models.task import (
    AnchorVideoTask,
    AudioConfig,
    CreativeVideoTask,
    ManualConfig,
    ManuscriptVideoTask,
    PoetryVideoTask,
    SimpleVideoTask,
    SubtitleConfig,
    SubtitleStyle,
    TaskType,
    VideoMode,
)
from web import app_state, deps, helpers
from web.log_safe import safe_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["task-creation"])

# 上传文件允许的扩展名白名单（拒绝任意后缀，杜绝路径穿越）
_ALLOWED_UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".mov", ".webm"}


def _parse_scene_durations_json(scene_durations_json: str) -> list:
    """解析场景时长 JSON 数组，非法时抛 422。"""
    try:
        scene_durations = json.loads(scene_durations_json)
        if not isinstance(scene_durations, list):
            raise ValueError("not a list")
    except Exception:
        raise HTTPException(status_code=422, detail="scene_durations_json 必须为 JSON 数组")
    for i, d in enumerate(scene_durations):
        if not isinstance(d, (int, float)) or d < 2 or d > 30:
            raise HTTPException(status_code=422, detail=f"场景 {i+1} 时长范围 2-30 秒")
    return scene_durations


def _build_manual_config(execution_mode: str, pause_points: str) -> ManualConfig:
    """构建手动模式配置（v6.0）。

    Args:
        execution_mode: "auto"（默认）或 "manual"。
        pause_points: JSON 数组字符串（可选暂停点集合）；空/缺省且 manual 时 = 全部检查点。

    Raises:
        HTTPException: execution_mode 非法或 pause_points 含非法值。
    """
    if execution_mode not in ("auto", "manual"):
        raise HTTPException(status_code=422, detail="execution_mode 必须为 auto 或 manual")
    if execution_mode == "auto":
        return ManualConfig()

    try:
        points = json.loads(pause_points) if pause_points else []
    except Exception:
        raise HTTPException(status_code=422, detail="pause_points 必须为 JSON 数组")
    if not isinstance(points, list):
        raise HTTPException(status_code=422, detail="pause_points 必须为 JSON 数组")

    valid = set(ALL_CHECKPOINTS)
    invalid = [p for p in points if p not in valid]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"非法暂停点: {invalid}，可选: {ALL_CHECKPOINTS}",
        )
    # 空 = 全部检查点暂停（PRD §4.3）
    return ManualConfig(enabled=True, pause_points=points or list(ALL_CHECKPOINTS))


def _build_subtitle_config(
    subtitle_enabled: bool,
    subtitle_style_mode: str,
    subtitle_style_hints: str,
    subtitle_font: str,
    subtitle_color: str,
    subtitle_fontsize: int,
    subtitle_position: str,
    subtitle_stroke_color: str,
    subtitle_stroke_width: int,
    subtitle_bg_color: str,
) -> SubtitleConfig:
    """构建独立字幕配置（v3.0）。"""
    subtitle_style = SubtitleStyle(
        font=subtitle_font,
        color=subtitle_color,
        fontsize=subtitle_fontsize,
        position=helpers._build_position(subtitle_position),
        stroke_color=subtitle_stroke_color,
        stroke_width=subtitle_stroke_width,
        bg_color=helpers._parse_bg_color(subtitle_bg_color),
        style_mode=subtitle_style_mode,
        style_hints=subtitle_style_hints,
    )
    return SubtitleConfig(
        enabled=subtitle_enabled,
        style=subtitle_style,
    )


async def _save_upload_file(upload: UploadFile, upload_dir: str, prefix: str) -> str:
    """保存上传文件（用 UUID 替代客户端文件名，避免路径穿越），返回落盘路径。

    扩展名取自白名单：客户端 filename 中夹带的任意后缀一律拒绝，
    再经 ``safe_join`` 锚定到 upload_dir 内，杜绝路径穿越（S2083）。
    """
    ext = (os.path.splitext(upload.filename)[1] or ".png").lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        ext = ".png"
    os.makedirs(upload_dir, exist_ok=True)
    upload_path = safe_join(upload_dir, f"{prefix}{ext}")
    await write_bytes(upload_path, await upload.read())
    return upload_path


@router.post("/api/tasks/simple")
async def create_simple_task(
    prompt: str = Form(...),
    mode: str = Form("t2v"),
    duration: int = Form(5),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    seed: Optional[int] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_image: UploadFile = File(None),
    end_frame_image: UploadFile = File(None),
    video_size: Optional[str] = Form(None),
):
    """创建简单视频任务（类型 1）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    # P7: 参数校验
    _VALID_MODES = {"t2v", "i2v", "ti2vid", "keyframes"}
    if mode not in _VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode 必须为 {_VALID_MODES} 之一，当前: {mode}",
        )
    # v6.2：2.5 系列模型时长档位为 4–12 秒；v2.0 仍用 DURATION_FRAME_MAP 档位
    video_model = get_selected_models().get("video") or ""
    valid_durations = VIDEO_25_DURATIONS if is_v25_video_model(video_model) else list(DURATION_FRAME_MAP.keys())
    if duration not in valid_durations:
        raise HTTPException(
            status_code=422,
            detail=f"duration 必须为 {sorted(valid_durations)} 之一，当前: {duration}",
        )
    if len(prompt) > 5000:
        raise HTTPException(status_code=422, detail="prompt 最多 5000 字符")

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
        video_size=video_size or "720P",
        seed=seed,
        negative_prompt=negative_prompt,
        system_prompt=system_prompt,
    )

    upload_dir = helpers.get_upload_dir()
    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        state.reference_image = await _save_upload_file(reference_image, upload_dir, f"{task_id}_ref")
    # 处理尾帧图上传（keyframes 模式）
    if end_frame_image and end_frame_image.filename:
        state.end_frame_image = await _save_upload_file(end_frame_image, upload_dir, f"{task_id}_end")

    pipeline = deps.create_pipeline_for_type(TaskType.SIMPLE, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Simple] Task created: {task_id}, mode={mode}, duration={duration}s (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/creative")
async def create_creative_task(
    idea: str = Form(...),
    creative_name: str = Form(""),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    # ── v3.x 场景配置 ──
    duration_source: str = Form("manual"),
    scene_count: int = Form(3),
    uniform_duration: bool = Form(True),
    scene_durations_json: str = Form("[5,5,5]"),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    scene_reference_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
    # v2.0 音频配置
    audio_enabled: bool = Form(False),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    audio_add_tashkeel: bool = Form(False),  # 阿拉伯语旁白自动加变音符号（harakat）
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
    # v6.0 手动模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
):
    """创建创意长视频任务（类型 2）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh")

    # P7: 参数校验
    if len(idea) > 10000:
        raise HTTPException(status_code=422, detail="idea 最多 10000 字符")
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(status_code=422, detail="duration_source 必须为 manual 或 prompt")
    if duration_source == "manual":
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="scene_count 范围 1-30")
        scene_durations = _parse_scene_durations_json(scene_durations_json)
    else:
        scene_durations = []

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"video_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
        add_tashkeel=audio_add_tashkeel,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_config = _build_subtitle_config(
        subtitle_enabled, subtitle_style_mode, subtitle_style_hints,
        subtitle_font, subtitle_color, subtitle_fontsize, subtitle_position,
        subtitle_stroke_color, subtitle_stroke_width, subtitle_bg_color,
    )

    state = CreativeVideoTask(
        task_id=task_id,
        creative_name=name,
        idea=idea,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        video_duration=5,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=_build_manual_config(execution_mode, pause_points),
    )

    logger.info(
        "[Pipeline] Scene config: source=%s, scenes=%s, durations=%s, uniform=%s, manual=%s",
        safe_log(duration_source), scene_count, scene_durations,
        uniform_duration, safe_log(execution_mode),
    )

    upload_dir = helpers.get_upload_dir()
    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        state.reference_image = await _save_upload_file(reference_image, upload_dir, f"{task_id}_ref")

    # P3: 处理自定义尾帧图片上传
    if use_custom_end_frames and end_frame_images:
        saved_paths = []
        for idx, ef_file in enumerate(end_frame_images):
            if ef_file and ef_file.filename:
                saved_paths.append(await _save_upload_file(ef_file, upload_dir, f"{task_id}_end_{idx}"))
        if saved_paths:
            state.end_frame_images = saved_paths
            logger.info(f"[Pipeline] Saved {len(saved_paths)} custom end frame images for task {task_id}")

    # v5.0 优化 5：用户上传分镜场景图（按场景顺序落盘，场景数不匹配时按场景 index 对齐）
    if scene_reference_images:
        saved_scene_refs = []
        for idx, sref_file in enumerate(scene_reference_images):
            if sref_file and sref_file.filename:
                saved_scene_refs.append(await _save_upload_file(sref_file, upload_dir, f"{task_id}_scene_{idx}"))
        if saved_scene_refs:
            state.scene_reference_images = saved_scene_refs
            logger.info(f"[Pipeline] Saved {len(saved_scene_refs)} user scene reference images for task {task_id}")

    pipeline = deps.create_pipeline_for_type(TaskType.CREATIVE, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info("[Creative] Task created: %s, idea=%s... (queued)",
                safe_log(task_id), safe_log(idea[:40]))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/manuscript")
async def create_manuscript_task(
    manuscript_text: str = Form(...),
    creative_name: str = Form(""),
    style: str = Form(""),
    # v6.4（PR #33 吸收）：逐段参考图——每张上传图对应一组段落 index（reference_images_map），
    # 用于该段落视频的 i2v 画面引导；一张图可服务多个段落。
    reference_images: List[UploadFile] = File([]),
    reference_images_map: str = Form("[]"),  # JSON: [[0,2],[1],...] 顺序与 reference_images 一致
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(10),
    # v2.0 音频配置
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    audio_add_tashkeel: bool = Form(False),  # 阿拉伯语旁白自动加变音符号（harakat）
    # v3.0 字幕独立配置
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(48),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
    # v6.0 手动模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
):
    """创建稿件长视频任务（类型 3）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    if not manuscript_text.strip():
        raise HTTPException(status_code=400, detail="稿件内容不能为空")
    # P7: 文本长度上限
    if len(manuscript_text) > 50000:
        raise HTTPException(status_code=422, detail="稿件文本最多 50000 字符")

    # v4.0: 稿件正文已知，做脚本级音色兼容性校验（最准确）
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh", text=manuscript_text)

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"manuscript_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # 处理逐段参考图上传（PRD 1.5）：每张图对应一组段落 index，用于 i2v 引导该段落画面。
    # reference_images_map 校验：必须为 JSON 数组，每个元素为「非负整数数组」；
    # 上界（段落数）在任务执行拆段后才确定，此处不校验，越界 index 由流水线 warning 忽略。
    ref_images_by_para: dict = {}
    if reference_images:
        try:
            idx_map = json.loads(reference_images_map) if reference_images_map else []
            if not isinstance(idx_map, list):
                raise ValueError("not a list")
            for item in idx_map:
                if not isinstance(item, list) or not all(isinstance(i, int) for i in item):
                    raise ValueError("element must be list[int]")
        except Exception:
            raise HTTPException(
                status_code=422,
                detail="reference_images_map 必须为 JSON 数组，元素为段落 index 的整数数组",
            )
        upload_dir = helpers.get_upload_dir()
        for i, up in enumerate(reference_images):
            if not up or not up.filename:
                continue
            saved_path = await _save_upload_file(up, upload_dir, f"{task_id}_ref{i}")
            para_indices = idx_map[i] if i < len(idx_map) else []
            for pidx in para_indices:
                if pidx < 0:
                    logger.warning(
                        "[Manuscript] reference image %d has negative paragraph "
                        "index %d, ignored", i, pidx,
                    )
                    continue
                ref_images_by_para.setdefault(str(pidx), []).append(saved_path)

    # 构建音频配置
    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
        add_tashkeel=audio_add_tashkeel,
    )
    # 构建独立字幕配置（v3.0）
    subtitle_config = _build_subtitle_config(
        subtitle_enabled, subtitle_style_mode, subtitle_style_hints,
        subtitle_font, subtitle_color, subtitle_fontsize, subtitle_position,
        subtitle_stroke_color, subtitle_stroke_width, subtitle_bg_color,
    )

    state = ManuscriptVideoTask(
        task_id=task_id,
        creative_name=name,
        manuscript_text=manuscript_text.strip(),
        style=style.strip(),
        reference_images=ref_images_by_para,
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=_build_manual_config(execution_mode, pause_points),
    )

    pipeline = deps.create_pipeline_for_type(TaskType.MANUSCRIPT, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Manuscript] Task created: {task_id}, text_len={len(manuscript_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/poetry")
async def create_poetry_task(
    poem_text: str = Form(...),
    creative_name: str = Form(""),
    user_scene_prompts_json: str = Form("[]"),
    style: str = Form("电影质感写实风格"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(30),
    # ── 场景配置（与创意视频完全一致）──
    duration_source: str = Form("manual"),
    scene_count: int = Form(3),
    uniform_duration: bool = Form(True),
    scene_durations_json: str = Form("[5,5,5]"),
    # 音频配置（默认开启朗诵配音）
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("-15%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    # 字幕配置（默认开启，固定诗歌样式，用户仅开关）
    subtitle_enabled: bool = Form(True),
    # v6.0 手动模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
):
    """创建诗词视频任务（类型 6）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh")

    if not poem_text.strip():
        raise HTTPException(status_code=400, detail="古诗原文不能为空")
    if len(poem_text) > 2000:
        raise HTTPException(status_code=422, detail="古诗原文最多 2000 字符")
    if video_duration < 5 or video_duration > 300:
        raise HTTPException(status_code=422, detail="video_duration 范围 5-300 秒")
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(status_code=422, detail="duration_source 必须为 manual 或 prompt")
    if duration_source == "manual":
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="scene_count 范围 1-30")
        scene_durations = _parse_scene_durations_json(scene_durations_json)
    else:
        scene_durations = []

    # 解析可选分镜 prompt 列表（JSON 数组）
    try:
        user_scene_prompts = json.loads(user_scene_prompts_json)
        if not isinstance(user_scene_prompts, list):
            raise ValueError("not a list")
        user_scene_prompts = [str(p) for p in user_scene_prompts]
    except Exception:
        raise HTTPException(status_code=422, detail="user_scene_prompts_json 必须为 JSON 数组")

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"poetry_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    # 字幕使用固定诗歌样式，用户仅控制开关
    subtitle_config = SubtitleConfig(
        enabled=subtitle_enabled,
        style=POETRY_SUBTITLE_STYLE,
    )

    state = PoetryVideoTask(
        task_id=task_id,
        creative_name=name,
        poem_text=poem_text.strip(),
        user_scene_prompts=user_scene_prompts,
        style=style.strip() or "电影质感写实风格",
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=_build_manual_config(execution_mode, pause_points),
    )

    pipeline = deps.create_pipeline_for_type(TaskType.POETRY, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info("[Poetry] Task created: %s, poem=%r (queued)",
                safe_log(task_id), safe_log(poem_text[:20]))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/anchor")
async def create_anchor_task(
    anchor_prompt: str = Form(""),
    anchor_reference_image: str = Form(""),
    script_text: str = Form(...),
    audio_source: str = Form("post_stitch"),
    video_width: int = Form(768),
    video_height: int = Form(1344),
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("+0%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    subtitle_enabled: bool = Form(True),
    subtitle_style_mode: str = Form("fixed"),
    subtitle_style_hints: str = Form(""),
    subtitle_font: str = Form("STHeitiMedium.ttc"),
    subtitle_color: str = Form("white"),
    subtitle_fontsize: int = Form(42),
    subtitle_position: str = Form("bottom"),
    subtitle_stroke_color: str = Form("black"),
    subtitle_stroke_width: int = Form(2),
    subtitle_bg_color: str = Form("black@0.5"),
    # v6.0 手动模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
):
    """创建数字人口播任务（类型 4 / Phase 3）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

    # v4.0: 音色与稿件文本兼容性校验
    # 数字人口播的稿件由用户直接输入，应以「稿件文本的实际文字体系」为准做脚本级
    # 校验，而非页面语言。否则中文环境下输入英文稿 + 选英文音色会被误判为不支持。
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh", text=script_text)

    if not script_text.strip():
        raise HTTPException(status_code=400, detail="口播稿件不能为空")
    if len(script_text) > 50000:
        raise HTTPException(status_code=422, detail="口播稿件最多 50000 字符")

    task_id = uuid.uuid4().hex[:12]
    name = f"anchor_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    audio_config = AudioConfig(
        enabled=audio_enabled,
        voice=audio_voice,
        rate=audio_rate,
    )
    subtitle_config = _build_subtitle_config(
        subtitle_enabled, subtitle_style_mode, subtitle_style_hints,
        subtitle_font, subtitle_color, subtitle_fontsize, subtitle_position,
        subtitle_stroke_color, subtitle_stroke_width, subtitle_bg_color,
    )

    state = AnchorVideoTask(
        task_id=task_id,
        creative_name=name,
        anchor_prompt=anchor_prompt,
        anchor_reference_image=anchor_reference_image,
        script_text=script_text.strip(),
        audio_source=audio_source,
        video_width=video_width,
        video_height=video_height,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=_build_manual_config(execution_mode, pause_points),
    )

    pipeline = deps.create_pipeline_for_type(TaskType.ANCHOR, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Anchor] Task created: {task_id}, script_len={len(script_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


# ═══════════════════════════════════════════════════
# 向后兼容：旧的 POST /api/tasks → 映射到 creative
# ═══════════════════════════════════════════════════

@router.post("/api/tasks")
async def create_task_legacy(
    idea: str = Form(...),
    creative_name: str = Form(""),
    user_requirement: str = Form("3个场景，每个场景10秒，电影质感"),
    style: str = Form("电影质感写实风格"),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    use_custom_end_frames: bool = Form(False),
    generate_end_frames_from_ref: bool = Form(True),
):
    """向后兼容旧端点，映射到 create_creative_task。"""
    return await create_creative_task(
        idea=idea,
        creative_name=creative_name,
        style=style,
        chaining_mode=chaining_mode,
        video_width=video_width,
        video_height=video_height,
        reference_image=reference_image,
        end_frame_images=end_frame_images,
        scene_reference_images=[],
        use_custom_end_frames=use_custom_end_frames,
        generate_end_frames_from_ref=generate_end_frames_from_ref,
        # v3.x 场景配置：直接调用时 Form() 默认值是对象而非字符串，
        # 必须显式传值（旧端点语义：3 个场景，每场景 10 秒）
        duration_source="manual",
        scene_count=3,
        uniform_duration=True,
        scene_durations_json="[10,10,10]",
        # 提供音频/字幕默认值（旧端点不传这些参数）
        audio_enabled=False,
        audio_voice="zh-CN-XiaoxiaoNeural",
        audio_rate="+0%",
        audio_lang="",
        audio_add_tashkeel=False,
        subtitle_enabled=True,
        subtitle_style_mode="fixed",
        subtitle_style_hints="",
        subtitle_font="STHeitiMedium.ttc",
        subtitle_color="white",
        subtitle_fontsize=48,
        subtitle_position="bottom",
        subtitle_stroke_color="black",
        subtitle_stroke_width=2,
        subtitle_bg_color="black@0.5",
        # v6.0 手动模式：旧端点语义为自动模式
        execution_mode="auto",
        pause_points="",
    )


# ═══════════════════════════════════════════════════
# 诗词分镜提示词生成（供前端展示与复制）
# ═══════════════════════════════════════════════════

@router.get("/api/poetry-scene-prompt")
async def poetry_scene_prompt(
    poem: str = "",
    scene_count: int = 0,
    scene_durations: str = "",
    total_duration: int = 30,
    style: str = "",
):
    """返回已填充的诗歌分镜提示词（中文），供前端展示与复制。

    参数与内部 LLM 使用的完全一致（scene_count / scene_durations / total_duration / style），
    因此用户拿去任意 LLM 生成、再把「原诗句 | 画面描述」行格式贴回，与系统内生成结果一致。
    """
    try:
        durations = json.loads(scene_durations) if scene_durations else []
    except (ValueError, TypeError):
        durations = []
    if not isinstance(durations, list):
        durations = []
    return build_poetry_scene_prompt(
        poem=poem,
        scene_count=scene_count,
        scene_durations=[int(d) for d in durations if str(d).isdigit()],
        total_duration=total_duration,
        style=style,
    )
