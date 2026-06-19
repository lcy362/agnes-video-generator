"""core.pipelines.manuscript_video -- 稿件长视频生成流水线（类型 3）

用户粘贴长文本稿件 -> 按朗读时长拆段 -> 每段生成视频 prompt -> 视频生成 -> TTS+字幕 -> 拼接。
"""

import asyncio
import json
import logging
import math
import os
import re
import subprocess
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
    SubtitleConfig,
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

            # ── Step 4: 音频生成 ─────────────────────────────────────
            self._check_shutdown()
            sub_maker = await self._run_step_audio(paragraphs, state.audio_config)

            # ── Step 5: 字幕生成 ─────────────────────────────────────
            self._check_shutdown()
            await self._run_step_subtitle(paragraphs, state.audio_config, state.subtitle_config, sub_maker)

            # ── Step 6: 拼接 ─────────────────────────────────────────
            self._check_shutdown()
            final_video = await self._run_step_concatenate(
                paragraphs, state.audio_config, state.subtitle_config
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

    async def _run_step_audio(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
    ) -> object:
        """运行 Step 4: TTS 旁白，带 resume 支持。返回 sub_maker 供字幕步骤使用。"""
        if self._state.step_audio == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 4 (audio): already completed, resuming")
            return None
        if (self._state.step_audio == StepStatus.PENDING
                and self._state.step_audio_subtitle == StepStatus.COMPLETED):
            logger.info("[Manuscript] Step 4 (audio): v2.0 step_audio_subtitle completed, resuming")
            self._state.step_audio = StepStatus.COMPLETED
            self.task_manager.update_step("step_audio", StepStatus.COMPLETED)
            return None

        self.task_manager.update_step("step_audio", StepStatus.RUNNING)
        await self._emit("audio", "running", "生成旁白...", 0.60)

        sub_maker = await self._step_audio(paragraphs, audio_config)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_audio", StepStatus.COMPLETED)
        await self._emit("audio", "completed", "旁白已生成", 0.75)
        return sub_maker

    async def _run_step_subtitle(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
        subtitle_config: SubtitleConfig,
        sub_maker: object = None,
    ) -> None:
        """运行 Step 5: 字幕生成，带 resume 支持。"""
        if self._state.step_subtitle == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 5 (subtitle): already completed, resuming")
            return
        if (self._state.step_subtitle == StepStatus.PENDING
                and self._state.step_audio_subtitle == StepStatus.COMPLETED):
            logger.info("[Manuscript] Step 5 (subtitle): v2.0 step_audio_subtitle completed, resuming")
            self._state.step_subtitle = StepStatus.COMPLETED
            self.task_manager.update_step("step_subtitle", StepStatus.COMPLETED)
            return

        self.task_manager.update_step("step_subtitle", StepStatus.RUNNING)
        await self._emit("subtitle", "running", "生成字幕...", 0.75)

        await self._step_subtitle(paragraphs, audio_config, subtitle_config, sub_maker)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_subtitle", StepStatus.COMPLETED)
        await self._emit("subtitle", "completed", "字幕已生成", 0.80)

    async def _run_step_concatenate(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
        subtitle_config: SubtitleConfig,
    ) -> str:
        """运行 Step 6: 视频拼接，带 resume 支持。"""
        if self._state.step_concatenation == StepStatus.COMPLETED:
            logger.info("[Manuscript] Step 6 (concatenation): already completed, resuming")
            if self._state.final_video_file:
                return self._state.final_video_file

        self.task_manager.update_step("step_concatenation", StepStatus.RUNNING)
        await self._emit("concatenate", "running", "拼接最终视频...", 0.80)

        final_video = await self._step_concatenate(paragraphs, audio_config, subtitle_config)

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

    # ------------------------------------------------------------------
    # Curl / task persistence helpers (per-paragraph)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_curl(video_id: str) -> str:
        return (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"'
        )

    def _save_para_task(self, para_dir: str, video_id: str) -> None:
        os.makedirs(para_dir, exist_ok=True)
        task_file = os.path.join(para_dir, "task.json")
        with open(task_file, "w") as f:
            json.dump({"video_id": video_id}, f, indent=2)
        curl_file = os.path.join(para_dir, "curl.sh")
        with open(curl_file, "w") as f:
            f.write(self._make_curl(video_id) + "\n")

    def _load_para_task(self, para_dir: str) -> Optional[str]:
        task_file = os.path.join(para_dir, "task.json")
        if os.path.exists(task_file):
            try:
                with open(task_file, "r") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception as e:
                logger.debug(f"[Manuscript] Failed to load cached task.json: {e}")
        return None

    async def _step_generate_videos(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """为每个段落调用 Agnes Video API 生成视频（两阶段并行）。

        Phase 1: 批量提交所有视频请求（服务端并行生成）。
        Phase 2: 逐个轮询等待完成并下载。

        每段视频保存到 ``{working_dir}/para_{index}/video.mp4``，
        同时记录 video_id 和 curl 命令到 ``task.json`` / ``curl.sh``。

        Args:
            paragraphs: 段落列表（就地修改 ``video_file``、``video_id`` 字段）。
        """
        _SUBMIT_RETRIES = 3
        _WAIT_RETRIES = 3
        total = len(paragraphs)

        # ── Phase 1: 批量提交 ────────────────────────────────────────────
        pending: list[tuple[int, str, str]] = []  # (para_index, video_id, video_path)

        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            para_dir = os.path.join(self.working_dir, f"para_{para.index}")
            video_path = os.path.join(para_dir, "video.mp4")

            # 已有视频文件 → 跳过
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

            # 续传：复用已提交的 video_id
            saved_video_id = self._load_para_task(para_dir)
            if saved_video_id:
                para.video_id = saved_video_id
                logger.info(
                    "[Manuscript] video: paragraph %d resuming video_id %s...",
                    para.index, saved_video_id[:16],
                )
                pending.append((para.index, saved_video_id, video_path))
                continue

            # 提交新视频
            logger.info(
                "[Manuscript] video: submitting paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "video_gen", "running",
                f"提交视频 {i + 1}/{total}",
                0.15 + 0.20 * (i / max(total, 1)),
            )

            para_duration = max(int(math.ceil(len(para.text) / _CHARS_PER_SEC)), 3)
            logger.info(
                "[Manuscript] video: paragraph %d estimated duration %.1fs (chars=%d)",
                para.index, para_duration, len(para.text),
            )

            for retry in range(_SUBMIT_RETRIES):
                try:
                    video_id = await self.video_api.submit_video(
                        prompt=para.scene_prompt,
                        duration=para_duration,
                        width=self._state.video_width,
                        height=self._state.video_height,
                    )
                    para.video_id = video_id
                    self._save_para_task(para_dir, video_id)
                    pending.append((para.index, video_id, video_path))
                    break
                except Exception as e:
                    if retry < _SUBMIT_RETRIES - 1:
                        delay = 15 * (retry + 1)
                        logger.warning(
                            "[Manuscript] video: paragraph %d submit failed "
                            "(%s), retry %d/%d in %ds...",
                            para.index, e, retry + 1, _SUBMIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

        # 提交完毕后持久化（断点续传可恢复 video_id）
        self.task_manager.update_state(paragraphs=paragraphs)
        logger.info(
            "[Manuscript] video: all %d paragraphs submitted, now waiting...",
            len(pending),
        )

        # ── Phase 2: 逐个等待完成 ────────────────────────────────────────
        for j, (para_idx, video_id, video_path) in enumerate(pending):
            self._check_shutdown()

            para = paragraphs[para_idx]
            await self._emit(
                "video_gen", "running",
                f"等待视频 {j + 1}/{len(pending)} ({video_id[:16]}...)",
                0.35 + 0.25 * (j / max(len(pending), 1)),
            )

            for retry in range(_WAIT_RETRIES):
                try:
                    video_output = await self.video_api.wait_for_video(video_id)
                    video_output.save(video_path)
                    break
                except Exception as e:
                    if retry < _WAIT_RETRIES - 1:
                        delay = 20 * (retry + 1)
                        logger.warning(
                            "[Manuscript] video: paragraph %d wait failed "
                            "(%s), retry %d/%d in %ds...",
                            para_idx, e, retry + 1, _WAIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

            para.video_file = video_path
            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Manuscript] video: paragraph %d saved → %s (video_id=%s)",
                para_idx, video_path, video_id[:16],
            )

    async def _step_audio(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
    ) -> object:
        """生成整段连续 TTS 音频。

        将所有段落文本拼接成一篇完整稿件 → 单次 edge_tts 调用 →
        一条连贯音频 + SubMaker（含全篇词级时间戳）。

        Args:
            paragraphs: 段落列表。
            audio_config: 音频配置。

        Returns:
            SubMaker cues object (or None if silent/disabled).
        """
        full_text = "\n\n".join(p.text for p in paragraphs if p.text)
        if not full_text:
            logger.warning("[Manuscript] audio: empty full text, skipping")
            return None

        audio_path = os.path.join(self.working_dir, "full_narration.mp3")

        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[Manuscript] audio: file already exists, skipping")
            return None

        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()

        await self._emit(
            "audio", "running",
            f"生成整段旁白 ({len(full_text)} 字)...",
            0.60,
        )

        sub_maker = None
        if audio_config.enabled:
            try:
                audio_result, sub_maker = await edge_tts.generate(
                    text=full_text,
                    output_path=audio_path,
                    voice=audio_config.voice,
                    rate=audio_config.rate,
                )
            except RuntimeError as e:
                logger.warning(f"[Manuscript] EdgeTTS failed, falling back to silent: {e}")
                audio_result, sub_maker = await silent_tts.generate(
                    text=full_text,
                    output_path=audio_path,
                )
        else:
            audio_result, sub_maker = await silent_tts.generate(
                text=full_text,
                output_path=audio_path,
            )

        self._state.combined_audio = audio_result
        self.task_manager.update_state(combined_audio=audio_result)
        logger.info("[Manuscript] audio: combined → %s", audio_path)
        return sub_maker

    async def _step_subtitle(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
        subtitle_config: SubtitleConfig,
        sub_maker: object = None,
    ) -> None:
        """生成整段 SRT 字幕。

        如果 TTS SubMaker cues 可用则从中生成细粒度 SRT，
        否则从纯文本估算时间生成 SRT。

        Args:
            paragraphs: 段落列表。
            audio_config: 音频配置。
            subtitle_config: 字幕配置。
            sub_maker: TTS SubMaker cues (optional).
        """
        full_text = "\n\n".join(p.text for p in paragraphs if p.text)
        if not full_text:
            logger.warning("[Manuscript] subtitle: empty full text, skipping")
            return

        srt_path = os.path.join(self.working_dir, "full_subtitle.srt")

        if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
            self._state.combined_subtitle = srt_path
            logger.info("[Manuscript] subtitle: file already exists, skipping")
            return

        await self._emit(
            "subtitle", "running",
            f"生成整段字幕 ({len(full_text)} 字, {len(paragraphs)} 段)...",
            0.75,
        )

        # ── 用实际音频时长替代估算值，确保字幕与音频同步 ──
        actual_audio_dur = 0.0
        audio_path = self._state.combined_audio or ""
        if audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", audio_path],
                    capture_output=True, text=True, timeout=15,
                )
                actual_audio_dur = float(r.stdout.strip())
            except Exception:
                pass

        num_paras = len(paragraphs)
        if subtitle_config.enabled and num_paras > 1:
            # ── v3.0: 段落感知字幕生成 ──
            # 每段的文本 + 实际音频时长比例分摊 → 场景感知细粒度 SRT
            para_texts = [p.text for p in paragraphs if p.text]
            para_durations = []
            total_est = 0.0
            for p in paragraphs:
                if p.text:
                    dur = max(len(p.text) / _CHARS_PER_SEC, 2.0)
                else:
                    dur = 5.0
                para_durations.append(dur)
                total_est += dur

            if actual_audio_dur > 0 and total_est > 0:
                scale = actual_audio_dur / total_est
                para_durations = [d * scale for d in para_durations]
                logger.info(f"[Manuscript] SRT durations scaled by {scale:.3f} (audio={actual_audio_dur:.2f}s, est={total_est:.2f}s)")

            srt_content = SubtitleGenerator._generate_scene_aware_srt(
                para_texts, para_durations,
                word_cues=sub_maker if sub_maker is not None else None,
            )
            if srt_content.strip():
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                entry_count = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 0
                logger.info(f"[Manuscript] Scene-aware SRT generated: {entry_count} entries across {num_paras} paragraphs")
            else:
                subtitle_config.enabled = False
        elif subtitle_config.enabled and sub_maker is not None:
            SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
        elif subtitle_config.enabled:
            total_duration = actual_audio_dur if actual_audio_dur > 0 else len(full_text) / _CHARS_PER_SEC
            SubtitleGenerator.text_to_srt(full_text, srt_path, total_duration)
        else:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("")

        # Phase 2: LLM 智能样式 — 仅在字幕启用且 style_mode == "llm" 时调用
        if subtitle_config.enabled and subtitle_config.style.style_mode == "llm":
            styles_path = os.path.join(self.working_dir, "subtitle_styles.json")
            if not os.path.exists(styles_path) or os.path.getsize(styles_path) == 0:
                try:
                    styles = await asyncio.to_thread(
                        self.screenwriter.generate_subtitle_styles,
                        srt_path=srt_path,
                        video_width=self._state.video_width,
                        video_height=self._state.video_height,
                        style_hints=subtitle_config.style.style_hints,
                    )
                    with open(styles_path, "w", encoding="utf-8") as f:
                        json.dump(styles, f, ensure_ascii=False, indent=2)
                    self._state.subtitle_styles_path = styles_path
                    self.task_manager.update_state(subtitle_styles_path=styles_path)
                    logger.info(f"[Manuscript] LLM subtitle styles saved: {styles_path} ({len(styles)} entries)")
                except Exception as e:
                    logger.warning(f"[Manuscript] LLM subtitle styles failed: {e}, falling back to fixed")
                    self._state.subtitle_styles_path = ""
                    self.task_manager.update_state(subtitle_styles_path="")

        self._state.combined_subtitle = srt_path
        self.task_manager.update_state(combined_subtitle=srt_path)
        logger.info("[Manuscript] subtitle: combined → %s", srt_path)

    async def _step_concatenate(
        self,
        paragraphs: List[ManuscriptParagraph],
        audio_config: AudioConfig,
        subtitle_config: SubtitleConfig,
    ) -> str:
        """先拼接所有段落视频，再统一叠加整段音频 + 整段字幕。

        不再逐段 ``_synthesize_single``（避免 padding 累积），
        而是参考 MoneyPrinterTurbo 方案：
        1. 把所有视频按段落顺序拼接成一条完整时间轴
        2. 挂载整段 ``combined_audio``（全稿 TTS）
        3. 叠加整段 ``combined_subtitle``（全稿 SRT，时间轴对齐音频）

        Args:
            paragraphs: 已完成视频生成的段落列表。
            audio_config: 音频配置。
            subtitle_config: 字幕配置。

        Returns:
            最终输出视频的文件路径。
        """
        output_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(output_path):
            logger.info("[Manuscript] concatenate: final video already exists, skipping")
            return output_path

        video_paths = [
            p.video_file for p in paragraphs
            if p.video_file and os.path.exists(p.video_file)
        ]
        if not video_paths:
            raise RuntimeError("[Manuscript] concatenate: no valid videos to concatenate")

        has_audio = self._state.audio_config.enabled and bool(self._state.combined_audio)
        has_subtitle = subtitle_config.enabled and bool(self._state.combined_subtitle)

        # Phase 2: LLM 样式 JSON 路径
        styles_path = self._state.subtitle_styles_path or ""
        if styles_path and not os.path.exists(styles_path):
            styles_path = ""

        logger.info(
            "[Manuscript] concatenate: %d videos + audio=%s + subtitle=%s → %s",
            len(video_paths), has_audio, has_subtitle, output_path,
        )

        if has_audio or has_subtitle:
            await self._emit(
                "concatenate", "running",
                f"拼接 {len(video_paths)} 段视频+音频+字幕...", 0.80,
            )
            await asyncio.to_thread(
                VideoConcatenator.concat_videos_with_audio_overlay,
                video_paths=video_paths,
                audio_path=self._state.combined_audio or "",
                srt_path=self._state.combined_subtitle if has_subtitle else None,
                output_path=output_path,
                subtitle_style=subtitle_config.style if has_subtitle else None,
                subtitle_styles_path=styles_path if styles_path else None,
            )
        else:
            await self._emit(
                "concatenate", "running",
                f"拼接 {len(video_paths)} 段视频（无音频字幕）...", 0.80,
            )
            await asyncio.to_thread(
                VideoConcatenator.concat_videos, video_paths, output_path
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
