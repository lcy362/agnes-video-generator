"""core.pipelines.creative.steps_script — 编剧步骤 mixin（v5.0 Batch 4 / 4.2 拆分）"""
import asyncio
import json
import logging
import os
from typing import List

from core.async_io import read_text, write_text
from core.pipelines import PipelineShutdown
from models.task import SceneTask, StepStatus

logger = logging.getLogger(__name__)

# 编剧步骤进度常量（scene_config 阶段）
_PROGRESS_SCENE_CONFIG_DONE = 0.02
_PROGRESS_SCENE_CONFIG_FAILED = 0.0

# 编剧步骤进度映射：分镜阶段线性推进 0.0 → 0.15（story → script）
_PROGRESS_IMAGE_ANALYSIS_START = 0.0
_PROGRESS_IMAGE_ANALYSIS_DONE = 0.05
_PROGRESS_SCENE_EXTRACT_START = 0.01
_PROGRESS_STORY_START = 0.05
_PROGRESS_STORY_DONE = 0.1
_PROGRESS_SCRIPT_START = 0.1
_PROGRESS_SCRIPT_DONE = 0.15
# 角色参考图属于参考图阶段（0.15 → 0.25），在尾帧 prompt 之前生成
_PROGRESS_CHARACTER_REF_START = 0.15
_PROGRESS_CHARACTER_REF_T2I = 0.17
_PROGRESS_CHARACTER_REF_DONE = 0.2
_PROGRESS_END_FRAME_PROMPTS_START = 0.2
_PROGRESS_END_FRAME_PROMPTS_DONE = 0.25


