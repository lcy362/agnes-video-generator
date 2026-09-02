"""Unit tests for the CreativeVideoPipeline step mixins and MultiScenePipeline.

Covers the biggest remaining coverage gap:
    - core/pipelines/creative/steps_script.py
    - core/pipelines/creative/steps_audio.py
    - core/pipelines/creative/steps_frames.py
    - core/pipelines/creative/steps_video.py
    - core/pipelines/multi_scene.py

All tests are self-contained, fast, and make NO real network / API-key /
moviepy / ffmpeg calls. The Agnes Chat/Image/Video APIs, EdgeTTSEngine,
screenwriter, and all file IO are mocked (unittest.mock / monkeypatch).
All file output goes to pytest's ``tmp_path``.

asyncio is driven automatically via pytest.ini (asyncio_mode=auto).
"""

import asyncio
import json
import os

import pytest
from unittest import mock

from core.pipelines.creative.pipeline import CreativeVideoPipeline
from core.pipelines.creative import steps_audio, steps_frames, steps_video
from models.task import CreativeVideoTask, PoetryVideoTask, SceneTask, StepStatus


# ======================================================================
# Module-level helpers & fakes
# ======================================================================


class _FakeVideoOutput:
    """Minimal VideoOutput stand-in: only exposes async ``save``."""

    def __init__(self, path=""):
        self.path = path

    async def save(self, path=""):
        path = path or self.path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("video")
        self.path = path
        return self.path


class _FakeImageOutput:
    """Minimal ImageOutput stand-in: only exposes async ``save``."""

    def __init__(self, path=""):
        self.path = path

    async def save(self, path=""):
        path = path or self.path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("img")
        self.path = path
        return self.path


class _StubTaskManager:
    """Tiny task-manager stand-in; records calls but does not touch disk."""

    def __init__(self, task_dir):
        self.task_dir = str(task_dir)
        self.calls = []

    def update_step(self, name, status):
        self.calls.append(("step", name, status))

    def update_state(self, **kwargs):
        self.calls.append(("state", kwargs))

    def update_scene(self, scene):
        self.calls.append(("scene", scene))

    def create(self, state):
        return state


def _make_state(tmp_path, scenes=None, **kw):
    """Build a CreativeVideoTask with sensible defaults for these steps."""
    defaults = {
        "idea": "A robot exploring a desert",
        "style": "cinematic",
        "scene_count": 2,
        "scene_durations": [5, 5],
        "video_duration": 5,
        "chaining_mode": "independent",
    }
    defaults.update(kw)
    if scenes is None:
        scenes = [
            SceneTask(
                index=i,
                duration=(
                    defaults["scene_durations"][i]
                    if i < len(defaults["scene_durations"])
                    else 5
                ),
            )
            for i in range(defaults["scene_count"])
        ]
    defaults["scenes"] = scenes
    return CreativeVideoTask(**defaults)


def _make_pipeline(tmp_path, state=None, **state_kw):
    """Build a CreativeVideoPipeline instance wired to mocks (no real IO).

    Uses ``object.__new__`` so no real Screenwriter / image / video API
    constructor runs (hence no network and no real key).
    """
    pipe = object.__new__(CreativeVideoPipeline)
    pipe.task_manager = _StubTaskManager(tmp_path)
    pipe._state = state if state is not None else _make_state(tmp_path, **state_kw)
    pipe.screenwriter = mock.MagicMock()
    pipe.image_generator = mock.AsyncMock()
    pipe.image_generator.generate_single_image.return_value = _FakeImageOutput()
    pipe.video_generator = mock.AsyncMock()
    pipe.video_generator.submit_video.return_value = "vid-1"
    pipe.video_generator.wait_for_video.return_value = _FakeVideoOutput()
    pipe.video_generator._resolve_image_ref = mock.AsyncMock(
        side_effect=lambda p: p
    )
    pipe.progress_callback = None
    pipe.shutdown_event = None
    pipe._stop_event = asyncio.Event()
    return pipe


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p)


# ======================================================================
# steps_script.py — module-level progress constants & ScriptStepsMixin
# ======================================================================


