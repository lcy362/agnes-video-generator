"""Unit tests for core.compositor.processor and core.screenwriter.

Motivation: raise coverage of the two heaviest untested modules.
processor.py uses subprocess+moviepy/ffmpeg under the hood, so those calls are
mocked/monkeypatched to keep tests fast and free of a real ffmpeg. screenwriter
is LLM-backed (AgnesChatAPI), so the chat API is monkeypatched to return canned
responses while exercising success + retry/fallback branches.

These tests live under tests/ root and therefore do NOT get the mock conftest
from tests/mock_regression/conftest.py — all external deps are mocked locally.
"""

import json
import os
import subprocess
import sys
import types
from unittest.mock import Mock

import pytest

from core.compositor import processor as processor_mod
from core.compositor.processor import VideoProcessor
from core.screenwriter import (
    Screenwriter,
    build_input_language_directive,
    build_poetry_scene_prompt,
    is_prompt_language_explicit,
    _DESCRIBE_RETRY_BASE_DELAY_SECONDS,
)
import core.screenwriter as screenwriter_mod


# ═══════════════════════════════════════════════════
# Processor helpers / fakes
# ═══════════════════════════════════════════════════

FFMPEG_FAKE = "/fake/ffmpeg"


@pytest.fixture
def fake_ffmpeg(monkeypatch, tmp_path):
    """Point resolve_binary at a fake path and neutralise subprocess.run."""

    run_mock = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(processor_mod, "resolve_binary", lambda name: FFMPEG_FAKE)
    monkeypatch.setattr(subprocess, "run", run_mock)
    return run_mock


class FakeVideoFileClip:
    def __init__(self, *args, **kwargs):
        self.duration = 12.0
        self.closed = False

    def get_frame(self, t):
        return "frame-array"

    def close(self):
        self.closed = True


class FakeImageClip:
    def __init__(self, img, duration=0.0):
        pass

    def close(self):
        pass


class FakeConcatClip:
    def __init__(self, output_path):
        self.output_path = output_path
        self.closed = False

    def write_videofile(self, output_path, logger=None, preset="fast"):
        open(output_path, "w").close()

    def close(self):
        self.closed = True


def fake_concatenate_videoclips(*clips, method="compose"):
    return FakeConcatClip("ignored")


@pytest.fixture
def fake_moviepy(monkeypatch):
    """Inject a fake ``moviepy`` module into sys.modules for the fallback path."""

    fake = types.ModuleType("moviepy")
    fake.ImageClip = FakeImageClip
    fake.VideoFileClip = FakeVideoFileClip
    fake.concatenate_videoclips = fake_concatenate_videoclips
    monkeypatch.setitem(sys.modules, "moviepy", fake)
    return fake


def _new_output_path(tmp_path, name):
    return str(tmp_path / name)


# ═══════════════════════════════════════════════════
# VideoProcessor
# ═══════════════════════════════════════════════════


def test_resize_video_success(fake_ffmpeg, tmp_path):
    out = _new_output_path(tmp_path, "resized.mp4")
    result = VideoProcessor.resize_video("in.mp4", 768, 1152, out)

    assert result == out
    assert os.path.exists(tmp_path)
    cmd = fake_ffmpeg.call_args_list[-1][0][0]
    assert cmd[:2] == [FFMPEG_FAKE, "-y"]
    assert "-i" in cmd
    assert any(a.startswith("scale=768:1152:") and "pad=768:1152:" in a for a in cmd)
    assert out in cmd


def test_resize_video_creates_parent_dir(fake_ffmpeg, tmp_path):
    out = str(tmp_path / "nested" / "deep" / "resized.mp4")
    VideoProcessor.resize_video("in.mp4", 640, 480, out)
    assert os.path.isdir(os.path.dirname(out))


def test_extract_last_frame_success(fake_ffmpeg, tmp_path):
    out = _new_output_path(tmp_path, "last.png")
    result = VideoProcessor.extract_last_frame("video.mp4", out)

    assert result == out
    cmd = fake_ffmpeg.call_args_list[-1][0][0]
    assert "-sseof" in cmd and "-frames:v" in cmd and out in cmd