class ScriptStepsMixin:
    """编剧步骤：图片分析 / 场景配置解析 / 故事 / 角色参考 / 脚本 / 尾帧 prompt。

    v5.0 Batch 4（4.2）拆分自 CreativeVideoPipeline，经 MRO 组合回主类。
    """

    # ==================================================================
    # Step 0: Image Analysis
    # ==================================================================

    async def _step_image_analysis(
        self, reference_image: str, end_frame_images: list
    ) -> str:
        """Analyze reference and end-frame images via the screenwriter LLM.

        Args:
            reference_image: Path or URL to the user-provided reference image.
            end_frame_images: List of paths/URLs for user-provided end frames.

        Returns:
            Image analysis text, or empty string if no images to analyze.
        """
        if self._state.step_image_analysis == StepStatus.COMPLETED:
            analysis_file = self._state.image_analysis_file
            if os.path.exists(analysis_file):
                content = await read_text(analysis_file)
                # 检测之前分析失败留下的错误文本，强制重新分析
                if "(分析失败" in content:
                    logger.warning(
                        "[Pipeline] Step image_analysis: detected error text in saved file, re-running"
                    )
                    self._state.step_image_analysis = StepStatus.PENDING
                    self.task_manager.update_step("step_image_analysis", StepStatus.PENDING)
                else:
                    logger.info("[Pipeline] Step image_analysis: SKIP (already completed, file exists)")
                    return content
            else:
                logger.warning("[Pipeline] Step image_analysis: marked completed but file missing, re-running")
                return ""

        logger.info("[Pipeline] Step image_analysis: RUNNING")
        images_to_analyze: List[str] = []
        if reference_image:
            ref_valid = reference_image.startswith(("http://", "https://")) or os.path.exists(reference_image)
            if ref_valid:
                images_to_analyze.append(reference_image)
        if end_frame_images:
            for p in end_frame_images:
                if p and (p.startswith(("http://", "https://")) or os.path.exists(p)):
                    images_to_analyze.append(p)

        if not images_to_analyze:
            self._state.step_image_analysis = StepStatus.COMPLETED
            self.task_manager.update_step("step_image_analysis", StepStatus.COMPLETED)
            return ""

        await self._emit("image_analysis", "running", f"分析 {len(images_to_analyze)} 张图片...", _PROGRESS_IMAGE_ANALYSIS_START)
        image_context = await asyncio.to_thread(
            self.screenwriter.describe_images, images_to_analyze,
            cache_dir=self.working_dir,
            language_hint=self._state.idea or "",
        )

        analysis_file = os.path.join(self.working_dir, "image_analysis.txt")
        await write_text(analysis_file, image_context)

        self._state.step_image_analysis = StepStatus.COMPLETED
        self._state.image_analysis_file = analysis_file
        self.task_manager.update_state(
            step_image_analysis=StepStatus.COMPLETED,
            image_analysis_file=analysis_file,
        )
        await self._emit("image_analysis", "completed", f"图片分析完成 ({len(image_context)} 字符)", _PROGRESS_IMAGE_ANALYSIS_DONE)
        return image_context

    # ==================================================================
    # Step 0: Resolve Scene Configuration (v3.x)
    # ==================================================================

    async def _step_resolve_scene_config(self) -> None:
        """Resolve scene count and per-scene durations.

        Two modes:
        - ``duration_source == "prompt"``: LLM extracts scene info from the
          user's idea.  Aborts the task on extraction failure.
        - ``duration_source == "manual"``: Use user-provided
          ``scene_count`` and ``scene_durations`` directly.
        """
        duration_source = self._state.duration_source
        idea = self._state.idea
        scene_count = self._state.scene_count
        scene_durations = list(self._state.scene_durations) if self._state.scene_durations else []

        # v6.1 断点续传：场景配置已确定（COMPLETED 且有结果）→ 直接跳过。
        # 恢复执行（暂停点继续 / resume）会重跑 _build_scenes，prompt 模式下
        # 无此检查会重复调用 LLM 提取场景信息，造成「恢复阶段」明显的等待。
        if (
            self._state.step_scene_config == StepStatus.COMPLETED
            and self._state.scene_count > 0
            and self._state.scene_durations
        ):
            logger.info("[Pipeline] Step scene_config: SKIP (already resolved)")
            return

        logger.info(
            f"[Pipeline] Resolving scene config: source={duration_source}, "
            f"manual_count={scene_count}, manual_durations={scene_durations}"
        )

        if duration_source == "prompt":
            await self._emit(
                "scene_config", "running",
                "正在从创意描述中提取场景信息...", _PROGRESS_SCENE_EXTRACT_START,
            )
            try:
                info = await asyncio.to_thread(
                    self.screenwriter.extract_scene_info_from_idea,
                    idea,
                    self._state.style,
                )
                extracted_count = info["scene_count"]
                extracted_durations = info["durations"]
                self._state.scene_count = extracted_count
                self._state.scene_durations = extracted_durations
                self.task_manager.update_state(
                    scene_count=extracted_count,
                    scene_durations=extracted_durations,
                )
                logger.info(
                    f"[Pipeline] Extracted from prompt: "
                    f"{extracted_count} scenes, durations={extracted_durations}"
                )
                await self._emit(
                    "scene_config", "completed",
                    f"从 prompt 提取: {extracted_count} 个场景, "
                    f"时长 {extracted_durations}",
                    _PROGRESS_SCENE_CONFIG_DONE,
                    {
                        "scene_count": extracted_count,
                        "durations": extracted_durations,
                        "source": "prompt",
                    },
                )
            except Exception as e:
                logger.error(f"[Pipeline] Failed to extract scene info from prompt: {e}")
                await self._emit(
                    "scene_config", "failed",
                    f"无法从创意描述中提取场景信息: {e}",
                    _PROGRESS_SCENE_CONFIG_FAILED,
                )
                raise PipelineShutdown(
                    f"场景信息提取失败: {e}. "
                    f"请手动设置场景数和每场景时长后重试。"
                ) from e
        else:
            # manual mode: apply user-provided values
            if scene_count <= 0:
                scene_count = 1
                self._state.scene_count = scene_count
            if not scene_durations:
                # fallback: all scenes 5s
                scene_durations = [5] * scene_count
            elif len(scene_durations) < scene_count:
                # pad with last value
                while len(scene_durations) < scene_count:
                    scene_durations.append(scene_durations[-1])
            elif len(scene_durations) > scene_count:
                scene_durations = scene_durations[:scene_count]

            self._state.scene_durations = scene_durations
            self.task_manager.update_state(
                scene_count=scene_count,
                scene_durations=scene_durations,
            )
            logger.info(
                f"[Pipeline] Manual scene config: "
                f"{scene_count} scenes, durations={scene_durations}"
            )
            await self._emit(
                "scene_config", "completed",
                f"场景配置: {scene_count} 个场景, "
                f"时长 {scene_durations}",
                _PROGRESS_SCENE_CONFIG_DONE,
                {
                    "scene_count": scene_count,
                    "durations": scene_durations,
                    "source": "manual",
                },
            )

        self._state.step_scene_config = StepStatus.COMPLETED
        self.task_manager.update_step(
            "step_scene_config", StepStatus.COMPLETED
        )

    # ==================================================================
    # Step 1: Story
    # ==================================================================

    async def _step_story(self, image_context: str) -> str:
        """Develop a story from the user idea, requirements, style, and image context.

        Args:
            image_context: Text from the image-analysis step (may be empty).

        Returns:
            Generated story text.
        """
        if self._state.step_story == StepStatus.COMPLETED:
            story_path = self._state.story_file
            if os.path.exists(story_path):
                logger.info("[Pipeline] Step story: SKIP (already completed, file exists)")
                return await read_text(story_path)
            logger.warning("[Pipeline] Step story: marked completed but file missing, re-running")

        logger.info("[Pipeline] Step story: RUNNING")
        await self._emit("story", "running", "正在生成故事...", _PROGRESS_STORY_START)
        story = await asyncio.to_thread(
            self.screenwriter.develop_story,
            self._state.idea,
            "",
            self._style_with_language_directive(),
            image_context,
            self._state.scene_count,
            self._state.scene_durations,
        )

        story_path = os.path.join(self.working_dir, "story.txt")
        await write_text(story_path, story)

        self._state.step_story = StepStatus.COMPLETED
        self._state.story_file = story_path
        self.task_manager.update_state(
            step_story=StepStatus.COMPLETED,
            story_file=story_path,
        )
        await self._emit("story", "completed", f"故事生成完成 ({len(story)} 字符)", _PROGRESS_STORY_DONE)
        return story

    # ==================================================================
    # Step 2: Character Reference
    # ==================================================================

    async def _step_character_reference(self, story: str) -> str:
        """Generate or reuse a character reference image.

        If the user supplied a reference image it is returned directly.
        Otherwise a character description is extracted from *story* and fed
        to the image generator (t2i).

        Args:
            story: Generated story text from Step 1.

        Returns:
            File path to the character reference image.
        """
        if self._state.step_character_ref == StepStatus.COMPLETED:
            ref_path = self._state.character_ref_file
            if ref_path and os.path.exists(ref_path):
                logger.info("[Pipeline] Step character_ref: SKIP (already completed, file exists)")
                return ref_path
            logger.warning("[Pipeline] Step character_ref: marked completed but file missing, re-running")

        if self._state.reference_image:
            logger.info("[Pipeline] Step character_ref: SKIP (user-provided reference image)")
            self._state.step_character_ref = StepStatus.COMPLETED
            self._state.character_ref_file = self._state.reference_image
            self.task_manager.update_state(
                step_character_ref=StepStatus.COMPLETED,
                character_ref_file=self._state.reference_image,
            )
            await self._emit("character_ref", "completed", "使用用户提供的参考图", _PROGRESS_CHARACTER_REF_DONE)
            return self._state.reference_image

        ref_prompt_path = os.path.join(self.working_dir, "character_ref_prompt.txt")
        ref_img_path = os.path.join(self.working_dir, "character_reference.png")

        if os.path.exists(ref_img_path) and os.path.exists(ref_prompt_path):
            self._state.step_character_ref = StepStatus.COMPLETED
            self._state.character_ref_file = ref_img_path
            self._state.character_ref_prompt = await read_text(ref_prompt_path)
            self.task_manager.update_state(
                step_character_ref=StepStatus.COMPLETED,
                character_ref_file=ref_img_path,
            )
            await self._emit("character_ref", "completed", "角色参考图已缓存", _PROGRESS_CHARACTER_REF_DONE)
            return ref_img_path

        await self._emit("character_ref", "running", "正在提取角色描述并生成参考图...", _PROGRESS_CHARACTER_REF_START)
        char_prompt = await asyncio.to_thread(
            self.screenwriter.extract_character_description, story, self._state.style
        )
        await write_text(ref_prompt_path, char_prompt)

        await self._emit("character_ref", "running", "正在生成角色参考图 (t2i)...", _PROGRESS_CHARACTER_REF_T2I)
        img_output = await self.image_generator.generate_single_image(
            prompt=char_prompt,
            size=f"{self._state.video_width}x{self._state.video_height}",
        )
        await img_output.save(ref_img_path)

        self._state.step_character_ref = StepStatus.COMPLETED
        self._state.character_ref_prompt = char_prompt
        self._state.character_ref_file = ref_img_path
        self.task_manager.update_state(
            step_character_ref=StepStatus.COMPLETED,
            character_ref_prompt=char_prompt,
            character_ref_file=ref_img_path,
        )
        await self._emit("character_ref", "completed", "角色参考图生成完成", _PROGRESS_CHARACTER_REF_DONE)
        return ref_img_path

    # ==================================================================
    # Step 3: Script
    # ==================================================================

    async def _step_script(self, story: str) -> list:
        """Write a scene-by-scene script from the story.

        Args:
            story: Generated story text.

        Returns:
            List of scene descriptions (dicts or strings).
        """
        if self._state.step_script == StepStatus.COMPLETED:
            script_path = self._state.script_file
            if os.path.exists(script_path):
                logger.info("[Pipeline] Step script: SKIP (already completed, file exists)")
                scenes = json.loads(await read_text(script_path))
                if self._state.scene_count == len(scenes):
                    return scenes
                logger.warning("[Pipeline] Step script: scene count mismatch, re-running")
            else:
                logger.warning("[Pipeline] Step script: marked completed but file missing, re-running")

        logger.info("[Pipeline] Step script: RUNNING")
        await self._emit("script", "running", "正在编写脚本...", _PROGRESS_SCRIPT_START)
        scenes = await asyncio.to_thread(
            self.screenwriter.write_script, story, "",
            self._style_with_language_directive(),
            self._state.scene_count,
            self._state.scene_durations,
        )

        script_path = os.path.join(self.working_dir, "script.json")
        await write_text(script_path, json.dumps(scenes, ensure_ascii=False, indent=2))

        self._state.scene_count = len(scenes)
        # Map durations to scenes: use scene_durations list, pad/trim as needed
        durations = list(self._state.scene_durations) if self._state.scene_durations else []
        if not durations:
            durations = [int(self._state.video_duration)] * len(scenes)
        elif len(durations) < len(scenes):
            while len(durations) < len(scenes):
                durations.append(durations[-1])
        elif len(durations) > len(scenes):
            durations = durations[:len(scenes)]

        if not self._state.scenes:
            self._state.scenes = [
                SceneTask(index=i, duration=durations[i] if i < len(durations) else 5)
                for i in range(len(scenes))
            ]
        elif len(self._state.scenes) != len(scenes):
            # Re-create scenes to match new scene count (resume with different config)
            self._state.scenes = [
                SceneTask(index=i, duration=durations[i] if i < len(durations) else 5)
                for i in range(len(scenes))
            ]
        else:
            # Update existing scenes' durations from the resolved config
            for i, scene_obj in enumerate(self._state.scenes):
                if i < len(durations):
                    scene_obj.duration = durations[i]

        self._state.scene_durations = durations
        logger.info(
            f"[Pipeline] Script: {len(scenes)} scenes, "
            f"durations={[s.duration for s in self._state.scenes]}"
        )

        self._state.step_script = StepStatus.COMPLETED
        self._state.script_file = script_path
        self.task_manager.update_state(
            step_script=StepStatus.COMPLETED,
            script_file=script_path,
            scene_count=len(scenes),
            scenes=[s.model_dump() for s in self._state.scenes],
        )
        await self._emit("script", "completed", f"脚本完成，共 {len(scenes)} 个场景", _PROGRESS_SCRIPT_DONE)
        return scenes

    # ==================================================================
    # Step 3.5: End Frame Prompts (keyframes mode)
    # ==================================================================

    async def _step_end_frame_prompts(self, story: str, scenes: list) -> list:
        """Generate end-frame prompt for each scene (keyframes mode only).

        Args:
            story: Generated story text.
            scenes: List of scene descriptions from the script step.

        Returns:
            List of end-frame prompt strings, or empty list when not in
            keyframes mode.
        """
        if self._state.chaining_mode != "keyframes":
            return []

        if self._state.step_end_frame_prompts == StepStatus.COMPLETED:
            prompts_path = self._state.end_frame_prompts_file
            if os.path.exists(prompts_path):
                logger.info("[Pipeline] Step end_frame_prompts: SKIP (already completed, file exists)")
                return json.loads(await read_text(prompts_path))
            logger.warning("[Pipeline] Step end_frame_prompts: marked completed but file missing, re-running")

        logger.info("[Pipeline] Step end_frame_prompts: RUNNING")
        await self._emit("end_frame_prompts", "running", "正在生成尾帧提示词...", _PROGRESS_END_FRAME_PROMPTS_START)
        character_appearance = await asyncio.to_thread(
            self.screenwriter.get_character_appearance, story
        )
        # 持久化角色外观文本，支持断点续传一致性（批次3）
        self._state.character_appearance = character_appearance
        self.task_manager.update_state(character_appearance=character_appearance)
        end_frame_prompts = await asyncio.to_thread(
            self.screenwriter.generate_end_frame_prompts,
            scenes, self._state.style, character_appearance
        )

        prompts_path = os.path.join(self.working_dir, "end_frame_prompts.json")
        await write_text(prompts_path, json.dumps(end_frame_prompts, ensure_ascii=False, indent=2))

        self._state.step_end_frame_prompts = StepStatus.COMPLETED
        self._state.end_frame_prompts_file = prompts_path
        self.task_manager.update_state(
            step_end_frame_prompts=StepStatus.COMPLETED,
            end_frame_prompts_file=prompts_path,
        )
        await self._emit("end_frame_prompts", "completed", f"尾帧提示词完成，共 {len(end_frame_prompts)} 个", _PROGRESS_END_FRAME_PROMPTS_DONE)
        return end_frame_prompts
