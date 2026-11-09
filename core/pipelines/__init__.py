"""core.pipelines — 业务流水线层

BasePipeline 抽象基类 + 四种流水线导出。
"""

import asyncio
import concurrent.futures
import functools
import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime
from types import SimpleNamespace
from typing import Callable, List, Optional

# 2.4：进度写盘节流阈值（秒）——_emit 进度类字段高频更新时合并落盘
_PROGRESS_SAVE_THROTTLE_SECONDS = 0.5

# 2.3：编码专用线程池——ffmpeg/moviepy 重型编码（分钟级）与轻量请求隔离，
# 避免占满默认线程池导致 API 请求/限速等待排队
_ENCODING_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="encoding"
)

from core.api.fast_retry import FAST_RETRY_AVAILABLE_AFTER
from core.api.key_manager import get_key_ring
from core.async_io import read_text, write_text
from core.compositor.ffmpeg_tool import probe_duration, resolve_cmd_binary
from core.compositor.watermark import add_watermark, detect_language
from core.config import get_watermark_config
from core.i18n_backend import translate
from core.task_manager import TaskManager
from models.task import AudioConfig, BaseTaskState, StepStatus, SubtitleConfig

# ── 优化路线图 1.2：词级 cues 持久化（续传免重采 TTS） ───────────────
# 生成音频时把 edge_tts SubMaker.cues（词级时间戳）序列化落盘到
# ``{音频路径}.cues.json``；续传时音频文件已存在、TTS 步骤被跳过时
# 直接读取缓存，避免重新消费 TTS 流采集 cues（10 分钟长稿件可省等量网络时间）。


def _cues_cache_path(audio_path: str) -> str:
    """cues 缓存文件路径（与音频文件同目录、同名加后缀）。"""
    return audio_path + ".cues.json"


def _serialize_sub_maker(sub_maker) -> list:
    """把 SubMaker.cues 序列化为 JSON 友好的列表（start/end 存秒）。"""
    if sub_maker is None or not getattr(sub_maker, "cues", None):
        return []
    out = []
    for cue in sub_maker.cues:
        try:
            start = cue.start
            end = cue.end
            out.append({
                "start": start.total_seconds() if hasattr(start, "total_seconds") else float(start),
                "end": end.total_seconds() if hasattr(end, "total_seconds") else float(end),
                "content": (cue.content or "").strip(),
            })
        except (AttributeError, TypeError):
            continue
    return out


def _deserialize_sub_maker(raw: list) -> Optional[object]:
    """还原 cues 缓存为消费方兼容的对象（含 .cues，每项含 start/end/content）。"""
    items = [SimpleNamespace(**c) for c in raw if c.get("content")]
    if not items:
        return None
    return SimpleNamespace(cues=items)

logger = logging.getLogger(__name__)


class PipelineShutdown(Exception):
    """流水线中断异常。"""
    pass


class CheckpointPause(Exception):
    """手动模式检查点暂停（v6.0）。

    非失败、非中断：流水线在某个检查点正常暂停，等待用户确认产物后
    通过 resume 恢复执行。携带暂停的检查点名，供 run() 捕获后返回。
    """

    def __init__(self, checkpoint: str, message: str = ""):
        self.checkpoint = checkpoint
        self.message = message or f"等待用户在检查点 '{checkpoint}' 确认产物"
        super().__init__(self.message)


# 检查点定义（v6.0，PRD §4.3）：步骤名 → 检查点名
CHECKPOINT_SCENES = "scenes"
CHECKPOINT_REFERENCES = "references"
CHECKPOINT_VIDEOS = "videos"
CHECKPOINT_AUDIO = "audio"
CHECKPOINT_SUBTITLE = "subtitle"
CHECKPOINT_FINAL = "final"

# 细粒度检查点（v6.1：所有有产物的环节均可暂停）
CHECKPOINT_IMAGE_ANALYSIS = "image_analysis"
CHECKPOINT_STORY = "story"
CHECKPOINT_SCRIPT = "script"
CHECKPOINT_CHARACTER_REF = "character_ref"
CHECKPOINT_END_FRAME_PROMPTS = "end_frame_prompts"
CHECKPOINT_END_FRAME_GEN = "end_frame_gen"

# 手动模式下全部可选暂停点（creative 用细粒度集合，其余任务类型用粗粒度）
ALL_CHECKPOINTS = [
    CHECKPOINT_IMAGE_ANALYSIS,
    CHECKPOINT_STORY,
    CHECKPOINT_SCRIPT,
    CHECKPOINT_CHARACTER_REF,
    CHECKPOINT_END_FRAME_PROMPTS,
    CHECKPOINT_END_FRAME_GEN,
    CHECKPOINT_SCENES,
    CHECKPOINT_REFERENCES,
    CHECKPOINT_VIDEOS,
    CHECKPOINT_AUDIO,
    CHECKPOINT_SUBTITLE,
    CHECKPOINT_FINAL,
]

# 步骤字段名 → 检查点名（_execute_step 完成后调用 _maybe_pause 时映射）
_STEP_TO_CHECKPOINT = {
    "step_build_scenes": CHECKPOINT_SCENES,
    "step_image_analysis": CHECKPOINT_IMAGE_ANALYSIS,
    "step_story": CHECKPOINT_STORY,
    "step_character_ref": CHECKPOINT_CHARACTER_REF,
    "step_script": CHECKPOINT_SCRIPT,
    "step_end_frame_prompts": CHECKPOINT_END_FRAME_PROMPTS,
    "step_end_frame_generation": CHECKPOINT_END_FRAME_GEN,
    "step_reference_images": CHECKPOINT_REFERENCES,
    "step_video_generation": CHECKPOINT_VIDEOS,
    "step_audio": CHECKPOINT_AUDIO,
    "step_subtitle": CHECKPOINT_SUBTITLE,
    "step_concatenation": CHECKPOINT_FINAL,
}

# 步骤 → 暂停点应展示的进度（步骤完成时的真实进度，而非 100%）。
# 与 multi_scene.StepProgressLimits 对齐；creative 细粒度步骤映射到所属大阶段。
_PAUSE_PROGRESS_BY_STEP = {
    "step_build_scenes": 0.08,
    "step_resolve_scene_config": 0.05,
    "step_image_analysis": 0.06,
    "step_story": 0.07,
    "step_script": 0.08,
    "step_reference_images": 0.12,
    "step_character_ref": 0.12,
    "step_end_frame_prompts": 0.12,
    "step_end_frame_generation": 0.15,
    "step_video_generation": 0.80,
    "step_audio": 0.86,
    "step_subtitle": 0.90,
    "step_concatenation": 0.98,
}


