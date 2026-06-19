"""core.pipelines — 业务流水线层

BasePipeline 抽象基类 + 三种流水线导出。
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

from core.task_manager import TaskManager
from models.task import BaseTaskState

logger = logging.getLogger(__name__)


class PipelineShutdown(Exception):
    """流水线中断异常。"""
    pass


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

    async def _emit(
        self,
        step: str,
        status: str,
        message: str,
        progress: float = 0.0,
        data: dict = None,
    ):
        """发送进度消息到前端。"""
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

    @property
    def state(self) -> Optional[BaseTaskState]:
        return self._state

    @property
    def working_dir(self) -> str:
        return self.task_manager.task_dir

    @abstractmethod
    async def run(self, state: BaseTaskState) -> str:
        """执行流水线，返回最终视频路径。"""
        ...


# 导出
from core.pipelines.simple_video import SimpleVideoPipeline
from core.pipelines.creative_video import CreativeVideoPipeline
from core.pipelines.manuscript_video import ManuscriptVideoPipeline
from core.pipelines.anchor_video import AnchorPipeline

__all__ = [
    "BasePipeline",
    "PipelineShutdown",
    "SimpleVideoPipeline",
    "CreativeVideoPipeline",
    "ManuscriptVideoPipeline",
    "AnchorPipeline",
]
