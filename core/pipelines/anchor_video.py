"""core.pipelines.anchor_video -- 数字人口播流水线（类型 4）

支持两种音频模式：
  - post_stitch: 生成一段短 i2v 视频循环 + TTS 后拼接音频（音频可控，嘴型较难匹配）
  - model:      交由视频模型自身生成音频（音频由模型控制，效果不可控）

v4.0 重构：继承 MultiScenePipeline，复用模板方法 run() 与步骤编排。
锚点形象图生成放入 _build_reference_images，clip prompt 生成放入 _build_scenes，
视频/音频/字幕/合成按模式覆写。
"""

import asyncio
import logging
import os
import re
from typing import Callable, Optional

from core.api.agnes_image import AgnesImageAPI
from core.api.agnes_video import AgnesVideoAPI, VideoTaskCancelled
from core.compositor.concatenator import VideoConcatenator
from core.pipelines import MultiScenePipeline
from core.screenwriter import Screenwriter
from models.task import (
    AnchorVideoTask,
    SceneTask,
    StepStatus,
)

logger = logging.getLogger(__name__)

# 单片段重试间隔基数（秒）：delay = 基数 * (attempt + 1)
_CLIP_RETRY_INTERVAL_BASE_SECONDS = 15

# 主播形象生成阶段起始进度
_PROGRESS_ANCHOR_IMAGE = 0.02

# 数字人流水线进度映射（阶段内固定值；保持原有行为不变）
_PROGRESS_ANCHOR_IMAGE_DONE = 0.08
_PROGRESS_CLIP_PROMPTS_START = 0.12
_PROGRESS_CLIP_PROMPTS_DONE = 0.18
_PROGRESS_CLIP_GEN_START = 0.28
_PROGRESS_CLIP_GEN_DONE = 0.55
_PROGRESS_AUDIO_START = 0.55
# 注意：post_stitch 音频完成态回退 0.28（历史行为，保持不变）
_PROGRESS_AUDIO_DONE = 0.28
_PROGRESS_SUBTITLE_START = 0.65
_PROGRESS_SUBTITLE_DONE = 0.75
_PROGRESS_CONCAT_START = 0.80

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