def compute_current_checkpoint(state) -> str:
    """推断任务当前所处检查点（最近一个已完成的步骤对应的检查点，v6.0）。

    自动变手动时用于确定展示边界（PRD §4.1）：中断可能发生在步骤中间
    （如生成到 scene_3/5），取最后一个步骤字段为 COMPLETED 的检查点作为
    current_checkpoint；无任何已完成步骤时返回空串。

    Args:
        state: 任务状态对象（含 step_* 字段）。

    Returns:
        检查点名（scenes/references/videos/audio/subtitle/final）或空串。
    """
    if not state:
        return ""
    for cp in reversed(ALL_CHECKPOINTS):
        step_field = None
        for name, c in _STEP_TO_CHECKPOINT.items():
            if c == cp:
                step_field = name
                break
        if step_field and getattr(state, step_field, None) == StepStatus.COMPLETED:
            return cp
    return ""


def _fast_retry_elapsed(started_at: str) -> Optional[float]:
    """快速重试已开启秒数；``started_at`` 缺失/非法时返回 None（视为已到期）。"""
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now() - started).total_seconds())


class _PipelineFastRetryHook:
    """v7.7 快速重试钩子：把「可否开启 / 是否生效 / 是否到期」落到任务状态。

    ``AgnesVideoAPI`` 每收到一次忙信号（503 / 429 / 队列满）就同步调用
    ``decide()``，由本钩子决定这一跳走常规忙轨还是快速节奏：

    - 未开启：累计连续忙信号，达到 ``FAST_RETRY_AVAILABLE_AFTER``（2 次）后
      置 ``available=True`` 并落盘 → 前端进度页出现开关；返回 None（常规节奏）。
    - 已开启且未到期：返回 ``interval_seconds``（60/x），由 API 层按该间隔
      连打，且**不占用**常规忙轨次数与视频提交令牌桶。
    - 已开启但到期：置 ``enabled=False, finished_reason="expired"`` 后返回
      None，API 层原样回到常规忙轨继续。

    状态读写都在流水线协程内（单写者）；用户点开关的 HTTP 请求侧走
    ``pipeline.task_manager`` 同一实例，因此不会出现两份缓存互相覆盖落盘。
    """

    def __init__(self, pipeline):
        self._pipeline = pipeline
        # attempts 落盘节流：快速模式 0.5–2 次/秒，逐跳写盘没有意义。
        # 用 0.8s（而不是 1.0s）配合前端 1s 轮询：轮询与落盘周期相同时
        # 会因相位差连续读到同一份旧值，看起来「完全不刷新」。
        self._last_attempts_save = 0.0

    def decide(self, busy_attempt: int, payload: dict) -> Optional[float]:
        """返回 None = 常规忙轨；返回秒数 = 本跳快速模式间隔。"""
        p = self._pipeline
        cfg = getattr(getattr(p, "_state", None), "fast_retry", None)
        if cfg is None:
            return None

        if not cfg.enabled:
            cfg.consecutive_busy += 1
            if cfg.consecutive_busy >= FAST_RETRY_AVAILABLE_AFTER and not cfg.available:
                cfg.available = True
                p._save_fast_retry()
                p._emit_fast_retry(
                    "progress.video.fast_retry.available",
                    {
                        "n": cfg.consecutive_busy,
                        "status": payload.get("status") or "",
                        "code": payload.get("code") or "",
                    },
                )
                logger.info(
                    "[FastRetry] Task %s: available after %d consecutive busy signals "
                    "(HTTP %s · %s), waiting for user to enable",
                    p.task_id, cfg.consecutive_busy,
                    payload.get("status"), payload.get("code") or "-",
                )
            return None

        # 已打次数同步（用户要在面板看到「已发 N 次」实时跳动）：
        # 每跳都更新内存值，最多每 1 秒落盘一次（前端快速模式期间 1s 轮询），
        # 到期/成功/关闭时各再落一次确保终值准确。
        probe = int(payload.get("probe") or 0)
        if probe and probe != cfg.attempts:
            cfg.attempts = probe
            now = time.monotonic()
            if now - self._last_attempts_save >= 0.8:
                self._last_attempts_save = now
                p._save_fast_retry()

        elapsed = _fast_retry_elapsed(cfg.started_at)
        limit = max(1, int(cfg.minutes or 1)) * 60
        if elapsed is None or elapsed >= limit:
            cfg.enabled = False
            cfg.finished_reason = "expired"
            p._save_fast_retry()
            p._emit_fast_retry(
                "progress.video.fast_retry.expired", {"y": int(cfg.minutes or 1)}
            )
            logger.info(
                "[FastRetry] Task %s: expired after %s (limit %ds), "
                "back to normal busy track",
                p.task_id, f"{elapsed:.0f}s" if elapsed is not None else "unknown", limit,
            )
            return None
        return cfg.interval_seconds

    def on_success(self, probe: int = 0) -> None:
        """提交成功：关闭快速模式（若开着）并清理可开启标记。

        Args:
            probe: 快速模式期间已发出的请求次数（含本次成功那跳）。
        """
        p = self._pipeline
        cfg = getattr(getattr(p, "_state", None), "fast_retry", None)
        if cfg is None:
            return
        was_enabled = cfg.enabled
        changed = bool(was_enabled or cfg.available or cfg.consecutive_busy or probe)
        cfg.consecutive_busy = 0
        cfg.available = False
        if probe:
            cfg.attempts = int(probe)
        if was_enabled:
            cfg.enabled = False
            cfg.finished_reason = "success"
        if not changed:
            return
        p._save_fast_retry()
        if was_enabled:
            p._emit_fast_retry("progress.video.fast_retry.success", {})
            logger.info(
                "[FastRetry] Task %s: submitted successfully in fast mode", p.task_id
            )


