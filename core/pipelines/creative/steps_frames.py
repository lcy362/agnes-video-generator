"""core.pipelines.creative.steps_frames — 参考图/尾帧步骤 mixin（v5.0 Batch 4 / 4.2 拆分）"""
import asyncio
import json
import logging
import os
import re
from typing import List, Optional

from core.pipelines import PipelineShutdown
from models.task import StepStatus
from utils.image_normalizer import PAD, normalize_image_async

logger = logging.getLogger(__name__)

# 尾帧预生成完成进度（对齐视频阶段起始 0.35）
_PROGRESS_END_FRAME_PREGEN_DONE = 0.35


def _fallback_end_frame(text: str) -> str:
    """返回与输入文本语言一致的尾帧回退描述。"""
    if re.search(r'[\u4e00-\u9fff]', text or ""):
        return "电影感尾帧画面"
    return "cinematic end frame"

def _localize_preserve_tags(scene_text: str) -> dict:
    """返回与场景文本语言一致的 [PRESERVE]/[CHANGE] 标签和指令。"""
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', scene_text or ""))
    if has_chinese:
        return {
            "preserve": "[保留 — 严格保持]",
            "change": "[变化 — 过渡到本场景尾帧]",
            "keep_identity": "保持相同的人物、相同的面部、相同的服装。不要改变身份。",
        }
    return {
        "preserve": "[PRESERVE — keep exactly]",
        "change": "[CHANGE — end frame of this scene]",
        "keep_identity": "Keep the same person, same face, same clothing. Do NOT alter identity.",
    }

