"""core.pipelines.creative.steps_video — 视频生成步骤 mixin（v5.0 Batch 4 / 4.2 拆分）"""
import logging
import os
import re
from typing import List

from core.api.agnes_video import is_remote_video_failure
from core.pipelines import PipelineShutdown
from models.task import StepStatus

from .steps_frames import _fallback_end_frame, _localize_preserve_tags, _run_ffmpeg_async

logger = logging.getLogger(__name__)

# 视频生成进度映射基数（阶段内线性插值）
_PROGRESS_WAIT_START = 0.38
_PROGRESS_WAIT_SPAN = 0.42
_PROGRESS_CACHED_START = 0.35
_PROGRESS_CACHED_SPAN = 0.45
_PROGRESS_KEYFRAME_SUBMIT_START = 0.35
_PROGRESS_KEYFRAME_SUBMIT_SPAN = 0.05
_PROGRESS_KEYFRAME_WAIT_START = 0.40
_PROGRESS_KEYFRAME_WAIT_SPAN = 0.40


def _localize_transition_prompt(next_scene_text: str) -> str:
    """返回与 next_scene_text 语言一致的过渡帧描述。"""
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', next_scene_text or ""))
    if has_chinese:
        return (
            f"电影感过渡画面，从当前场景平滑过渡到下一场景。"
            f"保持相同的人物和面部。下一场景：{next_scene_text[:200]}"
        )
    return (
        f"Cinematic transition frame, blending the end of the current scene "
        f"into the beginning of the next. Keep the same person and face exactly. "
        f"Next scene: {next_scene_text[:200]}"
    )

