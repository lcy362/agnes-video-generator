"""Unit tests for web.helpers and web.deps.

Self-contained: no network calls, no API key, no real moviepy/ffmpeg.
Heavy dependencies are monkeypatched. Async functions are driven with
asyncio.run() (no pytest-asyncio required). Writes are isolated to tmp_path.
"""
import asyncio
import base64
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipelines import PipelineShutdown  # noqa: E402
from models.task import BaseTaskState, StepStatus, TaskType  # noqa: E402
from web import app_state, deps, helpers  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════
# web.helpers
# ═══════════════════════════════════════════════════


class TestParseBgColor:
    def test_passes_tuple_through(self):
        assert helpers._parse_bg_color((1, 2, 3, 0.5)) == (1, 2, 3, 0.5)

    def test_parses_parenthesized_tuple_string(self):
        assert helpers._parse_bg_color("(10, 20, 30)") == (10, 20, 30)

    def test_parses_alpha_color(self):
        assert helpers._parse_bg_color("red@0.3") == (255, 0, 0, 76)
        assert helpers._parse_bg_color("WHITE@1") == (255, 255, 255, 255)

    def test_unknown_color_with_alpha_defaults_black(self):
        assert helpers._parse_bg_color("pink@0.5") == (0, 0, 0, 127)

    def test_none_transparent_empty_returns_none(self):
        assert helpers._parse_bg_color("none") is None
        assert helpers._parse_bg_color("transparent") is None
        assert helpers._parse_bg_color("") is None

    def test_falls_back_to_default(self):
        assert helpers._parse_bg_color("not-a-color") == (0, 0, 0, 128)


def test_build_position_top():
    assert helpers._build_position("top") == ("center", "top")


def test_build_position_bottom_default():
    assert helpers._build_position("bottom") == ("center", "bottom")
    assert helpers._build_position("") == ("center", "bottom")


class TestPreviewCacheKey:
    def test_key_is_deterministic_hash(self):
        k1 = helpers._preview_cache_key("zh-CN-XiaoxiaoNeural", "hello")
        k2 = helpers._preview_cache_key("zh-CN-XiaoxiaoNeural", "hello")
        assert k1 == k2
        assert "__" in k1
        assert "/" not in k1 and ".." not in k1


class TestGetOrGeneratePreview:
    def test_cache_hit_does_not_call_edge_tts(self, monkeypatch, tmp_path):
        monkeypatch.setattr(helpers, "VOICE_PREVIEW_CACHE_DIR", str(tmp_path))
        cache_path = os.path.join(
            str(tmp_path),
            helpers._preview_cache_key("v1", "hi") + ".mp3",
        )
        with open(cache_path, "w") as f:
            f.write("x")

        def fail(*a, **k):
            raise AssertionError("Communicate should not be called")

        monkeypatch.setattr("edge_tts.Communicate", fail)
        result = _run(helpers._get_or_generate_preview("v1", "hi"))
        assert result == cache_path

    def test_cache_miss_generates_and_swaps(self, monkeypatch, tmp_path):
        monkeypatch.setattr(helpers, "VOICE_PREVIEW_CACHE_DIR", str(tmp_path))
        calls = []

        class FakeCommunicate:
            def __init__(self, text, voice=None):
                calls.append((text, voice))

            async def save(self, path):
                with open(path, "w") as f:
                    f.write("audio")

        monkeypatch.setattr("edge_tts.Communicate", FakeCommunicate)
        result = _run(helpers._get_or_generate_preview("zh-Xiaoxiao", "你好"))
        assert os.path.exists(result)
        assert calls == [("你好", "zh-Xiaoxiao")]
        # only the final .mp3 remains (no .tmp leftover)
        assert not os.path.exists(result + ".tmp")


class TestResolvePreviewText:
    def test_explicit_text_wins(self, monkeypatch):
        monkeypatch.setattr(
            helpers, "get_voice_lang", lambda voice: "en"
        )
        assert helpers._resolve_preview_text("v", "my text") == "my text"

    def test_uses_preset_by_voice_lang(self):
        out = helpers._resolve_preview_text("en-US-JennyNeural", "")
        assert "Jenny" in out

    def test_falls_back_to_chinese_for_unknown_lang(self, monkeypatch):
        monkeypatch.setattr(helpers, "get_voice_lang", lambda voice: None)
        out = helpers._resolve_preview_text("xx-YY-BobNeural", "")
        assert "Bob" in out


class TestValidateVoiceCompat:
    def test_no_voice_returns_none(self):
        assert helpers._validate_voice_compat("", "zh") is None
        assert helpers._validate_voice_compat(None, "zh") is None

    def test_text_compatible_returns_none(self, monkeypatch):
        monkeypatch.setattr(helpers, "is_voice_compatible_with_text", lambda v, t: True)
        assert helpers._validate_voice_compat("v", "zh", "some text") is None

    def test_text_incompatible_raises_422(self, monkeypatch):
        monkeypatch.setattr(helpers, "is_voice_compatible_with_text", lambda v, t: False)
        with pytest.raises(Exception) as ei:
            helpers._validate_voice_compat("v", "zh", "some text")
        assert ei.value.status_code == 422

    def test_target_lang_compatible_returns_none(self, monkeypatch):
        monkeypatch.setattr(helpers, "is_voice_compatible", lambda v, t: True)
        assert helpers._validate_voice_compat("v", "zh") is None

    def test_no_target_lang_returns_none(self, monkeypatch):
        monkeypatch.setattr(helpers, "is_voice_compatible", lambda v, t: True)
        assert helpers._validate_voice_compat("v", "") is None

    def test_target_lang_incompatible_raises_422(self, monkeypatch):
        monkeypatch.setattr(helpers, "is_voice_compatible", lambda v, t: False)
        monkeypatch.setattr(helpers, "get_voice_lang", lambda v: "zh")
        with pytest.raises(Exception) as ei:
            helpers._validate_voice_compat("v", "en")
        assert ei.value.status_code == 422


def test_get_upload_dir(monkeypatch):
    monkeypatch.setattr(helpers, "get_working_dir", lambda: "/work")
    assert helpers.get_upload_dir() == os.path.join("/work", "uploads")


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("每个场景约5秒", 5),
            ("每段10秒", 10),
            ("每个 3 秒", 3),
            ("7 秒每", 7),
            ("各 7 秒", 7),
            ("3 seconds each", 3),
            ("each 4 seconds", 4),
            ("각 5초", 5),
            ("по 6 секунд", 6),
            ("5 saat setiap", 5),
            ("setiap 8 saat", 8),
            ("no duration here", 5),
        ],
    )
    def test_parses_duration(self, text, expected):
        assert helpers._parse_duration(text) == expected


class TestHasExplicitDuration:
    def test_true_when_present(self):
        assert helpers._has_explicit_duration("每个场景约5秒") is True

    def test_false_otherwise(self):
        assert helpers._has_explicit_duration("hello world") is False


class TestBuildEncryptedImagePrompt:
    def test_chinese_system_prompt(self):
        sys_prompt = "请生成一张中文图片"
        user_prompt = "一只猫"
        out = helpers._build_encrypted_image_prompt(sys_prompt, user_prompt)
        assert sys_prompt in out
        assert user_prompt in base64.b64decode(
            out.split("加密描述：\n")[1]
        ).decode("utf-8")

    def test_english_system_prompt(self):
        sys_prompt = "Generate an image"
        user_prompt = "a cat"
        out = helpers._build_encrypted_image_prompt(sys_prompt, user_prompt)
        assert sys_prompt in out
        dec = out.split("Encrypted description:\n")[1]
        assert base64.b64decode(dec).decode("utf-8") == "a cat"


class TestFindDirName:
    def _fake_tm(self, tasks):
        class FakeTM:
            def __init__(self, task_id="_"):
                pass

            def list_tasks(self):
                return tasks

        return FakeTM

    def test_matching_task_returns_dir_name(self, monkeypatch):
        monkeypatch.setattr(helpers, "TaskManager", self._fake_tm(
            [{"task_id": "t1", "dir_name": "d1"}]
        ))
        assert helpers.find_dir_name("t1") == "d1"

    def test_matching_task_without_dir_name_falls_back(self, monkeypatch):
        monkeypatch.setattr(helpers, "TaskManager", self._fake_tm(
            [{"task_id": "t1"}]
        ))
        assert helpers.find_dir_name("t1") == "t1"

    def test_unknown_task_returns_task_id(self, monkeypatch):
        monkeypatch.setattr(helpers, "TaskManager", self._fake_tm([]))
        assert helpers.find_dir_name("t-unknown") == "t-unknown"


class TestPickDirectoryNative:
    def _run_output(self, returncode, stdout):
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    def test_macos_success(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **k: self._run_output(0, "/chosen\n"))
        assert helpers._pick_directory_native() == "/chosen"

    def test_macos_returns_empty_on_error(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **k: self._run_output(1, ""))
        assert helpers._pick_directory_native() == ""

    def test_windows_success(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Windows")
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **k: self._run_output(0, "C:\\x\n"))
        assert helpers._pick_directory_native() == "C:\\x"

    def test_linux_zenity_then_kdialog(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Linux")
        results = iter([
            self._run_output(0, "/via-zenity\n"),
        ])
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **k: next(results))
        assert helpers._pick_directory_native() == "/via-zenity"

    def test_linux_kdialog_fallback_when_zenity_missing(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Linux")

        def fake_run(cmd, *a, **k):
            if cmd[0] == "zenity":
                raise FileNotFoundError("no zenity")
            return self._run_output(0, "/via-kdialog\n")

        monkeypatch.setattr(helpers.subprocess, "run", fake_run)
        assert helpers._pick_directory_native() == "/via-kdialog"

    def test_linux_both_fail_returns_empty(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Linux")
        monkeypatch.setattr(helpers.subprocess, "run",
                            lambda *a, **k: self._run_output(1, ""))
        assert helpers._pick_directory_native() == ""

    def test_timeout_returns_empty(self, monkeypatch):
        monkeypatch.setattr(helpers.platform, "system", lambda: "Darwin")

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired("osascript", timeout=120)

        monkeypatch.setattr(helpers.subprocess, "run", raise_timeout)
        assert helpers._pick_directory_native() == ""


class TestPickDirectory:
    def test_no_path_returns_ok_false(self, monkeypatch):
        monkeypatch.setattr(helpers, "_pick_directory_native", lambda: "")
        assert _run(helpers.pick_directory()) == {"ok": False, "path": ""}

    def test_with_path_returns_ok_true(self, monkeypatch):
        monkeypatch.setattr(helpers, "_pick_directory_native", lambda: "/picked")
        assert _run(helpers.pick_directory()) == {"ok": True, "path": "/picked"}


# ═══════════════════════════════════════════════════
# web.deps
# ═══════════════════════════════════════════════════


_MODELS = {"text": "t", "image": "i", "video": "v"}


class TestCreatePipelineForType:
    def _prepare(self, monkeypatch):
        monkeypatch.setattr(deps, "get_selected_models", lambda: _MODELS)
        fake = MagicMock()
        for name in (
            "SimpleVideoPipeline",
            "ManuscriptVideoPipeline",
            "AnchorPipeline",
            "PoetryVideoPipeline",
            "CreativeVideoPipeline",
        ):
            monkeypatch.setattr(deps, name, MagicMock())
        return fake

    def _assert_common(self, call_kwargs):
        assert call_kwargs["api_key"] == "key"
        assert call_kwargs["task_id"] == "tid"
        assert call_kwargs["dir_name"] == "dir"
        assert call_kwargs["chat_model"] == "t"
        assert call_kwargs["shutdown_event"] is app_state.shutdown_event

    def test_simple(self, monkeypatch):
        self._prepare(monkeypatch)
        result = deps.create_pipeline_for_type(TaskType.SIMPLE, "key", "tid", "dir")
        deps.SimpleVideoPipeline.assert_called_once()
        assert result is deps.SimpleVideoPipeline.return_value
        self._assert_common(deps.SimpleVideoPipeline.call_args.kwargs)
        assert deps.SimpleVideoPipeline.call_args.kwargs["image_model"] == "i"
        assert deps.SimpleVideoPipeline.call_args.kwargs["video_model"] == "v"

    def test_manuscript(self, monkeypatch):
        self._prepare(monkeypatch)
        deps.create_pipeline_for_type(TaskType.MANUSCRIPT, "key", "tid", "dir")
        deps.ManuscriptVideoPipeline.assert_called_once()
        self._assert_common(deps.ManuscriptVideoPipeline.call_args.kwargs)

    def test_anchor(self, monkeypatch):
        self._prepare(monkeypatch)
        deps.create_pipeline_for_type(TaskType.ANCHOR, "key", "tid", "dir")
        deps.AnchorPipeline.assert_called_once()
        self._assert_common(deps.AnchorPipeline.call_args.kwargs)

    def test_poetry_no_image_model(self, monkeypatch):
        self._prepare(monkeypatch)
        deps.create_pipeline_for_type(TaskType.POETRY, "key", "tid", "dir")
        deps.PoetryVideoPipeline.assert_called_once()
        kw = deps.PoetryVideoPipeline.call_args.kwargs
        assert "image_model" not in kw
        assert kw["video_model"] == "v"

    def test_creative_default(self, monkeypatch):
        self._prepare(monkeypatch)
        deps.create_pipeline_for_type(TaskType.CREATIVE, "key", "tid", "dir")
        deps.CreativeVideoPipeline.assert_called_once()
        self._assert_common(deps.CreativeVideoPipeline.call_args.kwargs)

    def test_unknown_falls_back_to_creative(self, monkeypatch):
        self._prepare(monkeypatch)
        deps.create_pipeline_for_type(TaskType.IMAGE, "key", "tid", "dir")
        deps.CreativeVideoPipeline.assert_called_once()


class TestRefreshTaskManifests:
    def test_success(self, monkeypatch):
        state = BaseTaskState(task_type=TaskType.CREATIVE)
        pipeline = SimpleNamespace(task_id="tid", working_dir="/wd")
        write = MagicMock()
        monkeypatch.setattr("core.artifacts.write_task_manifests", write)
        deps._refresh_task_manifests(state, pipeline)
        write.assert_called_once_with(state, "/wd")

    def test_exception_is_swallowed(self, monkeypatch):
        state = BaseTaskState(task_type=TaskType.CREATIVE)
        pipeline = SimpleNamespace(task_id="tid", working_dir="/wd")

        def boom(*a, **k):
            raise RuntimeError("manifest failed")

        monkeypatch.setattr("core.artifacts.write_task_manifests", boom)
        # must not propagate
        deps._refresh_task_manifests(state, pipeline)


def test_mark_task_queued():
    tm = MagicMock()
    deps.mark_task_queued(tm)
    tm.update_state.assert_called_once_with(
        status=StepStatus.QUEUED,
        current_step="init",
        current_status="running",
        current_message="任务排队中...",
        current_progress=0.0,
    )


class FakePipeline:
    def __init__(self, task_id="tid", run_result="ok"):
        self.task_id = task_id
        self._run_result = run_result
        self.failed_run = None

    async def run(self, state):
        if isinstance(self._run_result, Exception):
            raise self._run_result
        return self._run_result


def _make_state():
    return BaseTaskState(task_type=TaskType.CREATIVE)


class TestRunPipeline:
    @pytest.fixture(autouse=True)
    def _clean(self):
        app_state.active_pipelines.clear()
        yield
        app_state.active_pipelines.clear()

    def _patch(self, monkeypatch):
        monkeypatch.setattr(
            "core.api.error_collector.set_error_task_id", MagicMock()
        )
        manifest = MagicMock()
        monkeypatch.setattr(deps, "_refresh_task_manifests", manifest)
        return manifest

    def test_success(self, monkeypatch):
        self._patch(monkeypatch)
        p = FakePipeline("tid")
        app_state.active_pipelines["tid"] = p
        _run(deps.run_pipeline(p, _make_state()))
        assert "tid" not in app_state.active_pipelines

    def test_pipeline_shutdown(self, monkeypatch):
        self._patch(monkeypatch)
        p = FakePipeline("tid", run_result=PipelineShutdown())
        app_state.active_pipelines["tid"] = p
        _run(deps.run_pipeline(p, _make_state()))
        assert "tid" not in app_state.active_pipelines

    def test_generic_exception(self, monkeypatch):
        self._patch(monkeypatch)
        p = FakePipeline("tid", run_result=RuntimeError("boom"))
        app_state.active_pipelines["tid"] = p
        _run(deps.run_pipeline(p, _make_state()))
        assert "tid" not in app_state.active_pipelines

    def test_does_not_delete_foreign_pipeline(self, monkeypatch):
        self._patch(monkeypatch)
        p = FakePipeline("tid")
        other = FakePipeline("tid")
        app_state.active_pipelines["tid"] = other  # a different instance
        _run(deps.run_pipeline(p, _make_state()))
        assert app_state.active_pipelines["tid"] is other


class FakeSemaphore:
    def __init__(self, max_weight=10, acquire_error=None, release_error=None):
        self.max_weight = max_weight
        self.current = 0
        self.released = 0
        self.acquire_error = acquire_error
        self.release_error = release_error

    async def acquire(self, weight):
        if self.acquire_error is not None:
            raise self.acquire_error
        self.current += weight

    async def release(self, weight):
        if self.release_error is not None:
            raise self.release_error
        self.current -= weight
        self.released += weight


class TestRunPipelineWithConcurrency:
    @pytest.fixture(autouse=True)
    def _clean(self):
        app_state._queued_tasks.clear()
        yield
        app_state._queued_tasks.clear()

    def _patch(self, monkeypatch, semaphore, weights=None):
        monkeypatch.setattr(
            deps.app_state, "get_semaphore", lambda: semaphore
        )
        if weights is not None:
            monkeypatch.setattr(deps.app_state, "TASK_TYPE_WEIGHTS", weights)
        ran = []

        async def fake_run(pipeline, state):
            ran.append(pipeline.task_id)

        monkeypatch.setattr(deps, "run_pipeline", fake_run)
        return ran

    def test_weight_exceeds_max_rejected(self, monkeypatch):
        sem = FakeSemaphore(max_weight=2)
        self._patch(monkeypatch, sem, weights={TaskType.CREATIVE: 5})
        tm = MagicMock()
        _run(deps.run_pipeline_with_concurrency(
            FakePipeline("tid"), _make_state(), tm
        ))
        # marked queued then failed
        statuses = [
            c.kwargs.get("status") for c in tm.update_state.call_args_list
        ]
        assert StepStatus.QUEUED in statuses
        assert StepStatus.FAILED in statuses
        assert tm.update_state.call_args_list[-1].kwargs["current_status"] == "failed"
        assert "tid" not in app_state._queued_tasks
        assert sem.current == 0

    def test_normal_acquisition_runs_pipeline(self, monkeypatch):
        sem = FakeSemaphore(max_weight=10)
        ran = self._patch(monkeypatch, sem, weights={TaskType.CREATIVE: 1})
        tm = MagicMock()
        _run(deps.run_pipeline_with_concurrency(
            FakePipeline("tid"), _make_state(), tm
        ))
        assert ran == ["tid"]
        assert sem.released == 1
        assert "tid" not in app_state._queued_tasks

    def test_stopped_while_queued_skips_run(self, monkeypatch):
        sem = FakeSemaphore(max_weight=10)
        ran = self._patch(monkeypatch, sem, weights={TaskType.CREATIVE: 1})

        p = FakePipeline("tid")
        stop_event = asyncio.Event()
        stop_event.set()
        p._stop_event = stop_event

        tm = MagicMock()
        _run(deps.run_pipeline_with_concurrency(p, _make_state(), tm))
        assert ran == []
        assert sem.released == 1
        assert "tid" not in app_state._queued_tasks

    def test_cancelled_while_queued(self, monkeypatch):
        sem = FakeSemaphore(max_weight=10)
        ran = self._patch(monkeypatch, sem, weights={TaskType.CREATIVE: 1})
        tm = MagicMock()
        sem.acquire_error = asyncio.CancelledError()
        _run(deps.run_pipeline_with_concurrency(
            FakePipeline("tid"), _make_state(), tm
        ))
        assert ran == []
        assert "tid" not in app_state._queued_tasks

    def test_acquire_failure_marks_failed(self, monkeypatch):
        sem = FakeSemaphore(max_weight=10)
        self._patch(monkeypatch, sem, weights={TaskType.CREATIVE: 1})
        tm = MagicMock()
        sem.acquire_error = RuntimeError("boom")
        _run(deps.run_pipeline_with_concurrency(
            FakePipeline("tid"), _make_state(), tm
        ))
        last = tm.update_state.call_args_list[-1].kwargs
        assert last["status"] == StepStatus.FAILED
        assert "boom" in last["current_message"]
        assert "tid" not in app_state._queued_tasks
        assert sem.released == 0  # never acquired -> no release

    def test_release_exception_is_swallowed(self, monkeypatch):
        sem = FakeSemaphore(max_weight=10, release_error=RuntimeError("rel"))
        ran = self._patch(monkeypatch, sem, weights={TaskType.CREATIVE: 1})
        tm = MagicMock()
        _run(deps.run_pipeline_with_concurrency(
            FakePipeline("tid"), _make_state(), tm
        ))
        assert ran == ["tid"]
        assert "tid" not in app_state._queued_tasks  # cleanup still ran