"""core.pipelines.manuscript_video -- 稿件长视频生成流水线（类型 3）

用户粘贴长文本稿件 -> 按朗读时长拆段 -> 每段生成视频 prompt -> 视频生成 -> TTS+字幕 -> 拼接。
"""

import asyncio
import logging
import os
import re
from typing import Callable, List, Optional, Tuple

from core.api.agnes_video import AgnesVideoAPI
from core.audio.tts import EdgeTTSEngine, SilentTTSEngine
from core.audio.subtitle import SubtitleGenerator
from core.compositor.concatenator import VideoConcatenator
from core.screenwriter import Screenwriter
from core.task_manager import TaskManager
from core.pipelines import BasePipeline, PipelineShutdown
from models.task import (
    ManuscriptVideoTask,
    ManuscriptParagraph,
    StepStatus,
    AudioConfig,
)

logger = logging.getLogger(__name__)

# Chinese sentence-ending punctuation pattern.
_SENTENCE_END_RE = re.compile(r"(?<=[。！？])")

# Estimated Chinese speech rate: ~4 characters per second.
_CHARS_PER_SEC = 4.0

# Greedy-merge duration thresholds (seconds).
_MAX_SEGMENT_DURATION = 12.0
_MIN_SEGMENT_DURATION = 5.0