def test_generate_silent_audio_success(fake_ffmpeg, tmp_path):
    out = _new_output_path(tmp_path, "silent.mp3")
    result = VideoProcessor.generate_silent_audio(2.5, out)
    assert result == out
    cmd = fake_ffmpeg.call_args_list[-1][0][0]
    assert "anullsrc=r=44100:cl=mono" in cmd
    assert "2.5" in cmd


def _make_freezing_ffmpeg(monkeypatch, exc, tmp_path):
    """subprocess.run raises exc and creates/lists an empty output file."""

    def fake_run(cmd, *args, **kwargs):
        raise exc

    monkeypatch.setattr(processor_mod, "resolve_binary", lambda name: FFMPEG_FAKE)
    monkeypatch.setattr(subprocess, "run", fake_run)


def test_freeze_last_frame_tpad_success(fake_ffmpeg, tmp_path):
    out = _new_output_path(tmp_path, "frozen.mp4")
    # Simulate a real ffmpeg having produced a non-empty output file.
    with open(out, "w") as f:
        f.write("partial")
    result = VideoProcessor.freeze_last_frame("in.mp4", 3.0, out)
    assert result == out
    cmd = fake_ffmpeg.call_args_list[-1][0][0]
    assert any("tpad=stop_mode=clone:stop_duration=3.0" in a for a in cmd)


def test_freeze_last_frame_called_process_error_fallback(monkeypatch, fake_moviepy, tmp_path):
    out = _new_output_path(tmp_path, "frozen.mp4")
    _make_freezing_ffmpeg(monkeypatch, subprocess.CalledProcessError(1, ["ffmpeg"]), tmp_path)
    result = VideoProcessor.freeze_last_frame("in.mp4", 3.0, out)
    assert result == out
    assert os.path.exists(out)


def test_freeze_last_frame_timeout_fallback(monkeypatch, fake_moviepy, tmp_path):
    out = _new_output_path(tmp_path, "frozen2.mp4")
    _make_freezing_ffmpeg(monkeypatch, subprocess.TimeoutExpired("ffmpeg", 30), tmp_path)
    result = VideoProcessor.freeze_last_frame("in.mp4", 1.5, out)
    assert result == out


# ═══════════════════════════════════════════════════
# screenwriter module-level functions
# ═══════════════════════════════════════════════════


def test_describe_retry_base_delay_constant():
    assert _DESCRIBE_RETRY_BASE_DELAY_SECONDS == 15


def test_is_prompt_language_explicit_env_set(monkeypatch):
    monkeypatch.setenv("PROMPT_LANGUAGE", "en")
    assert is_prompt_language_explicit() is True


def test_is_prompt_language_explicit_dotenv(monkeypatch):
    from core import config as config_mod
    monkeypatch.delenv("PROMPT_LANGUAGE", raising=False)
    monkeypatch.setattr(config_mod, "_dotenv_value", lambda var: "zh")
    assert is_prompt_language_explicit() is True


def test_is_prompt_language_explicit_dotenv_empty(monkeypatch):
    from core import config as config_mod
    monkeypatch.delenv("PROMPT_LANGUAGE", raising=False)
    monkeypatch.setattr(config_mod, "_dotenv_value", lambda var: "")
    assert is_prompt_language_explicit() is False


def test_is_prompt_language_explicit_dotenv_error(monkeypatch):
    from core import config as config_mod
    monkeypatch.delenv("PROMPT_LANGUAGE", raising=False)

    def boom(var):
        raise RuntimeError("no dotenv")

    monkeypatch.setattr(config_mod, "_dotenv_value", boom)
    assert is_prompt_language_explicit() is False


def test_build_input_language_directive_empty():
    assert build_input_language_directive("") == ""
    assert build_input_language_directive("   ") == ""


def test_build_input_language_directive_zh():
    # Chinese returns an empty directive (keeps existing behaviour).
    assert build_input_language_directive("一只猫在花园里追蝴蝶") == ""


