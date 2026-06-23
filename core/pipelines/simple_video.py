"""core.pipelines.simple_video — 简单视频生成流水线（类型 1）

用户输入 prompt → 选择模式（t2v/i2v/keyframes）→ 调用 Agnes Video API → 返回视频。
"""

import asyncio
import json
import logging
import os
import re
from typing import Callable, Optional

from core.api.agnes_video import AgnesVideoAPI
from core.pipelines import BasePipeline, PipelineShutdown
from core.task_manager import TaskManager
from models.task import SimpleVideoTask, StepStatus

logger = logging.getLogger(__name__)


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
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.video_api = AgnesVideoAPI(api_key=api_key)
        self.video_api.shutdown_event = shutdown_event

    async def run(self, state: SimpleVideoTask) -> str:
        """执行简单视频生成流水线。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", "开始简单视频生成...", 0.0)

        try:
            video_path = await self._submit_and_wait()

            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = video_path
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=video_path,
            )
            await self._emit("done", "completed", "视频生成完成!", 1.0, {"final_video": video_path})
            return video_path

        except PipelineShutdown as e:
            logger.info(f"[Simple] Shutdown: {e}")
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise

    # ------------------------------------------------------------------
    # Curl / task persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_curl(video_id: str) -> str:
        return (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"'
        )

    def _save_task(self, video_id: str) -> None:
        task_file = os.path.join(self.working_dir, "task.json")
        with open(task_file, "w") as f:
            json.dump({"video_id": video_id}, f, indent=2)
        curl_file = os.path.join(self.working_dir, "curl.sh")
        with open(curl_file, "w") as f:
            f.write(self._make_curl(video_id) + "\n")

    def _load_task(self) -> Optional[str]:
        task_file = os.path.join(self.working_dir, "task.json")
        if os.path.exists(task_file):
            try:
                with open(task_file, "r") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception as e:
                logger.debug(f"[Simple] Failed to load cached task.json: {e}")
        return None

    async def _submit_and_wait(self) -> str:
        """提交视频任务并等待完成。支持 resume。"""
        video_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(video_path):
            logger.info("[Simple] Video already exists, skipping")
            return video_path

        # 尝试从 task.json 恢复（resume 场景）
        saved_video_id = self._load_task()
        if saved_video_id:
            logger.info(f"[Simple] Resuming from saved task.json video_id: {saved_video_id}")
            self._state.video_id = saved_video_id
            self.task_manager.update_state(video_id=saved_video_id)
            await self._emit("video_gen", "running", f"恢复轮询视频任务 {saved_video_id[:16]}...", 0.3)
            video_output = await self.video_api.wait_for_video(saved_video_id)
            video_output.save(video_path)
            return video_path

        # 也检查 state 中的 video_id（旧版 resume 兼容）
        if self._state.video_id:
            logger.info(f"[Simple] Resuming from state video_id: {self._state.video_id}")
            self._save_task(self._state.video_id)
            await self._emit("video_gen", "running", f"恢复轮询视频任务 {self._state.video_id[:16]}...", 0.3)
            video_output = await self.video_api.wait_for_video(self._state.video_id)
            video_output.save(video_path)
            return video_path

        # 构建参考图列表
        ref_images = []
        if self._state.reference_image:
            ref_images.append(self._state.reference_image)
        if self._state.end_frame_image:
            ref_images.append(self._state.end_frame_image)

        await self._emit("video_gen", "running", f"提交视频任务 (mode={self._state.mode})...", 0.1)

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
        )

        # 持久化 video_id + curl 命令
        self._state.video_id = video_id
        self._save_task(video_id)
        self.task_manager.update_state(video_id=video_id)

        await self._emit("video_gen", "running", f"等待视频生成 {video_id[:16]}...", 0.3)

        video_output = await self.video_api.wait_for_video(video_id)
        video_output.save(video_path)

        await self._emit("video_gen", "completed", "视频生成完成", 0.9)
        return video_path