class BasePipeline(ABC):
    """所有流水线的抽象基类。

    提供共享的进度回调、断点续传、shutdown 控制等基础设施。
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: str = None,
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        self.api_key = api_key
        self.task_id = task_id
        self.dir_name = dir_name or task_id
        self.task_manager = TaskManager(task_id, dir_name=self.dir_name)
        self.progress_callback = progress_callback
        self.shutdown_event = shutdown_event
        self._stop_event = asyncio.Event()
        self._state: Optional[BaseTaskState] = None
        # Batch 3（S4）：screenwriter 统一初始化，子类（creative/manuscript/anchor/poetry）
        # 在自身 __init__ 中赋真实实例；仅 LLM 样式生成使用，None 表示不可用。
        self.screenwriter = None

    async def _emit(
        self,
        step: str,
        status: str,
        message: str,
        progress: float = 0.0,
        data: dict = None,
        *,
        preserve_step: bool = False,
        message_key: str = None,
        message_params: dict = None,
    ):
        """更新进度并持久化到 state（轮询模式）。

        将 step/status/message/progress 写入 state 的 current_* 字段，
        前端通过 GET /api/tasks/{id} 轮询读取。

        Args:
            step: 步骤 key，写入 ``current_step`` 供前端与诊断报告定位环节。
            status: 步骤状态（running / completed / failed / awaiting_user）。
            message: 面向用户的进度文案（后端按 ui_language 译好的兜底句）。
            progress: 进度比例 0.0 ~ 1.0。
            data: 附带数据（仅回调透传，不落盘）。
            preserve_step: True 时**不覆盖** ``current_step``，用于 ``error``
                这类终态事件——它们表达的是「出了问题」而不是「在哪个环节」，
                覆盖会把真实失败环节冲掉，使诊断报告归因失真（issue #56/#57
                真实失败在视频下载，报告却显示 scene_config）。
            message_key: 可选。结构化消息的 i18n key（如
                ``"progress.video.queue_full"``），与 ``message_params`` 一并
                落盘，供前端用其 22 语言文案渲染；省略时清空这两个字段，
                避免上一次的结构化消息残留（旧前端仍读 ``current_message``）。
            message_params: ``message_key`` 的插值参数（如 ``{"n": 3}``）。

        落盘策略（2.4 节流 + v6.4.8 终态强制）：
        - ``status == "running"`` 的高频进度更新按 0.5s 阈值合并落盘；
        - 其余状态（completed / failed / awaiting_user 等终态）**强制落盘**，
          否则紧跟在上一次进度写入之后的终态会被节流整条丢弃，
          导致盘上的 current_step/current_message 停留在旧值。
        """
        if self._state:
            if not preserve_step:
                self._state.current_step = step
            self._state.current_status = status
            self._state.current_progress = progress
            self._state.current_message = message
            self._state.current_message_key = message_key or ""
            self._state.current_message_params = dict(message_params or {})
            # 2.4：进度写盘节流——进度类字段高频更新时合并落盘（0.5s 阈值）。
            # 关键状态（video_id / scenes / paragraphs 等）不经本路径，不受影响。
            force_save = status != "running"
            try:
                now = time.monotonic()
                last = getattr(self, "_last_progress_save", 0.0)
                if force_save or now - last >= _PROGRESS_SAVE_THROTTLE_SECONDS:
                    self._last_progress_save = now
                    fields = {
                        "current_status": status,
                        "current_progress": progress,
                        "current_message": message,
                        "current_message_key": message_key or "",
                        "current_message_params": dict(message_params or {}),
                    }
                    if not preserve_step:
                        fields["current_step"] = step
                    self.task_manager.update_state(**fields)
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to persist progress: {e}")

        # 保留 callback 兼容性（移除 WS 后通常为 None）
        if self.progress_callback:
            await self.progress_callback(step, status, message, progress, data or {})

    def _is_shutdown(self) -> bool:
        """检查是否收到停止信号。"""
        if self._stop_event.is_set():
            return True
        return self.shutdown_event is not None and self.shutdown_event.is_set()

    def stop(self):
        """请求流水线在下一个检查点停止。"""
        self._stop_event.set()

    def _get_pausable_steps(self) -> set[str]:
        """当前任务实际可暂停的步骤（v6.0 P3）。

        子类按实际产物覆写：空实现步骤（如 manuscript/poetry 的 references、
        anchor 的 model 模式 audio/subtitle）不在集合中，手动模式不会在
        无实际产物的步骤上暂停。默认返回全部标准步骤。

        Returns:
            步骤字段名集合（如 {"step_build_scenes", "step_video_generation", ...}）。
        """
        return set(_STEP_TO_CHECKPOINT.keys())

    async def _maybe_pause(self, step_name: str, progress: Optional[float] = None) -> bool:
        """手动模式检查点暂停判定（v6.0）。

        在步骤完成后调用。命中手动暂停点时落盘暂停态（PENDING + current_checkpoint），
        抛 ``CheckpointPause`` 使流水线正常返回（非失败）；未命中返回 False 继续执行。

        命中条件（PRD §4.1）：
            manual_config.enabled 且 pause_points 非空
            且 step 对应检查点在 pause_points 中
            且尚未在 approved_checkpoints 中
            且该步骤在本流水线实际可暂停（P3：空实现步骤自动跳过）

        Args:
            step_name: 步骤字段名（如 ``step_build_scenes``），经 _STEP_TO_CHECKPOINT 映射。
            progress: 暂停点应展示的进度。缺省按 _PAUSE_PROGRESS_BY_STEP 映射取
                该步骤完成时的真实进度（而非 100%）；未映射的步骤兜底 1.0。

        Returns:
            False（未暂停）；命中时抛出 CheckpointPause。
        """
        state = self._state
        mc = getattr(state, "manual_config", None)
        if not mc or not mc.enabled or not mc.pause_points:
            return False

        # P3：步骤实际不可暂停（空实现/无产物）→ 跳过
        if step_name not in self._get_pausable_steps():
            logger.info("[Pipeline] Task %s step %s is not pausable, skipping pause", self.task_id, step_name)
            return False

        checkpoint = _STEP_TO_CHECKPOINT.get(step_name)
        if not checkpoint:
            return False

        # v7.6 外部素材模式：音频来源=视频（保留视频自带音轨、不生成 TTS）
        # → audio 检查点无产物可确认，自动通过。
        if (
            checkpoint == CHECKPOINT_AUDIO
            and getattr(mc, "execution_mode", "auto") == "external"
            and getattr(mc, "audio_source", "project") == "video"
        ):
            logger.info(
                "[Pipeline] Task %s external mode keeps video audio, "
                "audio checkpoint auto-passed", self.task_id,
            )
            return False

        if checkpoint not in mc.pause_points:
            return False
        if checkpoint in mc.approved_checkpoints:
            return False

        # 落盘暂停态：复用 PENDING + current_checkpoint 表达"等待用户"（PRD §4.2）
        # 进度展示该步骤完成时的真实进度（progress 参数 > 映射表 > 兜底 1.0），避免暂停显示 100%
        if progress is None:
            progress = _PAUSE_PROGRESS_BY_STEP.get(step_name, 1.0)
        mc.current_checkpoint = checkpoint
        state.status = StepStatus.PENDING
        # v7.0（issue #64）：等待确认提示按任务落盘的 ui_language 双语化
        self.task_manager.update_state(
            status=StepStatus.PENDING,
            manual_config=mc,
            current_step=checkpoint,
            current_status="awaiting_user",
            current_message=self._t("task.awaiting_checkpoint", checkpoint=checkpoint),
            current_progress=progress,
        )
        logger.info(
            "[Pipeline] Task %s paused at checkpoint '%s' (manual mode)",
            self.task_id, checkpoint,
        )
        raise CheckpointPause(checkpoint)

    @property
    def state(self) -> Optional[BaseTaskState]:
        return self._state

    @property
    def working_dir(self) -> str:
        return self.task_manager.task_dir

    def _ui_lang(self) -> str:
        """读取当前任务落盘的 UI 语言（v7.0，issue #64）。

        Pipeline 在后台协程里跑，HTTP 请求级 ContextVar 早已切走，因此不能
        依赖 ``core.i18n_backend.get_current_lang()``；必须从 ``self._state``
        上读任务创建时快照下来的 ``ui_language``。

        Returns:
            2 字母语言代码；``state`` 未就绪或字段缺失时回退 ``zh``。
        """
        state = self._state
        if state is None:
            return "zh"
        return getattr(state, "ui_language", "") or "zh"

    def _t(self, key: str, **params) -> str:
        """``translate(key, self._ui_lang(), **params)`` 的快捷方式。"""
        return translate(key, self._ui_lang(), **params)

    def _is_external(self) -> bool:
        """是否为外部素材模式（v7.6，``execution_mode == "external"``）。

        该模式下画面素材由外部工具（如即梦）产出后导入，本项目**不调用 Agnes
        图像/视频模型生成素材**（角色参考图、尾帧、分场景视频均不再自动生成）。
        """
        mc = getattr(getattr(self, "_state", None), "manual_config", None)
        return bool(mc and getattr(mc, "execution_mode", "auto") == "external")

    def _keeps_video_audio(self) -> bool:
        """是否处于「保留视频自带音轨」的外部素材模式（v7.6）。

        该模式（``execution_mode == "external`` 且 ``audio_source == "video"``）下
        不再生成/采集本项目 TTS 音频或词级 cues，字幕时间轴改按**各场景视频真实时长**
        对齐（见 :meth:`resolve_segment_durations`）。
        """
        mc = getattr(getattr(self, "_state", None), "manual_config", None)
        return bool(
            mc
            and getattr(mc, "execution_mode", "auto") == "external"
            and getattr(mc, "audio_source", "project") == "video"
        )

    def _use_dialogue_subtitles(self) -> bool:
        """字幕是否取「人物对白」而非旁白（v7.6 外部素材模式）。

        仅当 ``execution_mode == "external"`` 且 ``subtitle_source == "dialogue"``
        时为真；此时字幕文本来源切换为各场景 ``dialogue``（空则回退旁白），
        音频/TTS 仍走旁白（字幕来源与音频来源相互独立）。
        """
        mc = getattr(getattr(self, "_state", None), "manual_config", None)
        return bool(
            mc
            and getattr(mc, "execution_mode", "auto") == "external"
            and getattr(mc, "subtitle_source", "narration") == "dialogue"
        )

    def resolve_segment_durations(self, video_paths: list, fallback: list) -> list:
        """解析字幕分段时长（v7.6）：外部素材模式用视频真实时长，否则用计划时长。

        Args:
            video_paths: 各分段视频文件路径（按展示顺序）。
            fallback: 各分段计划时长（秒），探测失败时逐项回退。

        Returns:
            与 ``video_paths`` 等长的时长列表（秒）。
        """
        if not self._keeps_video_audio():
            return [float(d) for d in fallback]
        from core.compositor.ffmpeg_tool import probe_duration

        durations: list = []
        for i, path in enumerate(video_paths):
            base = float(fallback[i]) if i < len(fallback) else 5.0
            d = probe_duration(path, 0.0) if path else 0.0
            durations.append(float(d) if d and d > 0 else base)
        logger.info(
            "[Pipeline] External keep-audio: subtitle durations from real videos = %s",
            durations,
        )
        return durations

    def _submit_progress_callback(self, step: str, progress: float):
        """U1（v7.0）：提交侧进度回调，供 ``AgnesVideoAPI.submit_video`` 使用。

        队列类 503（``video_queue_full``）命中独立重试轨道时，经此回调把
        「Agnes 视频队列已满 + 原样报错 + 错峰建议」实时推给前端（任务状态轮询读取）。
        回调为同步函数（API 层在重试循环内直接调用），内部调度异步 ``_emit``。

        Args（回调载荷 dict）：``attempt`` 重试次序、``waited_s`` 已等秒数、
        ``status`` HTTP 状态码、``code`` 上游 body code、``message`` 上游原始文案。
        """
        def _cb(stage: str, data: dict) -> None:
            if stage != "queue_full":
                return
            info = data or {}
            waited = float(info.get("waited_s") or 0)
            params = {
                "n": int(info.get("attempt") or 1),
                "waited": max(1, round(waited / 60)),
                "status": info.get("status") or "",
                "code": info.get("code") or "",
            }
            try:
                asyncio.get_running_loop().create_task(self._emit(
                    step, "running",
                    # 兜底句仍按任务语言渲染（旧前端 / 前端未覆盖该 key 时使用）
                    self._t("progress.video.queue_full", **params),
                    progress,
                    # 结构化 key + 参数：前端命中后用自己的 22 语言文案渲染
                    message_key="progress.video.queue_full",
                    message_params=params,
                ))
            except RuntimeError:
                # 无运行中事件循环（理论不可达）：降级日志
                logger.warning(
                    f"[Pipeline] Agnes video queue full (HTTP {info.get('status')} · "
                    f"{info.get('code')}), queue retry #{info.get('attempt')} "
                    f"(waited {waited:.0f}s)"
                )
        return _cb

    # ── v7.7 快速重试模式（503 队列满时由用户主动开启的高频重试）────────

    def _attach_fast_retry(self, video_api) -> None:
        """把流水线侧的可选钩子注入视频 API（v7.7 快速重试 + v7.8 轮询健壮性）。

        所有钩子在 ``AgnesVideoAPI`` 上默认 ``None``：未注入时忙轨与轮询行为
        与升级前完全一致（零回归）。5 个流水线构造视频 API 后各调用一次。
        """
        if video_api is None:
            return
        hooks = {
            "fast_retry_hook": _PipelineFastRetryHook(self),
            "on_task_key_bound": self._on_task_key_bound,
            "key_hint_resolver": self._resolve_video_key_hint,
            "poll_progress_hook": self._on_poll_progress,
        }
        for name, hook in hooks.items():
            try:
                setattr(video_api, name, hook)
            except Exception as e:  # 注入失败不影响主流程
                logger.debug(f"[KeyBind] attach {name} failed: {e}")

    # ── v7.8：视频任务与提交 Key 的绑定持久化 ────────────────────────

    @staticmethod
    def _key_fingerprint(key: str) -> str:
        """Key 指纹：只把哈希写进 task_state.json，不落明文。"""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def _on_task_key_bound(self, video_id: str, key: str) -> None:
        """提交成功时落盘 ``video_id → Key 指纹``（进程重启后仍可恢复）。"""
        state = self._state
        if state is None:
            return
        try:
            fp = self._key_fingerprint(key)
            hints = dict(getattr(state, "video_key_hints", {}) or {})
            if hints.get(video_id) == fp:
                return
            hints[video_id] = fp
            if len(hints) > 128:  # 长视频多场景兜底，避免状态文件无限膨胀
                hints = dict(list(hints.items())[-128:])
            state.video_key_hints = hints
            self.task_manager.update_state()
            logger.info(
                "[KeyBind] Task %s: persisted key hint for video %s (key=...%s)",
                self.task_id, video_id[:16], key[-4:],
            )
        except Exception as e:
            logger.debug(f"[KeyBind] persist key hint failed: {e}")

    def _resolve_video_key_hint(self, video_id: str):
        """resume：按指纹在当前 Key 池里找回提交时那把 Key；找不到交给 404 探测。"""
        state = self._state
        if state is None:
            return None
        fp = (getattr(state, "video_key_hints", {}) or {}).get(video_id)
        if not fp:
            return None
        try:
            for k in get_key_ring().keys:
                if self._key_fingerprint(k) == fp:
                    logger.info(
                        "[KeyBind] Task %s: restored submit key for video %s (key=...%s)",
                        self.task_id, video_id[:16], k[-4:],
                    )
                    return k
        except Exception as e:
            logger.debug(f"[KeyBind] restore key hint failed: {e}")
        logger.warning(
            "[KeyBind] Task %s: key hint %s 已不在池中，交给 404 归属探测",
            self.task_id, fp,
        )
        return None

    # ── v7.8：轮询进度透传 ──────────────────────────────────────────

    def _on_poll_progress(self, video_id: str, status: str, progress, elapsed: float) -> None:
        """每轮轮询回调：节流后把上游状态推到前端（避免 20s 一次刷盘）。"""
        if self._state is None:
            return
        now = time.monotonic()
        last_ts, last_status = getattr(self, "_last_poll_emit", (0.0, ""))
        if status == last_status and now - last_ts < 25.0:
            return
        self._last_poll_emit = (now, status)
        mins, secs = divmod(int(elapsed), 60)
        self._emit_status_message("progress.video.polling", {
            "status": status or "-",
            "t": f"{mins}m{secs:02d}s",
            "vid": video_id[:12],
        })

    def _save_fast_retry(self) -> None:
        """把当前内存状态落盘（快速模式字段变更后调用）。

        直接 ``update_state()``（无字段变更）刷新 ``updated_at`` 并整份落盘，
        保证落盘对象就是流水线正在用的 ``_state``（create 时已同引用），
        避免与用户端点侧的另一份缓存互相覆盖。
        """
        try:
            self.task_manager.update_state()
        except Exception as e:
            logger.debug(f"[FastRetry] persist failed: {e}")

    def _emit_status_message(self, message_key: str, params: dict) -> None:
        """异步推送一条用户可见消息（保留当前 step 与进度，只换文案）。"""
        state = self._state
        if state is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        step = getattr(state, "current_step", "") or "video_gen"
        progress = float(getattr(state, "current_progress", 0.0) or 0.0)
        try:
            loop.create_task(self._emit(
                step, "running",
                self._t(message_key, **params),
                progress,
                preserve_step=True,
                message_key=message_key,
                message_params=dict(params),
            ))
        except Exception as e:
            logger.debug(f"[StatusEmit] emit failed: {e}")

    def _emit_fast_retry(self, message_key: str, params: dict) -> None:
        """v7.7 快速重试：兼容入口（实际推送统一走 ``_emit_status_message``）。"""
        self._emit_status_message(message_key, params)

    @abstractmethod
    async def run(self, state: BaseTaskState) -> str:
        """执行流水线，返回最终视频路径。"""
        ...

    # ==================================================================
    # 通用工具方法
    # ==================================================================

    @staticmethod
    def fix_double_utf8(text: str) -> str:
        """检测并修复双重 UTF-8 编码的文本。

        当 UTF-8 字节被误解读为 Latin-1 后再编码为 UTF-8 时，
        会产生乱码。此方法尝试还原原始文本。

        Args:
            text: 可能双重编码的文本。

        Returns:
            修复后的文本，如果不需要修复则返回原文。
        """
        if not text:
            return text
        # 检测典型乱码特征：包含 Latin-1 扩展字符且可被还原
        try:
            # 尝试将文本当作 Latin-1 编码的 UTF-8 字节来解码
            fixed = text.encode('latin-1').decode('utf-8')
            # 验证修复后的文本是有效的中文/ASCII
            if all(ord(c) < 0x80 or '\u4e00' <= c <= '\u9fff'
                   or '\u3000' <= c <= '\u303f'
                   or '\uff00' <= c <= '\uffef'
                   or '\u2000' <= c <= '\u206f'
                   for c in fixed[:20]):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        return text

    def save_prompts(self, prompts_data: dict) -> str:
        """将自动生成的 prompt 记录保存到 working_dir/prompts.json。

        Args:
            prompts_data: 包含各类 prompt 的字典，如
                {"anchor_prompt": ..., "clip_prompts": [...], "subtitle_styles": ...}

        Returns:
            保存的文件路径。
        """
        path = os.path.join(self.working_dir, "prompts.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(prompts_data, f, ensure_ascii=False, indent=2)
            logger.info("[Pipeline] prompts saved → %s", path)
        except Exception as e:
            logger.warning("[Pipeline] Failed to save prompts: %s", e)
        return path

    def _save_narration_txt(self, text: str, audio_path: str = "") -> str:
        """将旁白/读稿纯文本导出为 .txt（v5.x 产物规范前置工作）。

        文件名与音频同名推导（``xxx.mp3`` → ``xxx.txt``）；未给 ``audio_path``
        时使用 ``narration.txt``。导出文件供用户 / 外部 Agent 直接投喂给 LLM
        润色或修正，属于 v6.0 手动模式「产物可外部处理」的前置。

        Args:
            text: 旁白纯文本（无则跳过）。
            audio_path: 对应音频文件路径（可为空）。

        Returns:
            落盘的 txt 路径；失败或空文本时返回空串。
        """
        if not text:
            return ""
        if audio_path:
            txt_path = os.path.splitext(audio_path)[0] + ".txt"
        else:
            txt_path = os.path.join(self.working_dir, "narration.txt")
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info("[Artifacts] narration txt saved → %s", txt_path)
        except Exception as e:
            logger.warning("[Artifacts] failed to save narration txt: %s", e)
            return ""
        return txt_path

    @staticmethod
    def get_audio_duration(audio_path: str) -> float:
        """获取音频文件时长（秒），失败返回 0.0。

        Issue #78：改用 ``ffmpeg_tool.probe_duration`` 统一解析可执行文件，
        ffprobe 缺失时回退 ffmpeg stderr 解析，不再静默降级为 0.0。
        """
        if not audio_path or not os.path.exists(audio_path):
            return 0.0
        if os.path.getsize(audio_path) == 0:
            return 0.0
        return probe_duration(audio_path, default=0.0)

    async def generate_subtitles_common(
        self,
        segment_texts: List[str],
        segment_durations: List[float],
        subtitle_config: SubtitleConfig,
        sub_maker: object = None,
        audio_path: str = "",
        srt_filename: str = "full_subtitle.srt",
        styles_filename: str = "subtitle_styles.json",
        screenwriter=None,
        video_width: int = 768,
        video_height: int = 1152,
        role: str = "",
    ) -> tuple:
        """通用字幕生成逻辑，供所有 pipeline 复用。

        统一处理：
            1. 获取实际音频时长并按比例缩放段落时长
            2. 场景感知 SRT 生成（多段落）/ cues_to_srt（单段+词级）/ text_to_srt（纯文本）
            3. LLM 智能样式生成（style_mode=llm 时）

        Args:
            segment_texts: 各段文本列表。
            segment_durations: 各段估算时长列表（秒）。
            subtitle_config: 字幕配置。
            sub_maker: TTS SubMaker cues（可选）。
            audio_path: 音频文件路径（用于获取实际时长）。
            srt_filename: SRT 文件名。
            styles_filename: LLM 样式 JSON 文件名。
            screenwriter: Screenwriter 实例（LLM 样式生成用）。
            video_width: 视频宽度。
            video_height: 视频高度。
            role: 角色描述（传给 LLM 样式生成）。

        Returns:
            (srt_path, styles_path) 元组，styles_path 为空串表示未生成。
        """
        from core.audio.subtitle import SubtitleGenerator

        srt_path = os.path.join(self.working_dir, srt_filename)
        styles_path = ""

        # ── 已存在则跳过 ──
        if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
            logger.info("[Subtitle] SRT already exists, skipping: %s", srt_path)
            if subtitle_config.enabled and subtitle_config.style.style_mode == "llm":
                sp = os.path.join(self.working_dir, styles_filename)
                if os.path.exists(sp) and os.path.getsize(sp) > 0:
                    styles_path = sp
            return srt_path, styles_path

        full_text = "\n\n".join(t for t in segment_texts if t)
        if not full_text:
            logger.warning("[Subtitle] empty text, skipping")
            return "", ""

        # ── 1. 获取实际音频时长 ──
        actual_audio_dur = self.get_audio_duration(audio_path)

        # ── 2. 生成 SRT ──
        num_segments = len(segment_texts)
        use_cue_timeline = getattr(subtitle_config, "use_cue_timeline", True)

        if subtitle_config.enabled and num_segments > 1:
            # 按音频时长等比缩放段落时长（场景时间轴/策略B 用；cues 路径计时本身不依赖缩放）
            total_est = sum(segment_durations)
            scaled_durations = list(segment_durations)
            if actual_audio_dur > 0 and total_est > 0:
                scale = actual_audio_dur / total_est
                scaled_durations = [d * scale for d in scaled_durations]
                logger.info(
                    "[Subtitle] durations scaled by %.3f (audio=%.2fs, est=%.2fs)",
                    scale, actual_audio_dur, total_est,
                )

            # cues 精确对齐（有 sub_maker 且开关开启）；否则回退 legacy 启发式
            if sub_maker is not None and use_cue_timeline:
                scene_start_times = []
                acc = 0.0
                for d in scaled_durations:
                    scene_start_times.append(acc)
                    acc += d
                srt_content = SubtitleGenerator.generate_cue_aware_srt(
                    sub_maker,
                    segment_texts=segment_texts,
                    scene_start_times=scene_start_times,
                    scene_durations=scaled_durations,
                    audio_duration=actual_audio_dur if actual_audio_dur > 0 else None,
                )
                if not srt_content.strip():
                    # cues 不足（如 raw_cues 粒度过低）→ 回退 legacy
                    logger.warning(
                        "[Subtitle] cue-aware produced empty SRT, "
                        "falling back to scene-aware"
                    )
                    srt_content = SubtitleGenerator._generate_scene_aware_srt(
                        segment_texts, scaled_durations, word_cues=None,
                    )
            else:
                srt_content = SubtitleGenerator._generate_scene_aware_srt(
                    segment_texts, scaled_durations, word_cues=None,
                )

            if srt_content.strip():
                await write_text(srt_path, srt_content)
                entry_count = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 0
                logger.info(
                    "[Subtitle] Scene-aware SRT: %d entries across %d segments",
                    entry_count, num_segments,
                )
            else:
                subtitle_config.enabled = False
        elif subtitle_config.enabled and sub_maker is not None:
            SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
        elif subtitle_config.enabled:
            total_dur = actual_audio_dur if actual_audio_dur > 0 else sum(segment_durations)
            SubtitleGenerator.text_to_srt(full_text, srt_path, total_dur)
        else:
            await write_text(srt_path, "")

        # ── 2.5 统一后处理：确保每条字幕不超过 2 行（参考中文短字幕规范，适配所有语言）──
        try:
            raw_srt = await read_text(srt_path)
            fixed_srt = SubtitleGenerator.enforce_max_lines(
                raw_srt, max_lines=2,
                video_width=video_width, fontsize=subtitle_config.style.fontsize,
            )
            if fixed_srt and fixed_srt != raw_srt:
                await write_text(srt_path, fixed_srt)
                entry_count = fixed_srt.count("\n\n") + 1 if "\n\n" in fixed_srt else 1
                logger.info(
                    "[Subtitle] enforce_max_lines applied: ≤2 lines/entry (%d entries)",
                    entry_count,
                )
        except Exception as e:
            logger.warning("[Subtitle] enforce_max_lines failed: %s", e)

        # ── 3. LLM 智能样式 ──
        if (subtitle_config.enabled
                and subtitle_config.style.style_mode == "llm"
                and screenwriter is not None):
            sp = os.path.join(self.working_dir, styles_filename)
            if not os.path.exists(sp) or os.path.getsize(sp) == 0:
                try:
                    styles = await asyncio.to_thread(
                        screenwriter.generate_subtitle_styles,
                        srt_path=srt_path,
                        video_width=video_width,
                        video_height=video_height,
                        style_hints=subtitle_config.style.style_hints,
                        **({"role": role} if role else {}),
                    )
                    await write_text(sp, json.dumps(styles, ensure_ascii=False, indent=2))
                    styles_path = sp
                    logger.info(
                        "[Subtitle] LLM styles saved: %s (%d entries)",
                        sp, len(styles),
                    )
                except Exception as e:
                    logger.warning(
                        "[Subtitle] LLM styles failed: %s, falling back to fixed", e
                    )

        return srt_path, styles_path


    # ==================================================================
    # 共享工具：上提自各 pipeline 子类（v4.0 重构消重）
    # ==================================================================

    def _check_shutdown(self) -> None:
        """检查是否需要停止流水线，收到停止信号则抛出 PipelineShutdown。"""
        if self._is_shutdown():
            raise PipelineShutdown("Pipeline shutdown requested")

    async def _recover_sub_maker(
        self, narration_text: str, audio_config, subtitle_config, audio_path: str = ""
    ) -> object:
        """恢复词级 cues（优化路线图 1.2：续传免重采 TTS）。

        续传场景下 ``_step_audio`` 常因音频文件已存在而跳过，导致 ``sub_maker``
        丢失，进而字幕退回 legacy 启发式（v2.0 cue 精确对齐失效）。

        1.2 起生成音频时会随写 ``{音频路径}.cues.json`` 缓存：本方法优先读取
        缓存（零网络开销），仅缓存缺失（旧产物）时才回退重新消费 TTS 流采集
        cues。

        Args:
            audio_path: 对应音频文件路径；提供时优先读 ``.cues.json`` 缓存。

        Returns:
            cues 兼容对象（含 ``.cues``）；不需要或失败时返回 None。
        """
        # v7.6 外部素材模式：字幕按视频真实时长对齐，不恢复 TTS cues。
        if self._keeps_video_audio():
            return None
        if not narration_text:
            return None
        use_cue = getattr(subtitle_config, "use_cue_timeline", True)
        if not (getattr(subtitle_config, "enabled", False) and use_cue):
            return None
        # 1.2：优先读缓存，免重新消费 TTS 流
        if audio_path:
            restored = self._load_cues_cache(audio_path)
            if restored is not None:
                logger.info(
                    "[Subtitle] recovered sub_maker from cues cache: %s",
                    _cues_cache_path(audio_path),
                )
                return restored
        try:
            from core.audio.tts import EdgeTTSEngine
            return await EdgeTTSEngine().harvest_cues(
                text=narration_text,
                voice=getattr(audio_config, "voice", ""),
                rate=getattr(audio_config, "rate", "+0%"),
            )
        except RuntimeError as e:
            logger.warning("[Subtitle] recover sub_maker via harvest_cues failed: %s", e)
            return None

    def _load_cues_cache(self, audio_path: str) -> Optional[object]:
        """读取音频旁路的 cues 缓存并还原为消费方兼容对象（1.2）。"""
        try:
            cache = _cues_cache_path(audio_path)
            if not os.path.exists(cache):
                return None
            with open(cache, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return _deserialize_sub_maker(raw)
        except Exception as e:
            logger.warning("[Subtitle] load cues cache failed: %s", e)
            return None

    def _save_cues_cache(self, audio_path: str, sub_maker) -> None:
        """把词级 cues 落盘到 ``{audio_path}.cues.json``（1.2）。"""
        try:
            cues = _serialize_sub_maker(sub_maker)
            if not cues:
                return
            with open(_cues_cache_path(audio_path), "w", encoding="utf-8") as f:
                json.dump(cues, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("[Subtitle] save cues cache failed: %s", e)

    async def _generate_audio_with_fallback(
        self,
        output_path: str,
        text: str,
        audio_config: AudioConfig,
        subtitle_config: Optional[SubtitleConfig] = None,
        duration_sec: float = 0.0,
        empty_placeholder: str = "",
    ) -> Optional[object]:
        """统一 TTS 音频生成（EdgeTTS → Silent 降级 + cues 采集）。

        S2 收敛目标：替代 multi_scene / creative / poetry / manuscript / anchor
        五处复制的"EdgeTTS → Silent 降级 + harvest_cues"逻辑（v5.0 Batch 2）。

        行为矩阵：
            0. 外部素材模式保留视频自带音轨（:meth:`_keeps_video_audio`）：直接返回
               None，不落盘、不调用 EdgeTTS、不采集 cues（本项目不产出任何音频）。
            1. text 为空：empty_placeholder="" → 跳过返回 None（不落盘）；
               非空 → 以占位文本直接走 Silent 落盘（不调用 EdgeTTS）。
            2. audio_config.enabled → EdgeTTSEngine.generate：
               成功 → 校验 cues（无逐词时间戳 → warning 并返回 None，
               字幕回退 legacy 启发式）；
               RuntimeError → Silent(duration_sec) 落盘。
            3. 音频关 + 字幕开 + harvest_cues_when_audio_off（路径 B）：
               harvest_cues 采集（RuntimeError 仅警告）→ 随后 Silent 落盘，返回 cues。
            4. 其他（音频关 / 不采集 cues）→ Silent 落盘，返回 None。

        Args:
            output_path: 输出音频文件路径。
            text: 配音文本。
            audio_config: 音频配置（AudioConfig 或含 enabled/voice/rate 的鸭子类型）。
            subtitle_config: 字幕配置（音频关闭时决定是否采集 cues）。
            duration_sec: Silent 降级音频时长（秒）；0 表示由引擎按文本估算。
            empty_placeholder: 文本为空时的占位文本；"" 表示空文本直接跳过。

        Returns:
            SubMaker cues 对象（有 cues 可用时）；否则 None。
        """
        # v7.6 外部素材模式（保留视频自带音轨）：本项目**完全不产出音频** ——
        # 不写 combined_narration.mp3、不调用 edge_tts、不采集 cues；字幕改按
        # 各场景视频真实时长对齐（见 :meth:`resolve_segment_durations`）。
        if self._keeps_video_audio():
            logger.info(
                "[Audio] external keep-audio mode: skip project audio generation: %s",
                output_path,
            )
            return None

        from core.audio.tts import EdgeTTSEngine, SilentTTSEngine

        audio_enabled = bool(getattr(audio_config, "enabled", True))
        subtitle_enabled = bool(getattr(subtitle_config, "enabled", False))
        harvest_cues = bool(getattr(subtitle_config, "harvest_cues_when_audio_off", True))
        voice = getattr(audio_config, "voice", "zh-CN-XiaoxiaoNeural")
        rate = getattr(audio_config, "rate", "+0%")

        # 空文本：无占位 → 跳过；有占位 → 直接 Silent 落盘（不调用 EdgeTTS）
        if not text:
            if not empty_placeholder:
                logger.info("[Audio] empty text, skipping TTS: %s", output_path)
                return None
            text = empty_placeholder
            await SilentTTSEngine().generate(
                text=text, output_path=output_path,
                **({"duration_sec": duration_sec} if duration_sec else {}),
            )
            return None

        silent_tts = SilentTTSEngine()

        # 路径 A：音频开 → EdgeTTS 生成
        if audio_enabled:
            try:
                edge_tts = EdgeTTSEngine()
                _, sub_maker = await edge_tts.generate(
                    text=text, output_path=output_path, voice=voice, rate=rate,
                )
                # cues 不足 → 字幕回退 legacy 启发式（不删音频，仅返回 None）
                if sub_maker is not None and not getattr(sub_maker, "cues", None):
                    logger.warning(
                        "[Audio] EdgeTTS produced no cues, "
                        "subtitles fall back to legacy: %s",
                        output_path,
                    )
                    return None
                # 1.2：cues 随音频落盘，续传免重采
                self._save_cues_cache(output_path, sub_maker)
                return sub_maker
            except RuntimeError as e:
                logger.warning("[Audio] EdgeTTS failed, falling back to silent: %s", e)
                await silent_tts.generate(
                    text=text, output_path=output_path,
                    **({"duration_sec": duration_sec} if duration_sec else {}),
                )
                return None

        # 路径 B：音频关 + 字幕开 + harvest_cues_when_audio_off → 仅采集 cues
        if subtitle_enabled and harvest_cues:
            sub_maker = None
            try:
                edge_tts = EdgeTTSEngine()
                sub_maker = await edge_tts.harvest_cues(
                    text=text, voice=voice, rate=rate,
                )
            except RuntimeError as e:
                logger.warning("[Audio] harvest_cues failed, silent fallback: %s", e)
            await silent_tts.generate(
                text=text, output_path=output_path,
                **({"duration_sec": duration_sec} if duration_sec else {}),
            )
            # 1.2：路径 B（音频关+字幕开）也随音频落盘 cues，供续传读取
            if sub_maker is not None:
                self._save_cues_cache(output_path, sub_maker)
            return sub_maker

        # 其他（音频关 / 不采集 cues）→ Silent 落盘
        await silent_tts.generate(
            text=text, output_path=output_path,
            **({"duration_sec": duration_sec} if duration_sec else {}),
        )
        return None

    def _make_curl(self, video_id: str) -> str:
        """生成用于查询视频状态的 curl 命令（供调试/续传）。

        域名取自该任务提交时使用的 Key（与真实轮询一致）：Key 绑定域名与全局
        域名可以不同，硬编码或取全局域名会给出打错站点的调试命令。
        拿不到 Key 记录（旧任务/进程重启）时才回退全局域名。
        """
        root = ""
        for attr in ("video_api", "video_generator"):
            api = getattr(self, attr, None)
            getter = getattr(api, "api_root_for_task", None)
            if callable(getter):
                root = getter(video_id) or ""
                if root:
                    break
        if not root:
            from core.config import get_agnes_api_root
            root = get_agnes_api_root()
        return (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"{root}/agnesapi?video_id={video_id}"'
        )

    def _save_task_json(self, sub_dir: str, data: dict) -> None:
        """持久化任务元数据（video_id 等）到 sub_dir/task.json + curl.sh。"""
        os.makedirs(sub_dir, exist_ok=True)
        task_file = os.path.join(sub_dir, "task.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        curl_file = os.path.join(sub_dir, "curl.sh")
        with open(curl_file, "w", encoding="utf-8") as f:
            f.write(self._make_curl(data.get("video_id", "")) + "\n")

    def _load_task_json(self, sub_dir: str) -> Optional[str]:
        """从 sub_dir/task.json 读取已保存的 video_id（断点续传用）。"""
        task_file = os.path.join(sub_dir, "task.json")
        if os.path.exists(task_file):
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to load cached task.json: {e}")
        return None

    def _get_watermark_language_text(self) -> str:
        """水印语言检测用文本。子类可覆盖以返回合适的来源文本。"""
        return ""

    async def _apply_watermark(self, video_path: str) -> str:
        """通用水印后处理：根据配置叠加水印（不修改原文件则原样返回）。

        优化路线图 0.3：``add_watermark`` 内部是 ffmpeg 全片重编码
        （``subprocess.run``，timeout=300s），此前在协程中同步执行会冻结整个
        事件循环——期间其他任务的轮询、进度落盘、API 请求全部停摆。
        改为下沉线程池执行。
        """
        wm_config = get_watermark_config()
        if wm_config.get("enabled") and os.path.exists(video_path):
            lang = wm_config.get("language", "auto")
            if lang == "auto":
                lang = detect_language(self._get_watermark_language_text())
            wm_output = video_path + ".wm_tmp.mp4"
            # 2.3：编码走专用线程池（与轻量请求隔离，不占用默认 to_thread 池）。
            # run_in_executor 只接受位置参数，关键字参数经 functools.partial 绑定。
            loop = asyncio.get_running_loop()
            ok = await loop.run_in_executor(
                _ENCODING_EXECUTOR,
                functools.partial(add_watermark, language=lang),
                video_path, wm_output,
            )
            if ok:
                os.replace(wm_output, video_path)
        return video_path

    @staticmethod
    async def run_ffmpeg_async(cmd: List[str], timeout: float = 30.0) -> None:
        """异步执行 ffmpeg 命令（不阻塞事件循环）。等价于 subprocess.run(check=True)。

        Issue #78：命令首元素为 ``"ffmpeg"``/``"ffprobe"`` 时统一解析为真实路径，
        避免在无系统 ffmpeg 的环境里抛裸 ``[WinError 2]``。
        """
        cmd = resolve_cmd_binary(cmd)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:500] if stderr else ""
            raise RuntimeError(f"ffmpeg exited with code {proc.returncode}: {err}")


# 导出
# 注意：导入顺序是刻意设计（multi_scene 必须先于 anchor 导入，避免循环导入）。
# ruff isort（I001）排序会破坏该顺序，故本文件在 ruff.toml 中豁免 I001。
from core.pipelines.multi_scene import MultiScenePipeline
from core.pipelines.simple_video import SimpleVideoPipeline
from core.pipelines.creative_video import CreativeVideoPipeline
from core.pipelines.manuscript_video import ManuscriptVideoPipeline
from core.pipelines.anchor_video import AnchorPipeline
from core.pipelines.poetry_video import PoetryVideoPipeline

__all__ = [
    "BasePipeline",
    "PipelineShutdown",
    "MultiScenePipeline",
    "SimpleVideoPipeline",
    "CreativeVideoPipeline",
    "ManuscriptVideoPipeline",
    "AnchorPipeline",
    "PoetryVideoPipeline",
]