class AnchorPipeline(MultiScenePipeline):
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
        chat_model: str = "agnes-2.5-flash",
        image_model: str = "agnes-image-2.5-flash",
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

    # ------------------------------------------------------------------
    # 模板钩子
    # ------------------------------------------------------------------

    def _get_watermark_language_text(self) -> str:
        return self._state.script_text

    def _get_default_anchor_prompt(self) -> str:
        """根据 script_text 语言返回合适的主播默认描述。"""
        text = (self._state.script_text or "").strip()
        if re.search(r'[\u4e00-\u9fff]', text):
            return _DEFAULT_ANCHOR_PROMPT_ZH
        return _DEFAULT_ANCHOR_PROMPT_EN

    # ------------------------------------------------------------------
    # 数据来源：参考图（主播形象）
    # ------------------------------------------------------------------

    async def _build_reference_images(self) -> None:
        """Step: 生成主播形象图（t2i / i2i）。"""
        prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()
        output_path = os.path.join(self.working_dir, "anchor.png")

        if os.path.exists(output_path):
            self._state.anchor_image_path = output_path
            logger.info("[Anchor] anchor image already exists, skipping")
            return

        ref_image = self._state.anchor_reference_image
        size = f"{self._state.video_width}x{self._state.video_height}"

        await self._emit(
            "generate_anchor", "running",
            "生成主播形象图..." if not ref_image else "基于参考图生成主播形象...",
            _PROGRESS_ANCHOR_IMAGE,
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
            await img_output.save(output_path)
        except Exception as e:
            logger.error(f"[Anchor] Anchor image generation failed: {e}")
            raise RuntimeError(f"主播形象生成失败: {e}")

        self._state.anchor_image_path = output_path
        self.task_manager.update_state(anchor_image_path=output_path)
        await self._emit("generate_anchor", "completed", "主播形象生成完成", _PROGRESS_ANCHOR_IMAGE_DONE)

    # ------------------------------------------------------------------
    # 数据来源：分镜（单段 clip 的 prompt）
    # ------------------------------------------------------------------

    async def _build_scenes(self) -> None:
        """构建单段场景：生成循环优化 / 含口播的视频 prompt。

        v6.1 断点续传：场景 prompt 已生成（scenes 已填充）→ 直接复用，
        避免恢复执行（暂停点继续 / resume）重复调用 LLM。
        """
        if self._state.scenes and self._state.scenes[0].scene_prompt:
            logger.info("[Anchor] _build_scenes: SKIP (scene prompt already exists)")
            return
        audio_source = self._state.audio_source or "post_stitch"
        anchor_prompt = self._state.anchor_prompt or self._get_default_anchor_prompt()

        await self._emit(
            "clip_prompts", "running",
            "生成循环优化动态描述..." if audio_source == "post_stitch"
            else "生成含口播的视频描述...", _PROGRESS_CLIP_PROMPTS_START,
        )

        if audio_source == "post_stitch":
            prompt = await asyncio.to_thread(
                self.screenwriter.generate_anchor_smooth_loop_prompt,
                anchor_prompt=anchor_prompt,
            )
            prompt = prompt.strip()
            self.save_prompts({
                "anchor_prompt": anchor_prompt,
                "smooth_loop_prompt": prompt,
            })
        else:
            full_text = self._state.script_text
            prompt = await asyncio.to_thread(
                self.screenwriter.generate_anchor_model_audio_prompt,
                anchor_prompt=anchor_prompt,
                script_text=full_text,
            )
            prompt = prompt.strip()
            self.save_prompts({
                "anchor_prompt": anchor_prompt,
                "model_audio_prompt": prompt,
            })

        logger.info("[Anchor] clip_prompt: %s...", prompt[:80])
        self._state.scenes = [SceneTask(index=0, scene_prompt=prompt, duration=5)]
        self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])
        await self._emit("clip_prompts", "completed", "动态描述生成完成", _PROGRESS_CLIP_PROMPTS_DONE)

    # ------------------------------------------------------------------
    # 视频生成（单段 i2v 循环，覆写通用实现）
    # ------------------------------------------------------------------

    async def _generate_videos(self) -> None:
        """生成单段 i2v 视频（5 秒，循环用）。"""
        scene = self._state.scenes[0]
        anchor_image_path = self._state.anchor_image_path
        prompt = scene.scene_prompt

        clip_dir = os.path.join(self.working_dir, "clip")
        os.makedirs(clip_dir, exist_ok=True)
        clip_path = os.path.join(clip_dir, "clip.mp4")

        if os.path.exists(clip_path):
            scene.video_file = clip_path
            logger.info("[Anchor] single clip already exists, skipping")
            return

        self.task_manager.update_step("step_clip_generation", StepStatus.RUNNING)
        await self._emit("clip_gen", "running", "生成单段循环视频...", _PROGRESS_CLIP_GEN_START)

        vw = self._state.video_width
        vh = self._state.video_height

        saved_video_id = self._load_task_json(clip_dir)
        if saved_video_id:
            video_id = saved_video_id
        else:
            video_id = await self.video_generator.submit_video(
                prompt=prompt,
                reference_image_paths=[anchor_image_path],
                duration=5,
                width=vw,
                height=vh,
            )
            self._save_task_json(clip_dir, {"video_id": video_id})

        for attempt in range(3):
            try:
                video_output = await self.video_generator.wait_for_video(video_id)
                await video_output.save(clip_path)
                break
            except VideoTaskCancelled:
                # 优化路线图 0.2：用户停止不是临时错误，不重试、直接穿透
                raise
            except Exception as e:
                if attempt < 2:
                    logger.warning(
                        "[Anchor] single clip attempt %d failed: %s, retrying...",
                        attempt + 1, e,
                    )
                    await asyncio.sleep(_CLIP_RETRY_INTERVAL_BASE_SECONDS * (attempt + 1))
                else:
                    raise

        scene.video_file = clip_path
        self.task_manager.update_step("step_clip_generation", StepStatus.COMPLETED)
        await self._emit("clip_gen", "completed", "单段循环视频生成完成", _PROGRESS_CLIP_GEN_DONE)

    # ------------------------------------------------------------------
    # 音频生成（覆写通用实现）
    # ------------------------------------------------------------------

    # v6.0 P3：model 音频模式下 audio/subtitle 步骤无实际产物（直接 return），
    # 手动模式不应在无产物的检查点上暂停；post_stitch 模式全部可暂停。
    def _get_pausable_steps(self) -> set:
        from core.pipelines import _STEP_TO_CHECKPOINT

        steps = set(_STEP_TO_CHECKPOINT.keys())
        if (self._state.audio_source or "post_stitch") == "model":
            steps.discard("step_audio")
            steps.discard("step_subtitle")
        return steps

    async def _generate_audio(self) -> object:
        """生成整段 TTS 音频（post_stitch 模式）；model 模式返回 None。"""
        audio_source = self._state.audio_source or "post_stitch"
        if audio_source == "model":
            logger.info("[Anchor] model audio mode: skip TTS")
            return None

        full_text = self._state.script_text
        if not full_text:
            logger.warning("[Anchor] audio: empty text, skipping")
            return None

        audio_path = os.path.join(self.working_dir, "full_narration.mp3")
        # v5.x 产物规范前置：导出读稿纯文本（供外部 Agent/工具处理）
        self._save_narration_txt(full_text, audio_path)

        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[Anchor] audio: file already exists, skipping")
            # 续传：音频已存在则仅重采 cues，避免字幕退回 legacy 启发式
            return await self._recover_sub_maker(
                full_text, self._state.audio_config, self._state.subtitle_config,
                audio_path,
            )

        audio_config = self._state.audio_config
        await self._emit("audio", "running", f"生成整段读稿 ({len(full_text)} 字)...", _PROGRESS_AUDIO_START)

        sub_maker = await self._generate_audio_with_fallback(
            output_path=audio_path,
            text=full_text,
            audio_config=audio_config,
            subtitle_config=self._state.subtitle_config,
            duration_sec=len(full_text) / _CHARS_PER_SEC,
            empty_placeholder="",
        )

        self._state.combined_audio = audio_path
        self.task_manager.update_state(combined_audio=audio_path)
        await self._emit("audio", "completed", "读稿音频生成完成", _PROGRESS_AUDIO_DONE)
        return sub_maker

    # ------------------------------------------------------------------
    # 字幕生成（覆写通用实现）
    # ------------------------------------------------------------------

    async def _generate_subtitles(self, sub_maker: object = None) -> None:
        """生成整段 SRT 字幕（post_stitch 模式）；model 模式跳过。"""
        audio_source = self._state.audio_source or "post_stitch"
        if audio_source == "model":
            logger.info("[Anchor] model audio mode: skip subtitle")
            return

        full_text = self._state.script_text
        if not full_text:
            logger.warning("[Anchor] subtitle: empty text, skipping")
            return

        subtitle_config = self._state.subtitle_config
        audio_duration = max(len(full_text) / _CHARS_PER_SEC, 2.0)
        segment_texts = [full_text]
        segment_durations = [audio_duration]

        await self._emit("subtitle", "running", f"生成整段字幕 ({len(full_text)} 字)...", _PROGRESS_SUBTITLE_START)

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
        await self._emit("subtitle", "completed", "字幕生成完成", _PROGRESS_SUBTITLE_DONE)

    # ------------------------------------------------------------------
    # 合成（覆写通用实现）
    # ------------------------------------------------------------------

    async def _composite_final(self) -> str:
        """循环单段视频 + 叠加音频 + 字幕（post_stitch）；model 模式返回 clip。"""
        audio_source = self._state.audio_source or "post_stitch"
        clip_path = self._state.scenes[0].video_file

        if audio_source == "model":
            logger.info("[Anchor] model audio mode: return clip directly (watermark by template)")
            return clip_path

        output_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(output_path):
            logger.info("[Anchor] composite: final video already exists, skipping")
            return output_path

        audio_path = self._state.combined_audio or ""
        audio_duration = 0.0
        if audio_path and os.path.exists(audio_path):
            audio_duration = VideoConcatenator._get_duration(audio_path)

        has_subtitle = (
            self._state.subtitle_config.enabled
            and bool(self._state.combined_subtitle)
        )

        await self._emit("concatenate", "running", "循环拼接视频+音频+字幕...", _PROGRESS_CONCAT_START)

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

        logger.info("[Anchor] composite: final video → %s", output_path)
        return output_path
