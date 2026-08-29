"""core.pipelines.creative.steps_audio — 音频/字幕/拼接步骤 mixin（v5.0 Batch 4 / 4.2 拆分）"""
import asyncio
import json
import logging
import os
import re
from typing import Optional

from core.compositor.concatenator import VideoConcatenator
from core.screenwriter import clean_narration_text
from models.task import StepStatus

logger = logging.getLogger(__name__)


_CHARS_PER_SEC = 4.0
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？.!?])")

# 音频/字幕阶段起始进度（阶段内线性插值）
_PROGRESS_NARRATIONS_START = 0.15
_PROGRESS_AUDIO_START = 0.82
_PROGRESS_AUDIO_DONE = 0.86
_PROGRESS_SUBTITLE_START = 0.86
_PROGRESS_SUBTITLE_DONE = 0.9
_PROGRESS_CONCAT_START = 0.92
_PROGRESS_CONCAT_DONE = 0.95

def _trim_to_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    candidate = text[:max_chars]
    # find the last sentence boundary within the valid prefix
    matches = list(_SENTENCE_BOUNDARY_RE.finditer(candidate))
    if matches and matches[-1].end() > max_chars * 0.4:
        return text[: matches[-1].end()]
    return candidate[:max_chars]

def _split_narration_into_scenes(text: str, num_scenes: int) -> list[str]:
    """将单段旁白文本按场景数均匀切分（基于字符数比例，在句末断开）。

    Args:
        text: 旁白文本
        num_scenes: 目标场景数

    Returns:
        每个场景的旁白文本列表。
    """
    if num_scenes <= 1 or not text:
        return [text] if text else [""]
    if num_scenes >= len(text):
        # 极短文本：逐字分配
        return [text[i:i+1] for i in range(len(text))] + [""] * (num_scenes - len(text))

    # 在句末标点处分段，尽量均匀
    sentences = [s.strip() for s in _SENTENCE_BOUNDARY_RE.split(text) if s.strip()]
    if not sentences:
        sentences = [text]

    total_chars = len(text)
    target_per_scene = total_chars / num_scenes

    scenes_texts = []
    current_text = ""
    current_chars = 0

    for sent in sentences:
        if current_chars > 0 and (current_chars + len(sent)) / target_per_scene > 1.3:
            scenes_texts.append(current_text)
            current_text = sent
            current_chars = len(sent)
        else:
            current_text += sent
            current_chars += len(sent)

    if current_text:
        scenes_texts.append(current_text)

    # 补足或合并到目标场景数
    while len(scenes_texts) < num_scenes:
        scenes_texts.append("")
    while len(scenes_texts) > num_scenes:
        scenes_texts[-2] += scenes_texts[-1]
        scenes_texts.pop()

    return scenes_texts

