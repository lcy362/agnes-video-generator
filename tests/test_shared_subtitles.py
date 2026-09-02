"""Unit tests for MultiScenePipeline.generate_subtitles_common.

覆盖共享字幕生成逻辑的各分支（含 v6.x 改为异步文件 IO 的落盘路径，
Sonar S7493 修复点）。所有字幕生成/后处理均打桩，不触发 moviepy/ffmpeg。
"""
import asyncio
import json
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.audio.subtitle as subtitle_pkg  # noqa: E402
from core.pipelines import MultiScenePipeline  # noqa: E402
from models.task import PoetryVideoTask, SceneTask, SubtitleConfig, SubtitleStyle  # noqa: E402


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


class _ConcreteMulti(MultiScenePipeline):
    async def _build_scenes(self):
        pass

    async def _build_reference_images(self):
        pass

    async def _composite_final(self):
        return os.path.join(self.working_dir, "final.mp4")


def _make_pipe(tmp_path):
    pipe = object.__new__(_ConcreteMulti)
    pipe.task_manager = _StubTaskManager(tmp_path)
    pipe._state = PoetryVideoTask(
        video_width=768, video_height=1152, video_duration=5,
        scene_count=2, scene_durations=[5, 5],
        scenes=[SceneTask(index=0, duration=5), SceneTask(index=1, duration=5)],
    )
    pipe.task_id = "sub-test"
    pipe.screenwriter = mock.MagicMock()
    pipe.progress_callback = None
    pipe.shutdown_event = None
    pipe._stop_event = asyncio.Event()
    return pipe


@pytest.fixture(autouse=True)
def _stub_subtitle_generator(monkeypatch):
    """打桩全部 SubtitleGenerator 方法，隔离 moviepy/ffmpeg。"""
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "generate_cue_aware_srt",
        staticmethod(lambda *a, **k: "1\n00:00:00,000 --> 00:00:01,000\nhello\n"),
    )
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "_generate_scene_aware_srt",
        staticmethod(lambda *a, **k: "1\n00:00:00,000 --> 00:00:01,000\nhello\n"),
    )
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "cues_to_srt",
        staticmethod(lambda *a, **k: None),
    )
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "text_to_srt",
        staticmethod(lambda *a, **k: None),
    )
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "enforce_max_lines",
        staticmethod(lambda raw, **k: raw),
    )


def _run(coro):
    return asyncio.run(coro)


def test_multi_segment_writes_srt(tmp_path):
    """多段 + 无 cues → scene-aware 生成并异步落盘（write_text 路径）。"""
    pipe = _make_pipe(tmp_path)
    srt_path, styles = _run(pipe.generate_subtitles_common(
        segment_texts=["a", "b"], segment_durations=[5.0, 5.0],
        subtitle_config=SubtitleConfig(), sub_maker=None, audio_path="",
    ))
    assert styles == ""
    assert srt_path == str(tmp_path / "full_subtitle.srt")
    assert "hello" in open(srt_path, encoding="utf-8").read()


def test_disabled_writes_empty_srt(tmp_path):
    """字幕关闭 → 写空 SRT（此前同步 open()，现为异步 write_text）。"""
    pipe = _make_pipe(tmp_path)
    cfg = SubtitleConfig(enabled=False)
    srt_path, _ = _run(pipe.generate_subtitles_common(
        segment_texts=["a", "b"], segment_durations=[5.0, 5.0],
        subtitle_config=cfg, sub_maker=None, audio_path="",
    ))
    assert open(srt_path, encoding="utf-8").read() == ""


