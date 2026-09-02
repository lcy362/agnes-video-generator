"""Unit tests for manuscript / poetry subtitle persistence branches.

覆盖 v6.x 改为异步文件 IO（Sonar S7493 修复点）的落盘路径：
- ManuscriptVideoPipeline._generate_subtitles 的 prompts.json 合并写入
- PoetryVideoPipeline._generate_subtitles 的逐场景 SRT 写入

全部依赖打桩，不触发网络 / moviepy / ffmpeg。
"""
import asyncio
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.audio.subtitle as subtitle_pkg  # noqa: E402
from core.pipelines.manuscript_video import ManuscriptVideoPipeline  # noqa: E402
from core.pipelines.poetry_video import PoetryVideoPipeline  # noqa: E402
from models.task import (  # noqa: E402
    ManuscriptParagraph,
    ManuscriptVideoTask,
    PoetryVideoTask,
    SceneTask,
    SubtitleConfig,
)


class _StubTaskManager:
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


def _run(coro):
    return asyncio.run(coro)


def _base(pipe, tmp_path):
    pipe.task_manager = _StubTaskManager(tmp_path)
    pipe.task_id = "sub-branch"
    pipe.screenwriter = mock.MagicMock()
    pipe.progress_callback = None
    pipe.shutdown_event = None
    pipe._stop_event = asyncio.Event()
    pipe._emit = mock.AsyncMock()
    return pipe


# ═══════════════════════════════════════════════════
# ManuscriptVideoPipeline._generate_subtitles
# ═══════════════════════════════════════════════════

def _make_manuscript(tmp_path):
    pipe = object.__new__(ManuscriptVideoPipeline)
    _base(pipe, tmp_path)
    pipe._state = ManuscriptVideoTask(
        manuscript_text="第一段。第二段。",
        video_width=768, video_height=1152, video_duration=5,
        paragraphs=[
            ManuscriptParagraph(index=0, text="第一段"),
            ManuscriptParagraph(index=1, text="第二段"),
        ],
    )
    return pipe


def test_manuscript_merges_styles_into_prompts_json(tmp_path):
    """styles_path 非空 → prompts.json 与字幕样式合并后异步落盘。"""
    pipe = _make_manuscript(tmp_path)
    (tmp_path / "prompts.json").write_text(
        json.dumps({"scenes": ["p0"]}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "subtitle_styles.json").write_text(
        json.dumps({"fontsize": 44}), encoding="utf-8")

    async def _common(**kwargs):
        return (str(tmp_path / "full_subtitle.srt"), str(tmp_path / "subtitle_styles.json"))

    pipe.generate_subtitles_common = _common
    _run(pipe._generate_subtitles(None))

    merged = json.loads((tmp_path / "prompts.json").read_text(encoding="utf-8"))
    assert merged["scenes"] == ["p0"]
    assert merged["subtitle_styles"] == {"fontsize": 44}
    assert pipe._state.subtitle_styles_path == str(tmp_path / "subtitle_styles.json")


def test_manuscript_no_styles_path_skips_merge(tmp_path):
    """styles_path 为空 → 不触碰 prompts.json。"""
    pipe = _make_manuscript(tmp_path)

    async def _common(**kwargs):
        return (str(tmp_path / "full_subtitle.srt"), "")

    pipe.generate_subtitles_common = _common
    _run(pipe._generate_subtitles(None))
    assert not os.path.exists(tmp_path / "prompts.json")


def test_manuscript_empty_text_skips(tmp_path):
    """全部段落无文本 → 直接跳过。"""
    pipe = _make_manuscript(tmp_path)
    pipe._state.paragraphs = [ManuscriptParagraph(index=0, text="")]
    _run(pipe._generate_subtitles(None))
    assert not os.path.exists(tmp_path / "full_subtitle.srt")


# ═══════════════════════════════════════════════════
# PoetryVideoPipeline._generate_subtitles
# ═══════════════════════════════════════════════════

class _FakeSubMaker:
    def __init__(self, has_cues=True):
        self.cues = [{"type": "word", "offset": 0, "duration": 1}] if has_cues else []


@pytest.fixture(autouse=True)
def _stub_subtitles(monkeypatch):
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "cues_to_srt",
        staticmethod(lambda sm, path: open(path, "w", encoding="utf-8").write("cue\n")),
    )
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "text_to_srt",
        staticmethod(lambda text, path, **k: open(path, "w", encoding="utf-8").write("est\n")),
    )


def _make_poetry(tmp_path, sub_maker):
    pipe = object.__new__(PoetryVideoPipeline)
    _base(pipe, tmp_path)
    pipe._state = PoetryVideoTask(
        poem="床前明月光",
        video_width=768, video_height=1152, video_duration=5,
        scene_count=2, scene_durations=[5, 5],
        scenes=[
            SceneTask(index=0, duration=5, narration_text="床前明月光"),
            SceneTask(index=1, duration=5, narration_text="疑是地上霜"),
        ],
    )
    pipe._scene_sub_makers = {0: sub_maker} if sub_maker is not None else {}
    pipe.get_audio_duration = lambda path: 0.0
    return pipe


def test_poetry_uses_scene_cues(tmp_path):
    """场景有 cues → cues_to_srt 生成精确字幕并写回 scene.subtitle_srt。"""
    pipe = _make_poetry(tmp_path, _FakeSubMaker(has_cues=True))
    _run(pipe._generate_subtitles(None))
    for idx, scene in enumerate(pipe._state.scenes):
        srt = os.path.join(str(tmp_path), f"scene_{idx}", "subtitle.srt")
        assert scene.subtitle_srt == srt
        assert os.path.exists(srt)


def test_poetry_falls_back_to_text_estimate(tmp_path):
    """场景无 cues → 回退纯文本估算字幕。"""
    pipe = _make_poetry(tmp_path, _FakeSubMaker(has_cues=False))
    _run(pipe._generate_subtitles(None))
    for idx, scene in enumerate(pipe._state.scenes):
        srt = os.path.join(str(tmp_path), f"scene_{idx}", "subtitle.srt")
        assert "est" in open(srt, encoding="utf-8").read()
        assert scene.subtitle_srt == srt


def test_poetry_disabled_skips(tmp_path):
    """字幕关闭 → 不生成任何 SRT。"""
    pipe = _make_poetry(tmp_path, None)
    pipe._state.subtitle_config = SubtitleConfig(enabled=False)
    _run(pipe._generate_subtitles(None))
    assert not os.path.exists(os.path.join(str(tmp_path), "scene_0"))
