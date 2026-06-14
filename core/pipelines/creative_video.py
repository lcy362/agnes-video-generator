"""core.pipelines.creative_video -- Creative long-form video pipeline (Type 2).

Ports the original ``core/pipeline.py`` VideoPipeline to the new pipeline
architecture with audio/subtitle support (v2.0).

Steps:
    image_analysis -> story -> character_reference -> script ->
    end_frame_prompts -> pregenerate_end_frames -> generate_videos ->
    audio_subtitle -> concatenate
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
from models.task import CreativeVideoTask, SceneTask, StepStatus

_CHARS_PER_SEC = 4.0
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？.!?])")


def _trim_to_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    candidate = text[:max_chars]
    # find the last sentence boundary within the valid prefix
    matches = list(_SENTENCE_BOUNDARY_RE.finditer(candidate))
    if matches and matches[-1].end() > max_chars * 0.4:
        return text[: matches[-1].end()]
    return candidate[:max_chars]

logger = logging.getLogger(__name__)


class CreativeVideoPipeline(BasePipeline):
    """Creative long-form video generation pipeline with audio/subtitle support.

    Generates multi-scene videos from a user idea, with optional TTS narration
    and subtitle overlays.  Supports three chaining modes (``independent``,
    ``chained/ti2vid``, ``keyframes``) and full resume from any completed step.

    Inherits shared infrastructure (progress callbacks, shutdown control,
    task-manager integration) from :class:`BasePipeline`.
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
        """Initialize the creative video pipeline.

        Args:
            api_key: Agnes API key for authentication.
            task_id: Unique identifier for this task.
            dir_name: Optional working-directory name; defaults to *task_id*.
            chat_model: Model name for the screenwriter (LLM chat).
            image_model: Model name for image generation (t2i).
            video_model: Model name for video generation.
            progress_callback: Async callable ``(step, status, message, progress, data)``
                for reporting progress to the caller.
            shutdown_event: External ``asyncio.Event`` that signals a graceful
                shutdown request.
        """
        super().__init__(api_key, task_id, dir_name, progress_callback, shutdown_event)

        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self.image_generator = AgnesImageAPI(api_key=api_key, model=image_model)
        self.video_generator = AgnesVideoAPI(api_key=api_key, model=video_model)
        self.video_generator.shutdown_event = shutdown_event

        self._state: Optional[CreativeVideoTask] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> Optional[CreativeVideoTask]:
        """Current pipeline task state."""
        return self._state

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
                logger.info("[Pipeline] Step image_analysis: SKIP (already completed, file exists)")
                with open(analysis_file, "r") as f:
                    return f.read()
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

        await self._emit("image_analysis", "running", f"分析 {len(images_to_analyze)} 张图片...", 0.0)
        image_context = await asyncio.to_thread(
            self.screenwriter.describe_images, images_to_analyze, cache_dir=self.working_dir
        )

        analysis_file = os.path.join(self.working_dir, "image_analysis.txt")
        with open(analysis_file, "w") as f:
            f.write(image_context)

        self._state.step_image_analysis = StepStatus.COMPLETED
        self._state.image_analysis_file = analysis_file
        self.task_manager.update_state(
            step_image_analysis=StepStatus.COMPLETED,
            image_analysis_file=analysis_file,
        )
        await self._emit("image_analysis", "completed", f"图片分析完成 ({len(image_context)} 字符)", 0.05)
        return image_context

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
                with open(story_path, "r") as f:
                    return f.read()
            logger.warning("[Pipeline] Step story: marked completed but file missing, re-running")

        logger.info("[Pipeline] Step story: RUNNING")
        await self._emit("story", "running", "正在生成故事...", 0.05)
        story = await asyncio.to_thread(
            self.screenwriter.develop_story,
            self._state.idea,
            self._state.user_requirement,
            self._state.style,
            image_context,
        )

        story_path = os.path.join(self.working_dir, "story.txt")
        with open(story_path, "w") as f:
            f.write(story)

        self._state.step_story = StepStatus.COMPLETED
        self._state.story_file = story_path
        self.task_manager.update_state(
            step_story=StepStatus.COMPLETED,
            story_file=story_path,
        )
        await self._emit("story", "completed", f"故事生成完成 ({len(story)} 字符)", 0.1)
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
            await self._emit("character_ref", "completed", "使用用户提供的参考图", 0.15)
            return self._state.reference_image

        ref_prompt_path = os.path.join(self.working_dir, "character_ref_prompt.txt")
        ref_img_path = os.path.join(self.working_dir, "character_reference.png")

        if os.path.exists(ref_img_path) and os.path.exists(ref_prompt_path):
            self._state.step_character_ref = StepStatus.COMPLETED
            self._state.character_ref_file = ref_img_path
            with open(ref_prompt_path, "r") as f:
                self._state.character_ref_prompt = f.read()
            self.task_manager.update_state(
                step_character_ref=StepStatus.COMPLETED,
                character_ref_file=ref_img_path,
            )
            await self._emit("character_ref", "completed", "角色参考图已缓存", 0.15)
            return ref_img_path

        await self._emit("character_ref", "running", "正在提取角色描述并生成参考图...", 0.1)
        char_prompt = await asyncio.to_thread(
            self.screenwriter.extract_character_description, story, self._state.style
        )
        with open(ref_prompt_path, "w") as f:
            f.write(char_prompt)

        await self._emit("character_ref", "running", "正在生成角色参考图 (t2i)...", 0.12)
        img_output = await self.image_generator.generate_single_image(
            prompt=char_prompt,
            size=f"{self._state.video_width}x{self._state.video_height}",
        )
        img_output.save(ref_img_path)

        self._state.step_character_ref = StepStatus.COMPLETED
        self._state.character_ref_prompt = char_prompt
        self._state.character_ref_file = ref_img_path
        self.task_manager.update_state(
            step_character_ref=StepStatus.COMPLETED,
            character_ref_prompt=char_prompt,
            character_ref_file=ref_img_path,
        )
        await self._emit("character_ref", "completed", "角色参考图生成完成", 0.15)
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
                with open(script_path, "r") as f:
                    scenes = json.load(f)
                if self._state.scene_count == len(scenes):
                    return scenes
                logger.warning("[Pipeline] Step script: scene count mismatch, re-running")
            else:
                logger.warning("[Pipeline] Step script: marked completed but file missing, re-running")

        logger.info("[Pipeline] Step script: RUNNING")
        await self._emit("script", "running", "正在编写脚本...", 0.15)
        scenes = await asyncio.to_thread(
            self.screenwriter.write_script, story, self._state.user_requirement, self._state.style
        )

        script_path = os.path.join(self.working_dir, "script.json")
        with open(script_path, "w") as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)

        self._state.scene_count = len(scenes)
        if not self._state.scenes:
            self._state.scenes = [
                SceneTask(index=i) for i in range(len(scenes))
            ]

        self._state.step_script = StepStatus.COMPLETED
        self._state.script_file = script_path
        self.task_manager.update_state(
            step_script=StepStatus.COMPLETED,
            script_file=script_path,
            scene_count=len(scenes),
            scenes=[s.model_dump() for s in self._state.scenes],
        )
        await self._emit("script", "completed", f"脚本完成，共 {len(scenes)} 个场景", 0.2)
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
                with open(prompts_path, "r") as f:
                    return json.load(f)
            logger.warning("[Pipeline] Step end_frame_prompts: marked completed but file missing, re-running")

        logger.info("[Pipeline] Step end_frame_prompts: RUNNING")
        await self._emit("end_frame_prompts", "running", "正在生成尾帧提示词...", 0.2)
        character_appearance = await asyncio.to_thread(
            self.screenwriter.get_character_appearance, story
        )
        end_frame_prompts = await asyncio.to_thread(
            self.screenwriter.generate_end_frame_prompts,
            scenes, self._state.style, character_appearance
        )

        prompts_path = os.path.join(self.working_dir, "end_frame_prompts.json")
        with open(prompts_path, "w") as f:
            json.dump(end_frame_prompts, f, ensure_ascii=False, indent=2)

        self._state.step_end_frame_prompts = StepStatus.COMPLETED
        self._state.end_frame_prompts_file = prompts_path
        self.task_manager.update_state(
            step_end_frame_prompts=StepStatus.COMPLETED,
            end_frame_prompts_file=prompts_path,
        )
        await self._emit("end_frame_prompts", "completed", f"尾帧提示词完成，共 {len(end_frame_prompts)} 个", 0.25)
        return end_frame_prompts

    # ==================================================================
    # Step 3.6: Pre-generate End Frames (keyframes mode)
    # ==================================================================

    async def _step_pregenerate_end_frames(
        self, scenes: list, end_frame_prompts: list, character_ref_path: str
    ) -> dict:
        """Pre-generate end-frame images for every scene (keyframes mode only).

        Args:
            scenes: List of scene descriptions.
            end_frame_prompts: Per-scene end-frame prompt strings.
            character_ref_path: Path to the character reference image.

        Returns:
            Dict mapping ``str(scene_idx)`` to end-frame file paths, or
            empty dict when not in keyframes mode.
        """
        if self._state.chaining_mode != "keyframes":
            return {}

        if self._state.step_end_frame_generation == StepStatus.COMPLETED:
            logger.info("[Pipeline] Step end_frame_gen: SKIP (already completed)")
            return self._state.pregenerated_end_frames or {}

        logger.info(f"[Pipeline] Step end_frame_gen: RUNNING ({len(end_frame_prompts)} frames)")

        vw = self._state.video_width
        vh = self._state.video_height
        end_frame_images = self._state.end_frame_images

        pregenerated: dict = {}
        cached = self._state.pregenerated_end_frames or {}

        for scene_idx in range(len(scenes)):
            if self._is_shutdown():
                raise PipelineShutdown(f"interrupted during end frame gen scene {scene_idx}")
            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)
            end_frame_path = os.path.join(scene_dir, "end_frame.png")

            if str(scene_idx) in cached and os.path.exists(end_frame_path):
                pregenerated[scene_idx] = end_frame_path
                continue

            user_ef = (
                end_frame_images[scene_idx]
                if end_frame_images and scene_idx < len(end_frame_images) and end_frame_images[scene_idx]
                else None
            )

            if user_ef:
                await self._emit(
                    "end_frame_gen", "running",
                    f"场景 {scene_idx+1}/{len(scenes)}: 使用自定义尾帧",
                    0.25 + 0.05 * scene_idx / len(scenes),
                )
                if os.path.exists(user_ef):
                    dest = os.path.join(scene_dir, "end_frame.png")
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", user_ef,
                            "-vf", f"scale={vw}:{vh}:force_original_aspect_ratio=decrease,pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2",
                            dest,
                        ],
                        capture_output=True, check=True, timeout=30,
                    )
                    end_frame_path = dest
                pregenerated[scene_idx] = end_frame_path
                cached[str(scene_idx)] = end_frame_path
                continue

            if os.path.exists(end_frame_path):
                pregenerated[scene_idx] = end_frame_path
                cached[str(scene_idx)] = end_frame_path
                continue

            if self._state.generate_end_frames_from_ref and character_ref_path:
                await self._emit(
                    "end_frame_gen", "running",
                    f"场景 {scene_idx+1}/{len(scenes)}: 基于参考图生成尾帧 (i2i)",
                    0.25 + 0.05 * scene_idx / len(scenes),
                )
                end_frame_prompt = (
                    end_frame_prompts[scene_idx]
                    if scene_idx < len(end_frame_prompts)
                    else "cinematic end frame"
                )
                for attempt in range(3):
                    if self._is_shutdown():
                        raise PipelineShutdown(f"interrupted during end frame gen scene {scene_idx}")
                    try:
                        img_output = await self.image_generator.generate_single_image(
                            prompt=end_frame_prompt,
                            reference_image_paths=[character_ref_path],
                            size=f"{vw}x{vh}",
                        )
                        img_output.save(end_frame_path)
                        pregenerated[scene_idx] = end_frame_path
                        cached[str(scene_idx)] = end_frame_path
                        break
                    except Exception as e:
                        if attempt < 2:
                            wait = (attempt + 1) * 20
                            logger.warning(
                                f"[EndFrame] Scene {scene_idx} attempt {attempt+1} failed: {e}, "
                                f"retrying in {wait}s..."
                            )
                            await asyncio.sleep(wait)
                        else:
                            logger.error(f"[EndFrame] Scene {scene_idx} failed after 3 attempts: {e}")
                            raise
            else:
                end_frame_prompt = (
                    end_frame_prompts[scene_idx]
                    if scene_idx < len(end_frame_prompts)
                    else "cinematic end frame"
                )
                await self._emit(
                    "end_frame_gen", "running",
                    f"场景 {scene_idx+1}/{len(scenes)}: 自动生成尾帧 (t2i)",
                    0.25 + 0.05 * scene_idx / len(scenes),
                )
                img_output = await self.image_generator.generate_single_image(
                    prompt=end_frame_prompt,
                    size=f"{vw}x{vh}",
                )
                img_output.save(end_frame_path)
                pregenerated[scene_idx] = end_frame_path
                cached[str(scene_idx)] = end_frame_path

            if scene_idx < len(scenes) - 1:
                await asyncio.sleep(2)

        self._state.pregenerated_end_frames = cached
        self._state.step_end_frame_generation = StepStatus.COMPLETED
        self.task_manager.update_state(
            pregenerated_end_frames=cached,
            step_end_frame_generation=StepStatus.COMPLETED,
        )
        await self._emit(
            "end_frame_gen", "completed",
            f"尾帧预生成全部完成 ({len(pregenerated)}/{len(scenes)})",
            0.35,
        )
        return pregenerated

    # ==================================================================
    # Step 4: Video Generation
    # ==================================================================

    def _make_curl(self, video_id: str) -> str:
        """Build a curl command string for manual video-task retrieval.

        Args:
            video_id: The remote video task identifier.

        Returns:
            Shell command string.
        """
        return (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"https://apihub.agnes-ai.com/agnesapi?video_id={video_id}"'
        )

    def _save_scene_task(self, scene_dir: str, video_id: str) -> None:
        """Persist a scene's video-task ID to ``task.json`` and ``curl.sh``.

        Args:
            scene_dir: Directory for the scene.
            video_id: Remote video task identifier.
        """
        task_file = os.path.join(scene_dir, "task.json")
        with open(task_file, "w") as f:
            json.dump({"video_id": video_id}, f, indent=2)
        curl_file = os.path.join(scene_dir, "curl.sh")
        with open(curl_file, "w") as f:
            f.write(self._make_curl(video_id) + "\n")

    def _load_scene_task(self, scene_dir: str) -> Optional[str]:
        """Load a previously saved video-task ID from ``task.json``.

        Args:
            scene_dir: Directory for the scene.

        Returns:
            The video/task ID string, or ``None`` if no task file exists.
        """
        task_file = os.path.join(scene_dir, "task.json")
        if os.path.exists(task_file):
            try:
                with open(task_file, "r") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception:
                pass
        return None

    async def _step_generate_videos(
        self,
        scenes: list,
        character_ref_path: str,
        end_frame_prompts: list,
        pregenerated_end_frames: dict,
    ) -> list:
        """Generate videos for all scenes using the configured chaining mode.

        Dispatches to one of three generation strategies:
        - ``keyframes``: first-frame / end-frame pair for each scene.
        - ``ti2vid``: chained scenes where each uses the previous last frame.
        - ``independent``: every scene is generated independently.

        Args:
            scenes: List of scene descriptions.
            character_ref_path: Path to the character reference image.
            end_frame_prompts: Per-scene end-frame prompts (keyframes mode).
            pregenerated_end_frames: Pre-generated end-frame paths (keyframes mode).

        Returns:
            Ordered list of video file paths.
        """
        if self._state.step_video_generation == StepStatus.COMPLETED:
            logger.info("[Pipeline] Step video_gen: SKIP (already completed), reconstructing video paths from disk")
            all_video_paths = []
            for scene_idx in range(len(scenes)):
                video_path = os.path.join(self.working_dir, f"scene_{scene_idx}", "video.mp4")
                if os.path.exists(video_path):
                    all_video_paths.append(video_path)
            logger.info(f"[Pipeline] Step video_gen: reconstructed {len(all_video_paths)} video paths from disk")
            return all_video_paths

        logger.info(
            f"[Pipeline] Step video_gen: RUNNING "
            f"({len(scenes)} scenes, mode={self._state.chaining_mode})"
        )

        vw = self._state.video_width
        vh = self._state.video_height
        chaining_mode = self._state.chaining_mode
        end_frame_images = self._state.end_frame_images

        if chaining_mode == "keyframes":
            all_video_paths = await self._generate_keyframe_scenes(
                scenes, character_ref_path, end_frame_prompts,
                pregenerated_end_frames, vw, vh, end_frame_images,
            )
        elif chaining_mode == "ti2vid":
            all_video_paths = await self._generate_chained_scenes(
                scenes, character_ref_path, vw, vh,
            )
        else:
            all_video_paths = await self._generate_independent_scenes(
                scenes, character_ref_path, vw, vh,
            )

        self._state.step_video_generation = StepStatus.COMPLETED
        self.task_manager.update_step("step_video_generation", StepStatus.COMPLETED)
        return all_video_paths

    # ------------------------------------------------------------------
    # Video generation strategies
    # ------------------------------------------------------------------

    async def _generate_independent_scenes(
        self, scenes: list, character_ref_path: str, vw: int, vh: int
    ) -> list:
        """Generate all scenes independently (no chaining).

        Phase 1 submits all video tasks; Phase 2 waits for them to complete.

        Args:
            scenes: Scene description list.
            character_ref_path: Path to the character reference image.
            vw: Video width in pixels.
            vh: Video height in pixels.

        Returns:
            Ordered list of video file paths.
        """
        total = len(scenes)
        pending: List[dict] = []

        # Phase 1: Submit all video tasks, saving scene state for resumability
        for scene_idx, scene_text in enumerate(scenes):
            if self._is_shutdown():
                raise PipelineShutdown(f"interrupted during independent scene {scene_idx}")
            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            if os.path.exists(video_path):
                continue

            existing_video_id = self._load_scene_task(scene_dir)
            if existing_video_id:
                logger.info(
                    f"[Pipeline] Scene {scene_idx}: resuming existing video task "
                    f"{existing_video_id[:16]}..."
                )
                pending.append({
                    "scene_idx": scene_idx, "video_path": video_path,
                    "video_id": existing_video_id, "scene_dir": scene_dir,
                    "already_submitted": True,
                })
                continue

            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 提交任务 (ti2vid)...",
                0.35 + 0.45 * scene_idx / total,
            )
            video_id = await self.video_generator.submit_video(
                prompt=scene_text,
                reference_image_paths=[character_ref_path],
                duration=self._state.video_duration,
                width=vw,
                height=vh,
            )
            self._save_scene_task(scene_dir, video_id)
            pending.append({
                "scene_idx": scene_idx, "video_path": video_path,
                "video_id": video_id, "scene_dir": scene_dir,
                "already_submitted": True,
            })

        if pending:
            await self._emit(
                "video_gen", "running",
                f"等待 {len(pending)} 个视频生成完成 (independent)...",
                0.38,
            )

        # Phase 2: Wait for all submitted videos
        for info in pending:
            scene_idx = info["scene_idx"]
            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 等待生成中...",
                0.38 + 0.42 * pending.index(info) / len(pending),
            )
            try:
                video_output = await self.video_generator.wait_for_video(info["video_id"])
                video_output.save(info["video_path"])
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 完成",
                    0.38 + 0.42 * (pending.index(info) + 1) / len(pending),
                )
            except Exception as e:
                logger.error(f"Scene {scene_idx} video failed: {e}")
                task_file = os.path.join(info["scene_dir"], "task.json")
                if os.path.exists(task_file):
                    os.remove(task_file)
                raise

        all_video_paths: List[str] = []
        for scene_idx in range(len(scenes)):
            video_path = os.path.join(self.working_dir, f"scene_{scene_idx}", "video.mp4")
            if os.path.exists(video_path):
                all_video_paths.append(video_path)

        return all_video_paths

    async def _generate_chained_scenes(
        self, scenes: list, reference_image: str, vw: int, vh: int
    ) -> list:
        """Generate scenes in a chain where each uses the previous last frame.

        Args:
            scenes: Scene description list.
            reference_image: Initial reference image for the first scene.
            vw: Video width in pixels.
            vh: Video height in pixels.

        Returns:
            Ordered list of video file paths.
        """
        all_video_paths: List[str] = []
        current_image = reference_image
        total = len(scenes)

        for scene_idx, scene_text in enumerate(scenes):
            if self._is_shutdown():
                raise PipelineShutdown(f"interrupted during chained scene {scene_idx}")
            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            if os.path.exists(video_path):
                all_video_paths.append(video_path)
                last_frame_path = os.path.join(scene_dir, "last_frame.jpg")
                if os.path.exists(last_frame_path):
                    current_image = last_frame_path
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 已缓存",
                    0.35 + 0.45 * (scene_idx + 1) / total,
                )
                continue

            # Check for previously submitted but unwatched task
            existing_video_id = self._load_scene_task(scene_dir)

            if existing_video_id:
                logger.info(
                    f"[Pipeline] Scene {scene_idx}: resuming existing video task "
                    f"{existing_video_id[:16]}..."
                )
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 续传视频 (ti2vid)...",
                    0.35 + 0.45 * scene_idx / total,
                )
            else:
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 提交任务 (ti2vid)...",
                    0.35 + 0.45 * scene_idx / total,
                )
                video_id = await self.video_generator.submit_video(
                    prompt=scene_text,
                    reference_image_paths=[current_image],
                    duration=self._state.video_duration,
                    width=vw,
                    height=vh,
                )
                self._save_scene_task(scene_dir, video_id)
                existing_video_id = video_id

            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 等待生成中...",
                0.35 + 0.45 * scene_idx / total,
            )
            try:
                video_output = await self.video_generator.wait_for_video(existing_video_id)
                video_output.save(video_path)
            except Exception as e:
                logger.error(f"Scene {scene_idx} video failed: {e}")
                task_file = os.path.join(scene_dir, "task.json")
                if os.path.exists(task_file):
                    os.remove(task_file)
                raise

            all_video_paths.append(video_path)

            if scene_idx + 1 < total:
                last_frame_path = os.path.join(scene_dir, "last_frame.jpg")
                cmd = [
                    "ffmpeg", "-y",
                    "-sseof", "-1",
                    "-i", video_path,
                    "-frames:v", "1",
                    "-update", "1",
                    last_frame_path,
                ]
                subprocess.run(cmd, capture_output=True, timeout=30, check=True)

                last_frame_url = await self.video_generator._resolve_image_ref(last_frame_path)

                next_scene_text = scenes[scene_idx + 1]
                transition_prompt = (
                    f"Cinematic transition frame, blending the end of the current scene "
                    f"into the beginning of the next. Keep the same person and face exactly. "
                    f"Next scene: {next_scene_text[:200]}"
                )
                transition_path = os.path.join(scene_dir, f"transition_to_{scene_idx+1}.png")

                img_output = await self.image_generator.generate_single_image(
                    prompt=transition_prompt,
                    reference_image_paths=[last_frame_url],
                    size=f"{vw}x{vh}",
                )
                img_output.save(transition_path)
                current_image = transition_path

            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 完成",
                0.35 + 0.45 * (scene_idx + 1) / total,
            )

        return all_video_paths

    async def _generate_keyframe_scenes(
        self,
        scenes: list,
        reference_image: str,
        end_frame_prompts: list,
        pregenerated_end_frames: dict,
        vw: int,
        vh: int,
        end_frame_images: list,
    ) -> list:
        """Generate scenes using first-frame / end-frame keyframe pairs.

        Args:
            scenes: Scene description list.
            reference_image: Initial first-frame reference image.
            end_frame_prompts: Per-scene end-frame prompt strings.
            pregenerated_end_frames: Dict of pre-generated end-frame paths.
            vw: Video width in pixels.
            vh: Video height in pixels.
            end_frame_images: User-provided end-frame image paths.

        Returns:
            Ordered list of video file paths.
        """
        current_first_frame = reference_image
        total = len(scenes)

        pending: List[dict] = []
        for scene_idx, scene_text in enumerate(scenes):
            if self._is_shutdown():
                raise PipelineShutdown(f"interrupted during keyframe scene {scene_idx}")
            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            if os.path.exists(video_path):
                end_frame_path = os.path.join(scene_dir, "end_frame.png")
                if os.path.exists(end_frame_path):
                    current_first_frame = end_frame_path
                continue

            existing_video_id = self._load_scene_task(scene_dir)
            if existing_video_id:
                logger.info(
                    f"[Pipeline] Scene {scene_idx}: resuming existing video task "
                    f"{existing_video_id[:16]}..."
                )
                end_frame_path = os.path.join(scene_dir, "end_frame.png")
                pending.append({
                    "scene_idx": scene_idx,
                    "video_path": video_path,
                    "video_id": existing_video_id,
                    "scene_dir": scene_dir,
                    "already_submitted": True,
                })
                current_first_frame = end_frame_path
                continue

            if str(scene_idx) in pregenerated_end_frames:
                end_frame_path = pregenerated_end_frames[str(scene_idx)]
            else:
                end_frame_path = os.path.join(scene_dir, "end_frame.png")
                if not os.path.exists(end_frame_path):
                    user_ef = (
                        end_frame_images[scene_idx]
                        if end_frame_images and scene_idx < len(end_frame_images) and end_frame_images[scene_idx]
                        else None
                    )
                    if user_ef and os.path.exists(user_ef):
                        dest = os.path.join(scene_dir, "end_frame.png")
                        subprocess.run(
                            [
                                "ffmpeg", "-y", "-i", user_ef,
                                "-vf", f"scale={vw}:{vh}:force_original_aspect_ratio=decrease,pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2",
                                dest,
                            ],
                            capture_output=True, check=True, timeout=30,
                        )
                        end_frame_path = dest
                    else:
                        end_frame_prompt = (
                            end_frame_prompts[scene_idx]
                            if scene_idx < len(end_frame_prompts)
                            else "cinematic end frame"
                        )
                        img_output = await self.image_generator.generate_single_image(
                            prompt=end_frame_prompt,
                            size=f"{vw}x{vh}",
                        )
                        img_output.save(end_frame_path)

            first_frame_url = await self.video_generator._resolve_image_ref(current_first_frame)
            end_frame_url = await self.video_generator._resolve_image_ref(end_frame_path)

            pending.append({
                "scene_idx": scene_idx,
                "scene_text": scene_text,
                "video_path": video_path,
                "first_frame_url": first_frame_url,
                "end_frame_url": end_frame_url,
                "end_frame_path": end_frame_path,
                "scene_dir": scene_dir,
                "already_submitted": False,
            })
            current_first_frame = end_frame_path

        new_submissions = [i for i in pending if not i.get("already_submitted")]
        if new_submissions:
            await self._emit(
                "video_gen", "running",
                f"提交 {len(new_submissions)} 个视频任务 (keyframes)...",
                0.35,
            )
        else:
            logger.info(
                f"[Pipeline] All {len(pending)} scene(s) already submitted, "
                f"waiting for completion..."
            )

        for info in new_submissions:
            scene_idx = info["scene_idx"]
            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 提交任务...",
                0.35 + 0.05 * scene_idx / total,
            )
            video_id = await self.video_generator.submit_video(
                prompt=info["scene_text"],
                reference_image_paths=[info["first_frame_url"], info["end_frame_url"]],
                duration=self._state.video_duration,
                width=vw,
                height=vh,
            )
            info["video_id"] = video_id
            info["already_submitted"] = True
            self._save_scene_task(info["scene_dir"], video_id)

        if pending:
            await self._emit(
                "video_gen", "running",
                f"等待 {len(pending)} 个视频生成完成...",
                0.4,
            )

        for info in pending:
            scene_idx = info["scene_idx"]
            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 等待生成中...",
                0.4 + 0.4 * pending.index(info) / len(pending),
            )
            try:
                video_output = await self.video_generator.wait_for_video(info["video_id"])
                video_output.save(info["video_path"])
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 完成",
                    0.4 + 0.4 * (pending.index(info) + 1) / len(pending),
                )
            except Exception as e:
                logger.error(f"Scene {scene_idx} video failed: {e}")
                task_file = os.path.join(info["scene_dir"], "task.json")
                if os.path.exists(task_file):
                    os.remove(task_file)
                raise

        all_video_paths: List[str] = []
        for scene_idx in range(len(scenes)):
            video_path = os.path.join(self.working_dir, f"scene_{scene_idx}", "video.mp4")
            if os.path.exists(video_path):
                all_video_paths.append(video_path)

        return all_video_paths

    # ==================================================================
    # Step 4.5: Populate narrations from story
    # ==================================================================

    def _populate_narrations(self, story: str) -> None:
        if self._state.narrations:
            return
        num_scenes = len(self._state.scenes)
        if not num_scenes or not story:
            return
        paragraphs = [p.strip() for p in story.split("\n\n") if p.strip()]
        if not paragraphs:
            self._state.narrations = [story] * num_scenes
            self.task_manager.update_state(narrations=self._state.narrations)
            return
        narrations = []
        base = len(paragraphs) // num_scenes
        rem = len(paragraphs) % num_scenes
        idx = 0
        for i in range(num_scenes):
            count = base + (1 if i < rem else 0)
            narrations.append("\n".join(paragraphs[idx : idx + count]))
            idx += count

        # Trim each narration to fit within video_duration * 4 chars/sec speaking rate
        max_chars = max(int(self._state.video_duration * _CHARS_PER_SEC), 20)
        narrations = [_trim_to_sentence(n, max_chars) for n in narrations]

        self._state.narrations = narrations
        self.task_manager.update_state(narrations=narrations)

    # ==================================================================
    # Step 5: Audio & Subtitle Generation (NEW in v2.0)
    # ==================================================================

    async def _step_audio_subtitle(self) -> None:
        """Generate TTS narration audio and SRT subtitles for each scene.

        When ``audio_config.enabled`` is ``True``, uses :class:`EdgeTTSEngine`
        to produce narration audio and extract word-level timing cues, then
        converts cues to SRT via :class:`SubtitleGenerator`.

        When audio is disabled, generates silent placeholder audio via
        :class:`SilentTTSEngine` so that the concatenation step still has a
        consistent timeline.

        Supports resume: scenes that already have a valid ``narration_audio``
        file on disk are skipped.
        """
        if self._state.step_audio_subtitle == StepStatus.COMPLETED:
            logger.info("[Pipeline] Step audio_subtitle: SKIP (already completed)")
            return

        audio_enabled = self._state.audio_config.enabled
        voice = self._state.audio_config.voice
        rate = self._state.audio_config.rate

        logger.info(
            f"[Pipeline] Step audio_subtitle: RUNNING "
            f"(enabled={audio_enabled}, scenes={len(self._state.scenes)})"
        )

        edge_tts = EdgeTTSEngine() if audio_enabled else None
        silent_tts = SilentTTSEngine()

        await self._emit(
            "audio_subtitle", "running",
            f"{'生成旁白和字幕' if audio_enabled else '生成静音时间轴'}...",
            0.82,
        )

        total_scenes = len(self._state.scenes)

        for i in range(len(self._state.scenes)):
            if self._is_shutdown():
                raise PipelineShutdown(f"interrupted during audio/subtitle scene {i}")

            scene = self._state.scenes[i]
            scene_dir = os.path.join(self.working_dir, f"scene_{i}")
            os.makedirs(scene_dir, exist_ok=True)

            # Resume: skip if narration audio already exists on disk
            if scene.narration_audio and os.path.exists(scene.narration_audio):
                logger.info(f"[Pipeline] Scene {i}: audio already exists, skipping")
                continue

            # Determine narration text (scene field first, then narrations list)
            narration_text = scene.narration_text
            if not narration_text and i < len(self._state.narrations):
                narration_text = self._state.narrations[i]

            audio_path = os.path.join(scene_dir, "narration.mp3")
            srt_path = os.path.join(scene_dir, "subtitle.srt")

            if not narration_text:
                # No narration for this scene -- generate silent placeholder
                await silent_tts.generate(
                    text="placeholder",
                    output_path=audio_path,
                    duration_sec=float(self._state.video_duration),
                )
                self._state.scenes[i].narration_audio = audio_path
                self._state.scenes[i].subtitle_srt = ""
                self.task_manager.update_scene(self._state.scenes[i])
                continue

            if audio_enabled and edge_tts is not None:
                # Generate real TTS narration + word-level cues
                await self._emit(
                    "audio_subtitle", "running",
                    f"场景 {i+1}/{total_scenes}: 生成旁白...",
                    0.82 + 0.08 * i / total_scenes,
                )
                audio_path, sub_maker = await edge_tts.generate(
                    text=narration_text,
                    output_path=audio_path,
                    voice=voice,
                    rate=rate,
                )
                SubtitleGenerator.cues_to_srt(sub_maker, srt_path)
            else:
                # Audio disabled -- silent placeholder for timeline alignment
                await silent_tts.generate(
                    text=narration_text,
                    output_path=audio_path,
                    duration_sec=float(self._state.video_duration),
                )
                SubtitleGenerator.cues_to_srt({}, srt_path)

            self._state.scenes[i].narration_audio = audio_path
            self._state.scenes[i].subtitle_srt = srt_path

            # Persist per-scene progress
            self.task_manager.update_scene(self._state.scenes[i])

        self._state.step_audio_subtitle = StepStatus.COMPLETED
        self.task_manager.update_state(
            step_audio_subtitle=StepStatus.COMPLETED,
            scenes=[s.model_dump() for s in self._state.scenes],
        )
        await self._emit("audio_subtitle", "completed", "音频和字幕生成完成", 0.9)

    # ==================================================================
    # Step 6: Concatenation (MODIFIED in v2.0)
    # ==================================================================

    async def _step_concatenate(self, all_video_paths: list) -> str:
        """Concatenate scene videos into the final output.

        When audio is enabled, uses :meth:`VideoConcatenator.concat_with_audio`
        to merge each video with its narration audio and subtitle overlay before
        joining.  Falls back to :meth:`VideoConcatenator.concat_videos` for
        pure video concatenation when audio is disabled or unavailable.

        Args:
            all_video_paths: Ordered list of per-scene video file paths.

        Returns:
            Path to the final concatenated video file.

        Raises:
            RuntimeError: If no videos were generated.
        """
        final_video_path = os.path.join(self.working_dir, "final_video.mp4")

        if os.path.exists(final_video_path):
            self._state.step_concatenation = StepStatus.COMPLETED
            self._state.final_video_file = final_video_path
            self.task_manager.update_state(
                step_concatenation=StepStatus.COMPLETED,
                final_video_file=final_video_path,
            )
            return final_video_path

        await self._emit("concatenate", "running", "正在拼接视频...", 0.92)

        audio_enabled = (
            self._state.audio_config.enabled
            and self._state.step_audio_subtitle == StepStatus.COMPLETED
        )

        if audio_enabled:
            # Build clip tuples: (video_path, audio_path, srt_path_or_None)
            clip_tuples: List[tuple] = []
            for i, video_path in enumerate(all_video_paths):
                scene = self._state.scenes[i] if i < len(self._state.scenes) else None
                audio_path = scene.narration_audio if scene else ""
                srt_path = scene.subtitle_srt if scene else ""
                clip_tuples.append((
                    video_path,
                    audio_path or "",
                    srt_path if srt_path and os.path.exists(srt_path) else None,
                ))

            VideoConcatenator.concat_with_audio(
                clip_tuples=clip_tuples,
                output_path=final_video_path,
                subtitle_style=self._state.audio_config.subtitle_style,
            )
        else:
            # Fallback: pure video concatenation without audio
            VideoConcatenator.concat_videos(all_video_paths, final_video_path)

        self._state.step_concatenation = StepStatus.COMPLETED
        self._state.final_video_file = final_video_path
        self.task_manager.update_state(
            step_concatenation=StepStatus.COMPLETED,
            final_video_file=final_video_path,
        )
        await self._emit("concatenate", "completed", "视频拼接完成", 0.95)
        return final_video_path

    # ==================================================================
    # Main Run
    # ==================================================================

    async def run(self, state: CreativeVideoTask) -> str:
        """Execute the full creative video generation pipeline.

        Steps (in order):
            0. Image analysis
            1. Story generation
            2. Character reference
            3. Script writing
            3.5. End-frame prompts (keyframes mode)
            3.6. End-frame pre-generation (keyframes mode)
            4. Video generation
            5. Audio & subtitle generation (v2.0)
            6. Concatenation

        Each step is checkpointed for resume.  A ``PipelineShutdown`` exception
        is raised at every checkpoint when a shutdown is requested.

        Args:
            state: The creative video task state to execute.

        Returns:
            Path to the final video file.

        Raises:
            PipelineShutdown: If a graceful shutdown was requested.
            Exception: On unrecoverable errors (state is marked FAILED).
        """
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", "开始视频生成流程...", 0.0)

        try:
            image_context = await self._step_image_analysis(
                self._state.reference_image, self._state.end_frame_images
            )
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after image analysis")

            story = await self._step_story(image_context)
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after story")

            character_ref_path = await self._step_character_reference(story)
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after character reference")

            scenes = await self._step_script(story)
            self._populate_narrations(story)
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after script")

            end_frame_prompts = await self._step_end_frame_prompts(story, scenes)
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after end frame prompts")

            pregenerated_end_frames = await self._step_pregenerate_end_frames(
                scenes, end_frame_prompts, character_ref_path
            )
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after end frame generation")

            all_video_paths = await self._step_generate_videos(
                scenes, character_ref_path, end_frame_prompts, pregenerated_end_frames
            )
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after video generation")

            # NEW v2.0: audio & subtitle generation
            await self._step_audio_subtitle()
            if self._is_shutdown():
                raise PipelineShutdown("interrupted after audio/subtitle")

            final_video_path = await self._step_concatenate(all_video_paths)

            self._state.status = StepStatus.COMPLETED
            self.task_manager.update_state(status=StepStatus.COMPLETED)
            await self._emit(
                "done", "completed", "视频生成完成!", 1.0,
                {"final_video": final_video_path},
            )

            return final_video_path

        except PipelineShutdown as e:
            logger.info(f"[Pipeline] Shutdown: {e}")
            await self._emit("error", "failed", "任务已被中断，可从任务列表续传", 0.0)
            raise
        except Exception as e:
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(status=StepStatus.FAILED)
            await self._emit("error", "failed", str(e), 0.0)
            raise