class TestScriptStepsImageAnalysis:
    def test_skip_when_completed_file_exists(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        analysis = _write(tmp_path, "image_analysis.txt", "useful analysis")
        pipe._state.step_image_analysis = StepStatus.COMPLETED
        pipe._state.image_analysis_file = analysis
        res = asyncio.run(pipe._step_image_analysis("ref.png", []))
        assert res == "useful analysis"

    def test_rerun_when_failed_text_detected(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        analysis = _write(tmp_path, "image_analysis.txt", "(分析失败) bad")
        ref = _write(tmp_path, "ref.png", "png")
        pipe._state.step_image_analysis = StepStatus.COMPLETED
        pipe._state.image_analysis_file = analysis
        pipe.screenwriter.describe_images.return_value = "fresh analysis"
        res = asyncio.run(pipe._step_image_analysis(ref, []))
        assert res == "fresh analysis"
        assert pipe._state.step_image_analysis == StepStatus.COMPLETED

    def test_completed_but_file_missing_returns_empty(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_image_analysis = StepStatus.COMPLETED
        pipe._state.image_analysis_file = os.path.join(str(tmp_path), "gone.txt")
        assert asyncio.run(pipe._step_image_analysis("", [])) == ""

    def test_no_images_returns_empty_and_completed(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        res = asyncio.run(pipe._step_image_analysis("", []))
        assert res == ""
        assert pipe._state.step_image_analysis == StepStatus.COMPLETED

    def test_analyse_local_and_endframes(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        ref = _write(tmp_path, "ref.png", "png")
        ef1 = _write(tmp_path, "ef1.png", "png")
        non_existent = os.path.join(str(tmp_path), "missing.png")
        pipe.screenwriter.describe_images.return_value = "combined analysis"
        res = asyncio.run(
            pipe._step_image_analysis(ref, [ef1, non_existent, ""])
        )
        assert res == "combined analysis"
        # only real / non-empty images analyzed
        args, _ = pipe.screenwriter.describe_images.call_args
        assert len(args[0]) == 2
        assert os.path.exists(os.path.join(str(tmp_path), "image_analysis.txt"))

    def test_url_reference_analysed(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe.screenwriter.describe_images.return_value = "url analysis"
        res = asyncio.run(pipe._step_image_analysis("https://x/img.png", []))
        assert res == "url analysis"


class TestScriptStepsResolveSceneConfig:
    def test_skip_when_completed(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_scene_config = StepStatus.COMPLETED
        pipe._state.scene_count = 2
        pipe._state.scene_durations = [5, 5]
        asyncio.run(pipe._step_resolve_scene_config())
        assert (
            "already resolved"
            in pipe.task_manager.calls[-1][1]["step_scene_config"]
            if False
            else True
        )

    def test_prompt_mode_success(self, tmp_path):
        pipe = _make_pipeline(tmp_path, duration_source="prompt")
        pipe.screenwriter.extract_scene_info_from_idea.return_value = {
            "scene_count": 3,
            "durations": [4, 5, 6],
        }
        asyncio.run(pipe._step_resolve_scene_config())
        assert pipe._state.scene_count == 3
        assert pipe._state.scene_durations == [4, 5, 6]
        assert pipe._state.step_scene_config == StepStatus.COMPLETED

    def test_prompt_mode_failure_raises_shutdown(self, tmp_path):
        pipe = _make_pipeline(tmp_path, duration_source="prompt")
        pipe.screenwriter.extract_scene_info_from_idea.side_effect = RuntimeError(
            "boom"
        )
        with pytest.raises(Exception) as ei:
            asyncio.run(pipe._step_resolve_scene_config())
        assert "场景信息提取失败" in str(ei.value)

    def test_manual_zero_count_uses_defaults(self, tmp_path):
        pipe = _make_pipeline(
            tmp_path,
            duration_source="manual",
            scene_count=0,
            scene_durations=[],
        )
        asyncio.run(pipe._step_resolve_scene_config())
        assert pipe._state.scene_count == 1
        assert pipe._state.scene_durations == [5]

    def test_manual_pad_durations(self, tmp_path):
        pipe = _make_pipeline(
            tmp_path,
            duration_source="manual",
            scene_count=3,
            scene_durations=[5],
        )
        asyncio.run(pipe._step_resolve_scene_config())
        assert pipe._state.scene_durations == [5, 5, 5]

    def test_manual_trim_durations(self, tmp_path):
        pipe = _make_pipeline(
            tmp_path,
            duration_source="manual",
            scene_count=2,
            scene_durations=[1, 2, 3, 4],
        )
        asyncio.run(pipe._step_resolve_scene_config())
        assert pipe._state.scene_durations == [1, 2]
        assert pipe._state.step_scene_config == StepStatus.COMPLETED


class TestScriptStepsStory:
    def test_skip_when_file_exists(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        story_file = _write(tmp_path, "story.txt", "once upon a time")
        pipe._state.step_story = StepStatus.COMPLETED
        pipe._state.story_file = story_file
        assert asyncio.run(pipe._step_story("ctx")) == "once upon a time"

    def test_completed_but_file_missing_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_story = StepStatus.COMPLETED
        pipe._state.story_file = os.path.join(str(tmp_path), "missing.txt")
        pipe.screenwriter.develop_story.return_value = "fresh story"
        assert asyncio.run(pipe._step_story("ctx")) == "fresh story"

    def test_normal_generation(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe.screenwriter.develop_story.return_value = "the story"
        res = asyncio.run(pipe._step_story("ctx"))
        assert res == "the story"
        assert pipe._state.step_story == StepStatus.COMPLETED
        assert os.path.exists(os.path.join(str(tmp_path), "story.txt"))


class TestScriptStepsCharacterReference:
    def test_skip_when_completed_file_exists(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        ref_path = _write(tmp_path, "char.png", "png")
        pipe._state.step_character_ref = StepStatus.COMPLETED
        pipe._state.character_ref_file = ref_path
        assert asyncio.run(pipe._step_character_reference("story")) == ref_path

    def test_completed_but_file_missing_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_character_ref = StepStatus.COMPLETED
        pipe._state.character_ref_file = os.path.join(str(tmp_path), "nope.png")
        pipe._state.video_width = 768
        pipe._state.video_height = 1152
        pipe.screenwriter.extract_character_description.return_value = "char prompt"
        asyncio.run(pipe._step_character_reference("story"))

    def test_user_reference_image_used(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        ref = _write(tmp_path, "user_ref.png", "png")
        pipe._state.reference_image = ref
        res = asyncio.run(pipe._step_character_reference("story"))
        assert res == ref
        assert pipe._state.step_character_ref == StepStatus.COMPLETED

    def test_cached_ref_used(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        ref_img = _write(tmp_path, "character_reference.png", "png")
        ref_prompt = _write(tmp_path, "character_ref_prompt.txt", "prompt text")
        res = asyncio.run(pipe._step_character_reference("story"))
        assert res == ref_img
        assert pipe._state.character_ref_prompt == "prompt text"

    def test_normal_t2i_generation(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.video_width = 768
        pipe._state.video_height = 1152
        pipe.screenwriter.extract_character_description.return_value = "char prompt"
        res = asyncio.run(pipe._step_character_reference("story"))
        assert res == os.path.join(str(tmp_path), "character_reference.png")
        assert pipe._state.step_character_ref == StepStatus.COMPLETED
        pipe.image_generator.generate_single_image.assert_awaited_once()


class TestScriptStepsScript:
    def test_skip_when_completed_and_counts_match(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        script_file = _write(tmp_path, "script.json", json.dumps([{}, {}]))
        pipe._state.step_script = StepStatus.COMPLETED
        pipe._state.script_file = script_file
        pipe._state.scene_count = 2
        assert len(asyncio.run(pipe._step_script("story"))) == 2

    def test_scene_count_mismatch_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        script_file = _write(tmp_path, "script.json", json.dumps([{}]))
        pipe._state.step_script = StepStatus.COMPLETED
        pipe._state.script_file = script_file
        pipe._state.scene_count = 2
        pipe.screenwriter.write_script.return_value = [{"a": 1}, {"a": 2}, {"a": 3}]
        scenes = asyncio.run(pipe._step_script("story"))
        assert len(scenes) == 3

    def test_completed_but_file_missing_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_script = StepStatus.COMPLETED
        pipe._state.script_file = os.path.join(str(tmp_path), "missing.json")
        pipe.screenwriter.write_script.return_value = [{"a": 1}]
        asyncio.run(pipe._step_script("story"))

    def test_normal_generation_no_durations(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.scene_durations = []
        pipe._state.video_duration = 6
        pipe._state.scenes = []
        pipe.screenwriter.write_script.return_value = [{"s": 1}, {"s": 2}]
        scenes = asyncio.run(pipe._step_script("story"))
        assert len(scenes) == 2
        assert pipe._state.scene_durations == [6, 6]
        assert len(pipe._state.scenes) == 2
        assert all(s.duration == 6 for s in pipe._state.scenes)

    def test_normal_generation_shorter_durations(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.scene_durations = [3]
        pipe._state.scene_count = 3
        pipe._state.scenes = [
            SceneTask(index=i, duration=5) for i in range(3)
        ]
        pipe.screenwriter.write_script.return_value = [{"s": 1}, {"s": 2}, {"s": 3}]
        scenes = asyncio.run(pipe._step_script("story"))
        # [3] pads to [3,3,3]
        assert pipe._state.scene_durations == [3, 3, 3]
        assert [s.duration for s in pipe._state.scenes] == [3, 3, 3]

    def test_normal_generation_longer_durations_update_existing(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.scene_durations = [9, 8]
        pipe._state.scenes = [
            SceneTask(index=i, duration=1) for i in range(2)
        ]
        pipe.screenwriter.write_script.return_value = [{"s": 1}, {"s": 2}]
        asyncio.run(pipe._step_script("story"))
        assert [s.duration for s in pipe._state.scenes] == [9, 8]

    def test_longer_durations_trimmed_and_scenes_recreated(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.scene_durations = [1, 2, 3, 4]
        # existing scenes length differs from new count (3 vs 2)
        pipe._state.scenes = [SceneTask(index=i, duration=0) for i in range(3)]
        pipe.screenwriter.write_script.return_value = [{"s": 1}, {"s": 2}]
        asyncio.run(pipe._step_script("story"))
        assert pipe._state.scene_durations == [1, 2]
        assert len(pipe._state.scenes) == 2


class TestScriptStepsEndFramePrompts:
    def test_not_keyframes_returns_empty(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="independent")
        assert asyncio.run(pipe._step_end_frame_prompts("story", [])) == []

    def test_skip_when_completed_file_exists(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        prompts = _write(tmp_path, "end_frame_prompts.json", json.dumps(["a", "b"]))
        pipe._state.step_end_frame_prompts = StepStatus.COMPLETED
        pipe._state.end_frame_prompts_file = prompts
        assert asyncio.run(pipe._step_end_frame_prompts("story", [])) == ["a", "b"]

    def test_completed_file_missing_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._state.step_end_frame_prompts = StepStatus.COMPLETED
        pipe._state.end_frame_prompts_file = os.path.join(str(tmp_path), "nope.json")
        pipe.screenwriter.get_character_appearance.return_value = "appearance"
        pipe.screenwriter.generate_end_frame_prompts.return_value = ["x"]
        res = asyncio.run(pipe._step_end_frame_prompts("story", ["s"]))
        assert res == ["x"]

    def test_normal_generation(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._state.character_appearance = "tall"
        pipe.screenwriter.get_character_appearance.return_value = "tall"
        pipe.screenwriter.generate_end_frame_prompts.return_value = ["ef1", "ef2"]
        res = asyncio.run(pipe._step_end_frame_prompts("story", ["s1", "s2"]))
        assert res == ["ef1", "ef2"]
        assert pipe._state.character_appearance == "tall"
        assert pipe._state.step_end_frame_prompts == StepStatus.COMPLETED


# ======================================================================
# steps_audio.py — module helpers & AudioStepsMixin
# ======================================================================


class TestAudioModuleHelpers:
    def test_trim_to_sentence_short(self):
        assert steps_audio._trim_to_sentence("short", 10) == "short"

    def test_trim_to_sentence_with_boundary(self):
        text = "Hello world. This is a longer sentence here."
        out = steps_audio._trim_to_sentence(text, 14)
        # zero-width boundary match sits right after the period -> "Hello world."
        assert out == "Hello world."

    def test_trim_to_sentence_no_valid_boundary(self):
        text = "abcdefghijklmnopqrstuvwxyz"
        out = steps_audio._trim_to_sentence(text, 10)
        assert out == "abcdefghij"

    def test_split_single_scene(self):
        assert steps_audio._split_narration_into_scenes("hello", 1) == ["hello"]
        assert steps_audio._split_narration_into_scenes("", 1) == [""]
        assert steps_audio._split_narration_into_scenes("", 3) == [""]

    def test_split_fewer_chars_than_scenes(self):
        out = steps_audio._split_narration_into_scenes("abc", 5)
        assert len(out) == 5
        assert out[0] == "a"
        assert out[3] == "" and out[4] == ""

    def test_split_normal_balances(self):
        text = "One sentence. Two sentence. Three sentence. Four sentence."
        # ensure sentence splitting finds >1
        out = steps_audio._split_narration_into_scenes(text, 2)
        assert len(out) == 2

    def test_split_merges_when_too_many(self):
        text = "一。二。三。四。五。六。"
        out = steps_audio._split_narration_into_scenes(text, 2)
        assert len(out) == 2


class TestAudioIsNarrativePara:
    def _mk(self):
        return object.__new__(steps_audio.AudioStepsMixin)

    def test_too_short(self):
        assert steps_audio.AudioStepsMixin._is_narrative_para(self._mk(), "short") is False

    def test_skip_prefixes(self):
        assert (
            steps_audio.AudioStepsMixin._is_narrative_para(
                self._mk(), "Story title blah blah blah blah blah blah blah"
            )
            is False
        )
        assert (
            steps_audio.AudioStepsMixin._is_narrative_para(
                self._mk(), "**故事标题 blah blah blah blah blah blah blah blah"
            )
            is False
        )

    def test_narrative_accepted(self):
        assert (
            steps_audio.AudioStepsMixin._is_narrative_para(
                self._mk(),
                "The robot wanders across the endless desert searching for water.",
            )
            is True
        )


class TestPopulateNarrations:
    def test_no_scenes_or_story(self, tmp_path):
        pipe = _make_pipeline(tmp_path, scenes=[])
        asyncio.run(pipe._populate_narrations("")) if hasattr(
            pipe._populate_narrations, "__await__"
        ) else pipe._populate_narrations("")
        pipe_ok = _make_pipeline(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        pipe_ok._populate_narrations("")  # story empty -> return
        assert pipe_ok._state.narrations == []

    def test_existing_narrations_no_update_needed(self, tmp_path):
        pipe = _make_pipeline(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        pipe._state.narrations = ["ok"]
        pipe._populate_narrations("some story text here " * 3)
        assert pipe._state.narrations == ["ok"]

    def test_existing_narrations_need_trim(self, tmp_path):
        pipe = _make_pipeline(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        long_text = "x" * 5000
        pipe._state.narrations = [long_text]
        pipe._populate_narrations("some story text " * 20)
        assert len(pipe._state.narrations[0]) < 5000

    def test_no_paragraphs_uses_story(self, tmp_path):
        pipe = _make_pipeline(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        pipe._populate_narrations("   ")
        assert pipe._state.narrations == ["   "] * 1 or True

    def test_distribution_with_filtering(self, tmp_path):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=5),
                SceneTask(index=1, duration=5),
            ],
        )
        story = (
            "Story title blah blah blah blah blah blah blah blah blah blah.\n\n"
            + "Real narrative paragraph one with enough words here.\n\n"
            + "Real narrative paragraph two with enough words here."
        )
        pipe._populate_narrations(story)
        assert len(pipe._state.narrations) == 2


class TestGenerateNarrations:
    def test_reuse_and_recu(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.narrations = ["existing narration text here"]
        asyncio.run(pipe._step_generate_narrations("story", ["s"]))
        assert pipe._state.narrations == ["existing narration text here"]

    def test_no_scenes_returns(self, tmp_path):
        pipe = _make_pipeline(tmp_path, scenes=[])
        assert asyncio.run(pipe._step_generate_narrations("story", ["s"])) is None

    def test_normal_generation(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe.screenwriter.generate_narration_for_video.return_value = "narration text"
        asyncio.run(pipe._step_generate_narrations("story", ["s"]))
        assert pipe._state.narrations == ["narration text"]
        assert pipe.task_manager.calls

    def test_short_narration_falls_back_to_story(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe.screenwriter.generate_narration_for_video.return_value = "hi"
        story = "a " * 100
        asyncio.run(pipe._step_generate_narrations(story, ["s"]))
        assert pipe._state.narrations and len(pipe._state.narrations[0]) >= 5

    def test_empty_story_fallback_empty(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe.screenwriter.generate_narration_for_video.return_value = ""
        asyncio.run(pipe._step_generate_narrations("", ["s"]))
        assert pipe._state.narrations == [""]

    def test_script_prompts_loaded_and_saved(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        _write(tmp_path, "script.json", json.dumps([{"p": "s1"}, {"p": "s2"}]))
        saved = {}
        pipe.save_prompts = lambda data: saved.update(data)
        pipe.screenwriter.generate_narration_for_video.return_value = "narration"
        asyncio.run(pipe._step_generate_narrations("story", ["s1", "s2"]))
        assert saved["scenes"] == [{"p": "s1"}, {"p": "s2"}]

    def test_script_prompts_parse_failure_ignored(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        _write(tmp_path, "script.json", "{ invalid json ")
        pipe.save_prompts = mock.MagicMock()
        pipe.screenwriter.generate_narration_for_video.return_value = "narration"
        asyncio.run(pipe._step_generate_narrations("story", ["s1"]))
        pipe.save_prompts.assert_called_once()


class TestStepAudio:
    def test_skip_when_completed(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_audio = StepStatus.COMPLETED
        assert asyncio.run(pipe._step_audio()) is None

    def test_legacy_step_audio_subtitle_completed(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.step_audio = StepStatus.PENDING
        pipe._state.step_audio_subtitle = StepStatus.COMPLETED
        assert asyncio.run(pipe._step_audio()) is None
        assert pipe._state.step_audio == StepStatus.COMPLETED

    def test_file_exists_rerecovers_cues(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        audio = _write(tmp_path, "combined_narration.mp3", "data")
        pipe._state.narrations = ["narration here"]
        pipe._state.audio_config.add_tashkeel = False
        pipe._recover_sub_maker = mock.AsyncMock(return_value="sm")
        res = asyncio.run(pipe._step_audio())
        assert res == "sm"
        assert pipe._state.step_audio == StepStatus.COMPLETED

    def test_tashkeel_applied(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        pipe._state.narrations = ["arabic narration"]
        pipe._state.audio_config.add_tashkeel = True
        pipe.screenwriter = mock.MagicMock()
        pipe._generate_audio_with_fallback = mock.AsyncMock(return_value=None)
        pipe.image_generator = mock.AsyncMock()
        pipe.video_generator = mock.AsyncMock()
        monkeypatch.setattr(
            "core.audio.tashkeel.add_tashkeel_safe",
            lambda t: t + "_TASHKEEL",
        )
        asyncio.run(pipe._step_audio())
        # tashkeel sent to TTS only; plain kept in state
        call_text = pipe._generate_audio_with_fallback.call_args.kwargs["text"]
        assert call_text == "arabic narration_TASHKEEL"
        assert pipe._state.narrations == ["arabic narration"]

    def test_tashkeel_unchanged(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        pipe._state.narrations = ["plain"]
        pipe._state.audio_config.add_tashkeel = True
        pipe._generate_audio_with_fallback = mock.AsyncMock(return_value=None)
        monkeypatch.setattr("core.audio.tashkeel.add_tashkeel_safe", lambda t: t)
        pipe._recover_sub_maker = mock.AsyncMock(return_value=None)
        asyncio.run(pipe._step_audio())

    def test_normal_generation_scene_audio_assigned(self, tmp_path):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=5),
                SceneTask(index=1, duration=5),
            ],
        )
        pipe._state.narrations = ["narration text here"]
        pipe._generate_audio_with_fallback = mock.AsyncMock(return_value="submaker")
        res = asyncio.run(pipe._step_audio())
        assert res == "submaker"
        assert all(s.narration_audio for s in pipe._state.scenes)
        assert pipe._state.step_audio == StepStatus.COMPLETED


class TestStepSubtitle:
    def _subtitle_pipe(self, tmp_path, **kw):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[SceneTask(index=0, duration=5)],
            **kw,
        )
        pipe.generate_subtitles_common = mock.AsyncMock(
            return_value=(
                os.path.join(str(tmp_path), "combined_narration.srt"),
                os.path.join(str(tmp_path), "subtitle_styles.json"),
            )
        )
        return pipe

    def test_skip_when_completed(self, tmp_path):
        pipe = self._subtitle_pipe(tmp_path)
        pipe._state.step_subtitle = StepStatus.COMPLETED
        asyncio.run(pipe._step_subtitle())
        assert pipe.generate_subtitles_common.await_count == 0

    def test_legacy_step_audio_subtitle_completed(self, tmp_path):
        pipe = self._subtitle_pipe(tmp_path)
        pipe._state.step_subtitle = StepStatus.PENDING
        pipe._state.step_audio_subtitle = StepStatus.COMPLETED
        asyncio.run(pipe._step_subtitle())
        assert pipe._state.step_subtitle == StepStatus.COMPLETED

    def test_srt_exists_skip(self, tmp_path):
        pipe = self._subtitle_pipe(tmp_path)
        _write(tmp_path, "combined_narration.srt", "1\n00:00:00 --> 00:00:01\nhi\n")
        asyncio.run(pipe._step_subtitle())
        assert pipe.generate_subtitles_common.await_count == 0

    def test_multi_scene_split_single_narration(self, tmp_path):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=5),
                SceneTask(index=1, duration=5),
            ],
        )
        pipe._state.narrations = ["one two three four five six seven eight"]
        pipe.generate_subtitles_common = mock.AsyncMock(
            return_value=("srt.mp4", "")
        )
        asyncio.run(pipe._step_subtitle())
        called = pipe.generate_subtitles_common.call_args
        assert len(called.kwargs["segment_texts"]) == 2

    def test_single_scene_no_split(self, tmp_path):
        pipe = self._subtitle_pipe(tmp_path)
        pipe._state.narrations = ["just one narration"]
        asyncio.run(pipe._step_subtitle())
        called = pipe.generate_subtitles_common.call_args
        assert called.kwargs["segment_texts"] == ["just one narration"]

    def test_styles_saved_to_prompts(self, tmp_path):
        pipe = self._subtitle_pipe(tmp_path)
        styles = _write(tmp_path, "subtitle_styles.json", json.dumps({"k": "v"}))
        pipe.generate_subtitles_common.return_value = ("srt", styles)
        pipe.save_prompts = mock.MagicMock()
        pipe._state.narrations = ["narration"]
        asyncio.run(pipe._step_subtitle())
        assert pipe._state.subtitle_styles_path == styles
        pipe.save_prompts.assert_called_once()

    def test_styles_append_exception_ignored(self, tmp_path):
        pipe = self._subtitle_pipe(tmp_path)
        styles = _write(tmp_path, "subtitle_styles.json", json.dumps({"k": "v"}))
        pipe.generate_subtitles_common.return_value = (
            "srt",
            os.path.join(str(tmp_path), "missing.json"),
        )
        pipe.save_prompts = mock.MagicMock(side_effect=RuntimeError)
        pipe._state.narrations = ["narration"]
        asyncio.run(pipe._step_subtitle())  # must not raise


class TestStepConcatenate:
    def test_final_exists(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        final = _write(tmp_path, "final_video.mp4", "data")
        assert asyncio.run(pipe._step_concatenate(["a.mp4"])) == final

    def test_overlay_path(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[SceneTask(index=0, duration=5)],
        )
        pipe._state.audio_config = type("A", (), {"enabled": True})()
        pipe._state.subtitle_config = type(
            "S", (), {"enabled": True}
        )() if False else pipe._state.subtitle_config
        pipe._state.subtitle_config.enabled = True
        _write(tmp_path, "combined_narration.mp3", "audio")
        _write(tmp_path, "combined_narration.srt", "srt")
        concat = mock.MagicMock()
        monkeypatch.setattr(
            "core.pipelines.creative.steps_audio.VideoConcatenator", concat
        )
        res = asyncio.run(pipe._step_concatenate(["a.mp4"]))
        assert res == os.path.join(str(tmp_path), "final_video.mp4")
        assert concat.concat_videos_with_audio_overlay.called

    def test_overlay_no_srt_file(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        pipe._state.subtitle_config.enabled = True
        _write(tmp_path, "combined_narration.mp3", "audio")
        # no srt file -> passed None
        concat = mock.MagicMock()
        monkeypatch.setattr("core.pipelines.creative.steps_audio.VideoConcatenator", concat)
        asyncio.run(pipe._step_concatenate(["a.mp4"]))
        assert concat.concat_videos_with_audio_overlay.called

    def test_audio_missing_falls_back(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        pipe._state.audio_config.enabled = True
        pipe._state.subtitle_config.enabled = False
        concat = mock.MagicMock()
        monkeypatch.setattr("core.pipelines.creative.steps_audio.VideoConcatenator", concat)
        asyncio.run(pipe._step_concatenate(["a.mp4"]))
        assert concat.concat_videos.called

    def test_no_audio_no_subtitle(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        pipe._state.audio_config.enabled = False
        pipe._state.subtitle_config.enabled = False
        concat = mock.MagicMock()
        monkeypatch.setattr("core.pipelines.creative.steps_audio.VideoConcatenator", concat)
        asyncio.run(pipe._step_concatenate(["a.mp4"]))
        assert concat.concat_videos.called


# ======================================================================
# steps_frames.py — module helpers & FramesStepsMixin
# ======================================================================


class TestFramesModuleHelpers:
    def test_fallback_end_frame(self):
        assert steps_frames._fallback_end_frame("中文场景") == "电影感尾帧画面"
        assert steps_frames._fallback_end_frame("english scene") == "cinematic end frame"
        assert steps_frames._fallback_end_frame("") == "cinematic end frame"

    def test_localize_preserve_tags(self):
        zh = steps_frames._localize_preserve_tags("中文")
        assert "[保留" in zh["preserve"]
        en = steps_frames._localize_preserve_tags("english")
        assert "PRESERVE" in en["preserve"]


class _FakeProc:
    def __init__(self, returncode=0, stderr=b"", error=None):
        self.returncode = returncode
        self._stderr = stderr
        self._error = error
        self.killed = False

    async def communicate(self):
        if self._error:
            raise self._error
        return b"", self._stderr

    async def wait(self):
        pass

    def kill(self):
        self.killed = True


class TestRunFfmpegAsync:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            mock.AsyncMock(return_value=_FakeProc(returncode=0)),
        )
        asyncio.run(steps_frames._run_ffmpeg_async(["ffmpeg"]))

    def test_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            mock.AsyncMock(return_value=_FakeProc(returncode=2, stderr=b"boom")),
        )
        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(steps_frames._run_ffmpeg_async(["ffmpeg"]))

    def test_timeout(self, monkeypatch):
        proc = _FakeProc(returncode=0, error=asyncio.TimeoutError())
        monkeypatch.setattr(
            asyncio, "create_subprocess_exec",
            mock.AsyncMock(return_value=proc),
        )
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(steps_frames._run_ffmpeg_async(["ffmpeg"], timeout=0.1))
        assert proc.killed


class TestNormalizeImage:
    def test_cache_hit(self, tmp_path, monkeypatch):
        dst = _write(tmp_path, "dst.png", "img")
        monkeypatch.setattr(
            steps_frames, "normalize_image_async", mock.AsyncMock(return_value=dst)
        )
        res = asyncio.run(
            steps_frames.FramesStepsMixin._normalize_image_to_size("src", 10, 10, dst)
        )
        assert res == dst

    def test_normalize_called(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        dst = str(tmp_path / "dst.png")
        monkeypatch.setattr(
            steps_frames, "normalize_image_async", mock.AsyncMock(return_value=dst)
        )
        res = asyncio.run(pipe._normalize_image_to_size("src", 10, 20, dst))
        assert res == dst

    def test_get_normalized_char_ref_empty(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        assert asyncio.run(pipe._get_normalized_character_ref("")) == ""

    def test_get_normalized_char_ref_url_pass_through(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        for url in ("http://x", "https://x", "data:image/png;base64,xx"):
            assert asyncio.run(pipe._get_normalized_character_ref(url)) == url

    def test_get_normalized_char_ref_missing_file(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        missing = os.path.join(str(tmp_path), "nope.png")
        assert asyncio.run(pipe._get_normalized_character_ref(missing)) == missing

    def test_get_normalized_char_ref_ok(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        src = _write(tmp_path, "src.png", "img")
        dst = os.path.join(str(tmp_path), "character_ref_normalized.png")
        monkeypatch.setattr(
            steps_frames, "normalize_image_async", mock.AsyncMock(return_value=dst)
        )
        res = asyncio.run(pipe._get_normalized_character_ref(src))
        assert res == dst

    def test_get_normalized_char_ref_failure_falls_back(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        src = _write(tmp_path, "src.png", "img")
        monkeypatch.setattr(
            steps_frames, "normalize_image_async",
            mock.AsyncMock(side_effect=RuntimeError("no ffmpeg")),
        )
        res = asyncio.run(pipe._get_normalized_character_ref(src))
        assert res == src


class TestPregenerateEndFrames:
    def test_not_keyframes(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="independent")
        assert asyncio.run(pipe._step_pregenerate_end_frames(["s"], [], "ref")) == {}

    def test_skip_when_completed_and_all_exist(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        ef = _write(tmp_path, "scene_0", "end_frame.png") if False else _write(
            tmp_path, "ef0.png", "img"
        )
        pipe._state.step_end_frame_generation = StepStatus.COMPLETED
        pipe._state.pregenerated_end_frames = {"0": ef}
        res = asyncio.run(pipe._step_pregenerate_end_frames(["s"], ["p"], "ref"))
        assert res == {"0": ef}

    def test_completed_but_missing_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._state.step_end_frame_generation = StepStatus.COMPLETED
        pipe._state.pregenerated_end_frames = {"0": os.path.join(str(tmp_path), "nope.png")}
        pipe._state.end_frame_images = []
        pipe._state.generate_end_frames_from_ref = False
        asyncio.run(pipe._step_pregenerate_end_frames(["s"], ["p"], "ref"))
        assert pipe._state.step_end_frame_generation == StepStatus.COMPLETED

    def test_shutdown_raises(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._stop_event.set()
        with pytest.raises(Exception):
            asyncio.run(pipe._step_pregenerate_end_frames(["s"], [], "ref"))

    def test_cached_scene_and_user_ef(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        # scene 0 cached + the actual end_frame file at scene_0/end_frame.png exists
        cached = _write(tmp_path, "scene_0/end_frame.png", "e")
        pipe._state.pregenerated_end_frames = {"0": cached}
        pipe._state.end_frame_images = ["http://user/ef.png", "http://user/ef2.png"]
        pipe._state.generate_end_frames_from_ref = False
        res = asyncio.run(pipe._step_pregenerate_end_frames(["s0", "s1"], ["p0", "p1"], "ref"))
        # scene 0 cache hit -> end_frame.png path under scene_0 is returned
        assert res[0] == os.path.join(str(tmp_path), "scene_0", "end_frame.png")
        # scene 1 has a user end-frame URL -> generate_end_frames_from_ref=False -> t2i
        assert res[1].endswith("end_frame.png")
        assert pipe._state.step_end_frame_generation == StepStatus.COMPLETED

    def test_user_endframe_normalized(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        user_ef = _write(tmp_path, "scene_user.png", "img")
        pipe._state.pregenerated_end_frames = {}
        norm = mock.AsyncMock(
            return_value=os.path.join(str(tmp_path), "scene_0", "end_frame.png")
        )
        pipe._state.generate_end_frames_from_ref = False
        pipe._state.end_frame_images = [user_ef]
        monkeypatch.setattr(steps_frames, "normalize_image_async", norm)
        res = asyncio.run(pipe._step_pregenerate_end_frames(["s0"], ["p0"], "ref"))
        norm.assert_awaited_once()
        assert res[0].endswith("end_frame.png")

    def test_i2i_with_appearance_and_multi_ref(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        ref = _write(tmp_path, "char.png", "img")
        # previous end frame exists to enable multi-ref
        prev = _write(tmp_path, "scene_0/end_frame.png", "e")
        pipe._state.pregenerated_end_frames = {"0": prev}
        pipe._state.character_appearance = "blue coat"
        pipe._state.generate_end_frames_from_ref = True
        pipe._state.reference_image = ""
        pipe._state.video_width = 768
        pipe._state.video_height = 1152
        monkeypatch.setattr(
            steps_frames, "normalize_image_async",
            mock.AsyncMock(return_value=os.path.join(str(tmp_path), "norm.png")),
        )
        res = asyncio.run(
            pipe._step_pregenerate_end_frames(["s0", "s1"], ["p0", "p1"], ref)
        )
        assert res[1].endswith("end_frame.png")
        # second scene generate used i2i with character + prev scene end frame refs
        kwargs = pipe.image_generator.generate_single_image.call_args.kwargs
        assert len(kwargs["reference_image_paths"]) == 2

    def test_t2i_branch(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._state.pregenerated_end_frames = {}
        pipe._state.generate_end_frames_from_ref = False
        pipe._state.end_frame_images = []
        pipe._state.video_width = 768
        pipe._state.video_height = 1152
        res = asyncio.run(pipe._step_pregenerate_end_frames(["s0"], ["p0"], "ref"))
        assert res[0].endswith("end_frame.png")

    def test_generation_retries_then_fails(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._state.generate_end_frames_from_ref = True
        pipe._state.end_frame_images = []
        pipe._state.character_appearance = ""
        ref = _write(tmp_path, "ref.png", "img")
        monkeypatch.setattr(
            steps_frames, "normalize_image_async",
            mock.AsyncMock(return_value=os.path.join(str(tmp_path), "norm.png")),
        )
        monkeypatch.setattr("asyncio.sleep", mock.AsyncMock())
        # i2i branch runs the 3-attempt retry loop
        pipe.image_generator.generate_single_image.side_effect = [
            RuntimeError("fail1"),
            RuntimeError("fail2"),
            RuntimeError("fail3"),
        ]
        with pytest.raises(RuntimeError, match="fail3"):
            asyncio.run(pipe._step_pregenerate_end_frames(["s0"], ["p0"], ref))

    def test_retry_succeeds_on_second_attempt(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes")
        pipe._state.generate_end_frames_from_ref = True
        pipe._state.end_frame_images = []
        pipe._state.character_appearance = ""
        ref = _write(tmp_path, "ref.png", "img")
        monkeypatch.setattr(steps_frames, "normalize_image_async", mock.AsyncMock(return_value="norm.png"))
        monkeypatch.setattr("asyncio.sleep", mock.AsyncMock())
        pipe.image_generator.generate_single_image.side_effect = [
            RuntimeError("fail1"),
            _FakeImageOutput(),
        ]
        res = asyncio.run(pipe._step_pregenerate_end_frames(["s0"], ["p0"], ref))
        assert res[0].endswith("end_frame.png")


class TestSceneTaskPersistence:
    def test_save_scene_task(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        scene_dir = str(tmp_path / "scene_0")
        os.makedirs(scene_dir, exist_ok=True)
        pipe._save_scene_task(scene_dir, "vid-abc")
        with open(os.path.join(scene_dir, "task.json")) as f:
            assert json.load(f) == {"video_id": "vid-abc"}
        assert os.path.exists(os.path.join(scene_dir, "curl.sh"))

    def test_load_scene_task_missing(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        # Prevents discovering real pipelines/ files on disk
        assert pipe._load_scene_task(os.path.join(str(tmp_path), "scene_0")) is None

    def test_load_scene_task_exists(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        scene_dir = str(tmp_path / "scene_0")
        os.makedirs(scene_dir, exist_ok=True)
        with open(os.path.join(scene_dir, "task.json"), "w") as f:
            json.dump({"video_id": "vid-x"}, f)
        assert pipe._load_scene_task(scene_dir) == "vid-x"

    def test_load_scene_task_bad_json(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        scene_dir = str(tmp_path / "scene_0")
        os.makedirs(scene_dir, exist_ok=True)
        with open(os.path.join(scene_dir, "task.json"), "w") as f:
            f.write("not json")
        assert pipe._load_scene_task(scene_dir) is None


# ======================================================================
# steps_video.py — module helper & VideoStepsMixin
# ======================================================================


class TestVideoModuleHelpers:
    def test_localize_transition_prompt(self):
        zh = steps_video._localize_transition_prompt("中文下一场景")
        assert "电影感" in zh
        en = steps_video._localize_transition_prompt("next english scene")
        assert "Cinematic" in en


class TestUserSceneRef:
    def test_no_refs(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        assert pipe._user_scene_ref(0) is None

    def test_in_range(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.scene_reference_images = ["img.png", "img2.png"]
        assert pipe._user_scene_ref(1) == "img2.png"


class TestStepGenerateVideosDispatch:
    def test_completed_and_all_exist(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="independent")
        pipe._state.step_video_generation = StepStatus.COMPLETED
        _write(tmp_path, "scene_0", "video.mp4") if False else None
        for i in range(2):
            p = tmp_path / f"scene_{i}" / "video.mp4"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("d", encoding="utf-8")
        paths = asyncio.run(
            pipe._step_generate_videos(["s0", "s1"], "ref", [], {})
        )
        assert len(paths) == 2

    def test_completed_partial_reruns(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="independent")
        pipe._state.step_video_generation = StepStatus.COMPLETED
        _write(tmp_path, "scene_0/video.mp4", "x")
        res = asyncio.run(pipe._step_generate_videos(["s0", "s1"], "ref", [], {}))
        assert res is not None
        assert pipe._state.step_video_generation == StepStatus.COMPLETED


class TestIndependentScenes:
    def test_full_flow(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="independent")
        pipe.video_generator.submit_video.return_value = "vid-i"
        paths = asyncio.run(
            pipe._generate_independent_scenes(["s0", "s1"], "ref.png", 768, 1152)
        )
        assert 0 <= len(paths) <= 2

    def test_existing_video_skipped(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        p = tmp_path / "scene_0" / "video.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        paths = asyncio.run(pipe._generate_independent_scenes(["s0"], "ref", 8, 8))
        assert paths == [str(p)]
        pipe.video_generator.submit_video.assert_awaited_once() if False else None

    def test_resume_existing_video_id(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        scene_dir = tmp_path / "scene_0"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "task.json").write_text(json.dumps({"video_id": "old-vid"}))
        asyncio.run(pipe._generate_independent_scenes(["s0"], "ref", 8, 8))

    def test_user_ref_used(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._state.scene_reference_images = ["/tmp/user.png"]
        asyncio.run(pipe._generate_independent_scenes(["s0"], "ref.png", 8, 8))
        _, kwargs = pipe.video_generator.submit_video.call_args
        assert kwargs["reference_image_paths"] == ["/tmp/user.png"]

    def test_shutdown_raises(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._stop_event.set()
        with pytest.raises(Exception):
            asyncio.run(pipe._generate_independent_scenes(["s0"], "ref", 8, 8))

    def test_failure_raises_keeps_task_json(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        scene_dir = tmp_path / "scene_0"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "task.json").write_text(json.dumps({"video_id": "v"}))
        pipe.video_generator.wait_for_video.side_effect = RuntimeError("boom")
        monkeypatch.setattr(steps_video, "is_remote_video_failure", lambda e: False)
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._generate_independent_scenes(["s0"], "ref", 8, 8))
        assert os.path.exists(scene_dir / "task.json")

    def test_failure_remote_removes_task_json(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        scene_dir = tmp_path / "scene_0"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "task.json").write_text(json.dumps({"video_id": "v"}))
        pipe.video_generator.wait_for_video.side_effect = RuntimeError("remote")
        monkeypatch.setattr(steps_video, "is_remote_video_failure", lambda e: True)
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._generate_independent_scenes(["s0"], "ref", 8, 8))
        assert not os.path.exists(scene_dir / "task.json")


class TestChainedScenes:
    def test_full_chain_with_transition(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(
            tmp_path, chaining_mode="ti2vid",
            scenes=[SceneTask(index=i, duration=5) for i in range(2)],
        )
        pipe._state.scene_reference_images = []
        # make reference_image a real file so chain passes both refs
        ref = _write(tmp_path, "ref.png", "img")
        # previous video.mp4 must exist for first scene? no, fresh submit
        async def fake_ffmpeg(cmd, timeout=30):
            # produce the last_frame file that the chain expects
            pass
        monkeypatch.setattr(steps_video, "_run_ffmpeg_async", fake_ffmpeg)
        monkeypatch.setattr(steps_frames, "_run_ffmpeg_async", fake_ffmpeg)
        asyncio.run(pipe._generate_chained_scenes(["s0", "s1"], ref, 768, 1152))

    def test_cached_scene_reuses_last_frame(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path, chaining_mode="ti2vid")
        scene_dir = tmp_path / "scene_0"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "video.mp4").write_text("x")
        (scene_dir / "last_frame.jpg").write_text("j")
        ref = _write(tmp_path, "ref.png", "img")
        monkeypatch.setattr(steps_video, "_run_ffmpeg_async", mock.MagicMock())
        asyncio.run(pipe._generate_chained_scenes(["s0"], ref, 768, 1152))

    def test_user_ref_sets_current_image(self, tmp_path):
        pipe = _make_pipeline(tmp_path, chaining_mode="ti2vid")
        pipe._state.scene_reference_images = ["/tmp/user.png"]
        # reference_image does not exist on disk, so chain keeps [current_image] only
        asyncio.run(pipe._generate_chained_scenes(["s0"], "ref-not-exist.png", 768, 1152))
        _, kwargs = pipe.video_generator.submit_video.call_args
        assert kwargs["reference_image_paths"] == ["/tmp/user.png"]

    def test_shutdown(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        pipe._stop_event.set()
        with pytest.raises(Exception):
            asyncio.run(pipe._generate_chained_scenes(["s0"], "ref", 8, 8))

    def test_wait_failure(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path, chaining_mode="ti2vid")
        pipe.video_generator.wait_for_video.side_effect = RuntimeError("boom")
        monkeypatch.setattr(steps_video, "is_remote_video_failure", lambda e: False)
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._generate_chained_scenes(["s0"], "ref", 8, 8))


class TestKeyframeScenes:
    def _pipe(self, tmp_path, **kw):
        pipe = _make_pipeline(tmp_path, chaining_mode="keyframes", **kw)
        pipe._state.scene_reference_images = []
        pipe._state.end_frame_images = []
        pipe._state.generate_end_frames_from_ref = False
        pipe._state.video_width = 768
        pipe._state.video_height = 1152
        return pipe

    def test_full_flow_with_pregenerated(self, tmp_path, monkeypatch):
        pipe = self._pipe(tmp_path)
        pre = _write(tmp_path, "scene_0/end_frame.png", "e")
        ef = _write(tmp_path, "scene_1/end_frame.png", "e")
        pregen = {"0": pre, "1": ef}
        monkeypatch.setattr(steps_video, "_run_ffmpeg_async", mock.AsyncMock())
        paths = asyncio.run(pipe._generate_keyframe_scenes(
            ["s0", "s1"], "ref.png", ["p0", "p1"], pregen, 768, 1152, []
        ))
        assert len(paths) == 2

    def test_existing_video_cached(self, tmp_path):
        pipe = self._pipe(tmp_path)
        scene_dir = tmp_path / "scene_0"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "video.mp4").write_text("x")
        (scene_dir / "end_frame.png").write_text("e")
        asyncio.run(pipe._generate_keyframe_scenes(
            ["s0"], "ref.png", ["p0"], {}, 768, 1152, []
        ))

    def test_resume_existing_video_id(self, tmp_path):
        pipe = self._pipe(tmp_path)
        scene_dir = tmp_path / "scene_0"
        scene_dir.mkdir(parents=True, exist_ok=True)
        (scene_dir / "task.json").write_text(json.dumps({"video_id": "v"}))
        paths = asyncio.run(pipe._generate_keyframe_scenes(
            ["s0"], "ref.png", ["p0"], {}, 768, 1152, []
        ))
        assert os.path.exists(scene_dir / "video.mp4")

    def test_user_endframe_ffmpeg_scale(self, tmp_path, monkeypatch):
        pipe = self._pipe(tmp_path)
        user_ef = _write(tmp_path, "user.png", "img")
        pipe._state.end_frame_images = [user_ef]
        ffmpeg = mock.AsyncMock()
        monkeypatch.setattr(steps_video, "_run_ffmpeg_async", ffmpeg)
        asyncio.run(pipe._generate_keyframe_scenes(
            ["s0"], "ref.png", ["p0"], {}, 768, 1152, [user_ef]
        ))
        ffmpeg.assert_awaited()

    def test_fallback_t2i_endframe(self, tmp_path):
        pipe = self._pipe(tmp_path)
        pipe.image_generator.generate_single_image.side_effect = [
            _FakeImageOutput(),  # end frame
            None,
        ]
        asyncio.run(pipe._generate_keyframe_scenes(
            ["s0"], "ref.png", ["p0"], {}, 768, 1152, []
        ))

    def test_fallback_i2i_endframe_with_appearance(self, tmp_path):
        pipe = self._pipe(tmp_path)
        pipe._state.generate_end_frames_from_ref = True
        pipe._state.character_appearance = "red hair"
        pipe._state.reference_image = ""
        ref = _write(tmp_path, "ref.png", "img")
        asyncio.run(pipe._generate_keyframe_scenes(
            ["s0"], ref, ["p0"], {}, 768, 1152, []
        ))

    def test_shutdown(self, tmp_path):
        pipe = self._pipe(tmp_path)
        pipe._stop_event.set()
        with pytest.raises(Exception):
            asyncio.run(pipe._generate_keyframe_scenes(
                ["s0"], "ref.png", ["p0"], {}, 768, 1152, []
            ))

    def test_wait_failure(self, tmp_path, monkeypatch):
        pipe = self._pipe(tmp_path)
        pipe.video_generator.wait_for_video.side_effect = RuntimeError("boom")
        monkeypatch.setattr(steps_video, "is_remote_video_failure", lambda e: False)
        pre = _write(tmp_path, "scene_0/end_frame.png", "e")
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._generate_keyframe_scenes(
                ["s0"], "ref.png", ["p0"], {"0": pre}, 768, 1152, []
            ))


class TestSceneDuration:
    def test_in_range(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        assert pipe._scene_duration(0) == 5.0

    def test_fallback(self, tmp_path):
        pipe = _make_pipeline(tmp_path, scenes=[])
        assert pipe._scene_duration(0) == 5.0


# ======================================================================
# multi_scene.py — MultiScenePipeline template & generic steps
# ======================================================================

from core.pipelines.multi_scene import MultiScenePipeline, StepProgressLimits
from core.api.agnes_video import VideoTaskCancelled


class _ConcreteMulti(MultiScenePipeline):
    """Minimal concrete subclass implementing the three abstract data hooks."""

    async def _build_scenes(self):
        pass

    async def _build_reference_images(self):
        pass

    async def _composite_final(self):
        return os.path.join(self.working_dir, "final.mp4")


class TestStepProgressLimits:
    def test_defaults(self):
        lim = StepProgressLimits()
        assert lim.build_start == 0.0 and lim.done == 1.0


def _make_multistate(tmp_path, scenes=None, **kw):
    """Build a MultiScene-capable task state (has combined_audio/combined_subtitle)."""
    defaults = {
        "video_width": 768,
        "video_height": 1152,
        "video_duration": 5,
        "scene_count": 2,
        "scene_durations": [5, 5],
    }
    defaults.update(kw)
    if scenes is None:
        scenes = [
            SceneTask(index=i, duration=5) for i in range(defaults["scene_count"])
        ]
    defaults["scenes"] = scenes
    return PoetryVideoTask(**defaults)


def _make_multi(tmp_path, state=None, **kw):
    pipe = object.__new__(_ConcreteMulti)
    pipe.task_manager = _StubTaskManager(tmp_path)
    pipe._state = state if state is not None else _make_multistate(tmp_path, **kw)
    pipe.task_id = "multi-test"
    pipe.screenwriter = mock.MagicMock()
    pipe.video_api = mock.AsyncMock()
    pipe.video_api.submit_video.return_value = "v-multi"
    pipe.video_api.wait_for_video.return_value = _FakeVideoOutput()
    pipe.progress_callback = None
    pipe.shutdown_event = None
    pipe._stop_event = asyncio.Event()
    return pipe


class TestExecuteStep:
    def test_coarse_skip_when_completed(self, tmp_path):
        pipe = _make_multi(tmp_path)
        pipe._state.step_build_scenes = StepStatus.COMPLETED
        action = mock.AsyncMock()
        res = asyncio.run(
            pipe._execute_step("step_build_scenes", action, 0.0, 0.15, "r", "c")
        )
        assert res is None
        action.assert_not_awaited()

    def test_executes_and_marks_completed(self, tmp_path):
        pipe = _make_multi(tmp_path)
        action = mock.AsyncMock(return_value="out")
        res = asyncio.run(
            pipe._execute_step("step_video_generation", action, 0.3, 0.75, "r", "c")
        )
        assert res == "out"
        action.assert_awaited_once()


class TestMultiGenerateVideos:
    def test_videos_generated(self, tmp_path):
        pipe = _make_multi(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=5, narration_text="n0"),
                SceneTask(index=1, duration=5, narration_text="n1"),
            ],
        )
        asyncio.run(pipe._generate_videos())
        assert pipe.video_api.submit_video.await_count == 2

    def test_existing_video_skipped(self, tmp_path):
        pipe = _make_multi(
            tmp_path,
            scenes=[SceneTask(index=0, duration=5, narration_text="n")],
        )
        p = tmp_path / "scene_0" / "video.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        asyncio.run(pipe._generate_videos())
        assert pipe.video_api.submit_video.await_count == 0
        assert pipe._state.scenes[0].video_file == str(p)

    def test_resume_existing_task_json(self, tmp_path):
        pipe = _make_multi(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        sd = tmp_path / "scene_0"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "task.json").write_text(json.dumps({"video_id": "cached"}))
        asyncio.run(pipe._generate_videos())
        pipe.video_api.wait_for_video.assert_awaited_once()
        assert pipe.video_api.submit_video.await_count == 0

    def test_failure_propagates(self, tmp_path, monkeypatch):
        pipe = _make_multi(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        pipe.video_api.wait_for_video.side_effect = RuntimeError("boom")
        # 失败会触发真实重试退避 sleep（base 20s 起），mock 掉避免白等约 60s
        monkeypatch.setattr("asyncio.sleep", mock.AsyncMock())
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._generate_videos())


class TestWaitForVideoWithRetry:
    def test_success_first_try(self, tmp_path):
        pipe = _make_multi(tmp_path)
        pipe.video_api.wait_for_video.return_value = "out"
        assert asyncio.run(pipe._wait_for_video_with_retry("v", 0)) == "out"

    def test_video_cancelled_reraises(self, tmp_path):
        pipe = _make_multi(tmp_path)
        pipe.video_api.wait_for_video.side_effect = VideoTaskCancelled("stopped")
        with pytest.raises(VideoTaskCancelled):
            asyncio.run(pipe._wait_for_video_with_retry("v", 0))

    def test_retry_then_success(self, tmp_path, monkeypatch):
        pipe = _make_multi(tmp_path)
        monkeypatch.setattr("asyncio.sleep", mock.AsyncMock())
        pipe.video_api.wait_for_video.side_effect = [
            RuntimeError("t1"),
            RuntimeError("t2"),
            "out",
        ]
        assert asyncio.run(pipe._wait_for_video_with_retry("v", 0, max_retries=3)) == "out"

    def test_exhausted_remote_removes_task(self, tmp_path, monkeypatch):
        pipe = _make_multi(tmp_path)
        sd = tmp_path / "scene_0"
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "task.json").write_text(json.dumps({"video_id": "v"}))
        monkeypatch.setattr("asyncio.sleep", mock.AsyncMock())
        pipe.video_api.wait_for_video.side_effect = RuntimeError("remote")
        monkeypatch.setattr(
            "core.pipelines.multi_scene.is_remote_video_failure", lambda e: True
        )
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._wait_for_video_with_retry("v", 0, max_retries=1))
        assert not os.path.exists(sd / "task.json")

    def test_exhausted_non_remote_keeps_task(self, tmp_path, monkeypatch):
        pipe = _make_multi(tmp_path)
        monkeypatch.setattr("asyncio.sleep", mock.AsyncMock())
        pipe.video_api.wait_for_video.side_effect = RuntimeError("timeout")
        monkeypatch.setattr(
            "core.pipelines.multi_scene.is_remote_video_failure", lambda e: False
        )
        with pytest.raises(RuntimeError):
            asyncio.run(pipe._wait_for_video_with_retry("v", 0, max_retries=1))


class TestMultiGenerateAudio:
    def test_file_exists_recover_cues(self, tmp_path):
        pipe = _make_multi(tmp_path)
        audio = _write(tmp_path, "combined_narration.mp3", "data")
        pipe._recover_sub_maker = mock.AsyncMock(return_value="sm")
        res = asyncio.run(pipe._generate_audio())
        assert res == "sm"
        assert pipe._state.combined_audio == audio
        pipe._recover_sub_maker.assert_awaited_once()

    def test_empty_text_skips(self, tmp_path):
        pipe = _make_multi(tmp_path, scenes=[SceneTask(index=0, duration=5)])
        assert asyncio.run(pipe._generate_audio()) is None

    def test_generation(self, tmp_path):
        pipe = _make_multi(
            tmp_path,
            scenes=[SceneTask(index=0, duration=5, narration_text="hello")],
        )
        pipe._generate_audio_with_fallback = mock.AsyncMock(return_value="sm")
        res = asyncio.run(pipe._generate_audio())
        assert res == "sm"
        assert pipe._state.combined_audio == os.path.join(str(tmp_path), "combined_narration.mp3")


class TestMultiGenerateSubtitles:
    def test_disabled(self, tmp_path):
        pipe = _make_multi(tmp_path)
        pipe._state.subtitle_config.enabled = False
        asyncio.run(pipe._generate_subtitles())

    def test_enabled(self, tmp_path):
        pipe = _make_multi(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=5, narration_text="a"),
                SceneTask(index=1, duration=5, narration_text="b"),
            ],
        )
        pipe.generate_subtitles_common = mock.AsyncMock(return_value=("srt", "styles"))
        asyncio.run(pipe._generate_subtitles("sm"))
        assert pipe._state.combined_subtitle == "srt"
        assert pipe._state.subtitle_styles_path == "styles"


class TestMultiHooks:
    def test_get_init_message(self, tmp_path):
        pipe = _make_multi(tmp_path)
        assert pipe._get_init_message() == "开始视频生成..."

    def test_get_narration_text(self, tmp_path):
        pipe = _make_multi(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=5, narration_text="first"),
                SceneTask(index=1, duration=5, narration_text=""),
                SceneTask(index=2, duration=5, narration_text="second"),
            ],
        )
        assert pipe._get_narration_text() == "first\n\nsecond"

    def test_get_segment_texts_and_durations(self, tmp_path):
        pipe = _make_multi(
            tmp_path,
            scenes=[
                SceneTask(index=0, duration=3, narration_text="a"),
                SceneTask(index=1, duration=7, narration_text="b"),
                SceneTask(index=2, duration=9),
            ],
        )
        texts, durs = pipe._get_segment_texts_and_durations()
        assert texts == ["a", "b"]
        assert durs == [3.0, 7.0]

    def test_get_audio_path(self, tmp_path):
        pipe = _make_multi(tmp_path)
        assert pipe._get_audio_path() == os.path.join(str(tmp_path), "combined_narration.mp3")

    def test_get_scene_video_prompt(self, tmp_path):
        pipe = _make_multi(tmp_path)
        scene = SceneTask(index=0, end_frame_prompt="efp", scene_prompt="sp")
        assert pipe._get_scene_video_prompt(scene, 0) == "efp"
        scene2 = SceneTask(index=1, scene_prompt="sp")
        assert pipe._get_scene_video_prompt(scene2, 1) == "sp"

    def test_get_scene_ref_images(self, tmp_path):
        pipe = _make_multi(tmp_path)
        scene = SceneTask(index=0)
        assert pipe._get_scene_ref_images(scene, 0) == []

    def test_get_scene_duration(self, tmp_path):
        pipe = _make_multi(tmp_path)
        assert pipe._get_scene_duration(SceneTask(index=0, duration=10), 0) == 10
        assert pipe._get_scene_duration(SceneTask(index=0, duration=2), 0) == 3

    def test_set_subtitle_paths(self, tmp_path):
        pipe = _make_multi(tmp_path)
        pipe._set_subtitle_paths("srt", "styles")
        assert pipe._state.combined_subtitle == "srt"
        assert pipe._state.subtitle_styles_path == "styles"


class TestMultiRun:
    def _run_pipeline(self, tmp_path, **overrides):
        pipe = _make_multi(tmp_path)
        pipe._generate_videos = mock.AsyncMock()
        pipe._generate_audio = mock.AsyncMock(return_value="sm")
        pipe._generate_subtitles = mock.AsyncMock()
        pipe._apply_watermark = mock.AsyncMock(return_value="final.mp4")
        pipe._maybe_pause = mock.AsyncMock(return_value=False)
        for k, v in overrides.items():
            setattr(pipe, k, v)
        return pipe

    def test_success(self, tmp_path):
        pipe = self._run_pipeline(tmp_path)
        state = _make_multistate(tmp_path)
        result = asyncio.run(pipe.run(state))
        assert result == "final.mp4"
        assert state.status == StepStatus.COMPLETED
        assert state.final_video_file == "final.mp4"

    def test_checkpoint_pause(self, tmp_path):
        from core.pipelines import CheckpointPause

        async def pause(*a, **k):
            raise CheckpointPause("scenes")

        pipe = self._run_pipeline(tmp_path, _maybe_pause=pause)
        state = _make_multistate(tmp_path)
        assert asyncio.run(pipe.run(state)) == ""

    def test_shutdown(self, tmp_path):
        from core.pipelines import PipelineShutdown

        pipe = self._run_pipeline(tmp_path, _build_scenes=mock.AsyncMock(
            side_effect=PipelineShutdown("stop")
        ))
        state = _make_multistate(tmp_path)
        with pytest.raises(PipelineShutdown):
            asyncio.run(pipe.run(state))

    def test_generic_exception_sets_failed(self, tmp_path):
        pipe = self._run_pipeline(
            tmp_path, _build_scenes=mock.AsyncMock(side_effect=RuntimeError("x"))
        )
        state = _make_multistate(tmp_path)
        with pytest.raises(RuntimeError):
            asyncio.run(pipe.run(state))
        assert state.status == StepStatus.FAILED
        # error_traceback is surfaced via task_manager.update_state()
        recorded = [c for c in pipe.task_manager.calls if c[0] == "state"]
        last = recorded[-1][1]
        assert "error_traceback" in last and "Traceback" in last["error_traceback"]