def test_single_segment_falls_back_to_text_to_srt(tmp_path, monkeypatch):
    """单段 + 无 cues → text_to_srt 兜底分支。"""
    called = []
    monkeypatch.setattr(
        subtitle_pkg.SubtitleGenerator, "text_to_srt",
        staticmethod(lambda text, path, dur, **k: called.append((text, path, dur))),
    )
    pipe = _make_pipe(tmp_path)
    srt_path, _ = _run(pipe.generate_subtitles_common(
        segment_texts=["only"], segment_durations=[5.0],
        subtitle_config=SubtitleConfig(), sub_maker=None, audio_path="",
    ))
    assert srt_path
    assert called and called[0][0] == "only"


def test_enforce_max_lines_rewrites_file(tmp_path):
    """enforce_max_lines 返回不同内容时回写 SRT（write_text 路径）。"""
    subtitle_pkg.SubtitleGenerator.enforce_max_lines = staticmethod(
        lambda raw, **k: "1\n00:00:00,000 --> 00:00:01,000\nfixed\n"
    )
    try:
        pipe = _make_pipe(tmp_path)
        srt_path, _ = _run(pipe.generate_subtitles_common(
            segment_texts=["a", "b"], segment_durations=[5.0, 5.0],
            subtitle_config=SubtitleConfig(), sub_maker=None, audio_path="",
        ))
        assert "fixed" in open(srt_path, encoding="utf-8").read()
    finally:
        subtitle_pkg.SubtitleGenerator.enforce_max_lines = staticmethod(
            lambda raw, **k: raw
        )


def test_existing_srt_skips_generation(tmp_path):
    """SRT 已存在 → 直接跳过生成。"""
    existing = tmp_path / "full_subtitle.srt"
    existing.write_text("1\n00:00:00,000 --> 00:00:01,000\nold\n", encoding="utf-8")
    pipe = _make_pipe(tmp_path)
    srt_path, _ = _run(pipe.generate_subtitles_common(
        segment_texts=["a", "b"], segment_durations=[5.0, 5.0],
        subtitle_config=SubtitleConfig(), sub_maker=None, audio_path="",
    ))
    assert "old" in open(srt_path, encoding="utf-8").read()


def test_llm_style_mode_saves_styles_json(tmp_path):
    """style_mode=llm + screenwriter → 生成并异步写入样式 JSON。"""
    pipe = _make_pipe(tmp_path)
    pipe.screenwriter.generate_subtitle_styles.return_value = {
        "fontsize": 40, "color": "yellow",
    }
    cfg = SubtitleConfig(style=SubtitleStyle(style_mode="llm"))
    _, styles_path = _run(pipe.generate_subtitles_common(
        segment_texts=["a", "b"], segment_durations=[5.0, 5.0],
        subtitle_config=cfg, sub_maker=None, audio_path="", screenwriter=pipe.screenwriter,
    ))
    assert styles_path == str(tmp_path / "subtitle_styles.json")
    data = json.loads(open(styles_path, encoding="utf-8").read())
    assert data["fontsize"] == 40


def test_existing_styles_file_skips_llm(tmp_path):
    """样式文件已存在（SRT 新生成场景）→ 不调用 LLM，styles_path 保持为空。"""
    (tmp_path / "subtitle_styles.json").write_text("{}", encoding="utf-8")
    pipe = _make_pipe(tmp_path)
    cfg = SubtitleConfig(style=SubtitleStyle(style_mode="llm"))
    _, styles_path = _run(pipe.generate_subtitles_common(
        segment_texts=["a", "b"], segment_durations=[5.0, 5.0],
        subtitle_config=cfg, sub_maker=None, audio_path="",
        screenwriter=pipe.screenwriter,
    ))
    assert styles_path == ""
    pipe.screenwriter.generate_subtitle_styles.assert_not_called()


def test_empty_text_returns_empty(tmp_path):
    """无有效文本 → 直接返回 ("", "")。"""
    pipe = _make_pipe(tmp_path)
    res = _run(pipe.generate_subtitles_common(
        segment_texts=["", ""], segment_durations=[5.0, 5.0],
        subtitle_config=SubtitleConfig(), sub_maker=None, audio_path="",
    ))
    assert res == ("", "")