def test_build_input_language_directive_arabic():
    d = build_input_language_directive("مرحبا بالعالم")
    assert "Arabic" in d
    assert "English" in d


def test_build_input_language_directive_russian():
    d = build_input_language_directive("Привет мир")
    assert "Russian" in d


def test_build_input_language_directive_latin():
    d = build_input_language_directive("A cat chases a butterfly")
    assert "SAME language as the input idea" in d
    assert "do not write in Chinese" in d


# ═══════════════════════════════════════════════════
# Screenwriter class basics + wrappers
# ═══════════════════════════════════════════════════


def test_screenwriter_init_and_prompt():
    sw = Screenwriter(api_key="k", model="m-test", language="zh")
    assert sw.api_key == "k"
    assert sw.model == "m-test"
    assert sw.language == "zh"
    assert sw.headers["Authorization"] == "Bearer k"
    assert sw.chat_api is not None
    assert sw._prompt("中", "en") == "中"
    assert sw._prompt("中", "en") == "中"  # zh language picks zh_text

    sw_en = Screenwriter(api_key="k", language="en")
    assert sw_en.language == "en"
    assert sw_en._prompt("中", "en") == "en"


def test_screenwriter_chat_wrappers(monkeypatch):
    sw = Screenwriter(api_key="k", language="zh")
    sw.chat_api.chat = lambda sp, up: "canned-chat"
    sw.chat_api.chat_json = lambda sp, up: {"key": "value"}
    sw.chat_api.chat_multimodal = lambda sp, tp, imgs: "canned-mm"
    assert sw._chat("sys", "usr") == "canned-chat"
    assert sw._chat_json("sys", "usr") == {"key": "value"}
    assert sw._chat_multimodal("sys", "tp", ["a.png"]) == "canned-mm"


def test_screenwriter_image_to_b64(tmp_path):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG fake bytes")
    sw = Screenwriter(api_key="k", language="zh")
    uri = sw._image_to_b64_uri(str(img))
    assert uri.startswith("data:image/png;base64,")


# ═══════════════════════════════════════════════════
# describe_images + _describe_with_retry
# ═══════════════════════════════════════════════════


def test_describe_images_empty():
    sw = Screenwriter(api_key="k", language="zh")
    assert sw.describe_images([]) == ""


def _sw_with_mm(monkeypatch, responses):
    """Build a Screenwriter whose chat_api.chat_multimodal returns canned text."""
    sw = Screenwriter(api_key="k", language="zh")

    def fake_mm(system_prompt, text_prompt, image_paths):
        if isinstance(responses, list):
            return responses.pop(0)
        return responses

    monkeypatch.setattr(sw.chat_api, "chat_multimodal", fake_mm)
    return sw


def test_describe_images_no_cache(monkeypatch):
    sw = _sw_with_mm(monkeypatch, ["cat image", "bird image"])
    result = sw.describe_images(["a.png", "b.png"])
    assert "[起始帧]" in result
    assert "[尾帧 0]" in result
    assert "cat image" in result and "bird image" in result
    assert result.count("\n\n") == 1


def test_describe_images_uses_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "image_analysis.json"
    cache_file.write_text(json.dumps({
        "image_paths": ["a.png", "b.png"],
        "descriptions": {"0": "cached desc0", "1": "cached desc1"},
    }), encoding="utf-8")
    sw = _sw_with_mm(monkeypatch, ["should-not-be-used"])
    result = sw.describe_images(["a.png", "b.png"], cache_dir=str(tmp_path))
    assert "cached desc0" in result and "cached desc1" in result
    assert "should-not-be-used" not in result


def test_describe_images_filters_failed_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "image_analysis.json"
    cache_file.write_text(json.dumps({
        "image_paths": ["a.png"],
        "descriptions": {"0": "(分析失败) bad"},
    }), encoding="utf-8")
    sw = _sw_with_mm(monkeypatch, ["fresh desc"])
    result = sw.describe_images(["a.png"], cache_dir=str(tmp_path))
    assert "fresh desc" in result
    assert "(分析失败)" not in result


