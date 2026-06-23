"""core.pipelines.anchor_video -- 数字人口播流水线（类型 4）

支持两种音频模式：
  - post_stitch: 生成一段短 i2v 视频循环 + TTS 后拼接音频（音频可控，嘴型较难匹配）
  - model: 交由视频模型自身生成音频（音频由模型控制，效果不可控）
"""

import asyncio
import json
import logging
import math
import os
import re
from typing import Callable, List, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI
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
)

logger = logging.getLogger(__name__)

_DEFAULT_ANCHOR_PROMPT_ZH = (
    "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中，"
    "面带微笑，正面半身照，高清画质，专业灯光"
)

_DEFAULT_ANCHOR_PROMPT_EN = (
    "A professional news anchor in formal business attire, seated in a modern "
    "news studio, smiling warmly, front-facing half-body shot, high definition, "
    "professional studio lighting"
)

_SENTENCE_END_RE = re.compile(r"(?<=[。！？])")
_CHARS_PER_SEC = 4.0


class AnchorPipeline(BasePipeline):
    """数字人口播视频生成流水线。

    根据 audio_source 分两种模式：
      - post_stitch: 生成一段短 i2v 视频 → 循环播放 → TTS + 字幕叠加
      - model:      生成一段视频（模型自带音频）→ 不含 TTS/字幕叠加
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

        audio_source = self._state.audio_source or "post_stitch"
        mode_label = "模型音频" if audio_source == "model" else "后拼接音频"
        await self._emit("init", "running", f"开始数字人口播生成（{mode_label}）...", 0.0)

        try:
            # Step 1: 生成主播形象图
            self._check_shutdown()
            anchor_image_path = await self._step_generate_anchor()

            if audio_source == "model":
                return await self._run_model_audio(anchor_image_path)
            else:
                return await self._run_post_stitch(anchor_image_path)

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
    # 模式 A: 后拼接音频 — 单段视频 + 循环 + TTS + 字幕
    # ==================================================================

    async def _run_post_stitch(self, anchor_image_path: str) -> str:
        """后拼接音频模式：一段短 i2v 循环播放 + TTS + 字幕叠加。"""
        # Step 2: TTS 读稿音频（先行，获取时长和 sub_maker）
        self._check_shutdown()
        sub_maker = await self._step_audio()

        # Step 3: 生成单段循环优化的 i2v prompt
        self._check_shutdown()
        smooth_prompt = await self._step_generate_smooth_prompt()

        # Step 4: 生成单段 i2v 视频（5 秒）
        self._check_shutdown()
        clip_path = await self._step_generate_single_clip(
            anchor_image_path, smooth_prompt,
        )

        # Step 5: 字幕生成
        self._check_shutdown()
        await self._step_subtitle(sub_maker)

        # Step 6: 循环拼接 + 叠加音频 + 字幕
        self._check_shutdown()
        final_video = await self._step_composite_anchor(clip_path)

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

    # ==================================================================
    # 模式 B: 模型音频 — 视频由模型自带音频，不做后处理
    # ==================================================================

    async def _run_model_audio(self, anchor_image_path: str) -> str:
        """模型音频模式：一段视频由模型自带音频，不做后处理。"""
        # Step 2: 为全文生成单段 i2v prompt（含口播文本提示）
        self._check_shutdown()
        prompt = await self._step_generate_audio_prompt()

        # Step 3: 生成单段 i2v 视频（完整文本时长）
        self._check_shutdown()
        clip_path = await self._step_generate_single_clip(
            anchor_image_path, prompt,
        )

        self._state.status = StepStatus.COMPLETED
        self._state.final_video_file = clip_path
        self.task_manager.update_state(
            status=StepStatus.COMPLETED,
            final_video_file=clip_path,
        )
        await self._emit(
            "done", "completed", "数字人口播生成完成（模型音频）!", 1.0,
            {"final_video": clip_path},
        )
        return clip_path

    # ==================================================================
    # Step implementations
    # ==================================================================

    def _get_default_anchor_prompt(self) -> str:
        """根据 script_text 语言返回合适的主播默认描述。"""
        text = (self._state.script_text or "").strip()
        if re.search(r'[\u4e00-\u9fff]', text):
            return _DEFAULT_ANCHOR_PROMPT_ZH
        return _DEFAULT_ANCHOR_PROMPT_EN

    async def _step_generate_anchor(self) -> str:
        """Step 1: 生成主播形象图（t2i / i2i）。"""
        if self._state.step_generate_anchor == StepStatus.COMPLETED:
            if self._state.anchor_image_path and os.path.exists(self._state.anchor_image_path):
                logger.info("[Anchor] Step generate_anchor: SKIP (already completed)")
                return self._state.anchor_image_path
            logger.warning("[Anchor] Step generate_anchor: file missing, re-running")

        prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()
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

    async def _step_generate_smooth_prompt(self) -> str:
        """为后拼接音频模式生成循环优化的单段 prompt。"""
        await self._emit(
            "clip_prompts", "running",
            "生成循环优化动态描述...", 0.12,
        )

        anchor_prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()
        prompt = await asyncio.to_thread(
            self.screenwriter.generate_anchor_smooth_loop_prompt,
            anchor_prompt=anchor_prompt,
        )
        prompt = prompt.strip()

        self.save_prompts({
            "anchor_prompt": self._state.anchor_prompt or self._get_default_anchor_prompt(),
            "smooth_loop_prompt": prompt,
        })

        logger.info("[Anchor] smooth_loop_prompt: %s...", prompt[:80])
        await self._emit(
            "clip_prompts", "completed",
            "循环优化动态描述生成完成", 0.18,
        )
        return prompt

    async def _step_generate_audio_prompt(self) -> str:
        """为模型音频模式生成含口播文本的视频 prompt。"""
        await self._emit(
            "clip_prompts", "running",
            "生成含口播的视频描述...", 0.12,
        )

        full_text = self._state.script_text
        anchor_prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()

        prompt = await asyncio.to_thread(
            self.screenwriter.generate_anchor_model_audio_prompt,
            anchor_prompt=anchor_prompt,
            script_text=full_text,
        )
        prompt = prompt.strip()

        self.save_prompts({
            "anchor_prompt": self._state.anchor_prompt or self._get_default_anchor_prompt(),
            "model_audio_prompt": prompt,
        })

        logger.info("[Anchor] model_audio_prompt: %s...", prompt[:80])
        await self._emit(
            "clip_prompts", "completed",
            "含口播的视频描述生成完成", 0.18,
        )
        return prompt

    async def _step_generate_single_clip(
        self, anchor_image_path: str, prompt: str,
    ) -> str:
        """生成单段 i2v 视频（5 秒，循环用）。"""
        if self._state.step_clip_generation == StepStatus.COMPLETED:
            clip_dir = os.path.join(self.working_dir, "clip")
            clip_path = os.path.join(clip_dir, "clip.mp4")
            if os.path.exists(clip_path):
                logger.info("[Anchor] single clip already exists, skipping")
                return clip_path

        self.task_manager.update_step("step_clip_generation", StepStatus.RUNNING)
        await self._emit("clip_gen", "running", "生成单段循环视频...", 0.28)

        clip_dir = os.path.join(self.working_dir, "clip")
        os.makedirs(clip_dir, exist_ok=True)
        clip_path = os.path.join(clip_dir, "clip.mp4")

        vw = self._state.video_width
        vh = self._state.video_height

        for attempt in range(3):
            try:
                video_id = await self.video_generator.submit_video(
                    prompt=prompt,
                    reference_image_paths=[anchor_image_path],
                    duration=5,
                    width=vw,
                    height=vh,
                )
                video_output = await self.video_generator.wait_for_video(video_id)
                video_output.save(clip_path)
                self._save_task(clip_dir, video_id)
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(
                        "[Anchor] single clip attempt %d failed: %s, retrying...",
                        attempt + 1, e,
                    )
                    await asyncio.sleep(15 * (attempt + 1))
                else:
                    raise

        self._state.step_clip_generation = StepStatus.COMPLETED
        self.task_manager.update_state(step_clip_generation=StepStatus.COMPLETED)
        await self._emit("clip_gen", "completed", "单段循环视频生成完成", 0.55)
        return clip_path

    async def _step_audio(self) -> object:
        """生成整段 TTS 音频，返回 sub_maker 供字幕步骤。"""
        if self._state.step_audio == StepStatus.COMPLETED:
            logger.info("[Anchor] Step audio: already completed, resuming")
            return None

        self.task_manager.update_step("step_audio", StepStatus.RUNNING)
        await self._emit("audio", "running", "生成读稿音频...", 0.18)

        full_text = self._state.script_text
        if not full_text:
            logger.warning("[Anchor] audio: empty text, skipping")
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
        self.task_manager.update_step("step_audio", StepStatus.COMPLETED)
        await self._emit("audio", "completed", "读稿音频生成完成", 0.28)
        return sub_maker

    async def _step_subtitle(self, sub_maker: object = None) -> None:
        """生成整段 SRT 字幕。"""
        if self._state.step_subtitle == StepStatus.COMPLETED:
            logger.info("[Anchor] Step subtitle: already completed, resuming")
            return

        self.task_manager.update_step("step_subtitle", StepStatus.RUNNING)
        await self._emit("subtitle", "running", "生成字幕...", 0.65)

        full_text = self._state.script_text
        if not full_text:
            logger.warning("[Anchor] subtitle: empty text, skipping")
            return

        subtitle_config = self._state.subtitle_config
        audio_duration = max(len(full_text) / _CHARS_PER_SEC, 2.0)

        segment_texts = [full_text]
        segment_durations = [audio_duration]

        await self._emit(
            "subtitle", "running",
            f"生成整段字幕 ({len(full_text)} 字)...",
            0.65,
        )

        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=segment_texts,
            segment_durations=segment_durations,
            subtitle_config=subtitle_config,
            sub_maker=sub_maker,
            audio_path=self._state.combined_audio or "",
            screenwriter=self.screenwriter,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
            role="anchorperson digital human",
        )

        if styles_path:
            self._state.subtitle_styles_path = styles_path
            self.task_manager.update_state(subtitle_styles_path=styles_path)

        self._state.combined_subtitle = srt_path
        self.task_manager.update_state(combined_subtitle=srt_path)
        self.task_manager.update_step("step_subtitle", StepStatus.COMPLETED)
        await self._emit("subtitle", "completed", "字幕生成完成", 0.75)

    async def _step_composite_anchor(self, clip_path: str) -> str:
        """循环单段视频 + 叠加音频 + 字幕（使用 composite_anchor_video）。"""
        output_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(output_path):
            logger.info("[Anchor] composite: final video already exists, skipping")
            return output_path

        self.task_manager.update_step("step_concatenation", StepStatus.RUNNING)
        await self._emit(
            "concatenate", "running",
            "循环拼接视频+音频+字幕...", 0.80,
        )

        audio_path = self._state.combined_audio or ""
        audio_duration = 0.0
        if audio_path and os.path.exists(audio_path):
            from core.compositor.concatenator import VideoConcatenator as VC
            audio_duration = VC._get_duration(audio_path)

        has_subtitle = (
            self._state.subtitle_config.enabled
            and bool(self._state.combined_subtitle)
        )

        await asyncio.to_thread(
            VideoConcatenator.composite_anchor_video,
            clip_path=clip_path,
            audio_path=audio_path,
            srt_path=self._state.combined_subtitle if has_subtitle else None,
            output_path=output_path,
            audio_duration=audio_duration,
            subtitle_style=self._state.subtitle_config.style if has_subtitle else None,
            subtitle_styles_path=self._state.subtitle_styles_path or None,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )

        self._state.step_concatenation = StepStatus.COMPLETED
        self.task_manager.update_state(step_concatenation=StepStatus.COMPLETED)
        await self._emit("concatenate", "completed", "循环拼接完成", 0.95)
        return output_path

    # ==================================================================
    # Utilities
    # ==================================================================

    def _check_shutdown(self) -> None:
        if self._is_shutdown():
            raise PipelineShutdown("Pipeline shutdown requested")

    @staticmethod
    def _make_curl(video_id: str) -> str:
        return (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"'
        )

    def _save_task(self, clip_dir: str, video_id: str) -> None:
        task_file = os.path.join(clip_dir, "task.json")
        with open(task_file, "w") as f:
            json.dump({"video_id": video_id}, f, indent=2)
        curl_file = os.path.join(clip_dir, "curl.sh")
        with open(curl_file, "w") as f:
            f.write(self._make_curl(video_id) + "\n")