class ManuscriptVideoPipeline(BasePipeline):
    """稿件长视频生成流水线。

    将用户提交的长文本稿件拆分为若干段落，每个段落独立生成视频片段，
    再叠加 TTS 旁白和字幕后拼接为最终长视频。

    Pipeline steps:
        1. ``_step_split_text``          -- 按朗读时长拆分文本
        2. ``_step_generate_scene_prompts`` -- 为每段生成英文视频 prompt
        3. ``_step_generate_videos``     -- 调用 Agnes Video API 生成视频
        4. ``_step_audio_subtitle``      -- TTS 旁白 + SRT 字幕
        5. ``_step_concatenate``         -- 拼接为最终视频

    Supports:
        - Resume: 每个步骤在开始前检查是否已完成（通过 step 状态字段和产物文件是否存在）
        - Shutdown: 在步骤之间和耗时操作前检查 ``PipelineShutdown``

    Attributes:
        video_api: Agnes Video API 客户端。
        screenwriter: LLM 编剧客户端。
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
        self.screenwriter = Screenwriter(api_key=api_key)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, state: ManuscriptVideoTask) -> str:
        """执行稿件长视频生成流水线。

        Args:
            state: 稿件长视频任务状态。

        Returns:
            最终拼接视频的文件路径。

        Raises:
            PipelineShutdown: 收到停止信号时抛出。
        """
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", "开始稿件长视频生成...", 0.0)

        try:
            # ── Step 1: 拆分文本 ──────────────────────────────────────
            self._check_shutdown()
            paragraphs = await self._run_step_split_text()

            # ── Step 2: 生成场景 prompt ──────────────────────────────
            self._check_shutdown()
            await self._run_step_generate_scene_prompts(paragraphs)

            # ── Step 3: 生成视频 ─────────────────────────────────────
            self._check_shutdown()
            await self._run_step_generate_videos(paragraphs)

            # ── Step 4: 旁白 + 字幕 ──────────────────────────────────
            self._check_shutdown()
            await self._run_step_audio_subtitle(paragraphs, state.audio_config)

            # ── Step 5: 拼接 ─────────────────────────────────────────
            self._check_shutdown()
            final_video = await self._run_step_concatenate(
                paragraphs, state.audio_config
            )

            # ── 完成 ─────────────────────────────────────────────────
            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = final_video
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=final_video,
            )
            await self._emit(
                "done", "completed", "稿件长视频生成完成!", 1.0,
                {"final_video": final_video},
            )
            return final_video

        except PipelineShutdown as exc:
            logger.info(f"[Manuscript] Shutdown: {exc}")
            await self._emit(
                "error", "failed", "任务已被中断，可从任务列表续传", 0.0,
            )
            raise
        except Exception as exc:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(exc), 0.0)
            raise

    # ------------------------------------------------------------------
    # Step runners (wrap step logic + persistence + progress)
    # ------------------------------------------------------------------

    async def _run_step_split_text(self) -> List[ManuscriptParagraph]:
        """运行 Step 1: 文本拆分，带 resume 支持。"""
        if self._state.step_split == StepStatus.COMPLETED and self._state.paragraphs:
            logger.info("[Manuscript] Step 1 (split_text): already completed, resuming")
            return self._state.paragraphs

        self.task_manager.update_step("step_split", StepStatus.RUNNING)
        await self._emit("split_text", "running", "拆分文本段落...", 0.02)

        paragraphs = self._step_split_text(self._state.manuscript_text)
        self._state.paragraphs = paragraphs
        self.task_manager.update_state(
            paragraphs=paragraphs,
        )
        self.task_manager.update_step("step_split", StepStatus.COMPLETED)

        await self._emit(
            "split_text", "completed",
            f"文本已拆分为 {len(paragraphs)} 段", 0.05,
        )
        return paragraphs

    async def _run_step_generate_scene_prompts(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """运行 Step 2: 场景 prompt 生成，带 resume 支持。"""
        if self._state.step_scene_prompts == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 2 (scene_prompts): already completed, resuming")
            return

        self.task_manager.update_step("step_scene_prompts", StepStatus.RUNNING)
        await self._emit("scene_prompts", "running", "生成场景描述...", 0.05)

        await self._step_generate_scene_prompts(paragraphs)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_scene_prompts", StepStatus.COMPLETED)
        await self._emit("scene_prompts", "completed", "场景描述生成完成", 0.15)

    async def _run_step_generate_videos(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """运行 Step 3: 视频生成，带 resume 支持。"""
        if self._state.step_video_generation == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 3 (video_generation): already completed, resuming")
            return

        self.task_manager.update_step("step_video_generation", StepStatus.RUNNING)
        await self._emit("video_gen", "running", "生成段落视频...", 0.15)

        await self._step_generate_videos(paragraphs)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_video_generation", StepStatus.COMPLETED)
        await self._emit("video_gen", "completed", "所有段落视频已生成", 0.60)

    async def _run_step_audio_subtitle(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
    ) -> None:
        """运行 Step 4: TTS 旁白 + 字幕，带 resume 支持。"""
        if self._state.step_audio_subtitle == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 4 (audio_subtitle): already completed, resuming")
            return

        self.task_manager.update_step("step_audio_subtitle", StepStatus.RUNNING)
        await self._emit("audio_subtitle", "running", "生成旁白和字幕...", 0.60)

        await self._step_audio_subtitle(paragraphs, audio_config)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_audio_subtitle", StepStatus.COMPLETED)
        await self._emit("audio_subtitle", "completed", "旁白和字幕已生成", 0.80)

    async def _run_step_concatenate(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
    ) -> str:
        """运行 Step 5: 视频拼接，带 resume 支持。"""
        if self._state.step_concatenation == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 5 (concatenation): already completed, resuming")
            if self._state.final_video_file:
                return self._state.final_video_file

        self.task_manager.update_step("step_concatenation", StepStatus.RUNNING)
        await self._emit("concatenate", "running", "拼接最终视频...", 0.80)

        final_video = await self._step_concatenate(paragraphs, audio_config)

        self.task_manager.update_state(final_video_file=final_video)
        self.task_manager.update_step("step_concatenation", StepStatus.COMPLETED)
        await self._emit("concatenate", "completed", "视频拼接完成", 0.95)
        return final_video

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _step_split_text(self, text: str) -> List[ManuscriptParagraph]:
        """将长文本按朗读时长拆分为段落列表。

        拆分策略:
            1. 先按换行符 (``\\n``) 切分为粗段落。
            2. 每个粗段落再按中文句末标点 (``。！？``) 切分为候选句。
            3. 对候选句进行贪心合并：累积时长 <= 12s，最短 >= 5s。
            4. 短句 (< 5s) 合并到前一个段落；长句 (> 12s) 保持原样不拆分。

        Args:
            text: 用户输入的稿件原文。

        Returns:
            带 ``index``、``text`` 和估算时长的段落列表。
        """
        # Resume: if paragraphs already populated, return them directly.
        if self._state.paragraphs:
            logger.info(
                "[Manuscript] split_text: %d paragraphs already exist, resuming",
                len(self._state.paragraphs),
            )
            return self._state.paragraphs

        logger.info("[Manuscript] split_text: splitting %d chars...", len(text))

        # Step 1: split by newline.
        raw_blocks = [b.strip() for b in text.split("\n") if b.strip()]

        # Step 2: further split each block by Chinese sentence-ending punctuation.
        candidate_sentences: List[str] = []
        for block in raw_blocks:
            parts = _SENTENCE_END_RE.split(block)
            for part in parts:
                part = part.strip()
                if part:
                    candidate_sentences.append(part)

        if not candidate_sentences:
            logger.warning("[Manuscript] split_text: no sentences found in text")
            return []

        # Step 3: greedy merge.
        merged: List[str] = []
        current_text = ""
        current_duration = 0.0

        for sentence in candidate_sentences:
            sentence_duration = len(sentence) / _CHARS_PER_SEC

            if not current_text:
                # Starting a new group.
                current_text = sentence
                current_duration = sentence_duration
                continue

            prospective_duration = current_duration + sentence_duration

            if prospective_duration <= _MAX_SEGMENT_DURATION:
                # Merge into current group.
                current_text += sentence
                current_duration = prospective_duration
            else:
                # Flush current group.
                merged.append(current_text)
                current_text = sentence
                current_duration = sentence_duration

        # Flush remaining.
        if current_text:
            merged.append(current_text)

        # Step 4: post-process -- merge short trailing segments into previous.
        final_texts: List[str] = []
        for segment in merged:
            seg_duration = len(segment) / _CHARS_PER_SEC
            if seg_duration < _MIN_SEGMENT_DURATION and final_texts:
                # Merge into previous paragraph.
                final_texts[-1] += segment
            else:
                # Long sentences (> 12s) are accepted as-is (don't split).
                final_texts.append(segment)

        # Build ManuscriptParagraph list.
        paragraphs: List[ManuscriptParagraph] = []
        for idx, para_text in enumerate(final_texts):
            est_duration = len(para_text) / _CHARS_PER_SEC
            para = ManuscriptParagraph(
                index=idx,
                text=para_text,
            )
            paragraphs.append(para)
            logger.info(
                "[Manuscript] Paragraph %d: %d chars, ~%.1fs",
                idx, len(para_text), est_duration,
            )

        logger.info(
            "[Manuscript] split_text: %d paragraphs created", len(paragraphs),
        )
        return paragraphs

    async def _step_generate_scene_prompts(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """为每个段落生成英文视频场景描述 prompt。

        调用 ``Screenwriter.generate_scene_prompt_for_paragraph(text, style)``
        将中文段落文本转换为适合 AI 视频生成的英文 prompt。

        Args:
            paragraphs: 段落列表（就地修改 ``scene_prompt`` 字段）。
        """
        total = len(paragraphs)
        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            # Resume: skip paragraphs that already have a scene_prompt.
            if para.scene_prompt:
                logger.info(
                    "[Manuscript] scene_prompt: paragraph %d already has prompt, skipping",
                    para.index,
                )
                continue

            logger.info(
                "[Manuscript] scene_prompt: generating for paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "scene_prompts", "running",
                f"生成场景描述 {i + 1}/{total}",
                0.05 + 0.10 * (i / max(total, 1)),
            )

            prompt = await asyncio.to_thread(
                self.screenwriter.generate_scene_prompt_for_paragraph,
                para.text,
                "",  # style -- ManuscriptVideoTask has no style field; pass empty.
            )
            para.scene_prompt = prompt.strip()

            # Persist after each paragraph for crash recovery.
            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Manuscript] scene_prompt %d: %s...",
                para.index, para.scene_prompt[:80],
            )

    async def _step_generate_videos(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """为每个段落调用 Agnes Video API 生成视频。

        每段视频保存到 ``{working_dir}/para_{index}/video.mp4``。

        Args:
            paragraphs: 段落列表（就地修改 ``video_file`` 字段）。
        """
        total = len(paragraphs)
        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            para_dir = os.path.join(self.working_dir, f"para_{para.index}")
            video_path = os.path.join(para_dir, "video.mp4")

            # Resume: skip if video file already exists on disk.
            if os.path.exists(video_path):
                para.video_file = video_path
                logger.info(
                    "[Manuscript] video: paragraph %d already exists, skipping",
                    para.index,
                )
                continue

            if not para.scene_prompt:
                logger.warning(
                    "[Manuscript] video: paragraph %d has no scene_prompt, skipping",
                    para.index,
                )
                continue

            os.makedirs(para_dir, exist_ok=True)

            logger.info(
                "[Manuscript] video: submitting paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "video_gen", "running",
                f"提交视频 {i + 1}/{total}",
                0.15 + 0.45 * (i / max(total, 1)),
            )

            video_id = await self.video_api.submit_video(
                prompt=para.scene_prompt,
                duration=self._state.video_duration,
                width=self._state.video_width,
                height=self._state.video_height,
            )

            await self._emit(
                "video_gen", "running",
                f"等待视频生成 {i + 1}/{total} ({video_id[:16]}...)",
                0.15 + 0.45 * (i / max(total, 1)),
            )

            video_output = await self.video_api.wait_for_video(video_id)
            video_output.save(video_path)

            para.video_file = video_path
            # Persist after each video for crash recovery.
            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Manuscript] video: paragraph %d saved → %s",
                para.index, video_path,
            )

    async def _step_audio_subtitle(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
    ) -> None:
        """为每个段落生成 TTS 旁白音频和 SRT 字幕文件。

        - 如果 ``audio_config.enabled`` 为 True，使用 ``EdgeTTSEngine`` 生成语音。
        - 否则使用 ``SilentTTSEngine`` 生成静音占位音频。
        - 统一通过 ``SubtitleGenerator.cues_to_srt`` 生成 SRT 字幕。

        Args:
            paragraphs: 段落列表（就地修改 ``narration_audio`` 和 ``subtitle_srt`` 字段）。
            audio_config: 音频和字幕配置。
        """
        total = len(paragraphs)
        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()

        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            para_dir = os.path.join(self.working_dir, f"para_{para.index}")
            audio_path = os.path.join(para_dir, "narration.mp3")
            srt_path = os.path.join(para_dir, "narration.srt")

            # Resume: skip if audio file already exists on disk.
            if os.path.exists(audio_path):
                para.narration_audio = audio_path
                if os.path.exists(srt_path):
                    para.subtitle_srt = srt_path
                logger.info(
                    "[Manuscript] audio: paragraph %d already exists, skipping",
                    para.index,
                )
                continue

            os.makedirs(para_dir, exist_ok=True)

            logger.info(
                "[Manuscript] audio: generating for paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "audio_subtitle", "running",
                f"生成旁白 {i + 1}/{total}",
                0.60 + 0.20 * (i / max(total, 1)),
            )

            if audio_config.enabled:
                audio_result, sub_maker = await edge_tts.generate(
                    text=para.text,
                    output_path=audio_path,
                    voice=audio_config.voice,
                    rate=audio_config.rate,
                )
            else:
                audio_result, sub_maker = await silent_tts.generate(
                    text=para.text,
                    output_path=audio_path,
                )

            para.narration_audio = audio_result

            # Generate SRT from cues / SubMaker.
            SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
            para.subtitle_srt = srt_path

            # Persist after each paragraph for crash recovery.
            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Manuscript] audio: paragraph %d → %s + %s",
                para.index, audio_path, srt_path,
            )

    async def _step_concatenate(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
    ) -> str:
        """将所有段落视频、旁白、字幕拼接为最终长视频。

        Args:
            paragraphs: 已完成视频/音频/字幕生成的段落列表。
            audio_config: 音频和字幕样式配置。

        Returns:
            最终输出视频的文件路径。
        """
        output_path = os.path.join(self.working_dir, "final_video.mp4")

        # Resume: if final video already exists, return it directly.
        if os.path.exists(output_path):
            logger.info("[Manuscript] concatenate: final video already exists, skipping")
            return output_path

        # Build clip tuples: (video_path, audio_path, srt_path | None).
        clip_tuples: List[Tuple[str, str, Optional[str]]] = []
        for para in paragraphs:
            if not para.video_file:
                logger.warning(
                    "[Manuscript] concatenate: paragraph %d has no video, skipping",
                    para.index,
                )
                continue
            srt = para.subtitle_srt if para.subtitle_srt else None
            clip_tuples.append((para.video_file, para.narration_audio, srt))

        if not clip_tuples:
            raise RuntimeError("[Manuscript] concatenate: no valid clips to concatenate")

        logger.info(
            "[Manuscript] concatenate: assembling %d clips...", len(clip_tuples),
        )
        await self._emit("concatenate", "running", f"拼接 {len(clip_tuples)} 段视频...", 0.85)

        await asyncio.to_thread(
            VideoConcatenator.concat_with_audio,
            clip_tuples,
            output_path,
            audio_config.subtitle_style,
        )

        logger.info("[Manuscript] concatenate: final video → %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _check_shutdown(self) -> None:
        """检查是否需要停止流水线。

        Raises:
            PipelineShutdown: 如果收到停止信号。
        """
        if self._is_shutdown():
            raise PipelineShutdown("Pipeline shutdown requested")
