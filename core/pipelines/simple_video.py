"""core.pipelines.simple_video — 简单视频生成流水线（类型 1）

用户输入 prompt → 选择模式（t2v/i2v/keyframes）→ 调用 Agnes Video API → 返回视频。
"""

import asyncio
import logging
import os
import re
import traceback
from typing import Callable, List, Optional

from core.api.agnes_video import AgnesVideoAPI
from core.config import DEFAULT_TEXT_MODEL
from core.pipelines import BasePipeline, PipelineShutdown
from models.task import SimpleVideoTask, StepStatus, VideoMode
from utils.network import (
    describe_network_error,
    describe_queue_full_error,
    queue_full_message_params,
)

logger = logging.getLogger(__name__)

# 简单视频流水线进度常量（0.0 ~ 1.0）
_PROGRESS_INIT = 0.0
_PROGRESS_SUBMIT = 0.1
_PROGRESS_WAIT = 0.3
_PROGRESS_DONE = 0.9
_PROGRESS_COMPLETED = 1.0
_PROGRESS_FAILED = 0.0


class SimpleVideoPipeline(BasePipeline):
    """简单视频生成流水线。

    步骤：参数校验 → 提交视频任务 → 轮询等待 → 下载保存。
    支持 resume：通过 task.json 中保存的 video_id 恢复轮询。
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: str = None,
        chat_model: str = DEFAULT_TEXT_MODEL,
        image_model: str = "agnes-image-2.5-flash",
        video_model: str = "agnes-video-2.5-flash",
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.video_api = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_api.shutdown_event = shutdown_event
        # v7.7：批量提交阶段的 503 快速重试钩子（用户开启后才生效）
        self._attach_fast_retry(self.video_api)

    async def run(self, state: SimpleVideoTask) -> str:
        """执行简单视频生成流水线。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", self._t("progress.simple.start"), _PROGRESS_INIT)

        try:
            video_path = await self._submit_and_wait()

            # 水印后处理（共享实现；异步，避免阻塞事件循环）
            video_path = await self._apply_watermark(video_path)

            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = video_path
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=video_path,
            )
            await self._emit("done", "completed", self._t("progress.simple.done"), _PROGRESS_COMPLETED, {"final_video": video_path})
            return video_path

        except PipelineShutdown as e:
            logger.info(f"[Simple] Shutdown: {e}")
            # v7.0（issue #64）：中断提示按任务落盘的 ui_language 双语化
            await self._emit(
                "error", "failed",
                self._t("task.interrupted_resumable"),
                _PROGRESS_FAILED,
                preserve_step=True,
            )
            raise
        except Exception as e:
            # 网络 / 域名解析类故障翻译成可自助排查的提示（issue #56/#57）
            # v7.0（issue #64）：按 state.ui_language 输出中/英文，避免英文界面看到中文诊断
            # v7.0 U1：队列满优先走结构化提示（前端按 22 语言渲染，后端给 zh/en 兜底）
            message = (
                describe_queue_full_error(e, lang=self._ui_lang())
                or describe_network_error(e, lang=self._ui_lang())
                or str(e)
            )
            message_key = "error.video.queue_full" if queue_full_message_params(e) else None
            message_params = queue_full_message_params(e) or None
            failed_step = self._state.current_step if self._state else ""
            # 持久化完整 traceback，供诊断端点/前端反馈报告暴露（定位环境级异常如 [WinError 2]）
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(
                status=StepStatus.FAILED,
                error_traceback=traceback.format_exc(),
                # 失败即落盘真实环节 + 可读消息，避免诊断报告归因停留在旧快照
                current_step=failed_step,
                current_status="failed",
                current_message=message,
            )
            logger.error("[Simple] Task %s failed at step '%s': %s", self.task_id, failed_step, e)
            await self._emit(
                "error", "failed", message, _PROGRESS_FAILED, preserve_step=True,
                message_key=message_key, message_params=message_params,
            )
            raise

    # ------------------------------------------------------------------
    # 水印语言来源（共享 _apply_watermark 用）
    # ------------------------------------------------------------------

    def _get_watermark_language_text(self) -> str:
        return self._state.prompt

    async def _submit_and_wait(self) -> str:
        """提交视频任务并等待完成。支持 resume。"""
        video_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(video_path):
            logger.info("[Simple] Video already exists, skipping")
            return video_path

        resumed_path = await self._resume_saved_video(video_path)
        if resumed_path:
            return resumed_path

        ref_images, first_frame, last_frame, audio_urls = self._collect_media()
        await self._emit(
            "video_gen", "running",
            self._t("progress.simple.submitting", mode=self._state.mode),
            _PROGRESS_SUBMIT,
        )
        video_id = await self.video_api.submit_video(
            prompt=self._build_full_prompt(),
            reference_image_paths=ref_images,
            duration=self._state.duration,
            width=self._state.video_width,
            height=self._state.video_height,
            seed=self._state.seed,
            negative_prompt=self._state.negative_prompt,
            video_size=getattr(self._state, "video_size", None) or "720P",
            first_frame=first_frame or None,
            last_frame=last_frame or None,
            reference_audio_urls=audio_urls or None,
            # U1（v7.0）：队列满时实时向前端推「排队重试中」
            progress_callback=self._submit_progress_callback("video_gen", _PROGRESS_SUBMIT),
        )

        # 持久化 video_id + curl 命令
        self._state.video_id = video_id
        self._save_task_json(self.working_dir, {"video_id": video_id})
        self.task_manager.update_state(video_id=video_id)

        await self._emit("video_gen", "running", self._t("progress.simple.waiting", vid=video_id[:16]), _PROGRESS_WAIT)

        video_output = await self.video_api.wait_for_video(video_id)
        await video_output.save(video_path)

        await self._emit("video_gen", "completed", self._t("progress.simple.completed"), _PROGRESS_DONE)
        return video_path

    async def _resume_saved_video(self, video_path: str) -> Optional[str]:
        """按 task.json / state 中已落盘的 video_id 续跑轮询。

        Returns:
            续跑成功返回成片路径；无可用 video_id 时返回 ``None``。
        """
        saved_video_id = self._load_task_json(self.working_dir)
        if saved_video_id:
            logger.info(f"[Simple] Resuming from saved task.json video_id: {saved_video_id}")
            self._state.video_id = saved_video_id
            self.task_manager.update_state(video_id=saved_video_id)
            return await self._poll_saved_video(saved_video_id, video_path)

        # 也检查 state 中的 video_id（旧版 resume 兼容）
        if self._state.video_id:
            logger.info(f"[Simple] Resuming from state video_id: {self._state.video_id}")
            self._save_task_json(self.working_dir, {"video_id": self._state.video_id})
            return await self._poll_saved_video(self._state.video_id, video_path)
        return None

    async def _poll_saved_video(self, video_id: str, video_path: str) -> str:
        """轮询已提交的 video_id 并落盘成片（resume 共用）。"""
        await self._emit(
            "video_gen", "running",
            self._t("progress.simple.resume_polling", vid=video_id[:16]),
            _PROGRESS_WAIT,
        )
        video_output = await self.video_api.wait_for_video(video_id)
        await video_output.save(video_path)
        return video_path

    def _collect_media(self) -> tuple:
        """按模式归拢素材（v8.0：区分 keyframe 首尾帧 / reference 多图 / 参考音频）。

        Returns:
            ``(ref_images, first_frame, last_frame, audio_urls)``。
        """
        state = self._state
        ref_images: List[str] = list(getattr(state, "reference_images", None) or [])
        first_frame = getattr(state, "first_frame_image", "") or ""
        last_frame = getattr(state, "last_frame_image", "") or ""
        audio_urls = list(getattr(state, "reference_audio_urls", None) or [])

        if state.mode == VideoMode.KEYFRAMES:
            # 历史 keyframes 任务把首尾帧存在 reference_image / end_frame_image
            first_frame = first_frame or state.reference_image or ""
            last_frame = last_frame or state.end_frame_image or ""
            # 官方规则：keyframe 不允许 images/audios，素材互斥
            ref_images, audio_urls = [], []
        elif state.mode in (VideoMode.I2V, VideoMode.TI2VID):
            # 图生视频只走 reference(images)，不混入首尾帧
            first_frame, last_frame = "", ""
            if not ref_images and state.reference_image:
                ref_images = [state.reference_image]
        # t2v：保持「有素材则自动按 reference 处理」的旧行为（兼容旧 API 调用）
        return ref_images, first_frame, last_frame, audio_urls

    def _build_full_prompt(self) -> str:
        """拼接系统提示词与用户 prompt（分隔符跟随 prompt 语言）。"""
        prompt = self._state.prompt
        system_prompt = self._state.system_prompt.strip()
        if not system_prompt:
            return prompt
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", prompt))
        sep = (
            "--- 请严格按照以下描述生成图像/视频 ---" if has_chinese
            else "--- Generate image/video strictly based on the following description ---"
        )
        return f"{system_prompt}\n\n{sep}\n{prompt}"
