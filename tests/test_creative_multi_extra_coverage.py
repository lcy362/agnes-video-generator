"""Extra targeted unit tests filling the last uncovered lines of
core/pipelines/creative/steps_audio.py (and confirming multi_scene is complete).

The main coverage lives in tests/test_creative_steps_coverage.py; this file only
adds the residual branches:
  - _split_narration_into_scenes: no-sentence fallback + "too many scenes" merge
  - _populate_narrations: all paragraphs filtered out -> fall back to paragraphs
  - _step_generate_narrations: resume re-clean path when cleaned text differs
  - _step_subtitle: styles appended to an already-existing prompts.json
  - _step_concatenate: subtitle_styles_path set but file missing -> cleared

No real network / moviepy / ffmpeg / edge_tts calls; all IO goes to tmp_path.
"""

import asyncio
import json
import os
import sys

import pytest
from unittest import mock

# Make the project root importable regardless of how pytest is invoked.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.pipelines.creative import steps_audio
from core.pipelines.creative.pipeline import CreativeVideoPipeline
from models.task import CreativeVideoTask, SceneTask, StepStatus


class _StubTaskManager:
    """Records update_step / update_state calls; no disk access."""

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
    defaults = {
        "idea": "probe",
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
    pipe = object.__new__(CreativeVideoPipeline)
    pipe.task_manager = _StubTaskManager(tmp_path)
    pipe._state = state if state is not None else _make_state(tmp_path, **state_kw)
    pipe.screenwriter = mock.MagicMock()
    pipe.video_generator = mock.AsyncMock()
    pipe._emit = mock.AsyncMock()
    pipe.save_prompts = mock.MagicMock()
    pipe.progress_callback = None
    pipe.shutdown_event = None
    pipe._stop_event = asyncio.Event()
    return pipe


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestSplitNarrationExtra:
    def test_only_whitespace_uses_whole_text_as_single_sentence(self):
        # whitespace-only pieces strip to empty -> `not sentences` fallback
        res = steps_audio._split_narration_into_scenes("   ", 2)
        assert len(res) == 2 and res[0] == "   "

    def test_too_many_segments_merged_to_target(self):
        # 4 short boundary-separated sentences, target 3 scenes -> merge excess
        res = steps_audio._split_narration_into_scenes("aa。bb。cc。dd。", 3)
        assert len(res) == 3
        # merged text keeps all original characters (needle back into the 3 slots)
        assert "\n".join(res).replace("\n", "") == "aa。bb。cc。dd。"


class TestPopulateNarrationsExtra:
    def test_all_paragraphs_metadata_falls_back(self, tmp_path):
        pipe = _make_pipeline(tmp_path)
        story = "story title: X\n\nmain character: Y"
        pipe._populate_narrations(story)
        assert len(pipe._state.narrations) == 2
        # both metadata paragraphs are used verbatim
        assert pipe._state.narrations[0] == "story title: X"
        assert pipe._state.narrations[1] == "main character: Y"


class TestGenerateNarrationsReclean:
    def test_reclean_when_cleaned_differs(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(tmp_path)
        pipe._state.narrations = [
            "A fairly long narration that should be recleaned for history data"
        ]
        monkeypatch.setattr(
            steps_audio, "clean_narration_text", lambda t: "cleaned version"
        )
        asyncio.run(pipe._step_generate_narrations("story", ["s1"]))
        assert pipe._state.narrations == ["cleaned version"]
        assert any(
            c[0] == "state" and c[1].get("narrations") == ["cleaned version"]
            for c in pipe.task_manager.calls
        )


class TestSubtitleStylesExistingPrompts:
    def test_styles_appended_to_existing_prompts(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[SceneTask(index=0, duration=5), SceneTask(index=1, duration=5)],
        )
        pipe._state.subtitle_config.enabled = True
        _write(tmp_path, "combined_narration.srt", "")
        styles_path = _write(tmp_path, "styles.json", json.dumps({"style": "bold"}))
        _write(tmp_path, "prompts.json", json.dumps({"hello": 1}))
        pipe.generate_subtitles_common = mock.AsyncMock(
            return_value=(os.path.join(str(tmp_path), "combined_narration.srt"),
                          styles_path)
        )
        asyncio.run(pipe._step_subtitle(None))
        # save_prompts called with merged dict (existing + subtitle_styles)
        args, _ = pipe.save_prompts.call_args
        assert args[0]["hello"] == 1
        assert args[0]["subtitle_styles"] == {"style": "bold"}
        assert pipe._state.step_subtitle == StepStatus.COMPLETED


class TestConcatenateStylesMissing:
    def test_styles_path_missing_cleared(self, tmp_path, monkeypatch):
        pipe = _make_pipeline(
            tmp_path,
            scenes=[SceneTask(index=0, duration=5)],
        )
        pipe._state.subtitle_config.enabled = True
        pipe._state.audio_config.enabled = False
        pipe._state.subtitle_styles_path = str(tmp_path / "missing_styles.json")
        concat = mock.MagicMock()
        monkeypatch.setattr(
            "core.pipelines.creative.steps_audio.VideoConcatenator", concat
        )
        assert asyncio.run(pipe._step_concatenate(["a.mp4"])) == str(
            tmp_path / "final_video.mp4"
        )
        # no audio file -> concat_videos (not overlay) is used
        assert concat.concat_videos.called
        assert not concat.concat_videos_with_audio_overlay.called
        assert pipe._state.step_concatenation == StepStatus.COMPLETED