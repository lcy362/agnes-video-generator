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
