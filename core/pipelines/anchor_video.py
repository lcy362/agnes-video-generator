"""core.pipelines.anchor_video -- 数字人口播流水线（类型 4 / Phase 3 / v3.1 方案 B）

分段生成 + 口型近似匹配方案：
    1. 生成主播形象图（t2i / i2i）
    2. 按朗读时长拆分稿件（复用稿件视频拆段逻辑，5-12 秒/段）
    3. 为每段生成不同的英文动态 prompt（LLM 驱动，包含口型/手势描述）
    4. 逐段 i2v 生成不同动作的视频片段（以主播形象图为输入）
    5. TTS 读稿音频（整段连续）
    6. 字幕生成 + LLM 智能定位
    7. 拼接所有片段 + 叠加音频 + 字幕
"""

import asyncio
import json
import logging
import math
import os
import re
import subprocess
from typing import Callable, List, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
from core.audio.subtitle import SubtitleGenerator
from core.audio.tts import EdgeTTSEngine, SilentTTSEngine
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import BasePipeline, PipelineShutdown
from core.screenwriter import Screenwriter
from models.task import (
    AnchorVideoTask,
    ManuscriptParagraph,
    StepStatus,
    AudioConfig,
    SubtitleConfig,
    SubtitleStyle,
)

logger = logging.getLogger(__name__)

# 默认主播 prompt
_DEFAULT_ANCHOR_PROMPT = (
    "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中，"
    "面带微笑，正面半身照，高清画质，专业灯光"
)

# ── 拆段常量（复用稿件视频逻辑）──
_SENTENCE_END_RE = re.compile(r"(?<=[。！？])")
_CHARS_PER_SEC = 4.0
_MAX_SEGMENT_DURATION = 12.0
_MIN_SEGMENT_DURATION = 5.0