async def _run_ffmpeg_async(cmd: List[str], timeout: float = 30.0) -> None:
    """异步执行 ffmpeg 命令，等价于 ``subprocess.run(cmd, check=True, timeout=...)``。

    原实现用同步 ``subprocess.run`` 在 async pipeline 中阻塞事件循环，
    导致拼接/规范化阶段冻结整个 FastAPI 服务（WS 心跳/其他任务停摆）。
    改用 ``asyncio.create_subprocess_exec`` 让阻塞在子进程 IO 期间让出事件循环。

    Args:
        cmd: ffmpeg 命令列表。
        timeout: 超时秒数，超时则终止子进程并抛 ``TimeoutExpired``。

    Raises:
        RuntimeError: ffmpeg 退出码非 0（等价原 ``check=True`` 语义）。
        asyncio.TimeoutError: 超时。
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[:500] if stderr else ""
        raise RuntimeError(
            f"ffmpeg exited with code {proc.returncode}: {err}"
        )

class FramesStepsMixin:
    """参考图/尾帧步骤：尺寸归一化 / 角色参考图 / 尾帧预生成 / 场景任务落盘。

    v5.0 Batch 4（4.2）拆分自 CreativeVideoPipeline，经 MRO 组合回主类。
    """

    # ==================================================================
    # Helpers: image normalization
    # ==================================================================

    @staticmethod
    async def _normalize_image_to_size(src: str, vw: int, vh: int, dst: str) -> str:
        """Normalize an image to exactly ``vw x vh`` (delegated to utils.image_normalizer).

        Keeps the original aspect ratio (no stretching) and pads with black
        bars. This avoids feeding i2i a composition that the model would
        otherwise stretch/letterbox unpredictably — the i2i model then only
        needs to preserve identity, not reshape the layout.

        Outputs PNG（保摸底）with black bars, matching the legacy ffmpeg pad
        semantics. Uses ``normalize_image_async`` to avoid blocking the loop.

        Args:
            src: Source image path.
            vw: Target width.
            vh: Target height.
            dst: Destination path. If it already exists it is reused (cache).

        Returns:
            Path to the normalized image (``dst``).
        """
        if os.path.exists(dst):
            logger.debug(f"[Pipeline] normalize cache hit: {dst}")
            return dst
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        return await normalize_image_async(
            src=src, width=vw, height=vh, dst=dst,
            strategy=PAD, fmt="PNG", background=(0, 0, 0),  # 保持黑边语义
        )

    async def _get_normalized_character_ref(self, character_ref_path: str) -> str:
        """Return a character-reference image normalized to the video size.

        Caches the result under ``working_dir/character_ref_normalized.png``
        so it is generated at most once per task. Returns the original path
        unchanged if normalization is not possible (e.g. path is a URL).

        Args:
            character_ref_path: Original character reference path or URL.

        Returns:
            Path to the normalized image, or the original path on failure.
        """
        vw = self._state.video_width
        vh = self._state.video_height
        if not character_ref_path:
            return character_ref_path
        # Only normalize local files; URLs/data: are passed through as-is.
        if character_ref_path.startswith(("http://", "https://", "data:")):
            return character_ref_path
        if not os.path.exists(character_ref_path):
            return character_ref_path
        dst = os.path.join(self.working_dir, "character_ref_normalized.png")
        try:
            return await self._normalize_image_to_size(character_ref_path, vw, vh, dst)
        except Exception as e:
            logger.warning(
                f"[Pipeline] normalize character ref failed ({e}), using original"
            )
            return character_ref_path

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
            cached_frames = self._state.pregenerated_end_frames or {}
            # 验证缓存的文件是否实际存在（防止标记 completed 但文件丢失）
            all_exist = all(
                os.path.exists(p) for p in cached_frames.values()
            ) if cached_frames else False
            if all_exist:
                logger.info("[Pipeline] Step end_frame_gen: SKIP (already completed)")
                return cached_frames
            logger.warning(
                "[Pipeline] Step end_frame_gen: marked completed but some files missing, re-running"
            )
            self._state.step_end_frame_generation = StepStatus.PENDING
            self.task_manager.update_step("step_end_frame_generation", StepStatus.PENDING)

        logger.info(f"[Pipeline] Step end_frame_gen: RUNNING ({len(end_frame_prompts)} frames)")

        vw = self._state.video_width
        vh = self._state.video_height
        end_frame_images = self._state.end_frame_images

        pregenerated: dict = {}
        cached = self._state.pregenerated_end_frames or {}
        # 批次5：维护上一场景尾帧路径，用于多图 i2i 场景间视觉链
        prev_end_frame: Optional[str] = None

        for scene_idx in range(len(scenes)):
            if self._is_shutdown():
                raise PipelineShutdown(f"interrupted during end frame gen scene {scene_idx}")
            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)
            end_frame_path = os.path.join(scene_dir, "end_frame.png")

            if str(scene_idx) in cached and os.path.exists(end_frame_path):
                pregenerated[scene_idx] = end_frame_path
                prev_end_frame = end_frame_path  # 维护视觉链
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
                    # 优化 2：用户上传尾帧统一走归一化模块（PAD/PNG/黑边，与原 ffmpeg 语义一致）
                    end_frame_path = await normalize_image_async(
                        src=user_ef, width=vw, height=vh, dst=dest,
                        strategy=PAD, fmt="PNG", background=(0, 0, 0),
                    )
                pregenerated[scene_idx] = end_frame_path
                cached[str(scene_idx)] = end_frame_path
                prev_end_frame = end_frame_path  # 维护视觉链
                continue

            if os.path.exists(end_frame_path):
                pregenerated[scene_idx] = end_frame_path
                cached[str(scene_idx)] = end_frame_path
                prev_end_frame = end_frame_path  # 维护视觉链
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
                    else _fallback_end_frame(scenes[scene_idx])
                )
                # 程序化拼入 [PRESERVE] 角色外观硬约束，确保 i2i 身份一致性（批次3）
                # 用户提供了参考图时跳过：文本描述从故事提取，可能与参考图衣着矛盾，
                # 此时让 i2i 模型直接看参考图保持身份一致性。
                if self._state.character_appearance and not self._state.reference_image:
                    _tags = _localize_preserve_tags(scenes[scene_idx])
                    end_frame_prompt = (
                        f"{_tags['preserve']}\n"
                        f"{self._state.character_appearance}\n"
                        f"{_tags['keep_identity']}\n\n"
                        f"{_tags['change']}\n"
                        f"{end_frame_prompt}"
                    )
                # 规范化角色参考图到目标尺寸，避免 i2i 拉伸/构图错位
                normalized_ref = await self._get_normalized_character_ref(character_ref_path)
                # 批次5：多图 i2i 引导 —— 角色图锁身份 + 上一场景尾帧锁环境/风格延续
                ref_images = [normalized_ref]
                if prev_end_frame and os.path.exists(prev_end_frame):
                    ref_images.append(prev_end_frame)
                    logger.info(
                        f"[EndFrame] Scene {scene_idx}: multi-ref i2i "
                        f"(character + prev scene {scene_idx-1} end frame)"
                    )
                for attempt in range(3):
                    if self._is_shutdown():
                        raise PipelineShutdown(f"interrupted during end frame gen scene {scene_idx}")
                    try:
                        img_output = await self.image_generator.generate_single_image(
                            prompt=end_frame_prompt,
                            reference_image_paths=ref_images,
                            size=f"{vw}x{vh}",
                        )
                        await img_output.save(end_frame_path)
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
                    else _fallback_end_frame(scenes[scene_idx])
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
                await img_output.save(end_frame_path)
                pregenerated[scene_idx] = end_frame_path
                cached[str(scene_idx)] = end_frame_path

            # 维护视觉链：所有路径（i2i/t2i）生成完毕后更新 prev_end_frame
            prev_end_frame = end_frame_path

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
            _PROGRESS_END_FRAME_PREGEN_DONE,
        )
        return pregenerated

    # ==================================================================
    # Step 4: Video Generation
    # ==================================================================

    def _save_scene_task(self, scene_dir: str, video_id: str) -> None:
        """Persist a scene's video-task ID to ``task.json`` and ``curl.sh``.

        Args:
            scene_dir: Directory for the scene.
            video_id: Remote video task identifier.
        """
        task_file = os.path.join(scene_dir, "task.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump({"video_id": video_id}, f, indent=2)
        curl_file = os.path.join(scene_dir, "curl.sh")
        with open(curl_file, "w", encoding="utf-8") as f:
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
                with open(task_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("video_id") or data.get("task_id")
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to load cached task.json for scene: {e}")
        return None
