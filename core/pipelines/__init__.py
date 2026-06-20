"""core.pipelines — 业务流水线层

BasePipeline 抽象基类 + 四种流水线导出。
"""

import asyncio
import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from core.task_manager import TaskManager
from models.task import BaseTaskState, SubtitleConfig, SubtitleStyle

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

    # ==================================================================
    # 通用工具方法
    # ==================================================================

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

    @staticmethod
    def get_audio_duration(audio_path: str) -> float:
        """通过 ffprobe 获取音频文件时长（秒），失败返回 0.0。"""
        if not audio_path or not os.path.exists(audio_path):
            return 0.0
        if os.path.getsize(audio_path) == 0:
            return 0.0
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True, timeout=15,
            )
            return float(r.stdout.strip())
        except Exception:
            return 0.0

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
        if subtitle_config.enabled and num_segments > 1:
            # 按音频时长等比缩放段落时长
            total_est = sum(segment_durations)
            scaled_durations = list(segment_durations)
            if actual_audio_dur > 0 and total_est > 0:
                scale = actual_audio_dur / total_est
                scaled_durations = [d * scale for d in scaled_durations]
                logger.info(
                    "[Subtitle] durations scaled by %.3f (audio=%.2fs, est=%.2fs)",
                    scale, actual_audio_dur, total_est,
                )

            srt_content = SubtitleGenerator._generate_scene_aware_srt(
                segment_texts, scaled_durations,
                word_cues=sub_maker if sub_maker is not None else None,
            )
            if srt_content.strip():
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
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
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("")

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
                    with open(sp, "w", encoding="utf-8") as f:
                        json.dump(styles, f, ensure_ascii=False, indent=2)
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
