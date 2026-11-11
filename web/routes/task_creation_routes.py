"""任务创建路由：simple / creative / manuscript / poetry / anchor + 向后兼容旧端点。"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image

from core.async_io import write_bytes
from core.config import (
    SIMPLE_DEFAULT_PRESET,
    VIDEO_25_DURATIONS,
    api_key_missing_msg,
    get_api_key,
    get_max_ref_images,
    get_selected_models,
    get_video_model_capabilities,
    normalize_video_size,
)
from core.i18n_backend import get_current_lang, translate
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

# 场景数上限（与 create_creative_task / create_poetry_task / preview_creative_script
# 的 scene_count 校验同口径）。自定义尾帧的场景 index 是 0 基下标，合法上界为
# ``_MAX_SCENE_COUNT - 1``；它同时是尾帧槽位列表的**唯一长度来源**——用户可控的
# index 绝不进入任何分配大小（S6639：``[""] * max(ef_indices) + 1`` 可被
# ``[999999999]`` 之类输入放大成 GB 级分配打死进程）。
_MAX_SCENE_COUNT = 30

# v7.6 外部素材模式：各任务类型的默认暂停点（audio 检查点在 audio_source=video 时自动通过）
_EXTERNAL_PAUSE_POINTS = {
    "creative": ["scenes", "references", "videos", "subtitle"],
    "manuscript": ["scenes", "videos", "subtitle"],
    "poetry": ["scenes", "videos", "subtitle"],
    "anchor": ["scenes", "videos"],
}


def _parse_scene_durations_json(scene_durations_json: str) -> list:
    """解析场景时长 JSON 数组，非法时抛 422。"""
    try:
        scene_durations = json.loads(scene_durations_json)
        if not isinstance(scene_durations, list):
            raise ValueError("not a list")
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.scene_durations_not_list", None),
        )
    for i, d in enumerate(scene_durations):
        if not isinstance(d, (int, float)) or d < 2 or d > 30:
            raise HTTPException(
                status_code=422,
                detail=translate("validation.scene_duration_range", None, scene_index=i + 1),
            )
    return scene_durations


def _parse_end_frame_indices(end_frame_indices_json: str) -> list:
    """解析自定义尾帧的「场景 index」列表，非法时抛 422。

    除「JSON 数组 + 整数」形态校验外，还强制下界（非负）与上界
    （``< _MAX_SCENE_COUNT``）——上界同时是调用方分配尾帧槽位列表的大小，
    用户可控的 index 不得决定内存分配量（S6639）。
    """
    try:
        ef_indices = json.loads(end_frame_indices_json) if end_frame_indices_json else []
        if not isinstance(ef_indices, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) and 0 <= i < _MAX_SCENE_COUNT
            for i in ef_indices
        ):
            raise ValueError("not a list[int] in range")
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.end_frame_indices_not_list", None),
        )
    return ef_indices


def _build_manual_config(
    execution_mode: str,
    pause_points: str,
    provider: str = "jimeng",
    audio_source: str = "project",
    task_kind: str = "creative",
    subtitle_source: str = "narration",
) -> ManualConfig:
    """构建手动/外部素材模式配置（v6.0 / v7.6）。

    Args:
        execution_mode: "auto"（默认）/ "manual"（手动）/ "external"（外部素材）。
        pause_points: JSON 数组字符串（可选暂停点集合）；空/缺省时，
            manual = 全部检查点、external = 按 task_kind 的默认集合。
        provider: external 模式下所选外部工具 id（非法/空回退 "jimeng"）。
        audio_source: "project"（本项目 TTS）或 "video"（保留视频自带音轨）。
        task_kind: creative / manuscript / poetry / anchor，决定 external 默认暂停点。
        subtitle_source: external 模式字幕来源（"narration" 旁白 / "dialogue" 人物对白）；
            非 external 时忽略（强制 narration）。

    Raises:
        HTTPException: execution_mode / pause_points / audio_source /
            subtitle_source 非法。
    """
    if execution_mode not in ("auto", "manual", "external"):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.execution_mode_invalid", None),
        )
    if execution_mode == "auto":
        return ManualConfig()
    if audio_source not in ("project", "video"):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.audio_source_invalid", None),
        )

    points = _parse_pause_points(pause_points)

    if execution_mode == "external":
        if subtitle_source not in ("narration", "dialogue"):
            raise HTTPException(
                status_code=422,
                detail=translate("validation.subtitle_source_invalid", None),
            )
        from core.providers import get_provider

        return ManualConfig(
            enabled=True,
            pause_points=points or _EXTERNAL_PAUSE_POINTS.get(
                task_kind, _EXTERNAL_PAUSE_POINTS["creative"]),
            execution_mode="external",
            provider=get_provider(provider).id,   # 非法/空 → 回退 jimeng
            audio_source=audio_source,
            subtitle_source=subtitle_source,
        )

    # manual（空 = 全部检查点暂停，PRD §4.3）
    return ManualConfig(
        enabled=True,
        pause_points=points or list(ALL_CHECKPOINTS),
        execution_mode="manual",
    )


def _external_video_audio(manual_config: ManualConfig) -> bool:
    """外部素材模式 + 音频来源=视频 → 由视频自带音轨（禁用本项目 TTS）。"""
    return (
        manual_config.execution_mode == "external"
        and manual_config.audio_source == "video"
    )


def _parse_pause_points(pause_points: str) -> list:
    """解析并校验 pause_points JSON 数组（非法值抛 422）。"""
    try:
        points = json.loads(pause_points) if pause_points else []
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.pause_points_not_list", None),
        )
    if not isinstance(points, list):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.pause_points_not_list", None),
        )
    invalid = [p for p in points if p not in set(ALL_CHECKPOINTS)]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=translate(
                "validation.pause_point_invalid",
                None,
                invalid=invalid,
                options=ALL_CHECKPOINTS,
            ),
        )
    return points


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


def _upload_max_mb() -> int:
    """单文件上传大小上限（MB）；``0`` / 负数 = 不限制（兼容老部署）。"""
    try:
        return int(os.environ.get("AGNES_UPLOAD_MAX_MB", "10"))
    except (TypeError, ValueError):
        return 10


def _validate_image_bytes(data: bytes) -> bool:
    """校验字节是否为可解码图片（PIL verify），不可解码时返回 False。"""
    if not data:
        return False
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        return True
    except Exception:
        return False


async def _save_upload_file(
    upload: UploadFile,
    upload_dir: str,
    prefix: str,
    scene_index: Optional[int] = None,
) -> str:
    """保存上传文件（用 UUID 替代客户端文件名，避免路径穿越），返回落盘路径。

    扩展名取自白名单：客户端 filename 中夹带的任意后缀（含无扩展名）一律
    以可读错误拒绝——不再静默改写为 ``.png``（那会让 HEIC/AVIF/TIFF 变成
    「后缀撒谎」的伪 PNG）。随后经 ``safe_join`` 锚定到 upload_dir 内，杜绝
    路径穿越（S2083）。**上传时即校验字节是可解码图片**（issue #88），坏文件
    按 UI 语言报错并带上场景序号，避免拖到流水线 ``end_frame_gen`` 才抛 PIL
    原始栈打死整任务。

    Args:
        upload: 上传文件。
        upload_dir: 落盘目录。
        prefix: 文件名前缀（不含扩展名）。
        scene_index: 该文件对应的场景序号（1 起，可选），用于报错定位。

    Raises:
        HTTPException: 扩展名不在白名单（400）或字节非可解码图片（400）。
    """
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=translate(
                "error.upload_ext_invalid", None,
                ext=ext or "?", options=", ".join(sorted(_ALLOWED_UPLOAD_EXTS)),
            ),
        )
    data = await upload.read()
    # v8.1：单文件大小上限（默认 10MB，AGNES_UPLOAD_MAX_MB=0 关闭）。
    # 参考图会多张进内存并随请求发给上游，无上限时一张 60MB 的图就能拖垮进程。
    max_mb = _upload_max_mb()
    if max_mb > 0 and len(data) > max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=translate("error.upload_too_large", None, mb=max_mb),
        )
    if not _validate_image_bytes(data):
        key = "error.image_unreadable_scene" if scene_index is not None else "error.image_unreadable"
        raise HTTPException(
            status_code=400,
            detail=translate(key, None, scene_index=scene_index),
        )
    os.makedirs(upload_dir, exist_ok=True)
    upload_path = safe_join(upload_dir, f"{prefix}{ext}")
    await write_bytes(upload_path, data)
    return upload_path


#: v8.1：人物板 / 风格板各允许的上传张数（PRD §3.6「最多 2 张：脸 + 服装」）
_MAX_PLATE_IMAGES = 2


async def _save_ref_upload_list(
    uploads: Optional[List[UploadFile]],
    upload_dir: str,
    prefix: str,
    max_count: int,
) -> List[str]:
    """落盘一组成员图（人物板/风格板/逐段内容图），超限抛 422。

    Args:
        uploads: 上传文件列表（空/None 返回空列表）。
        upload_dir: 落盘目录。
        prefix: 文件名前缀（序号自动追加，避免覆盖）。
        max_count: 允许的张数上限（来自 ``get_max_ref_images`` 或板块常量）。

    Raises:
        HTTPException: 张数超限（422，复用 22 语言文案）。
    """
    # 直接调用路由函数（如旧端点转发）时，未显式传参的默认值是 FastAPI 的
    # ``File(...)`` 标记对象而非列表，这里统一按「没有上传」处理。
    if not isinstance(uploads, (list, tuple)):
        return []
    files = [f for f in uploads if f and getattr(f, "filename", "")]
    if len(files) > max_count:
        raise HTTPException(
            status_code=422,
            detail=translate(
                "validation.too_many_ref_images", None,
                max=max_count, current=len(files),
            ),
        )
    return [
        await _save_upload_file(f, upload_dir, f"{prefix}{idx}")
        for idx, f in enumerate(files)
    ]


#: 简单视频支持的生成模式（v8.0 对齐官方 2.5 协议）
_SIMPLE_VALID_MODES = {"t2v", "i2v", "ti2vid", "keyframes"}

#: 前端模式 → 任务模型枚举（校验通过后才会取值，缺省为文生视频）
_SIMPLE_MODE_MAP = {
    "i2v": VideoMode.I2V,
    "ti2vid": VideoMode.TI2VID,
    "keyframes": VideoMode.KEYFRAMES,
}


class _SimpleTaskExtras:
    """简单视频的兼容/扩展表单字段。

    放进 ``Depends()`` 只为保持路由签名精简（S107）：字段名与原路由参数
    完全一致，multipart 契约不变。``reference_image`` / ``end_frame_image``
    是 v8.0 之前的旧字段，仍需继续接受。
    """

    def __init__(
        self,
        reference_image: UploadFile = File(None),
        end_frame_image: UploadFile = File(None),
        reference_audio_urls: str = Form(""),
        video_size: Optional[str] = Form(None),
    ):
        self.reference_image = reference_image
        self.end_frame_image = end_frame_image
        self.reference_audio_urls = reference_audio_urls
        self.video_size = video_size


def _validate_simple_params(mode: str, duration: int, prompt: str) -> None:
    """校验简单视频的模式 / 时长 / prompt 长度，非法时抛 422。"""
    if mode not in _SIMPLE_VALID_MODES:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.mode_invalid", None, options=_SIMPLE_VALID_MODES, current=mode),
        )
    # v6.2：2.5 系列（当前唯一在线的视频模型）时长档位为 4–12 秒
    if duration not in VIDEO_25_DURATIONS:
        raise HTTPException(
            status_code=422,
            detail=translate(
                "validation.duration_invalid", None,
                options=sorted(VIDEO_25_DURATIONS), current=duration,
            ),
        )
    if len(prompt) > 5000:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.prompt_too_long", None),
        )


def _split_audio_urls(raw: str) -> List[str]:
    """拆分参考音频 URL（换行 / 逗号 / 分号 / 空白分隔）。"""
    return [u.strip() for u in re.split(r"[,，;；\s]+", raw or "") if u.strip()]


def _resolve_simple_media(
    reference_images: List[UploadFile],
    reference_audio_urls: str,
    video_model: str,
) -> tuple:
    """解析并校验简单视频素材（数量上限 / 音频协议），非法时抛 422。

    Returns:
        ``(ref_files, audio_urls)``。
    """
    caps = get_video_model_capabilities().get(video_model, {})
    # v8.1：图片/视频参考图上限统一走 core.config.get_max_ref_images（唯一出处）
    max_ref_images = get_max_ref_images(video_model)
    max_ref_audios = int(caps.get("max_ref_audios") or 3)
    ref_files = [f for f in (reference_images or []) if f and f.filename]
    audio_urls = _split_audio_urls(reference_audio_urls)

    if len(ref_files) > max_ref_images:
        raise HTTPException(
            status_code=422,
            detail=translate(
                "validation.too_many_ref_images", None,
                max=max_ref_images, current=len(ref_files),
            ),
        )
    if len(audio_urls) > max_ref_audios:
        raise HTTPException(
            status_code=422,
            detail=translate(
                "validation.too_many_ref_audios", None,
                max=max_ref_audios, current=len(audio_urls),
            ),
        )
    if audio_urls and any(not u.startswith(("http://", "https://")) for u in audio_urls):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.ref_audio_url_invalid", None),
        )
    return ref_files, audio_urls


async def _save_simple_uploads(
    state: SimpleVideoTask,
    task_id: str,
    upload_dir: str,
    ref_files: List[UploadFile],
    first_frame_image: UploadFile,
    last_frame_image: UploadFile,
    extras: _SimpleTaskExtras,
) -> None:
    """落盘参考图 / 首尾帧（UUID 命名，避免客户端文件名路径穿越）。"""
    saved_refs: List[str] = []
    for idx, f in enumerate(ref_files):
        saved_refs.append(await _save_upload_file(f, upload_dir, f"{task_id}_ref{idx}"))
    if extras.reference_image and extras.reference_image.filename:
        state.reference_image = await _save_upload_file(
            extras.reference_image, upload_dir, f"{task_id}_ref",
        )
        if not saved_refs:
            saved_refs = [state.reference_image]
    if saved_refs:
        state.reference_images = saved_refs
    # v8.0：keyframe 原生首/尾帧
    if first_frame_image and first_frame_image.filename:
        state.first_frame_image = await _save_upload_file(
            first_frame_image, upload_dir, f"{task_id}_first",
        )
    if last_frame_image and last_frame_image.filename:
        state.last_frame_image = await _save_upload_file(
            last_frame_image, upload_dir, f"{task_id}_last",
        )
    # 旧 keyframes 尾帧字段（历史前端仍可能只传这一个）
    if extras.end_frame_image and extras.end_frame_image.filename:
        state.end_frame_image = await _save_upload_file(
            extras.end_frame_image, upload_dir, f"{task_id}_end",
        )


@router.post(
    "/api/tasks/simple",
    responses={
        400: {"description": "缺少 API Key 或上传文件不可读"},
        422: {"description": "生成参数或素材组合不合法"},
    },
)
async def create_simple_task(
    prompt: str = Form(...),
    mode: str = Form(SIMPLE_DEFAULT_PRESET["mode"]),
    duration: int = Form(SIMPLE_DEFAULT_PRESET["duration"]),
    video_width: int = Form(SIMPLE_DEFAULT_PRESET["video_width"]),
    video_height: int = Form(SIMPLE_DEFAULT_PRESET["video_height"]),
    seed: Optional[int] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    system_prompt: str = Form(""),
    reference_images: List[UploadFile] = File(None),
    first_frame_image: UploadFile = File(None),
    last_frame_image: UploadFile = File(None),
    extras: _SimpleTaskExtras = Depends(),
):
    """创建简单视频任务（类型 1）。

    v8.0：只传 prompt 即走一键预设（免费 2.5-flash / 5s / 16:9 / 720P）；
    其余参数按官方 2.5 协议（mode/seconds/size/aspect_ratio + 模式专用素材）透传。
    """
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=api_key_missing_msg())

    _validate_simple_params(mode, duration, prompt)

    video_model = get_selected_models()["video"]
    ref_files, audio_urls = _resolve_simple_media(
        reference_images, extras.reference_audio_urls, video_model,
    )
    # 官方模式互斥：keyframe 不允许 images/audios。
    # 注：i2v/keyframes 缺素材不在后端硬拒——旧 API 调用方（含历史测试/脚本）依赖
    # 「无图也能建任务」；「选了图生视频却没传图」的拦截放在前端表单，既保证正常
    # 用户不会被静默降级，也不破坏既有契约。
    if mode == "keyframes" and (ref_files or audio_urls):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.mode_media_conflict", None),
        )

    # 清晰度归一到官方枚举（旧 960P → 1080P；flash 强制 720P）
    video_size = normalize_video_size(extras.video_size, video_model)

    task_id = uuid.uuid4().hex[:12]
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    state = SimpleVideoTask(
        task_id=task_id,
        creative_name=f"simple_{task_id}",
        prompt=prompt,
        mode=_SIMPLE_MODE_MAP.get(mode, VideoMode.T2V),
        duration=duration,
        video_width=video_width,
        video_height=video_height,
        video_size=video_size,
        seed=seed,
        negative_prompt=negative_prompt,
        system_prompt=system_prompt,
        reference_audio_urls=audio_urls,
        # v7.0（issue #64）：任务级 UI 语言快照，供异步流水线本地化消息
        ui_language=get_current_lang(),
    )

    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    # v8.0：reference 多图；旧单图字段同时回填，保证 pipeline 兼容两条入口
    upload_dir = helpers.get_upload_dir()
    await _save_simple_uploads(
        state, task_id, upload_dir, ref_files,
        first_frame_image, last_frame_image, extras,
    )

    pipeline = deps.create_pipeline_for_type(TaskType.SIMPLE, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm, lang=state.ui_language)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(
        "[Simple] Task created: %s, mode=%s, duration=%ss (queued)",
        task_id, safe_log(mode), duration,
    )
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}

@router.post("/api/tasks/creative")
async def create_creative_task(
    idea: str = Form(...),
    creative_name: str = Form(""),
    style: str = Form(""),
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
    # v8.1：逐场景多图映射（JSON [[0,3],[1],...]，与 scene_reference_images 顺序一致）
    scene_reference_images_map: str = Form("[]"),
    style_images: List[UploadFile] = File(None),
    end_frame_indices_json: str = Form("[]"),
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
    # v6.0 手动模式 / v7.6 外部素材模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
    provider: str = Form("jimeng"),
    audio_source: str = Form("project"),
    subtitle_source: str = Form("narration"),
):
    """创建创意长视频任务（类型 2）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=api_key_missing_msg())

    manual_config = _build_manual_config(
        execution_mode, pause_points, provider, audio_source, "creative",
        subtitle_source)
    # 外部素材 + 音频来源=视频 → 用视频自带音轨，禁用本项目 TTS
    if _external_video_audio(manual_config):
        audio_enabled = False

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh")

    # P7: 参数校验
    if len(idea) > 10000:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.idea_too_long", None),
        )
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.duration_source_invalid", None),
        )
    if duration_source == "manual":
        if scene_count < 1 or scene_count > _MAX_SCENE_COUNT:
            raise HTTPException(
                status_code=422,
                detail=translate("validation.scene_count_range", None,
                                 min=1, max=_MAX_SCENE_COUNT),
            )
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
        manual_config=manual_config,
        # v7.0（issue #64）：任务级 UI 语言快照
        ui_language=get_current_lang(),
    )

    logger.info(
        "[Pipeline] Scene config: source=%s, scenes=%s, durations=%s, uniform=%s, manual=%s",
        safe_log(duration_source), scene_count, safe_log(scene_durations),
        uniform_duration, safe_log(execution_mode),
    )

    upload_dir = helpers.get_upload_dir()
    # 处理参考图上传（L4: 用 UUID 替代客户端文件名，避免路径穿越）
    if reference_image and reference_image.filename:
        state.reference_image = await _save_upload_file(reference_image, upload_dir, f"{task_id}_ref")

    # P3: 处理自定义尾帧图片上传
    # 前端只上送非空槽位，并附带「文件 → 场景 index」映射（end_frame_indices_json）；
    # 此处按映射落盘并**保留空串占位**，维持「图片 ↔ 场景」索引对应（此前仅按上送顺序
    # 落盘，前面的空槽位会让后续文件整体前移、图场景错位，issue #88）。
    if use_custom_end_frames and end_frame_images:
        ef_indices = _parse_end_frame_indices(end_frame_indices_json)
        # 先按「场景 index → 路径」收集（分配量只与上传文件数有关，与 index 数值无关），
        # 再物化成带空串占位的定长列表。**列表长度只由常量 _MAX_SCENE_COUNT 决定**：
        # 用户可控的 scene index 绝不参与任何分配大小（S6639 修复前
        # ``[""] * (max(ef_indices) + 1)`` 可被 ``[999999999]`` 放大成 GB 级分配）。
        saved: dict = {}
        for pos, ef_file in enumerate(end_frame_images):
            scene_idx = ef_indices[pos] if pos < len(ef_indices) else pos
            if scene_idx < 0 or scene_idx >= _MAX_SCENE_COUNT or not (ef_file and ef_file.filename):
                continue
            saved[scene_idx] = await _save_upload_file(
                ef_file, upload_dir, f"{task_id}_end_{scene_idx}", scene_index=scene_idx + 1,
            )
        if saved:
            saved_paths = [saved.get(i, "") for i in range(_MAX_SCENE_COUNT)]
            # 裁掉尾部空槽位，与修复前的长度语义保持一致（下游一律按 index 取用）
            while len(saved_paths) > 1 and not saved_paths[-1]:
                saved_paths.pop()
            state.end_frame_images = saved_paths
            logger.info(
                f"[Pipeline] Saved {len(saved)} custom end frame images for task {task_id}"
            )

    # v8.1：用户上传分镜场景图（逐场景**多张**）。上传文件按
    # ``scene_reference_images_map`` 映射到场景 index；旧客户端不传 map 时
    # 退化为「第 i 个文件属于场景 i」（与 v5.0 行为一致）。
    if scene_reference_images:
        try:
            scene_idx_map = json.loads(scene_reference_images_map) if scene_reference_images_map else []
            if not isinstance(scene_idx_map, list):
                raise ValueError("not a list")
            for item in scene_idx_map:
                if not isinstance(item, list) or not all(isinstance(i, int) for i in item):
                    raise ValueError("element must be list[int]")
        except Exception:
            raise HTTPException(
                status_code=422,
                detail=translate("validation.reference_images_map_not_list", None),
            )
        saved_scene_map: dict = {}
        for pos, sref_file in enumerate(scene_reference_images):
            if not (sref_file and sref_file.filename):
                continue
            path = await _save_upload_file(sref_file, upload_dir, f"{task_id}_scene_{pos}")
            targets = scene_idx_map[pos] if pos < len(scene_idx_map) else [pos]
            for sidx in targets:
                if 0 <= sidx < _MAX_SCENE_COUNT:
                    saved_scene_map.setdefault(str(sidx), []).append(path)
        if saved_scene_map:
            state.scene_reference_images_map = saved_scene_map
            logger.info(
                "[Pipeline] Saved %d user scene reference images for %d scene(s), task %s",
                sum(len(v) for v in saved_scene_map.values()), len(saved_scene_map), task_id,
            )

    # v8.1：风格板（用户上传优先，空则由 style 文本生成）
    state.style_images = await _save_ref_upload_list(
        style_images, upload_dir, f"{task_id}_splate", _MAX_PLATE_IMAGES,
    )

    pipeline = deps.create_pipeline_for_type(TaskType.CREATIVE, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm, lang=state.ui_language)
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
    # v8.1：人物板 / 风格板（各 ≤2）+ 分镜衔接 / 逐段补图开关
    character_images: List[UploadFile] = File([]),
    style_images: List[UploadFile] = File([]),
    link_shots: bool = Form(False),
    pause_for_scene_refs: bool = Form(False),
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
    # v6.0 手动模式 / v7.6 外部素材模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
    provider: str = Form("jimeng"),
    audio_source: str = Form("project"),
    subtitle_source: str = Form("narration"),
):
    """创建稿件长视频任务（类型 3）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=api_key_missing_msg())

    manual_config = _build_manual_config(
        execution_mode, pause_points, provider, audio_source, "manuscript",
        subtitle_source)
    # v8.1：勾选「生成前暂停补图」时，即使用户处于自动模式也强制在
    # references 检查点暂停一次（否则勾选形同虚设）；只加这一个暂停点，
    # 用户恢复后不会在全流程反复被打断。
    if pause_for_scene_refs and "references" not in manual_config.pause_points:
        manual_config = ManualConfig(
            enabled=True,
            pause_points=[*manual_config.pause_points, "references"],
            provider=manual_config.provider,
            audio_source=manual_config.audio_source,
            execution_mode="manual",
            subtitle_source=manual_config.subtitle_source,
        )
    if _external_video_audio(manual_config):
        audio_enabled = False

    if not manuscript_text.strip():
        raise HTTPException(
            status_code=400,
            detail=translate("validation.manuscript_empty", None),
        )
    # P7: 文本长度上限
    if len(manuscript_text) > 50000:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.manuscript_too_long", None),
        )

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
                detail=translate("validation.reference_images_map_not_list", None),
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

    # v8.1：人物板 / 风格板（用户上传优先，未上传由流水线按需生成）
    character_paths = await _save_ref_upload_list(
        character_images, helpers.get_upload_dir(), f"{task_id}_cref", _MAX_PLATE_IMAGES,
    )
    style_paths = await _save_ref_upload_list(
        style_images, helpers.get_upload_dir(), f"{task_id}_splate", _MAX_PLATE_IMAGES,
    )

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
        character_images=character_paths,
        style_images=style_paths,
        link_shots=link_shots,
        pause_for_scene_refs=pause_for_scene_refs,
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=manual_config,
        # v7.0（issue #64）：任务级 UI 语言快照
        ui_language=get_current_lang(),
    )

    pipeline = deps.create_pipeline_for_type(TaskType.MANUSCRIPT, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm, lang=state.ui_language)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info(f"[Manuscript] Task created: {task_id}, text_len={len(manuscript_text)} (queued)")
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/poetry")
async def create_poetry_task(
    poem_text: str = Form(...),
    creative_name: str = Form(""),
    user_scene_prompts_json: str = Form("[]"),
    style: str = Form(""),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    video_duration: int = Form(30),
    # ── 场景配置（与创意视频完全一致）──
    duration_source: str = Form("manual"),
    scene_count: int = Form(3),
    uniform_duration: bool = Form(True),
    scene_durations_json: str = Form("[5,5,5]"),
    # v8.1：人物板 / 风格板（各 ≤2）+ 逐句内容图 + 句间衔接开关
    character_images: List[UploadFile] = File([]),
    style_images: List[UploadFile] = File([]),
    scene_reference_images: List[UploadFile] = File([]),
    scene_reference_images_map: str = Form("[]"),
    link_shots: bool = Form(False),
    # 音频配置（默认开启朗诵配音）
    audio_enabled: bool = Form(True),
    audio_voice: str = Form("zh-CN-XiaoxiaoNeural"),
    audio_rate: str = Form("-15%"),
    audio_lang: str = Form(""),  # 页面语言，用于音色兼容性校验
    # 字幕配置（默认开启，固定诗歌样式，用户仅开关）
    subtitle_enabled: bool = Form(True),
    # v6.0 手动模式 / v7.6 外部素材模式
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
    provider: str = Form("jimeng"),
    audio_source: str = Form("project"),
    subtitle_source: str = Form("narration"),
):
    """创建诗词视频任务（类型 6）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=api_key_missing_msg())

    manual_config = _build_manual_config(
        execution_mode, pause_points, provider, audio_source, "poetry",
        subtitle_source)
    if _external_video_audio(manual_config):
        audio_enabled = False

    # v4.0: 音色与目标语言兼容性校验
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh")

    if not poem_text.strip():
        raise HTTPException(
            status_code=400,
            detail=translate("validation.poem_empty", None),
        )
    if len(poem_text) > 2000:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.poem_too_long", None),
        )
    if video_duration < 5 or video_duration > 300:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.video_duration_range", None, min=5, max=300),
        )
    if duration_source not in ("manual", "prompt"):
        raise HTTPException(
            status_code=422,
            detail=translate("validation.duration_source_invalid", None),
        )
    if duration_source == "manual":
        if scene_count < 1 or scene_count > _MAX_SCENE_COUNT:
            raise HTTPException(
                status_code=422,
                detail=translate("validation.scene_count_range", None,
                                 min=1, max=_MAX_SCENE_COUNT),
            )
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
        raise HTTPException(
            status_code=422,
            detail=translate("validation.user_scene_prompts_not_list", None),
        )

    task_id = uuid.uuid4().hex[:12]
    name = creative_name.strip() if creative_name else f"poetry_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # v8.1：人物板 / 风格板 + 逐句内容图（按句 index 映射，一张图可服务多句）
    upload_dir = helpers.get_upload_dir()
    character_paths = await _save_ref_upload_list(
        character_images, upload_dir, f"{task_id}_cref", _MAX_PLATE_IMAGES,
    )
    style_paths = await _save_ref_upload_list(
        style_images, upload_dir, f"{task_id}_splate", _MAX_PLATE_IMAGES,
    )
    scene_ref_map: dict = {}
    if scene_reference_images:
        try:
            idx_map = json.loads(scene_reference_images_map) if scene_reference_images_map else []
            if not isinstance(idx_map, list):
                raise ValueError("not a list")
            for item in idx_map:
                if not isinstance(item, list) or not all(isinstance(i, int) for i in item):
                    raise ValueError("element must be list[int]")
        except Exception:
            raise HTTPException(
                status_code=422,
                detail=translate("validation.reference_images_map_not_list", None),
            )
        for i, up in enumerate(scene_reference_images):
            if not up or not up.filename:
                continue
            saved_path = await _save_upload_file(up, upload_dir, f"{task_id}_sref{i}")
            for sidx in (idx_map[i] if i < len(idx_map) else []):
                if sidx < 0:
                    continue
                scene_ref_map.setdefault(str(sidx), []).append(saved_path)

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
        style=style.strip(),
        character_images=character_paths,
        style_images=style_paths,
        scene_reference_images=scene_ref_map,
        link_shots=link_shots,
        video_width=video_width,
        video_height=video_height,
        video_duration=video_duration,
        duration_source=duration_source,
        scene_count=scene_count,
        uniform_duration=uniform_duration,
        scene_durations=scene_durations,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=manual_config,
        # v7.0（issue #64）：任务级 UI 语言快照
        ui_language=get_current_lang(),
    )

    pipeline = deps.create_pipeline_for_type(TaskType.POETRY, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm, lang=state.ui_language)
    app_state.launch_background_task(deps.run_pipeline_with_concurrency(pipeline, state, tm))
    logger.info("[Poetry] Task created: %s, poem=%r (queued)",
                safe_log(task_id), safe_log(poem_text[:20]))
    return {"ok": True, "task_id": task_id, "dir_name": dir_name}