class AudioStepsMixin:
    """音频/字幕/拼接步骤：旁白切分 / TTS 生成 / 字幕 / 最终拼接。

    v5.0 Batch 4（4.2）拆分自 CreativeVideoPipeline，经 MRO 组合回主类。
    """

    # ==================================================================
    # Step 4.5: Populate narrations from story
    # ==================================================================

    def _is_narrative_para(self, text: str) -> bool:
        t = text.strip()
        if len(t) < 40:
            return False
        lower = t.lower()
        skip_prefixes = (
            "story title", "target audience", "story outline",
            "main character", "character introduction", "full story narrative",
            "故事标题", "目标受众", "故事大纲",
            "角色介绍", "主要角色", "故事梗概",
            "**故事标题", "**目标受众", "**故事大纲",
            "**角色介绍", "**主要角色",
        )
        for p in skip_prefixes:
            if lower.startswith(p):
                return False
        return True

    def _populate_narrations(self, story: str) -> None:
        num_scenes = len(self._state.scenes)
        if not num_scenes or not story:
            return

        # On resume, re-trim existing narrations (old untrimmed data may persist)
        if self._state.narrations:
            _scenes = self._state.scenes
            needs_update = any(
                len(n) > max(int((_scenes[i].duration if i < len(_scenes) else self._state.video_duration) * _CHARS_PER_SEC), 20)
                for i, n in enumerate(self._state.narrations)
            )
            if needs_update:
                self._state.narrations = [
                    _trim_to_sentence(
                        n,
                        max(int((_scenes[i].duration if i < len(_scenes) else self._state.video_duration) * _CHARS_PER_SEC), 20),
                    )
                    for i, n in enumerate(self._state.narrations)
                ]
                self.task_manager.update_state(narrations=self._state.narrations)
            return

        paragraphs = [p.strip() for p in story.split("\n\n") if p.strip()]
        if not paragraphs:
            self._state.narrations = [story] * num_scenes
            self.task_manager.update_state(narrations=self._state.narrations)
            return

        # Filter out metadata paragraphs (title, audience, outline, character intro)
        narrative_paras = [p for p in paragraphs if self._is_narrative_para(p)]
        if not narrative_paras:
            narrative_paras = paragraphs

        narrations = []
        base = len(narrative_paras) // num_scenes
        rem = len(narrative_paras) % num_scenes
        idx = 0
        for i in range(num_scenes):
            count = base + (1 if i < rem else 0)
            narrations.append("\n".join(narrative_paras[idx : idx + count]))
            idx += count

        # Trim each narration to fit within its scene's duration * 4 chars/sec speaking rate
        _scenes = self._state.scenes
        narrations = [
            _trim_to_sentence(
                n,
                max(int((_scenes[i].duration if i < len(_scenes) else self._state.video_duration) * _CHARS_PER_SEC), 20),
            )
            for i, n in enumerate(narrations)
        ]

        self._state.narrations = narrations
        self.task_manager.update_state(narrations=narrations)

    async def _step_generate_narrations(self, story: str, scenes: list) -> None:
        """Use LLM to generate a single narration text for the entire video.

        Generates ONE continuous narration that covers all scenes, with length
        matching the total video duration (sum of per-scene durations).

        Args:
            story: Full story text for context.
            scenes: List of scene visual prompts from write_script.
        """
        total_duration = sum(float(s.duration) for s in self._state.scenes)
        single_narration = self._state.narrations[0] if self._state.narrations else ""

        if single_narration and len(single_narration) > 5:
            # 续传复用已有旁白：再清洗一次，修复历史脏数据（元数据/Markdown 结构）
            cleaned = clean_narration_text(single_narration)
            if cleaned and cleaned != single_narration:
                logger.info("[Pipeline] Step generate_narrations: re-cleaned existing narration")
                self._state.narrations = [cleaned]
                self.task_manager.update_state(narrations=[cleaned])
            logger.info("[Pipeline] Step generate_narrations: SKIP (narration already populated)")
            return

        if not self._state.scenes:
            return

        logger.info("[Pipeline] Step generate_narrations: RUNNING (single narration for entire video)")
        await self._emit("narrations", "running", "正在生成旁白文案...", _PROGRESS_NARRATIONS_START)

        narration = await asyncio.to_thread(
            self.screenwriter.generate_narration_for_video,
            story,
            scenes,
            total_duration,
            self._state.style,
        )

        if not narration or len(narration) < 5:
            logger.warning("[Pipeline] LLM returned empty/short narration, using cleaned story fallback")
            max_chars = max(int(total_duration * _CHARS_PER_SEC), 40)
            narration = clean_narration_text(_trim_to_sentence(story, max_chars)) if story else ""

        self._state.narrations = [narration]
        self.task_manager.update_state(narrations=[narration])
        logger.info(f"[Pipeline] Narration generated: {len(narration)} chars for {total_duration:.0f}s video")

        # 记录自动生成的 prompt（脚本 + 旁白）
        # 场景 prompt 存储在 script.json 中，而非 SceneTask 对象上
        script_prompts: list = []
        script_path = os.path.join(self.working_dir, "script.json")
        if os.path.exists(script_path):
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    script_prompts = json.load(f)
            except Exception:
                pass
        prompts_data = {
            "scenes": script_prompts,
            "narrations": self._state.narrations,
            "script": script_prompts,
        }
        self.save_prompts(prompts_data)

    # ==================================================================
    # Step 5: Audio Generation (v3.0 split from subtitle)
    # ==================================================================

    async def _step_audio(self) -> Optional[object]:
        """Generate TTS narration audio (or silent fallback) for the entire video.

        Returns:
            SubMaker cues object if TTS succeeded, None if silent/disabled.
            Used by _step_subtitle for word-level subtitle timing.
        """
        # v3.0 backward compat: check old combined step status
        if self._state.step_audio == StepStatus.COMPLETED:
            logger.info("[Pipeline] Step audio: SKIP (already completed)")
            return None
        if (self._state.step_audio == StepStatus.PENDING
                and self._state.step_audio_subtitle == StepStatus.COMPLETED):
            logger.info("[Pipeline] Step audio: SKIP (v2.0 step_audio_subtitle completed)")
            self._state.step_audio = StepStatus.COMPLETED
            self.task_manager.update_step("step_audio", StepStatus.COMPLETED)
            return None

        combined_audio = os.path.join(self.working_dir, "combined_narration.mp3")
        # v5.x 产物规范前置：导出旁白纯文本（供外部 Agent/工具处理）
        narration_text = self._state.narrations[0] if self._state.narrations else ""
        self._save_narration_txt(narration_text, combined_audio)
        if os.path.exists(combined_audio) and os.path.getsize(combined_audio) > 0:
            logger.info("[Pipeline] Step audio: SKIP (file exists)")
            self._state.step_audio = StepStatus.COMPLETED
            self.task_manager.update_step("step_audio", StepStatus.COMPLETED)
            # 续传：音频已存在则仅重采 cues，避免字幕退回 legacy 启发式
            return await self._recover_sub_maker(
                narration_text,
                self._state.audio_config, self._state.subtitle_config,
                combined_audio,
            )

        audio_enabled = self._state.audio_config.enabled
        total_duration = sum(float(s.duration) for s in self._state.scenes)

        logger.info(
            f"[Pipeline] Step audio: RUNNING "
            f"(enabled={audio_enabled}, narration={len(narration_text)} chars)"
        )
        await self._emit(
            "audio", "running",
            "生成旁白音频..." if audio_enabled else "生成静音时间轴...",
            _PROGRESS_AUDIO_START,
        )

        sub_maker = await self._generate_audio_with_fallback(
            output_path=combined_audio,
            text=narration_text,
            audio_config=self._state.audio_config,
            subtitle_config=self._state.subtitle_config,
            duration_sec=total_duration,
            empty_placeholder="placeholder",
        )

        for scene in self._state.scenes:
            scene.narration_audio = combined_audio
        self.task_manager.update_state(
            scenes=[s.model_dump() for s in self._state.scenes],
        )

        self._state.step_audio = StepStatus.COMPLETED
        self.task_manager.update_state(step_audio=StepStatus.COMPLETED)
        await self._emit("audio", "completed", "音频生成完成", _PROGRESS_AUDIO_DONE)
        return sub_maker

    # ==================================================================
    # Step 6: Subtitle Generation (v3.0 split from audio)
    # ==================================================================

    async def _step_subtitle(self, sub_maker: Optional[object] = None) -> None:
        """Generate SRT subtitles for the entire video.

        Uses SubMaker cues from TTS (if available) or plain-text fallback.

        Args:
            sub_maker: SubMaker cues from _step_audio, or None.
        """
        # v3.0 backward compat
        if self._state.step_subtitle == StepStatus.COMPLETED:
            logger.info("[Pipeline] Step subtitle: SKIP (already completed)")
            return
        if (self._state.step_subtitle == StepStatus.PENDING
                and self._state.step_audio_subtitle == StepStatus.COMPLETED):
            logger.info("[Pipeline] Step subtitle: SKIP (v2.0 step_audio_subtitle completed)")
            self._state.step_subtitle = StepStatus.COMPLETED
            self.task_manager.update_step("step_subtitle", StepStatus.COMPLETED)
            return

        combined_srt = os.path.join(self.working_dir, "combined_narration.srt")
        if os.path.exists(combined_srt) and os.path.getsize(combined_srt) > 0:
            logger.info("[Pipeline] Step subtitle: SKIP (file exists)")
            self._state.step_subtitle = StepStatus.COMPLETED
            self.task_manager.update_step("step_subtitle", StepStatus.COMPLETED)
            return

        subtitle_enabled = self._state.subtitle_config.enabled
        narration_text = self._state.narrations[0] if self._state.narrations else ""

        logger.info(
            f"[Pipeline] Step subtitle: RUNNING "
            f"(enabled={subtitle_enabled}, narration={len(narration_text)} chars, "
            f"scenes={len(self._state.scenes)})"
        )
        await self._emit(
            "subtitle", "running",
            "生成字幕..." if subtitle_enabled else "跳过字幕生成",
            _PROGRESS_SUBTITLE_START,
        )

        num_scenes = len(self._state.scenes)

        # ── 准备场景文本和时长 ──
        if num_scenes > 1:
            scene_texts = self._state.narrations[:]
            if len(scene_texts) == 1 and num_scenes > 1:
                scene_texts = _split_narration_into_scenes(
                    narration_text, num_scenes,
                )
        else:
            scene_texts = [narration_text] if narration_text else [""]

        scene_durations = (
            [float(s.duration) for s in self._state.scenes]
            if self._state.scenes
            else [float(self._state.video_duration)]
        )

        srt_path, styles_path = await self.generate_subtitles_common(
            segment_texts=scene_texts,
            segment_durations=scene_durations,
            subtitle_config=self._state.subtitle_config,
            sub_maker=sub_maker,
            audio_path=os.path.join(self.working_dir, "combined_narration.mp3"),
            srt_filename="combined_narration.srt",
            screenwriter=self.screenwriter,
            video_width=self._state.video_width,
            video_height=self._state.video_height,
        )

        if styles_path:
            self._state.subtitle_styles_path = styles_path
            self.task_manager.update_state(subtitle_styles_path=styles_path)

            # 追加字幕样式 prompt 到 prompts.json
            try:
                prompts_path = os.path.join(self.working_dir, "prompts.json")
                existing = {}
                if os.path.exists(prompts_path):
                    with open(prompts_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                with open(styles_path, "r", encoding="utf-8") as f:
                    existing["subtitle_styles"] = json.load(f)
                self.save_prompts(existing)
            except Exception:
                pass

        for scene in self._state.scenes:
            scene.subtitle_srt = srt_path
        self.task_manager.update_state(
            scenes=[s.model_dump() for s in self._state.scenes],
        )

        self._state.step_subtitle = StepStatus.COMPLETED
        self.task_manager.update_state(step_subtitle=StepStatus.COMPLETED)
        await self._emit("subtitle", "completed", "字幕生成完成", _PROGRESS_SUBTITLE_DONE)

    # ==================================================================
    # Step 6: Concatenation (MODIFIED in v2.0)
    # ==================================================================

    async def _step_concatenate(self, all_video_paths: list) -> str:
        """Concatenate scene videos into the final output.

        When audio is enabled, uses the single combined audio+subtitle track
        (from _step_audio_subtitle) and overlays it on the concatenated video.

        Falls back to :meth:`VideoConcatenator.concat_videos` when audio is
        disabled or unavailable.

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

        await self._emit("concatenate", "running", "正在拼接视频...", _PROGRESS_CONCAT_START)

        has_audio = self._state.audio_config.enabled
        has_subtitle = self._state.subtitle_config.enabled
        combined_audio = os.path.join(self.working_dir, "combined_narration.mp3")
        combined_srt = os.path.join(self.working_dir, "combined_narration.srt")

        # Phase 2: LLM 样式 JSON 路径
        styles_path = self._state.subtitle_styles_path or ""
        if styles_path and not os.path.exists(styles_path):
            styles_path = ""

        if has_audio or has_subtitle:
            audio_exists = os.path.exists(combined_audio) and os.path.getsize(combined_audio) > 0
            srt_exists = os.path.exists(combined_srt) and os.path.getsize(combined_srt) > 0

            if audio_exists:
                await asyncio.to_thread(
                    VideoConcatenator.concat_videos_with_audio_overlay,
                    video_paths=all_video_paths,
                    audio_path=combined_audio,
                    srt_path=combined_srt if (has_subtitle and srt_exists) else None,
                    output_path=final_video_path,
                    subtitle_style=self._state.subtitle_config.style if has_subtitle else None,
                    subtitle_styles_path=styles_path if styles_path else None,
                )
            else:
                await asyncio.to_thread(
                    VideoConcatenator.concat_videos, all_video_paths, final_video_path
                )
        else:
            await asyncio.to_thread(
                VideoConcatenator.concat_videos, all_video_paths, final_video_path
            )

        self._state.step_concatenation = StepStatus.COMPLETED
        self._state.final_video_file = final_video_path
        self.task_manager.update_state(
            step_concatenation=StepStatus.COMPLETED,
            final_video_file=final_video_path,
        )
        await self._emit("concatenate", "completed", "视频拼接完成", _PROGRESS_CONCAT_DONE)
        return final_video_path