class AnchorPipeline(BasePipeline):
    """数字人口播视频生成流水线（v3.1 方案 B：分段生成）。

    7 步流程：
        1. 生成主播形象图
        2. 拆分稿件为 5-12 秒段落
        3. 为每段生成英文动态 prompt（含口型/手势描述）
        4. 逐段 i2v 生成不同动作的视频片段
        5. TTS 读稿音频（整段连续）
        6. 字幕生成 + LLM 定位
        7. 拼接所有片段 + 叠加音频 + 字幕
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: Optional[str] = None,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.image_generator = AgnesImageAPI(api_key=api_key, model=image_model)
        self.video_generator = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_generator.shutdown_event = shutdown_event
        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self._state: Optional[AnchorVideoTask] = None

    @property
    def state(self) -> Optional[AnchorVideoTask]:
        return self._state

    # ==================================================================
    # Main Run
    # ==================================================================

    async def run(self, state: AnchorVideoTask) -> str:
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", "开始数字人口播生成（分段模式）...", 0.0)

        try:
            # ── Step 1: 生成主播形象图 ────────────────────────────────
            self._check_shutdown()
            anchor_image_path = await self._step_generate_anchor()

            # ── Step 2: 拆分稿件 ─────────────────────────────────────
            self._check_shutdown()
            paragraphs = await self._run_step_split_text()

            # ── Step 3: 为每段生成动态 prompt ─────────────────────────
            self._check_shutdown()
            await self._run_step_generate_clip_prompts(paragraphs)

            # ── Step 4: 逐段 i2v 生成视频片段 ────────────────────────
            self._check_shutdown()
            await self._run_step_generate_clips(paragraphs, anchor_image_path)

            # ── Step 5: TTS 读稿音频 ─────────────────────────────────
            self._check_shutdown()
            sub_maker = await self._run_step_audio()

            # ── Step 6: 字幕生成 ─────────────────────────────────────
            self._check_shutdown()
            await self._run_step_subtitle(sub_maker)

            # ── Step 7: 拼接 ────────────────────────────────────────
            self._check_shutdown()
            final_video = await self._run_step_concatenate(paragraphs)

            # ── 完成 ────────────────────────────────────────────────
            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = final_video
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=final_video,
            )
            await self._emit(
                "done", "completed", "数字人口播生成完成!", 1.0,
                {"final_video": final_video},
            )
            return final_video

        except PipelineShutdown as e:
            logger.info(f"[Anchor] Shutdown: {e}")
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise

    # ==================================================================
    # Step runners (wrap step logic + persistence + progress)
    # ==================================================================

    async def _run_step_split_text(self) -> List[ManuscriptParagraph]:
        """运行 Step 2: 文本拆分，带 resume 支持。"""
        if self._state.step_split == StepStatus.COMPLETED and self._state.paragraphs:
            logger.info("[Anchor] Step 2 (split_text): already completed, resuming")
            return self._state.paragraphs

        self.task_manager.update_step("step_split", StepStatus.RUNNING)
        await self._emit("split_text", "running", "拆分口播稿件...", 0.10)

        paragraphs = self._step_split_text(self._state.script_text)
        self._state.paragraphs = paragraphs
        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_split", StepStatus.COMPLETED)

        await self._emit(
            "split_text", "completed",
            f"稿件已拆分为 {len(paragraphs)} 段", 0.12,
        )
        return paragraphs

    async def _run_step_generate_clip_prompts(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """运行 Step 3: 为每段生成动态 prompt，带 resume 支持。"""
        if self._state.step_clip_prompts == StepStatus.COMPLETED:
            logger.info("[Anchor] Step 3 (clip_prompts): already completed, resuming")
            return

        self.task_manager.update_step("step_clip_prompts", StepStatus.RUNNING)
        await self._emit("clip_prompts", "running", "生成段落动态描述...", 0.12)

        await self._step_generate_clip_prompts(paragraphs)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_clip_prompts", StepStatus.COMPLETED)
        await self._emit("clip_prompts", "completed", "段落动态描述生成完成", 0.18)

    async def _run_step_generate_clips(
        self, paragraphs: List[ManuscriptParagraph], anchor_image_path: str,
    ) -> None:
        """运行 Step 4: 逐段 i2v 视频生成，带 resume 支持。"""
        if self._state.step_clip_generation == StepStatus.COMPLETED:
            logger.info("[Anchor] Step 4 (clip_generation): already completed, resuming")
            return

        self.task_manager.update_step("step_clip_generation", StepStatus.RUNNING)
        await self._emit("clip_gen", "running", "生成段落视频片段...", 0.18)

        await self._step_generate_clips(paragraphs, anchor_image_path)

        self.task_manager.update_state(paragraphs=paragraphs)
        self.task_manager.update_step("step_clip_generation", StepStatus.COMPLETED)
        await self._emit("clip_gen", "completed", "所有段落视频已生成", 0.55)

    async def _run_step_audio(self) -> object:
        """运行 Step 5: TTS 读稿，带 resume 支持。返回 sub_maker 供字幕步骤使用。"""
        if self._state.step_audio == StepStatus.COMPLETED:
            logger.info("[Anchor] Step 5 (audio): already completed, resuming")
            return None

        self.task_manager.update_step("step_audio", StepStatus.RUNNING)
        await self._emit("audio", "running", "生成读稿音频...", 0.55)

        sub_maker = await self._step_audio()

        self.task_manager.update_state(combined_audio=self._state.combined_audio)
        self.task_manager.update_step("step_audio", StepStatus.COMPLETED)
        await self._emit("audio", "completed", "读稿音频生成完成", 0.65)
        return sub_maker

    async def _run_step_subtitle(self, sub_maker: object = None) -> None:
        """运行 Step 6: 字幕生成，带 resume 支持。"""
        if self._state.step_subtitle == StepStatus.COMPLETED:
            logger.info("[Anchor] Step 6 (subtitle): already completed, resuming")
            return

        self.task_manager.update_step("step_subtitle", StepStatus.RUNNING)
        await self._emit("subtitle", "running", "生成字幕...", 0.65)

        await self._step_subtitle(sub_maker)

        self.task_manager.update_state(
            combined_subtitle=self._state.combined_subtitle,
            subtitle_styles_path=self._state.subtitle_styles_path,
        )
        self.task_manager.update_step("step_subtitle", StepStatus.COMPLETED)
        await self._emit("subtitle", "completed", "字幕生成完成", 0.75)

    async def _run_step_concatenate(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> str:
        """运行 Step 7: 视频拼接，带 resume 支持。"""
        if self._state.step_concatenation == StepStatus.COMPLETED:
            logger.info("[Anchor] Step 7 (concatenation): already completed, resuming")
            if self._state.final_video_file:
                return self._state.final_video_file

        self.task_manager.update_step("step_concatenation", StepStatus.RUNNING)
        await self._emit("concatenate", "running", "拼接最终视频...", 0.75)

        final_video = await self._step_concatenate(paragraphs)

        self.task_manager.update_state(final_video_file=final_video)
        self.task_manager.update_step("step_concatenation", StepStatus.COMPLETED)
        await self._emit("concatenate", "completed", "视频拼接完成", 0.95)
        return final_video

    # ==================================================================
    # Step implementations
    # ==================================================================

    async def _step_generate_anchor(self) -> str:
        """Step 1: 生成主播形象图（t2i / i2i），与之前版本一致。"""
        if self._state.step_generate_anchor == StepStatus.COMPLETED:
            if self._state.anchor_image_path and os.path.exists(self._state.anchor_image_path):
                logger.info("[Anchor] Step generate_anchor: SKIP (already completed)")
                return self._state.anchor_image_path
            logger.warning("[Anchor] Step generate_anchor: file missing, re-running")

        prompt = self._state.anchor_prompt or _DEFAULT_ANCHOR_PROMPT
        output_path = os.path.join(self.working_dir, "anchor.png")

        if os.path.exists(output_path):
            self._state.anchor_image_path = output_path
            self._state.step_generate_anchor = StepStatus.COMPLETED
            self.task_manager.update_state(
                anchor_image_path=output_path,
                step_generate_anchor=StepStatus.COMPLETED,
            )
            return output_path

        ref_image = self._state.anchor_reference_image
        size = f"{self._state.video_width}x{self._state.video_height}"

        await self._emit(
            "generate_anchor", "running",
            "生成主播形象图..." if not ref_image else "基于参考图生成主播形象...",
            0.02,
        )

        try:
            if ref_image and os.path.exists(ref_image):
                img_output = await self.image_generator.generate_single_image(
                    prompt=prompt,
                    reference_image_paths=[ref_image],
                    size=size,
                )
            else:
                img_output = await self.image_generator.generate_single_image(
                    prompt=prompt,
                    size=size,
                )
            img_output.save(output_path)
        except Exception as e:
            logger.error(f"[Anchor] Anchor image generation failed: {e}")
            raise RuntimeError(f"主播形象生成失败: {e}")

        self._state.anchor_image_path = output_path
        self._state.step_generate_anchor = StepStatus.COMPLETED
        self.task_manager.update_state(
            anchor_image_path=output_path,
            step_generate_anchor=StepStatus.COMPLETED,
        )
        await self._emit("generate_anchor", "completed", "主播形象生成完成", 0.08)
        return output_path

    # ------------------------------------------------------------------
    # Step 2: 拆分稿件（复用稿件视频拆段逻辑）
    # ------------------------------------------------------------------

    def _step_split_text(self, text: str) -> List[ManuscriptParagraph]:
        """将口播稿件按朗读时长拆分为段落列表（5-12 秒/段）。

        策略与 ManuscriptVideoPipeline._step_split_text 完全一致：
            1. 按换行符切粗段落。
            2. 按中文句末标点切候选句。
            3. 贪心合并：<= 12s，>= 5s。
            4. 短句合并到前一段。
        """
        if self._state.paragraphs:
            logger.info(
                "[Anchor] split_text: %d paragraphs already exist, resuming",
                len(self._state.paragraphs),
            )
            return self._state.paragraphs

        logger.info("[Anchor] split_text: splitting %d chars...", len(text))

        raw_blocks = [b.strip() for b in text.split("\n") if b.strip()]

        candidate_sentences: List[str] = []
        for block in raw_blocks:
            parts = _SENTENCE_END_RE.split(block)
            for part in parts:
                part = part.strip()
                if part:
                    candidate_sentences.append(part)

        if not candidate_sentences:
            logger.warning("[Anchor] split_text: no sentences found in text")
            return []

        # 贪心合并
        merged: List[str] = []
        current_text = ""
        current_duration = 0.0

        for sentence in candidate_sentences:
            sentence_duration = len(sentence) / _CHARS_PER_SEC

            if not current_text:
                current_text = sentence
                current_duration = sentence_duration
                continue

            prospective_duration = current_duration + sentence_duration

            if prospective_duration <= _MAX_SEGMENT_DURATION:
                current_text += sentence
                current_duration = prospective_duration
            else:
                merged.append(current_text)
                current_text = sentence
                current_duration = sentence_duration

        if current_text:
            merged.append(current_text)

        # 短句后处理
        final_texts: List[str] = []
        for segment in merged:
            seg_duration = len(segment) / _CHARS_PER_SEC
            if seg_duration < _MIN_SEGMENT_DURATION and final_texts:
                final_texts[-1] += segment
            else:
                final_texts.append(segment)

        paragraphs: List[ManuscriptParagraph] = []
        for idx, para_text in enumerate(final_texts):
            est_duration = len(para_text) / _CHARS_PER_SEC
            para = ManuscriptParagraph(
                index=idx,
                text=para_text,
            )
            paragraphs.append(para)
            logger.info(
                "[Anchor] Paragraph %d: %d chars, ~%.1fs",
                idx, len(para_text), est_duration,
            )

        logger.info("[Anchor] split_text: %d paragraphs created", len(paragraphs))
        return paragraphs

    # ------------------------------------------------------------------
    # Step 3: 为每段生成动态 prompt
    # ------------------------------------------------------------------

    async def _step_generate_clip_prompts(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> None:
        """为每个段落生成英文 i2v 动态 prompt（含口型/手势描述）。"""
        total = len(paragraphs)
        anchor_prompt = self._state.anchor_prompt or _DEFAULT_ANCHOR_PROMPT

        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            if para.scene_prompt:
                logger.info(
                    "[Anchor] clip_prompt: paragraph %d already has prompt, skipping",
                    para.index,
                )
                continue

            logger.info(
                "[Anchor] clip_prompt: generating for paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "clip_prompts", "running",
                f"生成动态描述 {i + 1}/{total}",
                0.12 + 0.06 * (i / max(total, 1)),
            )

            prompt = await asyncio.to_thread(
                self.screenwriter.generate_anchor_clip_prompt,
                paragraph_text=para.text,
                anchor_prompt=anchor_prompt,
                segment_index=i,
                total_segments=total,
            )
            para.scene_prompt = prompt.strip()

            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Anchor] clip_prompt %d: %s...",
                para.index, para.scene_prompt[:80],
            )

    # ------------------------------------------------------------------
    # Step 4: 逐段 i2v 生成视频片段
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
                logger.debug(f"[Anchor] Failed to load cached task.json: {e}")
        return None

    async def _step_generate_clips(
        self,
        paragraphs: List[ManuscriptParagraph],
        anchor_image_path: str,
    ) -> None:
        """为每个段落调用 i2v 生成视频片段（两阶段并行提交+等待）。"""
        _SUBMIT_RETRIES = 3
        _WAIT_RETRIES = 3
        total = len(paragraphs)
        vw = self._state.video_width
        vh = self._state.video_height

        # ── Phase 1: 批量提交 ────────────────────────────────────
        pending: list[tuple[int, str, str]] = []

        for i, para in enumerate(paragraphs):
            self._check_shutdown()

            para_dir = os.path.join(self.working_dir, f"clip_{para.index}")
            video_path = os.path.join(para_dir, "clip.mp4")

            if os.path.exists(video_path):
                para.video_file = video_path
                logger.info(
                    "[Anchor] clip: paragraph %d already exists, skipping",
                    para.index,
                )
                continue

            if not para.scene_prompt:
                logger.warning(
                    "[Anchor] clip: paragraph %d has no scene_prompt, skipping",
                    para.index,
                )
                continue

            os.makedirs(para_dir, exist_ok=True)

            saved_video_id = self._load_para_task(para_dir)
            if saved_video_id:
                para.video_id = saved_video_id
                logger.info(
                    "[Anchor] clip: paragraph %d resuming video_id %s...",
                    para.index, saved_video_id[:16],
                )
                pending.append((para.index, saved_video_id, video_path))
                continue

            logger.info(
                "[Anchor] clip: submitting paragraph %d/%d...",
                i + 1, total,
            )
            await self._emit(
                "clip_gen", "running",
                f"提交视频 {i + 1}/{total}",
                0.18 + 0.15 * (i / max(total, 1)),
            )

            para_duration = max(int(math.ceil(len(para.text) / _CHARS_PER_SEC)), 3)

            for retry in range(_SUBMIT_RETRIES):
                try:
                    video_id = await self.video_generator.submit_video(
                        prompt=para.scene_prompt,
                        reference_image_paths=[anchor_image_path],
                        duration=para_duration,
                        width=vw,
                        height=vh,
                    )
                    para.video_id = video_id
                    self._save_para_task(para_dir, video_id)
                    pending.append((para.index, video_id, video_path))
                    break
                except Exception as e:
                    if retry < _SUBMIT_RETRIES - 1:
                        delay = 15 * (retry + 1)
                        logger.warning(
                            "[Anchor] clip: paragraph %d submit failed "
                            "(%s), retry %d/%d in %ds...",
                            para.index, e, retry + 1, _SUBMIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

        self.task_manager.update_state(paragraphs=paragraphs)
        logger.info(
            "[Anchor] clip: all %d paragraphs submitted, now waiting...",
            len(pending),
        )

        # ── Phase 2: 逐个等待完成 ────────────────────────────────
        for j, (para_idx, video_id, video_path) in enumerate(pending):
            self._check_shutdown()

            para = paragraphs[para_idx]
            await self._emit(
                "clip_gen", "running",
                f"等待视频 {j + 1}/{len(pending)} ({video_id[:16]}...)",
                0.33 + 0.22 * (j / max(len(pending), 1)),
            )

            for retry in range(_WAIT_RETRIES):
                try:
                    video_output = await self.video_generator.wait_for_video(video_id)
                    video_output.save(video_path)
                    break
                except Exception as e:
                    if retry < _WAIT_RETRIES - 1:
                        delay = 20 * (retry + 1)
                        logger.warning(
                            "[Anchor] clip: paragraph %d wait failed "
                            "(%s), retry %d/%d in %ds...",
                            para_idx, e, retry + 1, _WAIT_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise

            para.video_file = video_path
            self.task_manager.update_state(paragraphs=paragraphs)
            logger.info(
                "[Anchor] clip: paragraph %d saved → %s (video_id=%s)",
                para_idx, video_path, video_id[:16],
            )

    # ------------------------------------------------------------------
    # Step 5: TTS 读稿音频（整段连续）
    # ------------------------------------------------------------------

    async def _step_audio(self) -> object:
        """生成整段连续 TTS 音频（复用稿件视频模式）。"""
        paragraphs = self._state.paragraphs
        full_text = "\n\n".join(p.text for p in paragraphs if p.text)
        if not full_text:
            logger.warning("[Anchor] audio: empty full text, skipping")
            return None

        audio_path = os.path.join(self.working_dir, "full_narration.mp3")

        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[Anchor] audio: file already exists, skipping")
            return None

        audio_config = self._state.audio_config
        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()

        await self._emit(
            "audio", "running",
            f"生成整段读稿 ({len(full_text)} 字)...",
            0.55,
        )

        sub_maker = None
        if audio_config.enabled:
            try:
                _, sub_maker = await edge_tts.generate(
                    text=full_text,
                    output_path=audio_path,
                    voice=audio_config.voice,
                    rate=audio_config.rate,
                )
            except RuntimeError as e:
                logger.warning(f"[Anchor] EdgeTTS failed, falling back to silent: {e}")
                audio_duration = len(full_text) / _CHARS_PER_SEC
                await silent_tts.generate(
                    text=full_text,
                    output_path=audio_path,
                    duration_sec=audio_duration,
                )
        else:
            audio_duration = len(full_text) / _CHARS_PER_SEC
            await silent_tts.generate(
                text=full_text,
                output_path=audio_path,
                duration_sec=audio_duration,
            )

        self._state.combined_audio = audio_path
        self.task_manager.update_state(combined_audio=audio_path)
        logger.info("[Anchor] audio: combined → %s", audio_path)
        return sub_maker

    # ------------------------------------------------------------------
    # Step 6: 字幕生成 + LLM 智能样式
    # ------------------------------------------------------------------

    async def _step_subtitle(self, sub_maker: object = None) -> None:
        """生成整段 SRT 字幕（复用稿件视频的段落感知字幕逻辑）。"""
        paragraphs = self._state.paragraphs
        subtitle_config = self._state.subtitle_config

        full_text = "\n\n".join(p.text for p in paragraphs if p.text)
        if not full_text:
            logger.warning("[Anchor] subtitle: empty full text, skipping")
            return

        srt_path = os.path.join(self.working_dir, "full_subtitle.srt")

        if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
            self._state.combined_subtitle = srt_path
            logger.info("[Anchor] subtitle: file already exists, skipping")
            return

        await self._emit(
            "subtitle", "running",
            f"生成整段字幕 ({len(full_text)} 字, {len(paragraphs)} 段)...",
            0.65,
        )

        # 获取实际音频时长
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
            # 段落感知字幕生成
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
                logger.info(
                    f"[Anchor] SRT durations scaled by {scale:.3f} "
                    f"(audio={actual_audio_dur:.2f}s, est={total_est:.2f}s)"
                )

            srt_content = SubtitleGenerator._generate_scene_aware_srt(
                para_texts, para_durations,
                word_cues=sub_maker if sub_maker is not None else None,
            )
            if srt_content.strip():
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                entry_count = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 0
                logger.info(
                    f"[Anchor] Scene-aware SRT generated: {entry_count} entries "
                    f"across {num_paras} paragraphs"
                )
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

        # LLM 智能样式
        if subtitle_config.enabled and subtitle_config.style.style_mode == "llm":
            styles_path = os.path.join(self.working_dir, "subtitle_styles.json")
            if not os.path.exists(styles_path) or os.path.getsize(styles_path) == 0:
                try:
                    hints = self._state.subtitle_position_hints or subtitle_config.style.style_hints
                    styles = await asyncio.to_thread(
                        self.screenwriter.generate_subtitle_styles,
                        srt_path=srt_path,
                        video_width=self._state.video_width,
                        video_height=self._state.video_height,
                        style_hints=hints,
                        role="anchorperson digital human",
                    )
                    with open(styles_path, "w", encoding="utf-8") as f:
                        json.dump(styles, f, ensure_ascii=False, indent=2)
                    self._state.subtitle_styles_path = styles_path
                    self.task_manager.update_state(subtitle_styles_path=styles_path)
                    logger.info(
                        f"[Anchor] LLM subtitle styles saved: {styles_path} "
                        f"({len(styles)} entries)"
                    )
                except Exception as e:
                    logger.warning(
                        f"[Anchor] LLM subtitle styles failed: {e}, "
                        f"falling back to fixed"
                    )
                    self._state.subtitle_styles_path = ""
                    self.task_manager.update_state(subtitle_styles_path="")

        self._state.combined_subtitle = srt_path
        self.task_manager.update_state(combined_subtitle=srt_path)
        logger.info("[Anchor] subtitle: combined → %s", srt_path)

    # ------------------------------------------------------------------
    # Step 7: 拼接所有片段 + 叠加音频 + 字幕
    # ------------------------------------------------------------------

    async def _step_concatenate(
        self, paragraphs: List[ManuscriptParagraph],
    ) -> str:
        """拼接所有段落视频 + 叠加整段音频 + 整段字幕。"""
        output_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(output_path):
            logger.info("[Anchor] concatenate: final video already exists, skipping")
            return output_path

        video_paths = [
            p.video_file for p in paragraphs
            if p.video_file and os.path.exists(p.video_file)
        ]
        if not video_paths:
            raise RuntimeError("[Anchor] concatenate: no valid videos to concatenate")

        has_audio = self._state.audio_config.enabled and bool(self._state.combined_audio)
        subtitle_config = self._state.subtitle_config
        has_subtitle = subtitle_config.enabled and bool(self._state.combined_subtitle)

        styles_path = self._state.subtitle_styles_path or ""
        if styles_path and not os.path.exists(styles_path):
            styles_path = ""

        logger.info(
            "[Anchor] concatenate: %d clips + audio=%s + subtitle=%s → %s",
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
                VideoConcatenator.concat_videos, video_paths, output_path,
            )

        logger.info("[Anchor] concatenate: final video → %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _check_shutdown(self) -> None:
        """检查是否需要停止流水线。"""
        if self._is_shutdown():
            raise PipelineShutdown("Pipeline shutdown requested")
"""core.pipelines.anchor_video -- 数字人口播流水线（类型 4 / Phase 3）

