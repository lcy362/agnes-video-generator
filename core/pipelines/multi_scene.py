"""core.pipelines.multi_scene — 多场景视频通用框架（v4.0 重构核心）

模板方法 ``run()`` 定义标准流程：
    build_scenes → build_reference_images → generate_videos → audio+subtitle → composite

子类只需提供数据来源（_build_scenes / _build_reference_images / _composite_final），
并可按需覆写通用步骤（_generate_videos / _generate_audio / _generate_subtitles）或钩子方法。

设计原则（见 docs/plans/v4.0/pipeline_refactor.md）：
    - 差异只在"数据从哪来"，不在"流程怎么做"
    - 通用步骤操作 ``self._state.scenes: List[SceneTask]``，通过钩子读取每场景参数
    - 子类可整体覆写某步骤以保留其特有的（如链式/循环）视频生成逻辑
"""

import asyncio
import logging
import os
import re
import traceback
from abc import abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional

from core.api.agnes_video import VideoTaskCancelled, is_remote_video_failure
from core.config import get_max_ref_images
from core.pipelines import BasePipeline, CheckpointPause, PipelineShutdown
from core.pipelines.ref_slots import (
    KIND_CHARACTER,
    KIND_STYLE,
    KIND_USER_SCENE,
    RefSlot,
    merge_ref_images,
)
from models.task import SceneTask, StepStatus
from utils.network import (
    describe_network_error,
    describe_queue_full_error,
    queue_full_message_params,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 命名常量（v5.0 Batch 5 / 5.3 魔法数字收敛）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StepProgressLimits:
    """模板方法各阶段的进度边界（0.0 ~ 1.0）。"""

    build_start: float = 0.0      # Phase 1 分镜
    build_end: float = 0.15
    reference_end: float = 0.30   # Phase 2 参考图
    video_end: float = 0.75       # Phase 3 视频生成
    audio_end: float = 0.85       # Phase 4 配音
    subtitle_end: float = 0.90    # Phase 5 字幕
    composite_end: float = 0.98   # Phase 6 合成
    done: float = 1.0             # 完成


_PROGRESS = StepProgressLimits()

# 失败/中断事件的统一进度值
_PROGRESS_FAILED = 0.0

# 视频等待失败的重试间隔基数（秒）：delay = 基数 * (retry + 1)
_RETRY_INTERVAL_BASE_SECONDS = 20

# ── v8.1：人物板 / 风格板 ──
# 「文案里有没有反复出现的人物」的轻量启发式：命中任一人称/职业词才画人物板，
# 纯意象文本（诗词常见）不发明一张脸。宁可少画一张，也不要把人物硬塞进画面。
_PERSON_HINT_RE = re.compile(
    r"(他|她|你|我|人们|人物|主角|男主|女主|少年|少女|老人|孩子|母亲|父亲|诗人|将军|"
    r"士兵|女子|男子|孩童|身影|"
    r"\b(he|she|his|her|him|they|them|man|woman|boy|girl|child|person|people|"
    r"protagonist|hero|heroine)\b)",
    re.IGNORECASE,
)

#: 风格板默认描述（用户未填视觉风格时使用；只写介质/调色/光线，不写人物与情节）
_DEFAULT_STYLE_PLATE_PROMPT = (
    "Cinematic still frame, consistent color grading, soft directional light, "
    "film grain, shallow depth of field. No people, no text, no logo."
)


class MultiScenePipeline(BasePipeline):
    """多场景视频生成通用框架。

    提供统一的步骤编排（模板方法 ``run``）、步骤执行包装器（``_execute_step``）、
    通用水印后处理（继承自 ``BasePipeline``）、以及通用视频/音频/字幕生成实现。

    子类必须实现三个抽象方法提供数据源：
        - ``_build_scenes``         构建 ``self._state.scenes``（List[SceneTask]）
        - ``_build_reference_images`` 生成参考图（可空实现跳过）
        - ``_composite_final``      合成最终视频

    并可通过钩子方法定制参数来源：
        - ``_get_narration_text``        配音文本
        - ``_get_segment_texts_and_durations`` 字幕分段文本与时长
        - ``_get_scene_video_prompt``     单场景视频 prompt
        - ``_get_scene_ref_images``       单场景参考图列表
        - ``_get_scene_duration``         单场景视频时长
        - ``_get_audio_path``             音频文件输出路径
        - ``_set_subtitle_paths``         字幕路径写回 state
    """

    # v5.0 Batch 3（S3，方案 A）：粗粒度步骤级 skip 默认开启；
    # Creative 依赖各 ``_step_*`` 读盘做细粒度续传，置 False 禁用（原覆写已删除）。
    coarse_skip: bool = True

    # ==================================================================
    # 模板方法：run()
    # ==================================================================

    async def run(self, state) -> str:
        """标准多场景视频流程（模板方法）。"""
        self._state = state
        self._state.status = StepStatus.RUNNING
        self.task_manager.create(self._state)

        await self._emit("init", "running", self._get_init_message(), _PROGRESS.build_start)

        try:
            # Phase 1: 分镜/拆段 → List[SceneTask]
            await self._execute_step(
                "step_build_scenes", self._build_scenes,
                _PROGRESS.build_start, _PROGRESS.build_end,
                self._t("progress.multi_scene.scenes_running"), self._t("progress.multi_scene.scenes_done"),
            )

            # Phase 2: 参考图（可选，子类可空实现跳过）
            await self._execute_step(
                "step_reference_images", self._build_reference_images,
                _PROGRESS.build_end, _PROGRESS.reference_end,
                self._t("progress.multi_scene.reference_running"), self._t("progress.multi_scene.reference_done"),
            )

            # Phase 3: 视频生成（通用，子类可覆写保留链式/循环逻辑）
            await self._execute_step(
                "step_video_generation", self._generate_videos,
                _PROGRESS.reference_end, _PROGRESS.video_end,
                self._t("progress.multi_scene.videos_running"), self._t("progress.multi_scene.videos_done"),
            )

            # Phase 4: 配音（通用，子类可覆写）
            sub_maker = await self._execute_step(
                "step_audio", self._generate_audio,
                _PROGRESS.video_end, _PROGRESS.audio_end,
                self._t("progress.multi_scene.audio_running"), self._t("progress.multi_scene.audio_done"),
            )

            # Phase 5: 字幕（通用，子类可覆写）
            await self._execute_step(
                "step_subtitle",
                lambda: self._generate_subtitles(sub_maker),
                _PROGRESS.audio_end, _PROGRESS.subtitle_end,
                self._t("progress.multi_scene.subtitles_running"), self._t("progress.multi_scene.subtitles_done"),
            )

            # Phase 6: 合成
            final_video = await self._execute_step(
                "step_concatenation", self._composite_final,
                _PROGRESS.subtitle_end, _PROGRESS.composite_end,
                self._t("progress.multi_scene.composite_running"), self._t("progress.multi_scene.composite_done"),
            )

            # 后处理：水印（继承自 BasePipeline；异步，避免阻塞事件循环）
            final_video = await self._apply_watermark(final_video)

            # 完成
            self._state.status = StepStatus.COMPLETED
            self._state.final_video_file = final_video
            self.task_manager.update_state(
                status=StepStatus.COMPLETED,
                final_video_file=final_video,
            )
            await self._emit(
                "done", "completed", self._t("progress.multi_scene.done"), _PROGRESS.done,
                {"final_video": final_video},
            )
            return final_video

        except CheckpointPause as e:
            # 手动模式暂停：状态已在 _maybe_pause 落盘为 PENDING + current_checkpoint，
            # 这里正常返回（非失败、非中断），等待用户确认后 resume 继续。
            logger.info("[MultiScene] Task %s paused: %s", self.task_id, e.message)
            return ""
        except PipelineShutdown:
            # v7.0（issue #64）：中断提示按任务落盘的 ui_language 双语化
            await self._emit(
                "error", "failed", self._t("task.interrupted_resumable"),
                _PROGRESS_FAILED,
                preserve_step=True,
            )
            raise
        except Exception as e:
            # 网络 / 域名解析类故障翻译成可自助排查的提示（issue #56/#57：此前只抛
            # RetryError[...]，用户看不出是本机 DNS 问题，反复点「重试任务」无效）
            # v7.0（issue #64）：按 state.ui_language 输出中/英文，避免英文界面看到中文诊断
            # v7.0 U1：队列满优先走结构化提示（前端按 22 语言渲染，后端给 zh/en 兜底）
            message = (
                describe_queue_full_error(e, lang=self._ui_lang())
                or describe_network_error(e, lang=self._ui_lang())
                or str(e)
            )
            message_key = "error.video.queue_full" if queue_full_message_params(e) else None
            message_params = queue_full_message_params(e) or None
            failed_step = self._state.current_step if self._state else ""
            # 持久化完整 traceback，供诊断端点/前端反馈报告暴露（定位环境级异常如 [WinError 2]）
            self._state.status = StepStatus.FAILED
            self.task_manager.update_state(
                status=StepStatus.FAILED,
                error_traceback=traceback.format_exc(),
                # 失败即落盘真实环节 + 可读消息：诊断报告的「失败环节」不再依赖前端
                # 挂载时的快照，也不会因进度写盘节流而停留在很久以前的旧值
                current_step=failed_step,
                current_status="failed",
                current_message=message,
            )
            logger.error(
                "[MultiScene] Task %s failed at step '%s': %s",
                self.task_id, failed_step, e,
            )
            await self._emit(
                "error", "failed", message, _PROGRESS_FAILED, preserve_step=True,
                message_key=message_key, message_params=message_params,
            )
            raise

    # ==================================================================
    # 步骤执行包装器
    # ==================================================================

    async def _execute_step(
        self, step_name: str, action: Callable,
        progress_start: float, progress_end: float,
        running_msg: str, completed_msg: str,
        coarse_skip: Optional[bool] = None,
    ):
        """统一的步骤执行器：自动处理断点续传、状态标记、进度上报。

        断点续传规则：启用粗粒度 skip 时（显式 ``coarse_skip`` 覆盖，缺省取
        ``self.coarse_skip``），若 ``self._state`` 上对应步骤字段已为 COMPLETED
        则整步跳过；禁用时总是执行，由步骤内部按文件/字段做细粒度续传。
        """
        skip_enabled = self.coarse_skip if coarse_skip is None else coarse_skip
        if skip_enabled and getattr(self._state, step_name, StepStatus.PENDING) == StepStatus.COMPLETED:
            logger.info(f"[Pipeline] Step {step_name}: already completed, skipping")
            return None

        self.task_manager.update_step(step_name, StepStatus.RUNNING)
        await self._emit(step_name, "running", running_msg, progress_start)

        result = await action()

        self.task_manager.update_step(step_name, StepStatus.COMPLETED)
        await self._emit(step_name, "completed", completed_msg, progress_end)

        # v6.0 手动模式：步骤完成后检查是否命中暂停点（coarse_skip 跳过的不触发）。
        # 传入步骤完成进度，暂停点展示真实进度而非 100%。
        await self._maybe_pause(step_name, progress_end)
        return result

    # ==================================================================
    # 抽象方法：数据来源（子类必须实现）
    # ==================================================================

    @abstractmethod
    async def _build_scenes(self) -> None:
        """构建场景列表，产出 ``self._state.scenes``（List[SceneTask]）。"""
        ...

    @abstractmethod
    async def _build_reference_images(self) -> None:
        """构建参考图。可空实现（直接 ``return``）跳过此阶段。"""
        ...

    @abstractmethod
    async def _composite_final(self) -> str:
        """合成最终视频，返回视频路径。"""
        ...

    # ==================================================================
    # 通用步骤实现（操作 self._state.scenes，子类可整体覆写）
    # ==================================================================

    async def _generate_videos(self) -> None:
        """通用视频生成：两阶段（批量提交 + 逐个等待）。

        每个场景从 SceneTask 对象获取 prompt / duration / ref_images（通过钩子）。
        子类（如链式/循环视频）可整体覆写本方法以保留其特有逻辑。
        """
        scenes = self._state.scenes

        if self._is_external():
            # v7.6 外部素材模式：分镜视频由外部工具产出、经 videos 检查点导入
            # （PRD 检查点产物矩阵中 videos 的「本项目产物」为「—」）。本项目在此
            # **不调用 Agnes 生成视频**，仅登记磁盘上已存在的分镜视频，随后在
            # videos 检查点暂停等待用户回填。
            for i, scene in enumerate(scenes):
                video_path = os.path.join(self.working_dir, f"scene_{i}", "video.mp4")
                if os.path.exists(video_path):
                    scene.video_file = video_path
                    scene.video_status = StepStatus.COMPLETED
            self.task_manager.update_state(scenes=[s.model_dump() for s in scenes])
            logger.info(
                "[Pipeline] Step video_gen: SKIP (external asset mode), %d scene videos on disk",
                sum(1 for s in scenes if s.video_file),
            )
            return

        # Phase 1: 批量提交
        pending: list = []
        for i, scene in enumerate(scenes):
            self._check_shutdown()
            scene_dir = os.path.join(self.working_dir, f"scene_{i}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            if os.path.exists(video_path):
                scene.video_file = video_path
                continue

            video_id = self._load_task_json(scene_dir)
            if video_id:
                scene.video_id = video_id
                pending.append((i, video_id, video_path))
                continue

            prompt = self._get_scene_video_prompt(scene, i)
            ref_images = self._get_scene_ref_images(scene, i)
            duration = self._get_scene_duration(scene, i)
            # v8.1 路径 K：该场景有首尾帧时只提交静帧（keyframe 与 reference 互斥）
            keyframes = self._get_scene_keyframes(scene, i)

            submit_kwargs = {}
            if keyframes:
                first_frame, last_frame = keyframes
                submit_kwargs = {"first_frame": first_frame, "last_frame": last_frame}
                ref_images = []

            video_id = await self.video_api.submit_video(
                prompt=prompt,
                reference_image_paths=ref_images,
                duration=duration,
                width=self._state.video_width,
                height=self._state.video_height,
                # U1（v7.0）：队列满时实时向前端推「排队重试中」
                progress_callback=self._submit_progress_callback("video_gen", 0.40),
                **submit_kwargs,
            )
            scene.video_id = video_id
            self._save_task_json(scene_dir, {"video_id": video_id})
            pending.append((i, video_id, video_path))

        self.task_manager.update_state(scenes=[s.model_dump() for s in scenes])

        # Phase 2: 并发等待全部视频（优化路线图 1.3）
        # 此前逐场景串行 wait_for_video，N 场景等待时长线性叠加；改为并行轮询
        # （视频 API 本身异步），整体耗时 ≈ 最慢场景，随后逐个落盘并上报进度。
        if pending:
            await self._emit(
                "video_gen", "running",
                self._t("progress.multi_scene.wait_videos", n=len(pending)),
                0.40,
            )

        async def _wait_one(idx: int, vid: str):
            out = await self._wait_for_video_with_retry(vid, idx)
            return idx, out

        done = await asyncio.gather(
            *[_wait_one(i, vid) for i, vid, _ in pending],
            return_exceptions=True,
        )
        # 任一场景失败 / 停止：立即穿透（保持 0.2 的停止即时性与异常语义）
        for item in done:
            if isinstance(item, BaseException):
                raise item
        results = dict(done)

        # 逐个落盘 + 上报进度（保存为磁盘 IO，串行避免并发写）
        for j, (scene_idx, video_id, video_path) in enumerate(pending):
            self._check_shutdown()
            video_output = results[scene_idx]
            await video_output.save(video_path)
            self._state.scenes[scene_idx].video_file = video_path
            self.task_manager.update_state(scenes=[s.model_dump() for s in self._state.scenes])
            await self._emit(
                "video_gen", "running",
                self._t("progress.multi_scene.save_video", cur=j + 1, total=len(pending)),
                0.40 + 0.35 * (j + 1) / max(len(pending), 1),
            )

    async def _wait_for_video_with_retry(
        self, video_id: str, scene_idx: int, max_retries: int = 3
    ):
        """带重试的视频等待。

        优化路线图 0.2：
        1. 用户停止（``VideoTaskCancelled``）不再被当作可重试的临时错误，直接
           穿透——此前停止会走 20s/40s 退避重试，导致「点停止后最长 ~120s 才停」。
        2. ``task.json`` 仅在**确认服务端失败**时删除；超时、用户取消、网络中断
           一律保留，否则续传只能重新提交，浪费 1 次/分钟/Key 的视频配额。
        """
        scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
        for retry in range(max_retries):
            try:
                return await self.video_api.wait_for_video(video_id)
            except VideoTaskCancelled:
                # 用户停止：不重试、不删 task.json，立即穿透
                raise
            except Exception as e:
                if retry < max_retries - 1:
                    delay = _RETRY_INTERVAL_BASE_SECONDS * (retry + 1)
                    logger.warning(
                        f"Video {video_id[:16]} retry {retry + 1}/{max_retries}: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    if is_remote_video_failure(e):
                        tf = os.path.join(scene_dir, "task.json")
                        if os.path.exists(tf):
                            os.remove(tf)
                    raise

    async def _generate_audio(self) -> Optional[object]:
        """通用 TTS 音频生成（EdgeTTS → Silent 降级）。返回 sub_maker。"""
        audio_path = self._get_audio_path()
        # v5.x 产物规范前置：导出旁白纯文本（供外部 Agent/工具处理）
        self._save_narration_txt(self._get_narration_text(), audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            self._state.combined_audio = audio_path
            logger.info("[MultiScene] audio: file already exists, skipping")
            # 续传：音频已存在则仅重采 cues，避免字幕退回 legacy 启发式
            text = self._get_narration_text()
            return await self._recover_sub_maker(
                text,
                self._state.audio_config,
                self._state.subtitle_config,
                audio_path,
            )

        text = self._get_narration_text()
        if not text:
            logger.info("[MultiScene] audio: empty narration text, skipping")
            return None

        total_duration = sum(float(s.duration) for s in self._state.scenes)
        # Batch 3（S4）：audio_config/subtitle_config 已为 BaseTaskState 共享字段
        audio_config = self._state.audio_config
        subtitle_config = self._state.subtitle_config

        await self._emit("audio", "running", self._t("progress.multi_scene.gen_audio", chars=len(text)), _PROGRESS.audio_end)

        sub_maker = await self._generate_audio_with_fallback(
            output_path=audio_path,
            text=text,
            audio_config=audio_config,
            subtitle_config=subtitle_config,
            duration_sec=total_duration,
            empty_placeholder="",
        )

        self._state.combined_audio = audio_path
        self.task_manager.update_state(combined_audio=audio_path)
        return sub_maker

    async def _generate_subtitles(self, sub_maker: Optional[object] = None) -> None:
        """通用字幕生成（复用 BasePipeline.generate_subtitles_common）。"""
        if not self._state.subtitle_config.enabled:
            return
        texts, durs = self._get_segment_texts_and_durations()
        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=texts,
            segment_durations=durs,
            subtitle_config=self._state.subtitle_config,
            sub_maker=sub_maker,
            audio_path=self._state.combined_audio or "",
            screenwriter=self.screenwriter,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )
        self._set_subtitle_paths(srt_path, styles_path)

    # ==================================================================
    # v8.1 参考图板块（人物板 / 风格板）与衔接静帧
    # ==================================================================

    def _ensure_image_generator(self):
        """延迟创建图片 API（稿件/诗词此前没有图片客户端，按需创建）。"""
        generator = getattr(self, "image_generator", None)
        if generator is None:
            from core.api.agnes_image import AgnesImageAPI

            generator = AgnesImageAPI(api_key=self.api_key)
            self.image_generator = generator
        return generator

    async def _generate_plate_image(self, prompt: str, output_path: str) -> str:
        """生成一张板块图（存在即复用），失败只记日志、不阻断任务。"""
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        generator = self._ensure_image_generator()
        size = f"{self._state.video_width}x{self._state.video_height}"
        try:
            output = await generator.generate_single_image(prompt=prompt, size=size)
            await output.save(output_path)
        except Exception as e:
            logger.warning("[MultiScene] plate image generation failed (%s): %s", output_path, e)
            return ""
        logger.info("[MultiScene] plate image ready: %s", output_path)
        return output_path

    async def _prepare_ref_plates(
        self, text: str, style: str = "", *, with_character: bool = True,
        with_style: bool = True,
    ) -> None:
        """准备人物板 / 风格板（用户上传优先，其余按需生成）。

        规则（PRD v8.1 §3.6）：
        - 用户上传的图直接写入对应板块，不另外生成；
        - 风格板默认生成 1 张（只描述介质/调色/光线，不写人物与情节）；
        - 人物板仅在文案里出现（反复出现的）人物时才生成——纯意象文本不发明一张脸。

        Args:
            text: 任务正文，用于判断是否需要人物板。
            style: 风格描述文本，用于生成风格板。
            with_character: 是否允许生成人物板。
            with_style: 是否准备风格板。创意关键帧模式传 ``False``：该模式视频
                只提交首尾帧、尾帧 i2i 也不读风格板，生成出来的图不会被任何
                请求使用（白白多一次图生图）。其余类型/路径保持默认 ``True``。

        本方法**不抛异常**：板块图属于「锦上添花」，生成失败只留 warning，
        后续路径会退化为无板参考（行为与升级前一致）。
        """
        state = self._state
        uploaded_character = [p for p in (getattr(state, "character_images", []) or []) if p]
        uploaded_style = [p for p in (getattr(state, "style_images", []) or []) if p]
        state.character_plate = uploaded_character[:2]
        state.style_plate = uploaded_style[:2] if with_style else []

        # v7.6 外部素材模式：板块图同样由外部工具产出（references 检查点导入），
        # 本项目不调用 Agnes 图像模型；用户已上传的图仍作为板块使用。
        external = self._is_external()

        if with_style and not state.style_plate and not external:
            raw_style = (style or "").strip()
            prompt = (
                f"Style reference only — medium, color grading and lighting: {raw_style}. "
                f"{_DEFAULT_STYLE_PLATE_PROMPT}"
                if raw_style else _DEFAULT_STYLE_PLATE_PROMPT
            )
            path = await self._generate_plate_image(
                prompt, os.path.join(self.working_dir, "style_plate.png"),
            )
            if path:
                state.style_plate = [path]

        if (
            with_character and not external
            and not state.character_plate and _PERSON_HINT_RE.search(text or "")
        ):
            appearance = ""
            screenwriter = getattr(self, "screenwriter", None)
            if screenwriter is not None:
                try:
                    appearance = await asyncio.to_thread(
                        screenwriter.get_character_appearance, text,
                    )
                except Exception as e:  # LLM 失败不影响主流程
                    logger.warning("[MultiScene] character appearance failed: %s", e)
            prompt = (
                f"Character reference sheet, single person, front-facing, neutral "
                f"background, full identity details visible. {appearance}"
                if appearance else
                "Character reference sheet, single person, front-facing, neutral "
                "background, cinematic lighting."
            )
            path = await self._generate_plate_image(
                prompt, os.path.join(self.working_dir, "character_plate.png"),
            )
            if path:
                state.character_plate = [path]

        self.task_manager.update_state(
            character_plate=state.character_plate or [],
            style_plate=state.style_plate or [],
        )
        logger.info(
            "[MultiScene] ref plates: character=%d style=%d",
            len(state.character_plate or []), len(state.style_plate or []),
        )

    @staticmethod
    def _frame_prompt(scene_prompt: str, roles: List[str], kind: str) -> str:
        """拼装首/尾帧图生图提示词：逐张说明角色，避免参考图互相抢画面。"""
        guidance = "；".join(
            f"第 {i + 1} 张：{desc}" for i, desc in enumerate(roles)
        ) if re.search(r"[\u4e00-\u9fff]", scene_prompt or "") else "; ".join(
            f"Picture {i + 1}: {desc}" for i, desc in enumerate(roles)
        )
        head = "本段首帧" if kind == "first" else "本段尾帧"
        return (
            f"{head}。{guidance}。画面内容：{scene_prompt}"
            if re.search(r"[\u4e00-\u9fff]", scene_prompt or "")
            else f"{'Opening' if kind == 'first' else 'Closing'} frame of the shot. "
                 f"{guidance}. Shot content: {scene_prompt}"
        )

    async def _prepare_link_shot_frames(self) -> None:
        """路径 K：逐段画首/尾帧静帧（存在即复用，按段串行以保证衔接）。

        首帧参考：人物板 + 风格板 + 上一镜**已画好的**尾帧 + 本段内容图；
        尾帧参考：人物板 + 风格板 + 本段首帧 + 本段内容图（不带上一镜，否则画面
        不会往前走）。超出图片侧上限时从末尾丢（先丢多出来的本段内容图）。
        """
        state = self._state
        scenes = list(getattr(state, "scenes", []) or [])
        if not scenes:
            return
        # v7.6 外部素材模式：首/尾帧由外部工具产出、经 references 检查点导入，
        # 本项目不调用 Agnes 画帧（导入后的文件同样满足路径 K 的提交条件）。
        if self._is_external():
            logger.info("[MultiScene] link shot frames: SKIP (external asset mode)")
            return
        generator = self._ensure_image_generator()
        limit = get_max_ref_images(getattr(generator, "i2i_model", ""), media="image")
        size = f"{state.video_width}x{state.video_height}"
        character = list(getattr(state, "character_plate", []) or [])
        style = list(getattr(state, "style_plate", []) or [])
        previous_end = ""

        for index, scene in enumerate(scenes):
            self._check_shutdown()
            scene_dir = os.path.join(self.working_dir, f"scene_{index}")
            os.makedirs(scene_dir, exist_ok=True)
            first_path = os.path.join(scene_dir, "start_frame.png")
            end_path = os.path.join(scene_dir, "end_frame.png")
            content = list(getattr(scene, "ref_images", []) or [])
            scene_prompt = self._get_scene_video_prompt(scene, index)

            if not (os.path.exists(first_path) and os.path.getsize(first_path) > 0):
                slots = [
                    RefSlot(KIND_CHARACTER, character),
                    RefSlot(KIND_STYLE, style),
                    RefSlot("continuity", [previous_end] if previous_end else []),
                    RefSlot(KIND_USER_SCENE, content),
                ]
                images, dropped = merge_ref_images(slots, limit)
                if dropped:
                    logger.warning("[MultiScene] Scene %d first-frame refs truncated: %s",
                                   index, dropped)
                roles = []
                if character:
                    roles.append("锁定人物身份，不改变长相")
                if style:
                    roles.append("只取风格（介质/调色/光线），不要复制构图")
                if previous_end:
                    roles.append("沿用上一镜的空间与光位")
                roles.extend(["本段内容参考"] * max(len(content), 1))
                try:
                    output = await generator.generate_single_image(
                        prompt=self._frame_prompt(
                            scene_prompt,
                            roles[: len(images)] or roles[:1],
                            "first",
                        ),
                        reference_image_paths=images,
                        size=size,
                    )
                    await output.save(first_path)
                except Exception as e:
                    logger.warning("[MultiScene] Scene %d first frame failed: %s", index, e)
                    raise

            if not (os.path.exists(end_path) and os.path.getsize(end_path) > 0):
                slots = [
                    RefSlot(KIND_CHARACTER, character),
                    RefSlot(KIND_STYLE, style),
                    RefSlot("continuity", [first_path]),
                    RefSlot(KIND_USER_SCENE, content),
                ]
                images, dropped = merge_ref_images(slots, limit)
                if dropped:
                    logger.warning("[MultiScene] Scene %d end-frame refs truncated: %s",
                                   index, dropped)
                roles = []
                if character:
                    roles.append("锁定人物身份，与首帧同一人")
                if style:
                    roles.append("只取风格，不要复制构图")
                roles.append("本段首帧，保持空间连续但画面推进到本段结尾")
                roles.extend(["本段内容参考"] * max(len(content), 1))
                try:
                    output = await generator.generate_single_image(
                        prompt=self._frame_prompt(
                            scene_prompt, roles[: len(images)] or roles[:1], "end",
                        ),
                        reference_image_paths=images,
                        size=size,
                    )
                    await output.save(end_path)
                except Exception as e:
                    logger.warning("[MultiScene] Scene %d end frame failed: %s", index, e)
                    raise

            scene.first_frame_file = first_path
            scene.end_frame_file = end_path
            previous_end = end_path
            self.task_manager.update_state(scenes=[s.model_dump() for s in scenes])
            await self._emit(
                "reference_images", "running",
                self._t("progress.multi_scene.link_shots", cur=index + 1, total=len(scenes)),
                0.20 + 0.08 * (index + 1) / len(scenes),
            )

    # ==================================================================
    # 钩子方法（子类可覆盖）
    # ==================================================================

    def _get_init_message(self) -> str:
        return self._t("progress.multi_scene.init")

    def _get_narration_text(self) -> str:
        """配音文本。默认拼接各场景 narration_text。"""
        return "\n\n".join(
            s.narration_text for s in self._state.scenes if s.narration_text
        )

    def _get_segment_texts_and_durations(self) -> tuple:
        """字幕分段文本与时长。默认取各场景 narration_text + duration。

        v7.6 外部素材模式 · 对白字幕来源（``subtitle_source == "dialogue"``）时
        改取各场景 ``dialogue``（空则回退该场景旁白）；无对白来源时即回退旁白。
        """
        use_dialogue = self._use_dialogue_subtitles()

        def _text_of(scene) -> str:
            if use_dialogue:
                return getattr(scene, "dialogue", "") or scene.narration_text
            return scene.narration_text

        pairs = [(s, _text_of(s)) for s in self._state.scenes]
        texts = [t for _s, t in pairs if t] or [""]
        durs = [float(s.duration) for s, t in pairs if t] or [5.0]
        return texts, durs

    def _get_audio_path(self) -> str:
        """音频输出路径。子类可覆写（如稿件用 full_narration.mp3）。"""
        return os.path.join(self.working_dir, "combined_narration.mp3")

    def _get_scene_video_prompt(self, scene: SceneTask, index: int) -> str:
        """单场景视频 prompt。默认优先 end_frame_prompt，回退 scene_prompt。"""
        return getattr(scene, "end_frame_prompt", "") or getattr(scene, "scene_prompt", "")

    def _get_scene_ref_images(self, scene: SceneTask, index: int) -> List[str]:
        """单场景参考图列表（v8.1 路径 R）。

        顺序唯一由 ``ref_slots.merge_ref_images`` 决定：人物板 → 风格板 → 本段
        内容图。超出模型上限时从末尾丢并留日志（不再静默截断）。
        """
        slots = [
            RefSlot(KIND_CHARACTER, list(getattr(self._state, "character_plate", []) or [])),
            RefSlot(KIND_STYLE, list(getattr(self._state, "style_plate", []) or [])),
            RefSlot(KIND_USER_SCENE, list(getattr(scene, "ref_images", []) or [])),
        ]
        images, dropped = merge_ref_images(slots, get_max_ref_images(self.video_api.model))
        if dropped:
            logger.warning(
                "[MultiScene] Scene %d ref images truncated: %s", index, dropped,
            )
        return images

    def _get_scene_keyframes(self, scene: SceneTask, index: int) -> Optional[tuple]:
        """单场景首尾帧（v8.1 路径 K）。默认 None = 走参考图路径。

        仅在任务开启「衔接」（``state.link_shots``）且该段首/尾帧已画好时返回
        ``(first_frame, last_frame)``，模板据此只提交 keyframe、不带 images[]。
        """
        if not getattr(self._state, "link_shots", False):
            return None
        first = getattr(scene, "first_frame_file", "") or ""
        last = getattr(scene, "end_frame_file", "") or ""
        if not (first and os.path.exists(first) and last and os.path.exists(last)):
            return None
        return first, last

    def _get_scene_duration(self, scene: SceneTask, index: int) -> int:
        """单场景视频时长。默认 max(scene.duration, 3)。"""
        return max(int(getattr(scene, "duration", 5)), 3)

    def _set_subtitle_paths(self, srt_path: str, styles_path: str) -> None:
        """字幕路径写回 state。子类覆写以匹配各自字段名。"""
        self._state.combined_subtitle = srt_path
        if styles_path:
            self._state.subtitle_styles_path = styles_path
        self.task_manager.update_state(
            combined_subtitle=srt_path,
            subtitle_styles_path=styles_path or self._state.subtitle_styles_path,
        )