@router.post("/api/tasks/anchor")
async def create_anchor_task(
    anchor_prompt: str = Form(""),
    # v8.1：多参考图（第 1 张为数字人形象，其余为服饰/场景辅助）。
    # 旧 ``anchor_reference_image``（str）保留为「首图」兼容读路径。
    anchor_reference_image: str = Form(""),
    anchor_reference_images: List[UploadFile] = File([]),
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
    # v6.0 手动模式 / v7.6 外部素材模式
    # ``audio_source`` 兼容两套词汇：anchor 自身的音频模式（post_stitch/model）
    # 与外部素材模式的音频来源（project/video）——后者映射为前者
    # （video→model=用视频自带音轨；project→post_stitch=本项目配音）。
    execution_mode: str = Form("auto"),
    pause_points: str = Form(""),
    provider: str = Form("jimeng"),
    subtitle_source: str = Form("narration"),
):
    """创建数字人口播任务（类型 4 / Phase 3）。"""
    api_key = get_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail=api_key_missing_msg())

    if audio_source == "video":
        audio_source, asset_audio_source = "model", "video"
    elif audio_source == "project":
        audio_source, asset_audio_source = "post_stitch", "project"
    else:
        asset_audio_source = "project"

    manual_config = _build_manual_config(
        execution_mode, pause_points, provider, asset_audio_source, "anchor",
        subtitle_source)
    if _external_video_audio(manual_config):
        audio_enabled = False

    # v4.0: 音色与稿件文本兼容性校验
    # 数字人口播的稿件由用户直接输入，应以「稿件文本的实际文字体系」为准做脚本级
    # 校验，而非页面语言。否则中文环境下输入英文稿 + 选英文音色会被误判为不支持。
    if audio_enabled:
        helpers._validate_voice_compat(audio_voice, audio_lang or "zh", text=script_text)

    if not script_text.strip():
        raise HTTPException(
            status_code=400,
            detail=translate("validation.anchor_script_empty", None),
        )
    if len(script_text) > 50000:
        raise HTTPException(
            status_code=422,
            detail=translate("validation.anchor_script_too_long", None),
        )

    task_id = uuid.uuid4().hex[:12]
    name = f"anchor_{task_id}"
    dir_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id}"

    # v8.1：数字人参考图落盘（此前该字段声明为 str 且全仓无落盘代码，
    # 用户上传的图 100% 丢失、锚点图静默退化为 t2i —— 属契约不一致修复）
    anchor_paths = await _save_ref_upload_list(
        anchor_reference_images,
        helpers.get_upload_dir(),
        f"{task_id}_aref",
        get_max_ref_images("", media="image"),
    )
    legacy_anchor_ref = anchor_reference_image.strip()

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
        anchor_reference_image=legacy_anchor_ref,
        anchor_reference_images=anchor_paths,
        script_text=script_text.strip(),
        audio_source=audio_source,
        video_width=video_width,
        video_height=video_height,
        audio_config=audio_config,
        subtitle_config=subtitle_config,
        manual_config=manual_config,
        # v7.0（issue #64）：任务级 UI 语言快照
        ui_language=get_current_lang(),
    )

    pipeline = deps.create_pipeline_for_type(TaskType.ANCHOR, api_key, task_id, dir_name)
    app_state.active_pipelines[task_id] = pipeline

    tm = TaskManager(task_id, dir_name=dir_name)
    tm.create(state)
    deps.mark_task_queued(tm, lang=state.ui_language)
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
    style: str = Form(""),
    chaining_mode: str = Form("keyframes"),
    video_width: int = Form(768),
    video_height: int = Form(1152),
    reference_image: UploadFile = File(None),
    end_frame_images: List[UploadFile] = File(None),
    end_frame_indices_json: str = Form("[]"),
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
        end_frame_indices_json=end_frame_indices_json,
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
