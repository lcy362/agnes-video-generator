"""core.pipelines.simple_video — 简单视频生成流水线（类型 1）

用户输入 prompt → 选择模式（t2v/i2v/keyframes）→ 调用 Agnes Video API → 返回视频。
"""

import asyncio
import logging
import os
import re
import traceback
from typing import Callable, Optional

from core.api.agnes_video import AgnesVideoAPI
from core.pipelines import BasePipeline, PipelineShutdown
from models.task import SimpleVideoTask, StepStatus

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
        chat_model: str = "agnes-2.5-flash",
        image_model: str = "agnes-image-2.5-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.video_api = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_api.shutdown_event = shutdown_event

    async def run(self, state: SimpleVideoTask) -> str:
        """执行简单视频生成流水线。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", "开始简单视频生成...", _PROGRESS_INIT)

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
            await self._emit("done", "completed", "视频生成完成!", _PROGRESS_COMPLETED, {"final_video": video_path})
            return video_path

        except PipelineShutdown as e:
            logger.info(f"[Simple] Shutdown: {e}")
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", _PROGRESS_FAILED)
            raise
        except Exception as e:
            # 持久化完整 traceback，供诊断端点/前端反馈报告暴露（定位环境级异常如 [WinError 2]）
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(
                status=StepStatus.FAILED,
                error_traceback=traceback.format_exc(),
            )
            await self._emit("error", "failed", str(e), _PROGRESS_FAILED)
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

        # 尝试从 task.json 恢复（resume 场景）
        saved_video_id = self._load_task_json(self.working_dir)
        if saved_video_id:
            logger.info(f"[Simple] Resuming from saved task.json video_id: {saved_video_id}")
            self._state.video_id = saved_video_id
            self.task_manager.update_state(video_id=saved_video_id)
            await self._emit("video_gen", "running", f"恢复轮询视频任务 {saved_video_id[:16]}...", _PROGRESS_WAIT)
            video_output = await self.video_api.wait_for_video(saved_video_id)
            await video_output.save(video_path)
            return video_path

        # 也检查 state 中的 video_id（旧版 resume 兼容）
        if self._state.video_id:
            logger.info(f"[Simple] Resuming from state video_id: {self._state.video_id}")
            self._save_task_json(self.working_dir, {"video_id": self._state.video_id})
            await self._emit("video_gen", "running", f"恢复轮询视频任务 {self._state.video_id[:16]}...", _PROGRESS_WAIT)
            video_output = await self.video_api.wait_for_video(self._state.video_id)
            await video_output.save(video_path)
            return video_path

        # 构建参考图列表
        ref_images = []
        if self._state.reference_image:
            ref_images.append(self._state.reference_image)
        if self._state.end_frame_image:
            ref_images.append(self._state.end_frame_image)

        await self._emit("video_gen", "running", f"提交视频任务 (mode={self._state.mode})...", _PROGRESS_SUBMIT)

        # 分隔符跟随用户 prompt 语言
        _has_chinese = bool(re.search(r'[\u4e00-\u9fff]', self._state.prompt))
        _sep = "--- 请严格按照以下描述生成图像/视频 ---" if _has_chinese else "--- Generate image/video strictly based on the following description ---"
        full_prompt = f"{self._state.system_prompt.strip()}\n\n{_sep}\n{self._state.prompt}" if self._state.system_prompt.strip() else self._state.prompt
        video_id = await self.video_api.submit_video(
            prompt=full_prompt,
            reference_image_paths=ref_images,
            duration=self._state.duration,
            width=self._state.video_width,
            height=self._state.video_height,
            seed=self._state.seed,
            negative_prompt=self._state.negative_prompt,
            video_size=getattr(self._state, "video_size", None) or "720P",
        )

        # 持久化 video_id + curl 命令
        self._state.video_id = video_id
        self._save_task_json(self.working_dir, {"video_id": video_id})
        self.task_manager.update_state(video_id=video_id)

        await self._emit("video_gen", "running", f"等待视频生成 {video_id[:16]}...", _PROGRESS_WAIT)

        video_output = await self.video_api.wait_for_video(video_id)
        await video_output.save(video_path)

        await self._emit("video_gen", "completed", "视频生成完成", _PROGRESS_DONE)
        return video_path