def test_describe_images_cache_mismatch(monkeypatch, tmp_path):
    cache_file = tmp_path / "image_analysis.json"
    cache_file.write_text(json.dumps({
        "image_paths": ["old.png"],
        "descriptions": {"0": "stale"},
    }), encoding="utf-8")
    sw = _sw_with_mm(monkeypatch, ["new desc"])
    result = sw.describe_images(["a.png"], cache_dir=str(tmp_path))
    assert "new desc" in result
    assert "stale" not in result


def test_describe_images_cache_load_error(monkeypatch, tmp_path):
    cache_file = tmp_path / "image_analysis.json"
    cache_file.write_text("{ not valid json !", encoding="utf-8")
    sw = _sw_with_mm(monkeypatch, ["recovered desc"])
    result = sw.describe_images(["a.png"], cache_dir=str(tmp_path))
    assert "recovered desc" in result


def test_describe_images_cache_write_error(monkeypatch, tmp_path):
    # Make the cache path a directory so open(..., "w") raises IsADirectoryError.
    bad = tmp_path / "image_analysis.json"
    bad.mkdir()
    sw = _sw_with_mm(monkeypatch, ["desc"])
    result = sw.describe_images(["a.png"], cache_dir=str(tmp_path))
    assert "desc" in result


def test_describe_with_retry_default_text_prompt(monkeypatch):
    sw = Screenwriter(api_key="k", language="zh")

    def fake_mm(system_prompt, text_prompt, image_paths):
        assert text_prompt == "请描述这张图片。"
        return "ok"

    monkeypatch.setattr(sw.chat_api, "chat_multimodal", fake_mm)
    assert sw._describe_with_retry("sys", "img.png", "起始帧") == "ok"


def test_describe_with_retry_succeeds_first_try(monkeypatch):
    sw = Screenwriter(api_key="k", language="zh")
    monkeypatch.setattr(
        sw.chat_api, "chat_multimodal", lambda sp, tp, imgs: "first"
    )
    assert sw._describe_with_retry("sys", "img.png", "起始帧", "desc") == "first"


def test_describe_with_retry_retries_then_succeeds(monkeypatch):
    sw = Screenwriter(api_key="k", language="zh")
    calls = {"n": 0}
    slept = []

    def fake_mm(sp, tp, imgs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return "recovered"

    def fake_sleep(sec):
        slept.append(sec)

    monkeypatch.setattr(sw.chat_api, "chat_multimodal", fake_mm)
    monkeypatch.setattr(screenwriter_mod._time, "sleep", fake_sleep)
    assert sw._describe_with_retry("sys", "img.png", "起始帧", "desc") == "recovered"
    assert calls["n"] == 2
    assert slept == [15 * (0 + 1)]


def test_describe_with_retry_all_fail(monkeypatch):
    sw = Screenwriter(api_key="k", language="zh")
    slept = []

    def fake_mm(sp, tp, imgs):
        raise RuntimeError("always fails")

    def fake_sleep(sec):
        slept.append(sec)

    monkeypatch.setattr(sw.chat_api, "chat_multimodal", fake_mm)
    monkeypatch.setattr(screenwriter_mod._time, "sleep", fake_sleep)
    with pytest.raises(RuntimeError, match="图片分析失败"):
        sw._describe_with_retry("sys", "img.png", "起始帧", "desc", max_retries=3)
    assert len(slept) == 2


# ═══════════════════════════════════════════════════
# build_poetry_scene_prompt
# ═══════════════════════════════════════════════════


def test_build_poetry_scene_prompt():
    out = build_poetry_scene_prompt(
        "春眠不觉晓", scene_count=2, scene_durations=[5, 8], total_duration=13, style="水墨"
    )
    assert set(out.keys()) == {"system_prompt", "user_prompt"}
    assert "春眠不觉晓" in out["user_prompt"]
    assert "2 个" in out["user_prompt"]


def test_build_poetry_scene_prompt_defaults():
    out = build_poetry_scene_prompt("静夜思")
    assert "目标总时长：30 秒" in out["user_prompt"]