"""core.pipelines.simple_image — 简单图片生成流水线（类型 5 的续传执行器）

背景（issue #114）：简单图片任务在创建时由 ``web/routes/image_routes.py``
同步直调上游（一次 HTTP 请求即完成），因此历史实现的「任务类型 → Pipeline」
映射里漏掉了 ``TaskType.IMAGE``。用户在失败卡片上点「重试任务」
（``POST /api/tasks/{id}/resume``）时会落进默认的 ``CreativeVideoPipeline``，
在 ``_execute_step("step_build_scenes")`` 处因为 ``SimpleImageTask`` 没有
``step_build_scenes`` 字段而抛：

    ValueError: "SimpleImageTask" object has no field "step_build_scenes"

本模块补上 IMAGE 对应的流水线：按 ``task_state.json`` 里已落盘的参数
（prompt / system_prompt / size / negative_prompt / reference_images）
重新发起一次图片生成并落盘 ``final_image.png``。走 Pipeline 常规通道的好处是
并发权重、产物清单（manifest）、诊断 traceback、失败消息本地化都与视频类任务
一致，前端「重试任务」按钮对图片任务同样可用。
"""

import logging
import os
import traceback
from typing import Callable, Optional

from core.api.agnes_image import AgnesImageAPI, build_full_image_prompt
from core.config import DEFAULT_IMAGE_MODEL
from core.i18n_backend import translate
from core.pipelines import BasePipeline, PipelineShutdown
from models.task import SimpleImageTask, StepStatus
from utils.network import describe_network_error

logger = logging.getLogger(__name__)

# 图片流水线进度常量（0.0 ~ 1.0）
_PROGRESS_INIT = 0.0
_PROGRESS_GENERATE = 0.2
_PROGRESS_COMPLETED = 1.0
_PROGRESS_FAILED = 0.0

# 结果文件名（与创建路由保持一致，前端预览 / `/api/image/{task_id}` 依赖）
OUTPUT_FILENAME = "final_image.png"


class SimpleImagePipeline(BasePipeline):
    """简单图片生成流水线（续传 / 重试入口）。

    步骤：读取落盘参数 → 调用 Agnes Image API → 保存图片 → 标记完成。
    与视频类流水线一样支持失败重试（``resume``）与用户停止。
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: str = None,
        image_model: str = DEFAULT_IMAGE_MODEL,
        progress_callback: Optional[Callable] = None,
        shutdown_event=None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.image_api = AgnesImageAPI(api_key=api_key, model=image_model)

    async def run(self, state: SimpleImageTask) -> str:
        """执行（或重试）图片生成。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", self._t("progress.image.start"), _PROGRESS_INIT)

        try:
            image_path = await self._generate()
        except PipelineShutdown:
            logger.info("[Image] Task %s stopped by user", self.task_id)
            await self._emit(
                "error", "failed",
                self._t("task.interrupted_resumable"),
                _PROGRESS_FAILED,
                preserve_step=True,
            )
            raise
        except Exception as e:
            # 网络 / 域名解析类故障翻译成可自助排查的提示（与创建路由同口径）
            message = describe_network_error(e, lang=self._ui_lang()) or str(e)
            failed_step = self._state.current_step if self._state else ""
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(
                status=StepStatus.FAILED,
                error_traceback=traceback.format_exc(),
                current_step=failed_step,
                current_status="failed",
                current_message=message,
            )
            logger.error("[Image] Task %s failed at step '%s': %s", self.task_id, failed_step, e)
            await self._emit(
                "error", "failed", message, _PROGRESS_FAILED, preserve_step=True,
            )
            raise

        self._state.status = StepStatus.COMPLETED
        self._state.final_video_file = image_path
        self.task_manager.update_state(
            status=StepStatus.COMPLETED,
            final_video_file=image_path,
        )
        await self._emit("done", "completed", self._t("progress.image.done"), _PROGRESS_COMPLETED)
        return image_path

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------

    async def _generate(self) -> str:
        """提交一次图片生成并落盘，返回图片绝对路径。"""
        if self._is_shutdown():
            raise PipelineShutdown("stopped before image generation")

        state = self._state
        await self._emit(
            "generate", "running", self._t("progress.image.generating"), _PROGRESS_GENERATE,
        )

        full_prompt = build_full_image_prompt(state.system_prompt, state.prompt)
        output = await self.image_api.generate_single_image(
            prompt=full_prompt,
            reference_image_paths=self._existing_reference_images(),
            size=state.size,
            negative_prompt=state.negative_prompt or None,
        )

        if self._is_shutdown():
            raise PipelineShutdown("stopped after image generation")

        image_path = os.path.join(self.working_dir, OUTPUT_FILENAME)
        try:
            await output.save(image_path)
        except Exception as e:
            reason = describe_network_error(e, lang=self._ui_lang()) or str(e)
            raise RuntimeError(translate("image.save_failed", self._ui_lang(), reason=reason)) from e

        logger.info("[Image] Task %s completed: %s", self.task_id, image_path)
        return image_path

    def _existing_reference_images(self) -> list:
        """过滤掉已被清理的参考图（缺文件时上游会当成坏图直接失败）。"""
        paths = []
        for p in (getattr(self._state, "reference_images", None) or []):
            if p and os.path.exists(p):
                paths.append(p)
            else:
                logger.warning("[Image] Task %s: reference image missing, skipped: %s",
                               self.task_id, p)
        return paths