class VideoStepsMixin:
    """视频生成步骤：independent / chained(ti2vid) / keyframes 三模式。

    v5.0 Batch 4（4.2）拆分自 CreativeVideoPipeline，经 MRO 组合回主类。
    """

    def _user_scene_ref(self, scene_idx: int):
        """返回用户上传的分镜参考图路径（优化 5），无则 None。

        用户在某场景上传参考图后，该场景以用户图为视频参考，
        跳过对应的 AI 分镜图生成 / 角色参考图。
        """
        refs = getattr(self._state, "scene_reference_images", None) or []
        if 0 <= scene_idx < len(refs):
            return refs[scene_idx]
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
            # 验证所有场景的视频文件都存在
            if len(all_video_paths) == len(scenes):
                logger.info(f"[Pipeline] Step video_gen: reconstructed {len(all_video_paths)} video paths from disk")
                return all_video_paths
            logger.warning(
                f"[Pipeline] Step video_gen: marked completed but only {len(all_video_paths)}/{len(scenes)} "
                "videos exist, re-running"
            )
            self._state.step_video_generation = StepStatus.PENDING
            self.task_manager.update_step("step_video_generation", StepStatus.PENDING)

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

    def _scene_duration(self, scene_idx: int) -> float:
        """Get the video duration for a specific scene by index.

        Falls back to ``self._state.video_duration`` when the scene object
        is not available (e.g. before scenes are created).
        """
        if scene_idx < len(self._state.scenes):
            return float(self._state.scenes[scene_idx].duration)
        return float(self._state.video_duration)

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
                _PROGRESS_CACHED_START + _PROGRESS_CACHED_SPAN * scene_idx / total,
            )
            # 优化 5：该场景有用户上传参考图时以用户图为参考
            user_ref = self._user_scene_ref(scene_idx)
            video_id = await self.video_generator.submit_video(
                prompt=scene_text,
                reference_image_paths=[user_ref] if user_ref else [character_ref_path],
                duration=self._scene_duration(scene_idx),
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
                _PROGRESS_WAIT_START,
            )

        # Phase 2: Wait for all submitted videos
        for info in pending:
            scene_idx = info["scene_idx"]
            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 等待生成中...",
                _PROGRESS_WAIT_START + _PROGRESS_WAIT_SPAN * pending.index(info) / len(pending),
            )
            try:
                video_output = await self.video_generator.wait_for_video(info["video_id"])
                await video_output.save(info["video_path"])
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 完成",
                    _PROGRESS_WAIT_START + _PROGRESS_WAIT_SPAN * (pending.index(info) + 1) / len(pending),
                )
            except Exception as e:
                logger.error(f"Scene {scene_idx} video failed: {e}")
                # 优化路线图 0.2：仅「服务端确认失败」才丢弃 video_id；
                # 超时/用户取消/网络中断保留 task.json 供续传复用，
                # 避免重复提交浪费 1 次/分钟/Key 的视频配额
                if is_remote_video_failure(e):
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
            # 优化 5：该场景有用户上传参考图时，以用户图为起点（跳过前场景链式图）
            user_ref = self._user_scene_ref(scene_idx)
            if user_ref:
                logger.info(f"[Pipeline] Scene {scene_idx}: using user reference image")
                current_image = user_ref
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
                    _PROGRESS_CACHED_START + _PROGRESS_CACHED_SPAN * (scene_idx + 1) / total,
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
                    _PROGRESS_CACHED_START + _PROGRESS_CACHED_SPAN * scene_idx / total,
                )
            else:
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 提交任务 (ti2vid)...",
                    _PROGRESS_CACHED_START + _PROGRESS_CACHED_SPAN * scene_idx / total,
                )
                # 优化路线图 3.6：双参考图——尾帧（时序连贯）+ 角色参考图
                # （身份稳定），缓解链式生成的角色漂移累积。
                # 首场景 current_image == reference_image 时避免重复提交同一张图。
                ref_paths = [current_image]
                if (
                    reference_image
                    and os.path.exists(reference_image)
                    and current_image != reference_image
                ):
                    ref_paths = [current_image, reference_image]
                video_id = await self.video_generator.submit_video(
                    prompt=scene_text,
                    reference_image_paths=ref_paths,
                    duration=self._scene_duration(scene_idx),
                    width=vw,
                    height=vh,
                )
                self._save_scene_task(scene_dir, video_id)
                existing_video_id = video_id

            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 等待生成中...",
                _PROGRESS_CACHED_START + _PROGRESS_CACHED_SPAN * scene_idx / total,
            )
            try:
                video_output = await self.video_generator.wait_for_video(existing_video_id)
                await video_output.save(video_path)
            except Exception as e:
                logger.error(f"Scene {scene_idx} video failed: {e}")
                # 优化路线图 0.2：仅「服务端确认失败」才丢弃 video_id；
                # 超时/用户取消/网络中断保留 task.json 供续传复用
                if is_remote_video_failure(e):
                    task_file = os.path.join(scene_dir, "task.json")
                    if os.path.exists(task_file):
                        os.remove(task_file)
                raise

            all_video_paths.append(video_path)

            if scene_idx + 1 < total:
                last_frame_path = os.path.join(scene_dir, "last_frame.jpg")
                await _run_ffmpeg_async(
                    [
                        "ffmpeg", "-y",
                        "-sseof", "-1",
                        "-i", video_path,
                        "-frames:v", "1",
                        "-update", "1",
                        last_frame_path,
                    ],
                    timeout=30,
                )

                last_frame_url = await self.video_generator._resolve_image_ref(last_frame_path)

                next_scene_text = scenes[scene_idx + 1]
                transition_prompt = _localize_transition_prompt(next_scene_text)
                transition_path = os.path.join(scene_dir, f"transition_to_{scene_idx+1}.png")

                img_output = await self.image_generator.generate_single_image(
                    prompt=transition_prompt,
                    reference_image_paths=[last_frame_url],
                    size=f"{vw}x{vh}",
                )
                await img_output.save(transition_path)
                current_image = transition_path

            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 完成",
                _PROGRESS_CACHED_START + _PROGRESS_CACHED_SPAN * (scene_idx + 1) / total,
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
            # 优化 5：该场景有用户上传参考图时，以用户图为 first frame（跳过角色参考图）
            user_ref = self._user_scene_ref(scene_idx)
            if user_ref:
                logger.info(f"[Pipeline] Scene {scene_idx}: using user reference image as first frame")
                current_first_frame = user_ref
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
                        await _run_ffmpeg_async(
                            [
                                "ffmpeg", "-y", "-i", user_ef,
                                "-vf", f"scale={vw}:{vh}:force_original_aspect_ratio=decrease,pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2",
                                dest,
                            ],
                            timeout=30,
                        )
                        end_frame_path = dest
                    else:
                        # 批次6：兖底尾帧生成与 Step 3.6 一致策略（i2i + 规范化角色图 + 拼合 prompt）
                        end_frame_prompt = (
                            end_frame_prompts[scene_idx]
                            if scene_idx < len(end_frame_prompts)
                            else _fallback_end_frame(scene_text)
                        )
                        use_i2i = (
                            self._state.generate_end_frames_from_ref
                            and reference_image
                        )
                        if use_i2i:
                            # 程序化拼入 [PRESERVE] 角色外观硬约束
                            # 用户提供了参考图时跳过，避免文本描述与参考图矛盾
                            if self._state.character_appearance and not self._state.reference_image:
                                _tags = _localize_preserve_tags(scene_text)
                                end_frame_prompt = (
                                    f"{_tags['preserve']}\n"
                                    f"{self._state.character_appearance}\n"
                                    f"{_tags['keep_identity']}\n\n"
                                    f"{_tags['change']}\n"
                                    f"{end_frame_prompt}"
                                )
                            normalized_ref = await self._get_normalized_character_ref(reference_image)
                            logger.info(
                                f"[Keyframes] Scene {scene_idx} fallback: i2i with normalized ref"
                            )
                            img_output = await self.image_generator.generate_single_image(
                                prompt=end_frame_prompt,
                                reference_image_paths=[normalized_ref],
                                size=f"{vw}x{vh}",
                            )
                        else:
                            img_output = await self.image_generator.generate_single_image(
                                prompt=end_frame_prompt,
                                size=f"{vw}x{vh}",
                            )
                        await img_output.save(end_frame_path)

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
                _PROGRESS_KEYFRAME_SUBMIT_START,
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
                _PROGRESS_KEYFRAME_SUBMIT_START + _PROGRESS_KEYFRAME_SUBMIT_SPAN * scene_idx / total,
            )
            video_id = await self.video_generator.submit_video(
                prompt=info["scene_text"],
                reference_image_paths=[info["first_frame_url"], info["end_frame_url"]],
                duration=self._scene_duration(scene_idx),
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
                _PROGRESS_KEYFRAME_WAIT_START,
            )

        for info in pending:
            scene_idx = info["scene_idx"]
            await self._emit(
                "video_gen", "running",
                f"场景 {scene_idx+1}/{total}: 等待生成中...",
                _PROGRESS_KEYFRAME_WAIT_START + _PROGRESS_KEYFRAME_WAIT_SPAN * pending.index(info) / len(pending),
            )
            try:
                video_output = await self.video_generator.wait_for_video(info["video_id"])
                await video_output.save(info["video_path"])
                await self._emit(
                    "video_gen", "running",
                    f"场景 {scene_idx+1}/{total}: 完成",
                    _PROGRESS_KEYFRAME_WAIT_START + _PROGRESS_KEYFRAME_WAIT_SPAN * (pending.index(info) + 1) / len(pending),
                )
            except Exception as e:
                logger.error(f"Scene {scene_idx} video failed: {e}")
                # 优化路线图 0.2：仅「服务端确认失败」才丢弃 video_id；
                # 超时/用户取消/网络中断保留 task.json 供续传复用，
                # 避免重复提交浪费 1 次/分钟/Key 的视频配额
                if is_remote_video_failure(e):
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