流程：
    1. 生成主播形象图（t2i / i2i）
    2. i2v 生成动态视频片段（~5 秒）
    3. TTS 读稿音频
    4. 字幕生成 + LLM 定位
    5. 循环拼接 + 叠加音视频字幕
"""

import asyncio
import json
import logging
import math
import os
from typing import Callable, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
from core.audio.subtitle import SubtitleGenerator
from core.audio.tts import EdgeTTSEngine, SilentTTSEngine
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import BasePipeline, PipelineShutdown
from core.screenwriter import Screenwriter
from models.task import AnchorVideoTask, StepStatus

logger = logging.getLogger(__name__)

# 默认主播 prompt
_DEFAULT_ANCHOR_PROMPT = (
    "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中，"
    "面带微笑，正面半身照，高清画质，专业灯光"
)


class AnchorPipeline(BasePipeline):
    """数字人口播视频生成流水线。

    5 步流程：
        1. 生成主播形象图
        2. 生成动态视频片段（i2v）
        3. TTS 读稿
        4. 字幕 + LLM 定位
        5. 循环拼接 + 叠加
    """

    def __init__(
        self,
        api_key: str,
        task_id: str,
        dir_name: Optional[str] = None,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        progress_callback: Optional[Callable] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ):
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)
        self.image_generator = AgnesImageAPI(api_key=api_key, model=image_model)
        self.video_generator = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_generator.shutdown_event = shutdown_event
        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self._state: Optional[AnchorVideoTask] = None

    @property
    def state(self) -> Optional[AnchorVideoTask]:
        return self._state

    # ==================================================================
    # Step 1: Generate anchor image (t2i or i2i)
    # ==================================================================

    async def _step_generate_anchor(self) -> str:
        if self._state.step_generate_anchor == StepStatus.COMPLETED:
            if self._state.anchor_image_path and os.path.exists(self._state.anchor_image_path):
                logger.info("[Anchor] Step generate_anchor: SKIP (already completed)")
                return self._state.anchor_image_path
            logger.warning("[Anchor] Step generate_anchor: file missing, re-running")

        prompt = self._state.anchor_prompt or _DEFAULT_ANCHOR_PROMPT
        output_path = os.path.join(self.working_dir, "anchor.png")

        if os.path.exists(output_path):
            self._state.anchor_image_path = output_path
            self._state.step_generate_anchor = StepStatus.COMPLETED
            self.task_manager.update_state(
                anchor_image_path=output_path,
                step_generate_anchor=StepStatus.COMPLETED,
            )
            return output_path

        ref_image = self._state.anchor_reference_image
        size = f"{self._state.video_width}x{self._state.video_height}"

        await self._emit(
            "generate_anchor", "running",
            "生成主播形象图..." if not ref_image else "基于参考图生成主播形象...",
            0.05,
        )

        try:
            if ref_image and os.path.exists(ref_image):
                img_output = await self.image_generator.generate_single_image(
                    prompt=prompt,
                    reference_image_paths=[ref_image],
                    size=size,
                )
            else:
                img_output = await self.image_generator.generate_single_image(
                    prompt=prompt,
                    size=size,
                )
            img_output.save(output_path)
        except Exception as e:
            logger.error(f"[Anchor] Anchor image generation failed: {e}")
            raise RuntimeError(f"主播形象生成失败: {e}")

        self._state.anchor_image_path = output_path
        self._state.step_generate_anchor = StepStatus.COMPLETED
        self.task_manager.update_state(
            anchor_image_path=output_path,
            step_generate_anchor=StepStatus.COMPLETED,
        )
        await self._emit("generate_anchor", "completed", "主播形象生成完成", 0.2)
        return output_path

    # ==================================================================
    # Step 2: Generate dynamic clip via I2V
    # ==================================================================

    async def _step_generate_clip(self, anchor_image_path: str) -> str:
        if self._state.step_generate_clip == StepStatus.COMPLETED:
            if self._state.anchor_clip_path and os.path.exists(self._state.anchor_clip_path):
                logger.info("[Anchor] Step generate_clip: SKIP (already completed)")
                return self._state.anchor_clip_path
            logger.warning("[Anchor] Step generate_clip: file missing, re-running")

        output_path = os.path.join(self.working_dir, "anchor_clip.mp4")
        if os.path.exists(output_path):
            self._state.anchor_clip_path = output_path
            self._state.step_generate_clip = StepStatus.COMPLETED
            self.task_manager.update_state(
                anchor_clip_path=output_path,
                step_generate_clip=StepStatus.COMPLETED,
            )
            return output_path

        vw = self._state.video_width
        vh = self._state.video_height

        clip_prompt = (
            "The anchorperson faces the camera with a natural smile, "
            "occasionally nodding slightly. The backdrop is a modern news studio "
            "with soft, warm lighting. Subtle micro-movements of the head and "
            "shoulders. The overall motion is gentle and natural, "
            "with the starting and ending posture nearly identical."
        )

        await self._emit("generate_clip", "running", "生成主播动态视频 (i2v)...", 0.25)

        try:
            video_id = await self.video_generator.submit_video(
                prompt=clip_prompt,
                reference_image_paths=[anchor_image_path],
                duration=5,
                width=vw,
                height=vh,
            )
            video_output = await self.video_generator.wait_for_video(video_id)
            video_output.save(output_path)
        except Exception as e:
            logger.error(f"[Anchor] Clip generation failed: {e}")
            raise RuntimeError(f"主播动态视频生成失败: {e}")

        self._state.anchor_clip_path = output_path
        self._state.step_generate_clip = StepStatus.COMPLETED
        self.task_manager.update_state(
            anchor_clip_path=output_path,
            step_generate_clip=StepStatus.COMPLETED,
        )
        await self._emit("generate_clip", "completed", "主播动态视频生成完成", 0.4)
        return output_path

    # ==================================================================
    # Step 3: Generate TTS audio
    # ==================================================================

    async def _step_generate_audio(self) -> object:
        if self._state.step_audio == StepStatus.COMPLETED:
            if self._state.audio_path and os.path.exists(self._state.audio_path):
                logger.info("[Anchor] Step audio: SKIP (already completed)")
                return None
            logger.warning("[Anchor] Step audio: file missing, re-running")

        audio_path = os.path.join(self.working_dir, "narration.mp3")
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.audio_path = audio_path
            self._state.step_audio = StepStatus.COMPLETED
            self.task_manager.update_state(
                audio_path=audio_path,
                step_audio=StepStatus.COMPLETED,
            )
            return None

        script_text = self._state.script_text
        audio_config = self._state.audio_config

        await self._emit(
            "audio", "running",
            f"生成读稿音频 ({len(script_text)} 字)...",
            0.45,
        )

        edge_tts = EdgeTTSEngine()
        silent_tts = SilentTTSEngine()
        sub_maker = None

        if audio_config.enabled and script_text:
            try:
                _, sub_maker = await edge_tts.generate(
                    text=script_text,
                    output_path=audio_path,
                    voice=audio_config.voice,
                    rate=audio_config.rate,
                )
            except RuntimeError as e:
                logger.warning(f"[Anchor] EdgeTTS failed, falling back to silent: {e}")
                audio_duration = len(script_text) / 4.0
                await silent_tts.generate(
                    text=script_text,
                    output_path=audio_path,
                    duration_sec=audio_duration,
                )
        else:
            audio_duration = len(script_text) / 4.0 if script_text else 10.0
            await silent_tts.generate(
                text=script_text or "placeholder",
                output_path=audio_path,
                duration_sec=audio_duration,
            )

        self._state.audio_path = audio_path
        self._state.step_audio = StepStatus.COMPLETED
        self.task_manager.update_state(
            audio_path=audio_path,
            step_audio=StepStatus.COMPLETED,
        )
        await self._emit("audio", "completed", "读稿音频生成完成", 0.6)
        return sub_maker

    # ==================================================================
    # Step 4: Generate subtitles + LLM styles
    # ==================================================================

    async def _step_generate_subtitle(self, sub_maker: object = None) -> None:
        if self._state.step_subtitle == StepStatus.COMPLETED:
            logger.info("[Anchor] Step subtitle: SKIP (already completed)")
            return

        srt_path = os.path.join(self.working_dir, "narration.srt")
        if os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
            self._state.srt_path = srt_path
            self._state.step_subtitle = StepStatus.COMPLETED
            self.task_manager.update_state(
                srt_path=srt_path,
                step_subtitle=StepStatus.COMPLETED,
            )
            return

        script_text = self._state.script_text
        subtitle_config = self._state.subtitle_config
        audio_path = self._state.audio_path

        await self._emit(
            "subtitle", "running",
            "生成字幕..." if subtitle_config.enabled else "跳过字幕生成",
            0.65,
        )

        if subtitle_config.enabled and sub_maker is not None:
            SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
        elif subtitle_config.enabled and script_text:
            audio_duration = len(script_text) / 4.0
            if audio_path and os.path.exists(audio_path):
                from moviepy import AudioFileClip
                try:
                    audio_clip = AudioFileClip(audio_path)
                    audio_duration = audio_clip.duration
                    audio_clip.close()
                except Exception:
                    pass
            SubtitleGenerator.text_to_srt(script_text, srt_path, audio_duration)
        else:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("")

        # LLM 智能样式
        if subtitle_config.enabled and subtitle_config.style.style_mode == "llm":
            styles_path = os.path.join(self.working_dir, "subtitle_styles.json")
            if not os.path.exists(styles_path) or os.path.getsize(styles_path) == 0:
                try:
                    hints = self._state.subtitle_position_hints or subtitle_config.style.style_hints
                    styles = await asyncio.to_thread(
                        self.screenwriter.generate_subtitle_styles,
                        srt_path=srt_path,
                        video_width=self._state.video_width,
                        video_height=self._state.video_height,
                        style_hints=hints,
                        role="anchorperson digital human",
                    )
                    with open(styles_path, "w", encoding="utf-8") as f:
                        json.dump(styles, f, ensure_ascii=False, indent=2)
                    self._state.styles_path = styles_path
                except Exception as e:
                    logger.warning(f"[Anchor] LLM subtitle styles failed: {e}, falling back to fixed")
                    self._state.styles_path = ""
                self.task_manager.update_state(styles_path=self._state.styles_path)
                logger.info(f"[Anchor] LLM subtitle styles saved: {styles_path}")

        self._state.srt_path = srt_path
        self._state.step_subtitle = StepStatus.COMPLETED
        self.task_manager.update_state(
            srt_path=srt_path,
            step_subtitle=StepStatus.COMPLETED,
        )
        await self._emit("subtitle", "completed", "字幕生成完成", 0.75)

    # ==================================================================
    # Step 5: Composite - loop clip + audio + subtitle
    # ==================================================================

    async def _step_composite(self) -> str:
        if self._state.step_composite == StepStatus.COMPLETED:
            if self._state.final_video_path and os.path.exists(self._state.final_video_path):
                logger.info("[Anchor] Step composite: SKIP (already completed)")
                return self._state.final_video_path
            logger.warning("[Anchor] Step composite: file missing, re-running")

        output_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(output_path):
            self._state.final_video_path = output_path
            self._state.step_composite = StepStatus.COMPLETED
            self._state.final_video_file = output_path
            self.task_manager.update_state(
                final_video_path=output_path,
                final_video_file=output_path,
                step_composite=StepStatus.COMPLETED,
            )
            return output_path

        clip_path = self._state.anchor_clip_path
        audio_path = self._state.audio_path
        srt_path = self._state.srt_path
        subtitle_config = self._state.subtitle_config
        srt_exists = bool(srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 0)

        # 获取音频时长
        audio_duration = 10.0
        if audio_path and os.path.exists(audio_path):
            from moviepy import AudioFileClip
            try:
                audio_clip = AudioFileClip(audio_path)
                audio_duration = audio_clip.duration
                audio_clip.close()
            except Exception:
                audio_duration = len(self._state.script_text) / 4.0 if self._state.script_text else 10.0
        else:
            audio_duration = len(self._state.script_text) / 4.0 if self._state.script_text else 10.0

        await self._emit(
            "composite", "running",
            f"循环拼接 + 叠加音视频 (音频 {audio_duration:.1f}s)...",
            0.8,
        )

        styles_path = self._state.styles_path or ""
        if styles_path and not os.path.exists(styles_path):
            styles_path = ""

        try:
            await asyncio.to_thread(
                VideoConcatenator.composite_anchor_video,
                clip_path=clip_path,
                audio_path=audio_path,
                srt_path=srt_path if (subtitle_config.enabled and srt_exists) else None,
                output_path=output_path,
                audio_duration=audio_duration,
                subtitle_style=subtitle_config.style if subtitle_config.enabled else None,
                subtitle_styles_path=styles_path if styles_path else None,
                video_width=self._state.video_width,
                video_height=self._state.video_height,
            )
        except Exception as e:
            logger.error(f"[Anchor] Composite failed: {e}")
            raise RuntimeError(f"视频合成失败: {e}")

        self._state.final_video_path = output_path
        self._state.final_video_file = output_path
        self._state.step_composite = StepStatus.COMPLETED
        self.task_manager.update_state(
            final_video_path=output_path,
            final_video_file=output_path,
            step_composite=StepStatus.COMPLETED,
        )
        await self._emit("composite", "completed", "视频合成完成", 0.95)
        return output_path

    # ==================================================================
    # Main Run
    # ==================================================================

    async def run(self, state: AnchorVideoTask) -> str:
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", "开始数字人口播生成...", 0.0)

        try:
            anchor_image_path = await self._step_generate_anchor()
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after anchor image")

            clip_path = await self._step_generate_clip(anchor_image_path)
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after clip generation")

            sub_maker = await self._step_generate_audio()
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after audio")

            await self._step_generate_subtitle(sub_maker)
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after subtitle")

            final_video = await self._step_composite()

            self._state.status = StepStatus.COMPLETED
            self.task_manager.update_state(status=StepStatus.COMPLETED)
            await self._emit(
                "done", "completed", "数字人口播生成完成!", 1.0,
                {"final_video": final_video},
            )
            return final_video

        except PipelineShutdown as e:
            logger.info(f"[Anchor] Shutdown: {e}")
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise
