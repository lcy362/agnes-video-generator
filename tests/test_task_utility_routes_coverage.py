"""
Coverage tests for web/routes/task_routes.py and web/routes/utility_routes.py.

Uses FastAPI TestClient mounting only the routers under test (no server.py).
All write paths are monkeypatched to tmp_path / stubbed TaskManager / stubbed
background launcher. No network, no API key required, no video rendering.

Usage:
    .venv/bin/python -m pytest tests/test_task_utility_routes_coverage.py \
        --cov=web.routes.task_routes --cov=web.routes.utility_routes \
        --cov-report=term-missing -q
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import artifacts as artifacts_mod
from models.task import (
    AnchorVideoTask,
    CreativeVideoTask,
    ManuscriptVideoTask,
    ManuscriptParagraph,
    PoetryVideoTask,
    SimpleImageTask,
    SimpleVideoTask,
    StepStatus,
    VideoMode,
)
from web import app_state
from web.routes import task_routes, utility_routes


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(task_routes.router)
    app.include_router(utility_routes.router)
    return TestClient(app)


class _StopEvent:
    def __init__(self, stopped):
        self._stopped = stopped

    def is_set(self):
        return self._stopped


class _FakePipeline:
    def __init__(self, stopped=False, task_type="creative"):
        self._stop_event = _StopEvent(stopped)
        self._task_type = task_type
        self.stopped = False

    def stop(self):
        self.stopped = True


class _StubTaskManager:
    """打桩 TaskManager：内存态，不写盘。"""

    task_list: list = []
    states: dict = {}  # task_id -> state
    updates: list = []
    latest_task_id: str = ""

    def __init__(self, task_id="", dir_name=None):
        self.task_id = task_id
        self.dir_name = dir_name
        self.state = _StubTaskManager.states.get(task_id)

    def list_tasks(self):
        return _StubTaskManager.task_list

    def load(self):
        return _StubTaskManager.states.get(self.task_id)

    def update_state(self, **kwargs):
        _StubTaskManager.updates.append(kwargs)
        if self.state is not None:
            for k, v in kwargs.items():
                if hasattr(self.state, k):
                    setattr(self.state, k, v)


def _reset_state(monkeypatch, task_list=None, states=None):
    _StubTaskManager.task_list = task_list or []
    _StubTaskManager.states = states or {}
    _StubTaskManager.updates = []
    monkeypatch.setattr(task_routes, "TaskManager", _StubTaskManager)
    app_state.active_pipelines.clear()
    app_state._queued_tasks.clear()


def _patch_runtime(monkeypatch, launched=None):
    monkeypatch.setattr(task_routes, "get_api_key", lambda: "test-api-key")
    monkeypatch.setattr(task_routes.helpers, "find_dir_name", lambda tid: tid)
    monkeypatch.setattr(
        task_routes.deps, "create_pipeline_for_type",
        lambda *a, **k: _FakePipeline(),
    )
    bucket = launched if launched is not None else []

    def fake_launch(coro):
        bucket.append(coro)
        if hasattr(coro, "close"):
            coro.close()

    monkeypatch.setattr(task_routes.app_state, "launch_background_task", fake_launch)
    monkeypatch.setattr(
        task_routes.deps, "run_pipeline_with_concurrency", lambda *a, **k: None
    )
    return bucket


# ═══════════════════════════════════════════════════
# task_routes: GET /api/tasks
# ═══════════════════════════════════════════════════

class _Tasks:
    creative = CreativeVideoTask(task_id="c-1", idea="I" * 150)
    manuscript = ManuscriptVideoTask(
        task_id="m-1",
        manuscript_text="M" * 150,
        paragraphs=[ManuscriptParagraph(index=0, text="a"),
                    ManuscriptParagraph(index=1, text="b")],
    )
    anchor = AnchorVideoTask(
        task_id="a-1",
        script_text="S" * 150,
        anchor_prompt="A" * 150,
        paragraphs=[ManuscriptParagraph(index=0, text="x"),
                    ManuscriptParagraph(index=1, text="y"),
                    ManuscriptParagraph(index=2, text="z")],
    )
    simple = SimpleVideoTask(task_id="s-1", prompt="P" * 150, mode=VideoMode.T2V)
    poetry = PoetryVideoTask(task_id="p-1", poem_text="T" * 150)
    image = SimpleImageTask(task_id="i-1", prompt="Q" * 150, size="1024x1024")


class TestListTasks:
    def test_list_all_types_with_fields(self, client, monkeypatch):
        _reset_state(monkeypatch, task_list=[
            {"task_id": "c-1", "status": "pending"},
            {"task_id": "m-1", "status": "pending"},
            {"task_id": "a-1", "status": "pending"},
            {"task_id": "s-1", "status": "pending"},
            {"task_id": "p-1", "status": "pending"},
            {"task_id": "i-1", "status": "pending"},
            {"task_id": "none", "status": "running"},  # load() -> None
        ], states={
            "c-1": _Tasks.creative,
            "m-1": _Tasks.manuscript,
            "a-1": _Tasks.anchor,
            "s-1": _Tasks.simple,
            "p-1": _Tasks.poetry,
            "i-1": _Tasks.image,
        })
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 7
        by_id = {t["task_id"]: t for t in data["tasks"]}
        assert by_id["c-1"]["task_type"] == "creative"
        assert by_id["c-1"]["scene_count"] == 3
        assert by_id["c-1"]["idea"] == "I" * 100
        assert by_id["m-1"]["paragraph_count"] == 2
        assert by_id["m-1"]["manuscript_text"] == "M" * 100
        assert by_id["a-1"]["paragraph_count"] == 3
        assert by_id["a-1"]["script_text"] == "S" * 100
        assert by_id["a-1"]["anchor_prompt"] == "A" * 100
        assert by_id["s-1"]["prompt"] == "P" * 100
        assert by_id["s-1"]["mode"] == "t2v"
        assert by_id["p-1"]["poem_text"] == "T" * 100
        assert by_id["i-1"]["prompt"] == "Q" * 100
        assert by_id["i-1"]["size"] == "1024x1024"
        # 无 state 的任务（load None）不进入字段增强分支
        assert "task_type" not in by_id["none"]
        assert by_id["c-1"]["current_mode"] == "auto"

    def test_list_status_filter_and_manual_awaiting(self, client, monkeypatch):
        poetry = PoetryVideoTask(task_id="p-1", poem_text="hi")
        poetry.status = StepStatus.PENDING
        poetry.manual_config.enabled = True
        poetry.manual_config.current_checkpoint = "story"
        img = SimpleImageTask(task_id="i-1", prompt="q", size="512x512")
        img.status = StepStatus.COMPLETED
        _reset_state(monkeypatch, task_list=[
            {"task_id": "p-1", "status": "pending"},
            {"task_id": "i-1", "status": "completed"},
        ], states={"p-1": poetry, "i-1": img})
        resp = client.get("/api/tasks", params={"status": "pending"})
        data = resp.json()
        assert data["total"] == 1
        assert data["tasks"][0]["task_id"] == "p-1"
        assert data["tasks"][0]["current_mode"] == "manual"
        assert data["tasks"][0]["current_checkpoint"] == "story"
        assert data["tasks"][0]["awaiting_user"] is True

    def test_list_pagination(self, client, monkeypatch):
        _reset_state(monkeypatch, task_list=[
            {"task_id": "x0", "status": "pending"},
            {"task_id": "x1", "status": "pending"},
            {"task_id": "x2", "status": "pending"},
        ], states={})
        resp = client.get("/api/tasks", params={"limit": "2", "offset": "1"})
        data = resp.json()
        assert data["total"] == 3
        assert [t["task_id"] for t in data["tasks"]] == ["x1", "x2"]


# ═══════════════════════════════════════════════════
# task_routes: GET /api/tasks/{task_id}
# ═══════════════════════════════════════════════════

class TestGetTask:
    def test_get_task_not_found(self, client, monkeypatch):
        _reset_state(monkeypatch)
        resp = client.get("/api/tasks/nope")
        assert resp.status_code == 404

    def test_get_task_inactive(self, client, monkeypatch):
        _reset_state(monkeypatch, states={"t1": SimpleVideoTask(task_id="t1")})
        resp = client.get("/api/tasks/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "t1"
        assert data["dir_name"] == "t1"
        assert data["active"] is False

    def test_get_task_active(self, client, monkeypatch):
        _reset_state(monkeypatch, states={"t1": SimpleVideoTask(task_id="t1")})
        app_state.active_pipelines["t1"] = _FakePipeline()
        resp = client.get("/api/tasks/t1")
        assert resp.json()["active"] is True


# ═══════════════════════════════════════════════════
# task_routes: GET /api/tasks/{task_id}/diagnostics
# ═══════════════════════════════════════════════════

def _write_error_logs(monkeypatch, tmp_path, files: dict):
    """把 {filename: content} 写进 tmp error_logs 目录并让端点使用。"""
    log_dir = tmp_path / "error_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (log_dir / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(task_routes, "_find_error_log_dir", lambda: log_dir)


class TestDiagnostics:
    def test_diagnostics_404(self, client, monkeypatch):
        _reset_state(monkeypatch)
        resp = client.get("/api/tasks/nope/diagnostics")
        assert resp.status_code == 404

    def test_diagnostics_exact_match_and_truncation(self, client, monkeypatch, tmp_path):
        _reset_state(monkeypatch, states={"t1": _Tasks.simple})
        _write_error_logs(monkeypatch, tmp_path, {
            "exact.json": (
                '{"task_id": "t1", "model_type": "v", "api_method": "video_submit",'
                ' "error_type": "Timeout", "status_code": 0,'
                ' "error_message": "' + "x" * 1000 + '", "retry_count": 2}'
            ),
            "bad.json": "{ not valid json ",
        })
        resp = client.get("/api/tasks/t1/diagnostics")
        data = resp.json()
        assert data["match_source"] == "exact"
        assert len(data["error_logs"]) == 1
        log = data["error_logs"][0]
        assert len(log["error_message"]) == 800
        assert "task_id" in log and "prompt" not in log

    def test_diagnostics_window_with_end(self, client, monkeypatch, tmp_path):
        st = SimpleVideoTask(task_id="t1")
        st.created_at = "2026-01-01T00:00:00"
        st.updated_at = "2026-01-01T01:00:00"
        _reset_state(monkeypatch, states={"t1": st})
        logs = {
            "in.json": '{"task_id": "other", "timestamp": "2026-01-01T02:00:00"}',
            "before.json": '{"task_id": "o1", "timestamp": "2025-12-31T00:00:00"}',
            "after.json": '{"task_id": "o2", "timestamp": "2026-01-02T00:00:00"}',
            "bad.json": '{"task_id": "o3", "timestamp": "not-a-date"}',
            "empty.json": '{"task_id": "o4", "timestamp": ""}',
        }
        _write_error_logs(monkeypatch, tmp_path, logs)
        resp = client.get("/api/tasks/t1/diagnostics")
        data = resp.json()
        assert data["match_source"] == "window"
        assert any(l["task_id"] == "other" for l in data["error_logs"])

    def test_diagnostics_window_without_end(self, client, monkeypatch, tmp_path):
        st = SimpleVideoTask(task_id="t1")
        st.created_at = "2026-01-01T00:00:00"
        st.updated_at = ""  # end 兜底 = start + 2h
        _reset_state(monkeypatch, states={"t1": st})
        _write_error_logs(monkeypatch, tmp_path, {
            "in.json": '{"task_id": "other", "timestamp": "2026-01-01T01:00:00"}',
        })
        resp = client.get("/api/tasks/t1/diagnostics")
        assert resp.json()["match_source"] == "window"

    def test_diagnostics_none(self, client, monkeypatch, tmp_path):
        _reset_state(monkeypatch, states={"t1": _Tasks.simple})
        # 目录不存在 → _iter_error_logs 返回 []
        log_dir = tmp_path / "missing_logs"
        monkeypatch.setattr(task_routes, "_find_error_log_dir", lambda: log_dir)
        resp = client.get("/api/tasks/t1/diagnostics")
        assert resp.json()["match_source"] == "none"
        assert resp.json()["error_logs"] == []


# ═══════════════════════════════════════════════════
# task_routes: POST /api/tasks/{task_id}/resume
# ═══════════════════════════════════════════════════

class TestResume:
    def test_resume_no_api_key(self, client, monkeypatch):
        _reset_state(monkeypatch)
        monkeypatch.setattr(task_routes, "get_api_key", lambda: "")
        resp = client.post("/api/tasks/t1/resume")
        assert resp.status_code == 400

    def test_resume_already_running(self, client, monkeypatch):
        _reset_state(monkeypatch)
        _patch_runtime(monkeypatch)
        app_state.active_pipelines["t1"] = _FakePipeline(stopped=False)
        resp = client.post("/api/tasks/t1/resume")
        assert resp.status_code == 400
        assert "already running" in resp.json()["detail"]

    def test_resume_not_found(self, client, monkeypatch):
        _reset_state(monkeypatch)
        _patch_runtime(monkeypatch)
        resp = client.post("/api/tasks/t1/resume")
        assert resp.status_code == 404

    def test_resume_already_completed(self, client, monkeypatch):
        st = SimpleVideoTask(task_id="t1", status=StepStatus.COMPLETED)
        _reset_state(monkeypatch, states={"t1": st})
        _patch_runtime(monkeypatch)
        resp = client.post("/api/tasks/t1/resume")
        assert resp.status_code == 400
        assert "already completed" in resp.json()["detail"]

    def test_resume_success(self, client, monkeypatch):
        _reset_state(monkeypatch, states={"t1": _Tasks.simple})
        launched = _patch_runtime(monkeypatch)
        resp = client.post("/api/tasks/t1/resume")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and body["task_id"] == "t1"
        assert len(launched) == 1
        assert "t1" in app_state.active_pipelines

    def test_resume_replaces_stopped(self, client, monkeypatch):
        _reset_state(monkeypatch, states={"t1": _Tasks.simple})
        _patch_runtime(monkeypatch)
        app_state.active_pipelines["t1"] = _FakePipeline(stopped=True)
        resp = client.post("/api/tasks/t1/resume")
        assert resp.status_code == 200
        assert "t1" in app_state.active_pipelines


# ═══════════════════════════════════════════════════
# task_routes: POST /api/tasks/{task_id}/stop
# ═══════════════════════════════════════════════════

class TestStop:
    def test_stop_not_running(self, client, monkeypatch):
        _reset_state(monkeypatch)
        resp = client.post("/api/tasks/t1/stop")
        assert resp.status_code == 400
        assert "not running" in resp.json()["detail"]

    def test_stop_active_running_state(self, client, monkeypatch):
        st = SimpleVideoTask(task_id="t1", status=StepStatus.RUNNING)
        _reset_state(monkeypatch, states={"t1": st})
        pl = _FakePipeline()
        app_state.active_pipelines["t1"] = pl
        resp = client.post("/api/tasks/t1/stop")
        assert resp.status_code == 200
        assert pl.stopped is True
        assert _StubTaskManager.updates[-1]["status"] == StepStatus.PENDING

    def test_stop_queued_still_updates_pending(self, client, monkeypatch):
        st = SimpleVideoTask(task_id="t1", status=StepStatus.QUEUED)
        _reset_state(monkeypatch, states={"t1": st})
        app_state._queued_tasks["t1"] = 1
        resp = client.post("/api/tasks/t1/stop")
        assert resp.status_code == 200
        assert _StubTaskManager.updates[-1]["status"] == StepStatus.PENDING

    def test_stop_active_pending_no_update(self, client, monkeypatch):
        st = SimpleVideoTask(task_id="t1", status=StepStatus.PENDING)
        _reset_state(monkeypatch, states={"t1": st})
        app_state.active_pipelines["t1"] = _FakePipeline()
        resp = client.post("/api/tasks/t1/stop")
        assert resp.status_code == 200
        assert _StubTaskManager.updates == []


# ═══════════════════════════════════════════════════
# task_routes: POST /api/tasks/{task_id}/mode
# ═══════════════════════════════════════════════════

class TestMode:
    def test_mode_invalid(self, client, monkeypatch):
        _reset_state(monkeypatch)
        resp = client.post("/api/tasks/t1/mode", data={"mode": "bogus"})
        assert resp.status_code == 422

    def test_mode_not_found(self, client, monkeypatch):
        _reset_state(monkeypatch)
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        assert resp.status_code == 404

    def test_manual_unsupported_simple(self, client, monkeypatch):
        _reset_state(monkeypatch, states={"t1": _Tasks.simple})
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        assert resp.status_code == 400
        assert "不支持手动模式" in resp.json()["detail"]

    def test_manual_idempotent_paused(self, client, monkeypatch):
        st = CreativeVideoTask(task_id="t1")
        st.status = StepStatus.PENDING
        st.manual_config.enabled = True
        st.manual_config.current_checkpoint = "story"
        _reset_state(monkeypatch, states={"t1": st})
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        body = resp.json()
        assert resp.status_code == 200
        assert body["changed"] is False
        assert body["current_checkpoint"] == "story"

    def test_manual_with_active_pipeline(self, client, monkeypatch):
        st = CreativeVideoTask(task_id="t1")
        _reset_state(monkeypatch, states={"t1": st})
        monkeypatch.setattr(task_routes, "compute_current_checkpoint", lambda s: "story")
        pl = _FakePipeline()
        app_state.active_pipelines["t1"] = pl
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        body = resp.json()
        assert resp.status_code == 200
        assert pl.stopped is True
        assert body["changed"] is True
        assert body["current_checkpoint"] == "story"
        assert st.manual_config.enabled is True
        assert _StubTaskManager.updates and \
            _StubTaskManager.updates[-1]["status"] == StepStatus.PENDING

    def test_manual_with_queued(self, client, monkeypatch):
        st = CreativeVideoTask(task_id="t1")
        _reset_state(monkeypatch, states={"t1": st})
        monkeypatch.setattr(task_routes, "compute_current_checkpoint", lambda s: "story")
        app_state._queued_tasks["t1"] = 3
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        assert resp.status_code == 200
        assert resp.json()["changed"] is True

    def test_manual_not_running(self, client, monkeypatch):
        st = CreativeVideoTask(task_id="t1")
        _reset_state(monkeypatch, states={"t1": st})
        monkeypatch.setattr(task_routes, "compute_current_checkpoint", lambda s: "")
        resp = client.post("/api/tasks/t1/mode", data={"mode": "manual"})
        body = resp.json()
        assert resp.status_code == 200
        assert body["changed"] is True
        assert body["current_checkpoint"] == ""

    def test_auto_not_paused(self, client, monkeypatch):
        st = CreativeVideoTask(task_id="t1")
        _reset_state(monkeypatch, states={"t1": st})
        resp = client.post("/api/tasks/t1/mode", data={"mode": "auto"})
        body = resp.json()
        assert resp.status_code == 200
        assert body["mode"] == "auto"
        assert body["changed"] is True

    def test_auto_paused_resumes(self, client, monkeypatch):
        st = CreativeVideoTask(task_id="t1")
        st.status = StepStatus.PENDING
        st.manual_config.enabled = True
        st.manual_config.current_checkpoint = "story"
        _reset_state(monkeypatch, states={"t1": st})
        launched = _patch_runtime(monkeypatch)
        resp = client.post("/api/tasks/t1/mode", data={"mode": "auto"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert len(launched) == 1


# ═══════════════════════════════════════════════════
# task_routes: POST /api/tasks/sweep
# ═══════════════════════════════════════════════════

class TestSweep:
    def _sweep(self, monkeypatch, fake_return, protect_set_default):
        monkeypatch.setattr(
            artifacts_mod, "sweep_stale_tasks",
            lambda age_days=7, protect_statuses=None: dict(fake_return),
        )
        monkeypatch.setattr(
            artifacts_mod, "_DEFAULT_PROTECT_STATUSES", protect_set_default
        )

    def test_sweep_default(self, client, monkeypatch):
        _reset_state(monkeypatch)
        app_state.active_pipelines["act"] = _FakePipeline()
        app_state._queued_tasks["que"] = 2
        self._sweep(monkeypatch, {
            "swept": ["act", "que", "stale"],
            "protected": ["p1"],
            "errors": [],
        }, {StepStatus.RUNNING})
        resp = client.post("/api/tasks/sweep")
        body = resp.json()
        assert resp.status_code == 200
        assert body["swept"] == ["stale"]  # act/que 被活跃保护过滤
        assert set(body["protected"]) == {"p1", "act", "que"}

    def test_sweep_none_protect(self, client, monkeypatch):
        _reset_state(monkeypatch)
        app_state.active_pipelines["act"] = _FakePipeline()
        self._sweep(monkeypatch, {
            "swept": ["act"], "protected": [], "errors": [],
        }, {StepStatus.RUNNING})
        resp = client.post("/api/tasks/sweep", params={"protect": "none"})
        body = resp.json()
        assert resp.status_code == 200
        assert body["swept"] == []
        assert body["protected"] == ["act"]

    def test_sweep_custom_protect(self, client, monkeypatch):
        _reset_state(monkeypatch)
        self._sweep(monkeypatch, {
            "swept": [], "protected": [], "errors": [],
        }, {StepStatus.RUNNING})
        resp = client.post(
            "/api/tasks/sweep",
            params={"protect": "running,pending", "age_days": "3"},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════
# task_routes: GET /api/concurrency
# ═══════════════════════════════════════════════════

class TestConcurrency:
    def test_concurrency_status(self, client, monkeypatch):
        _reset_state(monkeypatch)
        app_state.active_pipelines["run1"] = _FakePipeline(task_type="creative")
        app_state.active_pipelines["que1"] = _FakePipeline()
        app_state._queued_tasks["que1"] = 2

        class _FakeSem:
            max_weight = 10
            current = 4
            utilization = 0.4

        monkeypatch.setattr(app_state, "get_semaphore", lambda: _FakeSem())
        resp = client.get("/api/concurrency")
        assert resp.status_code == 200
        body = resp.json()
        assert body["max_weight"] == 10
        assert body["current_weight"] == 4
        assert body["utilization"] == 0.4
        assert body["running_count"] == 1
        assert body["queued_count"] == 1
        assert body["queued_tasks"] == [{"task_id": "que1", "weight": 2}]


# ═══════════════════════════════════════════════════
# utility_routes: GET /
# ═══════════════════════════════════════════════════

class TestUtilityRoot:
    def test_root_serves_static(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/html")

    def test_root_fallback_message(self, client, monkeypatch):
        # 仅对根路由场景模拟 index.html 不存在（monkeypatch 自动复原）
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"message": "Agnes Video Generator API"}


# ═══════════════════════════════════════════════════
# utility_routes: POST /api/cleanup-regression
# ═══════════════════════════════════════════════════

_REG_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(utility_routes.__file__), "..", "..")
)


def _manifest(tmp_path, **overrides):
    m = {
        "task_dirs": ["t1", "t2_missing"],
        "uploads": ["up1.txt", "up_missing.txt"],
        "reports": [],
        "server_log": "",
        "scenarios": {"s1": {"done": True}},
    }
    m.update(overrides)
    wd = tmp_path / "wd"
    wd.mkdir(parents=True, exist_ok=True)
    # 任务目录
    (wd / "t1").mkdir()
    (wd / "uploads").mkdir()
    (wd / "uploads" / "up1.txt").write_text("data", encoding="utf-8")
    (wd / "uploads" / "up_missing.txt").write_text("data", encoding="utf-8")
    # 上传清单里只有 up1.txt 存在
    m["uploads"].append("missing_only")
    (wd / ".regression_manifest.json").write_text(
        __import__("json").dumps(m), encoding="utf-8"
    )
    return wd


class TestCleanupRegression:
    def test_cleanup_missing_manifest_404(self, client, monkeypatch, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        monkeypatch.setattr(utility_routes, "get_working_dir", lambda: str(wd))
        resp = client.post("/api/cleanup-regression")
        assert resp.status_code == 404

    def test_cleanup_bad_manifest_500(self, client, monkeypatch, tmp_path):
        wd = tmp_path / "wd"
        wd.mkdir()
        (wd / ".regression_manifest.json").write_text("{oops", encoding="utf-8")
        monkeypatch.setattr(utility_routes, "get_working_dir", lambda: str(wd))
        resp = client.post("/api/cleanup-regression")
        assert resp.status_code == 500
        assert "读取清单失败" in resp.json()["detail"]

    def test_cleanup_success_including_reports_log(self, client, monkeypatch, tmp_path):
        wd = _manifest(
            tmp_path, reports=["docs/rel.md"], server_log="runtime.log",
        )
        monkeypatch.setattr(utility_routes, "get_working_dir", lambda: str(wd))

        orig_isfile = os.path.isfile
        orig_remove = os.remove
        fake_removed = []

        def fake_isfile(p):
            # 项目根下报告/日志视为存在（不真在仓库创建文件）
            if p.startswith(_REG_PROJECT_ROOT + os.sep):
                return True
            return orig_isfile(p)

        def fake_remove(p):
            if p.startswith(_REG_PROJECT_ROOT + os.sep):
                fake_removed.append(p)  # 假装删除，不触碰仓库文件
                return None
            return orig_remove(p)

        monkeypatch.setattr(os.path, "isfile", fake_isfile)
        monkeypatch.setattr(os, "remove", fake_remove)

        resp = client.post("/api/cleanup-regression")
        body = resp.json()
        assert resp.status_code == 200
        assert body["ok"] is True
        assert body["removed_dirs"] == 1  # t1；t2_missing 不存在
        assert body["scenarios_cleaned"] == 1
        assert len(fake_removed) >= 1
        # 清单本身也被删除
        assert not (wd / ".regression_manifest.json").exists()

    def test_cleanup_errors_collected(self, client, monkeypatch, tmp_path):
        wd = _manifest(tmp_path)
        monkeypatch.setattr(utility_routes, "get_working_dir", lambda: str(wd))

        def fake_rmtree(p):
            raise OSError("rmtree boom")

        def fake_remove(p):
            raise OSError("remove boom")

        monkeypatch.setattr(utility_routes.shutil, "rmtree", fake_rmtree)
        monkeypatch.setattr(os, "remove", fake_remove)

        resp = client.post("/api/cleanup-regression")
        body = resp.json()
        assert resp.status_code == 200
        assert body["ok"] is False
        assert body["removed_dirs"] == 0
        assert len(body["errors"]) >= 1

    def test_cleanup_report_and_log_remove_errors(self, client, monkeypatch, tmp_path):
        wd = _manifest(
            tmp_path, reports=["docs/rel.md"], server_log="runtime.log",
        )
        monkeypatch.setattr(utility_routes, "get_working_dir", lambda: str(wd))
        orig_isfile = os.path.isfile

        def fake_isfile(p):
            # 报告/日志在项目根下视为存在，触发删除失败分支
            if p.startswith(_REG_PROJECT_ROOT + os.sep):
                return True
            return orig_isfile(p)

        def fake_remove(p):
            raise OSError("remove boom")

        monkeypatch.setattr(os.path, "isfile", fake_isfile)
        monkeypatch.setattr(os, "remove", fake_remove)

        resp = client.post("/api/cleanup-regression")
        body = resp.json()
        assert resp.status_code == 200
        assert body["ok"] is False
        errors = "\n".join(body["errors"])
        assert "删除报告失败" in errors
        assert "删除日志失败" in errors