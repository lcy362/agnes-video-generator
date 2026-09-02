"""
test_video_routes_coverage.py — web/routes/video_routes.py 分支覆盖测试

仅挂载 video_routes.router 的独立 FastAPI app + TestClient。
所有写路径 / 网络 / 视频渲染全部打桩：
- get_working_dir / safe 路径 → 定向到 tmp_path
- helpers.find_dir_name / TaskManager / app_state 运行中与排队注册表 → 打桩
- core.artifacts 的产物枚举 / 解析 / 级联 / 清单函数 → 返回受控假对象
- core.dependency_graph / web.routes.task_routes.resume_task → 打桩

不触网、不需要真实 API Key、不做任何 moviepy/ffmpeg 渲染。
用法:
    .venv/bin/python -m pytest tests/test_video_routes_coverage.py -v
"""

import json
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.artifacts as artifacts_module
import core.task_manager as task_manager_module
import web.routes.task_routes as task_routes
from core.path_security import UnsafePathError
from models.task import StepStatus
from web import app_state
from web.routes import video_routes

WORKING_DIR = None


# ═════════════════════════════════════════════════════════
# 假对象 / 存储
# ═════════════════════════════════════════════════════════

class _TT:
    def __init__(self, value):
        self.value = value


class _Status:
    def __init__(self, value):
        self.value = value


class _ManualConfig:
    def __init__(self):
        self.enabled = True
        self.current_checkpoint = "scenes"
        self.modified_artifacts = []
        self.approved_checkpoints = []


class FakeState:
    def __init__(self, task_id="t1234567890", task_type="creative", status="completed", manual=True):
        self.task_id = task_id
        self.task_type = _TT(task_type)
        self.status = _Status(status)
        self.manual_config = _ManualConfig() if manual else None
        # 供 approve/regen 的步骤重置分支使用
        self.step_video_generation = StepStatus.COMPLETED


class FakeArtifact:
    def __init__(self, artifact_id="creative:script", step_key="script", label_key="artScript",
                 category="json", scope="task", scope_index=None, file_relpath="script.json",
                 exists=True, size=10, deletable=True, schema_hint="hint"):
        self.artifact_id = artifact_id
        self.step_key = step_key
        self.label_key = label_key
        self.category = category
        self.scope = scope
        self.scope_index = scope_index
        self.file_relpath = file_relpath
        self.exists = exists
        self.size = size
        self.deletable = deletable
        self.schema_hint = schema_hint


class FakePlan:
    def __init__(self, files=None, steps=None):
        self.files_to_delete = files or ["scene_0/video.mp4"]
        self.steps_to_reset = steps or ["step_video_generation"]


class FakeImpact:
    def __init__(self, affected=("creative:video",), steps=("step_video_generation",)):
        self.affected = list(affected)
        self.retained = []
        self.steps_to_reset = list(steps)
        self.affected_checkpoints = []

    def to_dict(self):
        return {
            "affected": self.affected,
            "retained": self.retained,
            "steps_to_reset": self.steps_to_reset,
            "affected_checkpoints": self.affected_checkpoints,
        }


class FakeGraph:
    def __init__(self, plan):
        self.plan = plan

    def compute_impact(self, state, modified, params=None):
        return self.plan


class Store:
    def __init__(self):
        self.states = {}
        self.tasks = []               # TaskManager.list_tasks() 返回值
        self.updates = []
        self.artifact_results = []
        self.resolve_result = None
        self.plan = None
        self.apply_result = {}
        self.graph = FakeGraph(FakeImpact())
        self.ckpt_manifest = {"checkpoints": {}, "files": []}
        self.write_ckpt_called = False
        self.manifest_path = ""
        self.md_path = ""
        self.manifest_data = {"artifacts": [], "files": []}


STORE = Store()


class StubTM:
    def __init__(self, task_id, dir_name=None):
        self.task_id = task_id
        self.dir_name = dir_name or task_id

    @property
    def task_dir(self):
        return os.path.join(WORKING_DIR, self.dir_name)

    def load(self):
        return STORE.states.get(self.task_id)

    def update_state(self, **kwargs):
        STORE.updates.append(kwargs)

    def list_tasks(self):
        return STORE.tasks


# ═════════════════════════════════════════════════════════
# fixture：组装 app + 全量打桩
# ═════════════════════════════════════════════════════════

@pytest.fixture
def env(monkeypatch, tmp_path):
    global WORKING_DIR
    WORKING_DIR = str(tmp_path)
    _reset_store()
    os.makedirs(WORKING_DIR, exist_ok=True)

    app = FastAPI()
    app.include_router(video_routes.router)
    client = TestClient(app)

    # 路径 / 任务存储
    monkeypatch.setattr(video_routes, "get_working_dir", lambda: WORKING_DIR)
    monkeypatch.setattr(video_routes.helpers, "find_dir_name", lambda tid: tid)
    monkeypatch.setattr(video_routes, "TaskManager", StubTM)
    monkeypatch.setattr(task_manager_module, "TaskManager", StubTM)

    # core.artifacts 产物函数（top-level 导入，patch 到 video_routes）
    monkeypatch.setattr(video_routes, "list_artifacts",
                        lambda state, task_dir: STORE.artifact_results)
    monkeypatch.setattr(video_routes, "resolve_artifact",
                        lambda aid, state, task_dir: STORE.resolve_result)
    monkeypatch.setattr(video_routes, "get_cascade_plan",
                        lambda aid, state, task_dir: STORE.plan)
    monkeypatch.setattr(video_routes, "apply_cascade_plan",
                        lambda state, plan: STORE.apply_result)
    monkeypatch.setattr(video_routes, "build_checkpoint_manifest",
                        lambda state, task_dir: STORE.ckpt_manifest)

    def _fake_write_ckpt(state, task_dir):
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "checkpoint.json"), "w", encoding="utf-8") as f:
            json.dump(STORE.ckpt_manifest, f)
        STORE.write_ckpt_called = True
        return os.path.join(task_dir, "checkpoint.json")

    monkeypatch.setattr(video_routes, "write_checkpoint_manifest", _fake_write_ckpt)

    # core.artifacts 懒加载函数（get_task_manifest / md），patch 源头模块
    monkeypatch.setattr(artifacts_module, "write_manifest",
                        lambda state, task_dir: STORE.manifest_path)
    monkeypatch.setattr(artifacts_module, "build_manifest",
                        lambda state, task_dir: STORE.manifest_data)
    monkeypatch.setattr(artifacts_module, "write_manifest_md",
                        lambda state, task_dir: STORE.md_path)

    # 依赖图 + resume
    monkeypatch.setattr(video_routes, "get_dependency_graph", lambda tt: STORE.graph)

    async def _fake_resume(tid):
        return {"ok": True, "task_id": tid, "resumed": True}

    monkeypatch.setattr(task_routes, "resume_task", _fake_resume)

    return client


def _reset_store():
    STORE.states = {}
    STORE.tasks = []
    STORE.updates = []
    STORE.artifact_results = []
    STORE.resolve_result = None
    STORE.plan = None
    STORE.apply_result = {}
    STORE.graph = FakeGraph(FakeImpact())
    STORE.ckpt_manifest = {"checkpoints": {}, "files": []}
    STORE.write_ckpt_called = False
    STORE.manifest_path = ""
    STORE.md_path = ""
    STORE.manifest_data = {"artifacts": [], "files": []}


def _register(task_id, task_type="creative", status="completed", manual=True):
    st = FakeState(task_id=task_id, task_type=task_type, status=status, manual=manual)
    STORE.states[task_id] = st
    os.makedirs(os.path.join(WORKING_DIR, task_id), exist_ok=True)
    return st


def _running_pipeline(task_id):
    """注入一个运行中 pipeline（_stop_event 未置位）到 app_state。"""
    app_state.active_pipelines[task_id] = SimpleNamespace(_stop_event=threading.Event())


def _stop_running(task_id):
    app_state.active_pipelines.pop(task_id, None)
    app_state._queued_tasks.pop(task_id, None)


# ═════════════════════════════════════════════════════════
# 1. GET /api/video/{task_id}
# ═════════════════════════════════════════════════════════

class TestServeVideo:
    def test_serve_video_success(self, env, tmp_path):
        _register("t1234567890")
        with open(os.path.join(WORKING_DIR, "t1234567890", "final_video.mp4"), "wb") as f:
            f.write(b"MP4DATA")
        r = env.get("/api/video/t1234567890")
        assert r.status_code == 200
        assert r.headers["content-type"] == "video/mp4"
        assert r.content == b"MP4DATA"

    def test_serve_video_unsafe_path_404(self, env, monkeypatch):
        # find_dir_name 返回逃逸路径 → safe_join 抛 UnsafePathError
        monkeypatch.setattr(video_routes.helpers, "find_dir_name", lambda tid: "../evil")
        r = env.get("/api/video/t1234567890")
        assert r.status_code == 404

    def test_serve_video_missing_file_404(self, env):
        _register("t1234567890")  # 无 final_video.mp4
        r = env.get("/api/video/t1234567890")
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════
# 2. GET /api/tasks/{task_id}/artifacts
# ═════════════════════════════════════════════════════════

class TestListTaskArtifacts:
    def test_list_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/artifacts")
        assert r.status_code == 404

    def test_list_success(self, env):
        _register("t1234567890")
        STORE.artifact_results = [
            FakeArtifact(artifact_id="creative:script", file_relpath="script.json"),
            FakeArtifact(artifact_id="creative:video:0", scope="scene", scope_index=0,
                         file_relpath="scene_0/video.mp4", category="video"),
        ]
        r = env.get("/api/tasks/t1234567890/artifacts")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["task_type"] == "creative"
        assert data["task_status"] == "completed"
        assert len(data["artifacts"]) == 2
        a = data["artifacts"][0]
        assert a["artifact_id"] == "creative:script"
        assert a["preview_url"] == "/api/tasks/t1234567890/artifacts/creative:script/file"

    def test_list_status_none_uses_pending(self, env):
        _register("t1234567890", status="pending")
        STORE.states["t1234567890"].status = None
        STORE.artifact_results = []
        r = env.get("/api/tasks/t1234567890/artifacts")
        assert r.json()["task_status"] == "pending"


# ═════════════════════════════════════════════════════════
# 3. GET /api/tasks/{task_id}/artifacts/{artifact_id}/file
# ═════════════════════════════════════════════════════════

class TestServeArtifactFile:
    def test_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/artifacts/x/file")
        assert r.status_code == 404

    def test_artifact_not_found_404(self, env):
        _register("t1234567890")
        STORE.resolve_result = None
        r = env.get("/api/tasks/t1234567890/artifacts/nope/file")
        assert r.status_code == 404

    def test_artifact_file_missing_404(self, env):
        _register("t1234567890")
        STORE.resolve_result = FakeArtifact(file_relpath="script.json", exists=False)
        r = env.get("/api/tasks/t1234567890/artifacts/creative:script/file")
        assert r.status_code == 404

    def test_path_traversal_forbidden_403(self, env):
        _register("t1234567890")
        STORE.resolve_result = FakeArtifact(file_relpath="../../evil.txt", exists=True)
        r = env.get("/api/tasks/t1234567890/artifacts/creative:script/file")
        assert r.status_code == 403

    def test_serve_success_json_media_type(self, env):
        _register("t1234567890")
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        with open(os.path.join(task_dir, "script.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        STORE.resolve_result = FakeArtifact(file_relpath="script.json", category="json", exists=True)
        r = env.get("/api/tasks/t1234567890/artifacts/creative:script/file")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]

    def test_serve_unknown_category_octet_stream(self, env):
        _register("t1234567890")
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        with open(os.path.join(task_dir, "odd.bin"), "wb") as f:
            f.write(b"x")
        STORE.resolve_result = FakeArtifact(file_relpath="odd.bin", category="weird", exists=True)
        r = env.get("/api/tasks/t1234567890/artifacts/creative:weird/file")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"


# ═════════════════════════════════════════════════════════
# 4. GET /api/tasks/{task_id}/manifest 与 manifest.md
# ═════════════════════════════════════════════════════════

class TestGetTaskManifest:
    def test_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/manifest")
        assert r.status_code == 404

    def test_existing_manifest_read(self, env):
        _register("t1234567890")
        path = os.path.join(WORKING_DIR, "t1234567890", "manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ok": "cached", "artifact_count": 1}, f)
        r = env.get("/api/tasks/t1234567890/manifest")
        assert r.status_code == 200
        assert r.json()["artifact_count"] == 1

    def test_manifest_missing_write_then_rebuild(self, env):
        # manifest.json 不存在 → write_manifest 被调用（138），随后 open 失败 OSError
        # → build_manifest 重建（142/144）
        _register("t1234567890")
        STORE.manifest_path = os.path.join(WORKING_DIR, "t1234567890", "manifest.json")
        # 不创建文件：stub 的 write_manifest 不落盘
        STORE.manifest_data = {"rebuilt": True, "artifacts": [], "files": []}
        r = env.get("/api/tasks/t1234567890/manifest")
        assert r.status_code == 200
        assert r.json()["rebuilt"] is True

    def test_manifest_corrupt_rebuilds(self, env, monkeypatch):
        _register("t1234567890")
        path = os.path.join(WORKING_DIR, "t1234567890", "manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt json")
        STORE.manifest_data = {"rebuilt": True}
        r = env.get("/api/tasks/t1234567890/manifest")
        assert r.status_code == 200
        assert r.json()["rebuilt"] is True


class TestGetTaskManifestMd:
    def test_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/manifest.md")
        assert r.status_code == 404

    def test_success(self, env):
        _register("t1234567890")
        md = os.path.join(WORKING_DIR, "t1234567890", "MANIFEST.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write("# readme")
        r = env.get("/api/tasks/t1234567890/manifest.md")
        assert r.status_code == 200
        assert r.content == b"# readme"

    def test_md_written_when_missing(self, env):
        _register("t1234567890")  # MANIFEST.md 缺失 → write_manifest_md
        STORE.md_path = os.path.join(WORKING_DIR, "t1234567890", "MANIFEST.md")
        with open(STORE.md_path, "w", encoding="utf-8") as f:
            f.write("# generated")
        r = env.get("/api/tasks/t1234567890/manifest.md")
        assert r.status_code == 200
        assert r.content == b"# generated"

    def test_md_still_missing_404(self, env):
        _register("t1234567890")
        STORE.md_path = ""  # write_manifest_md 未能落盘
        r = env.get("/api/tasks/t1234567890/manifest.md")
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════
# 5. /api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview
# ═════════════════════════════════════════════════════════

class TestPreviewCascade:
    def test_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/artifacts/x/cascade-preview")
        assert r.status_code == 404

    def test_artifact_not_found_404(self, env):
        _register("t1234567890")
        STORE.resolve_result = None
        r = env.get("/api/tasks/t1234567890/artifacts/nope/cascade-preview")
        assert r.status_code == 404

    def test_no_plan_400(self, env):
        _register("t1234567890")
        STORE.resolve_result = FakeArtifact()
        STORE.plan = None
        r = env.get("/api/tasks/t1234567890/artifacts/a/cascade-preview")
        assert r.status_code == 400

    def test_success_filters_existing_files(self, env):
        _register("t1234567890")
        os.makedirs(os.path.join(WORKING_DIR, "t1234567890", "scene_0"), exist_ok=True)
        with open(os.path.join(WORKING_DIR, "t1234567890", "scene_0", "video.mp4"), "wb") as f:
            f.write(b"v")
        STORE.resolve_result = FakeArtifact()
        STORE.plan = FakePlan(files=["scene_0/video.mp4", "scene_0/missing.mp4"],
                             steps=["step_video_generation"])
        r = env.get("/api/tasks/t1234567890/artifacts/a/cascade-preview")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["files_to_delete"] == ["scene_0/video.mp4"]
        assert body["steps_to_reset"] == ["step_video_generation"]


# ═════════════════════════════════════════════════════════
# 6. DELETE /api/tasks/{task_id}/artifacts/{artifact_id}
# ═════════════════════════════════════════════════════════

class TestDeleteArtifact:
    def test_running_409(self, env):
        _running_pipeline("t1234567890")
        try:
            r = env.delete("/api/tasks/t1234567890/artifacts/a")
            assert r.status_code == 409
        finally:
            _stop_running("t1234567890")

    def test_missing_task_404(self, env):
        r = env.delete("/api/tasks/t999/artifacts/a")
        assert r.status_code == 404

    def test_artifact_not_found_404(self, env):
        _register("t1234567890")
        STORE.resolve_result = None
        r = env.delete("/api/tasks/t1234567890/artifacts/a")
        assert r.status_code == 404

    def test_no_plan_400(self, env):
        _register("t1234567890")
        STORE.resolve_result = FakeArtifact()
        STORE.plan = None
        r = env.delete("/api/tasks/t1234567890/artifacts/a")
        assert r.status_code == 400

    def test_success_deletes_files(self, env, monkeypatch):
        _register("t1234567890")
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        f = os.path.join(task_dir, "video.mp4")
        with open(f, "wb") as fh:
            fh.write(b"v")
        STORE.resolve_result = FakeArtifact()
        STORE.plan = FakePlan(files=["video.mp4"])
        STORE.apply_result = {"status": StepStatus.PENDING, "step_video_generation": StepStatus.PENDING}

        r = env.delete("/api/tasks/t1234567890/artifacts/creative:video")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["deleted_files"] == ["video.mp4"]
        assert body["reset_steps"] == ["step_video_generation"]
        assert body["task_status"] == "completed"
        assert not os.path.exists(f)
        assert STORE.updates and STORE.updates[-1]["status"].value == "pending"

    def test_skips_out_of_dir_paths_and_oserror(self, env, monkeypatch):
        _register("t1234567890")
        # 真实存在的文件 + os.remove 抛 OSError → 进入 except 分支（235-236）
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        real_file = os.path.join(task_dir, "scene_0", "video.mp4")
        os.makedirs(os.path.dirname(real_file), exist_ok=True)
        with open(real_file, "wb") as fh:
            fh.write(b"v")
        STORE.resolve_result = FakeArtifact(file_relpath="scene_0/video.mp4", exists=True)
        STORE.plan = FakePlan(files=["../../evil", "scene_0/video.mp4"])  # 含逃逸路径
        STORE.apply_result = {}
        monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(OSError("denied")))
        r = env.delete("/api/tasks/t1234567890/artifacts/a")
        assert r.status_code == 200
        assert r.json()["deleted_files"] == []


# ═════════════════════════════════════════════════════════
# 7. DELETE /api/tasks/{task_id}
# ═════════════════════════════════════════════════════════

class TestDeleteTask:
    def test_running_400(self, env):
        _running_pipeline("t1234567890")
        try:
            r = env.delete("/api/tasks/t1234567890")
            assert r.status_code == 400
        finally:
            _stop_running("t1234567890")

    def test_queued_400(self, env):
        app_state._queued_tasks["t1234567890"] = 1
        try:
            r = env.delete("/api/tasks/t1234567890")
            assert r.status_code == 400
            assert "queued" in r.json()["detail"].lower()
        finally:
            _stop_running("t1234567890")

    def test_running_none_pipeline_no_stop(self, env):
        # active_pipelines 中 value 为 None（pipeline is not None 分支为 False）
        app_state.active_pipelines["t1234567890"] = None
        _register("t1234567890")
        try:
            r = env.delete("/api/tasks/t1234567890")
            assert r.status_code == 200
        finally:
            _stop_running("t1234567890")

    def test_success_removes_dir(self, env):
        _register("t1234567890")
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        assert os.path.isdir(task_dir)
        r = env.delete("/api/tasks/t1234567890")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["removed_dir"] is True
        assert not os.path.exists(task_dir)

    def test_unsafe_dir_skipped_but_task_exists(self, env, monkeypatch):
        # 目录逃逸工作区 → 跳过删除；但 _task_exists 为 True → 200 removed_dir=False
        monkeypatch.setattr(video_routes.helpers, "find_dir_name", lambda tid: "../evil")
        STORE.tasks = [{"task_id": "t1234567890", "dir_name": "t1234567890"}]
        r = env.delete("/api/tasks/t1234567890")
        assert r.status_code == 200
        assert r.json()["removed_dir"] is False

    def test_task_not_found_404(self, env):
        # dir 不存在 且 不在任务列表 → 404
        STORE.tasks = []
        r = env.delete("/api/tasks/ghost")
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════
# 8. 检查点：list / get
# ═════════════════════════════════════════════════════════

class TestCheckpoints:
    def test_list_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/checkpoints")
        assert r.status_code == 404

    def test_list_success(self, env):
        _register("t1234567890")
        STORE.ckpt_manifest = {
            "checkpoints": {"videos": {"artifacts": [], "status": "completed"}},
            "files": [],
        }
        r = env.get("/api/tasks/t1234567890/checkpoints")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["current_checkpoint"] == "scenes"
        assert "videos" in body["checkpoints"]

    def test_list_without_manual_config(self, env):
        _register("t1234567890", manual=False)
        STORE.ckpt_manifest = {"checkpoints": {}, "files": []}
        r = env.get("/api/tasks/t1234567890/checkpoints")
        assert r.json()["current_checkpoint"] == ""

    def test_list_corrupt_ckpt_rebuilds(self, env):
        # checkpoint.json 已存在但损坏 → ValueError → 现场 build（339-340）
        _register("t1234567890")
        path = os.path.join(WORKING_DIR, "t1234567890", "checkpoint.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        STORE.ckpt_manifest = {"checkpoints": {"videos": {"artifacts": [], "status": "completed"}}, "files": []}
        r = env.get("/api/tasks/t1234567890/checkpoints")
        assert r.status_code == 200
        assert "videos" in r.json()["checkpoints"]

    def test_get_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/checkpoints/videos")
        assert r.status_code == 404

    def test_get_checkpoint_not_found_404(self, env):
        _register("t1234567890")
        STORE.ckpt_manifest = {"checkpoints": {"videos": {"artifacts": []}}, "files": []}
        r = env.get("/api/tasks/t1234567890/checkpoints/audio")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_get_checkpoint_success_adds_abs_path(self, env):
        _register("t1234567890")
        STORE.ckpt_manifest = {
            "checkpoints": {"videos": {"artifacts": [
                {"artifact_id": "creative:video", "path": "scene_0/video.mp4"}]}},
            "files": [],
        }
        r = env.get("/api/tasks/t1234567890/checkpoints/videos")
        assert r.status_code == 200
        body = r.json()
        assert body["checkpoint"] == "videos"
        assert body["working_dir"] == os.path.join(WORKING_DIR, "t1234567890")
        assert body["artifacts"][0]["abs_path"].endswith("scene_0/video.mp4")


# ═════════════════════════════════════════════════════════
# 9. GET checkpoints/{checkpoint}/impact
# ═════════════════════════════════════════════════════════

class TestCheckpointImpact:
    def test_missing_task_404(self, env):
        r = env.get("/api/tasks/t999/checkpoints/videos/impact")
        assert r.status_code == 404

    def test_bad_modified_json_422(self, env):
        _register("t1234567890")
        r = env.get("/api/tasks/t1234567890/checkpoints/videos/impact",
                    params={"modified_artifact_ids": "{oops"})
        assert r.status_code == 422

    def test_bad_params_json_422(self, env):
        _register("t1234567890")
        r = env.get("/api/tasks/t1234567890/checkpoints/videos/impact",
                    params={"param_updates": "{oops"})
        assert r.status_code == 422

    def test_modified_not_list_422(self, env):
        _register("t1234567890")
        r = env.get("/api/tasks/t1234567890/checkpoints/videos/impact",
                    params={"modified_artifact_ids": json.dumps("notalist")})
        assert r.status_code == 422

    def test_success(self, env):
        _register("t1234567890")
        STORE.graph = FakeGraph(FakeImpact(affected=["creative:video"], steps=["step_video_generation"]))
        r = env.get("/api/tasks/t1234567890/checkpoints/videos/impact",
                    params={"modified_artifact_ids": json.dumps(["creative:video"])})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["affected"] == ["creative:video"]


# ═════════════════════════════════════════════════════════
# 10. POST upload artifact
# ═════════════════════════════════════════════════════════

class TestUploadArtifact:
    def test_running_409(self, env):
        _running_pipeline("t1234567890")
        try:
            r = env.post("/api/tasks/t1234567890/artifacts/a/upload",
                         files={"file": ("up.txt", b"hi")})
            assert r.status_code == 409
        finally:
            _stop_running("t1234567890")

    def test_missing_task_404(self, env):
        r = env.post("/api/tasks/t999/artifacts/a/upload",
                     files={"file": ("up.txt", b"hi")})
        assert r.status_code == 404

    def test_artifact_not_found_404(self, env):
        _register("t1234567890")
        STORE.resolve_result = None
        r = env.post("/api/tasks/t1234567890/artifacts/a/upload",
                     files={"file": ("up.txt", b"hi")})
        assert r.status_code == 404

    def test_not_deletable_400(self, env):
        _register("t1234567890")
        STORE.resolve_result = FakeArtifact(file_relpath="story.txt", deletable=False)
        r = env.post("/api/tasks/t1234567890/artifacts/a/upload",
                     files={"file": ("up.txt", b"hi")})
        assert r.status_code == 400

    def test_path_traversal_403(self, env):
        _register("t1234567890")
        STORE.resolve_result = FakeArtifact(file_relpath="../../evil.txt", deletable=True)
        r = env.post("/api/tasks/t1234567890/artifacts/a/upload",
                     files={"file": ("up.txt", b"hi")})
        assert r.status_code == 403

    def test_success_with_manual_config(self, env):
        st = _register("t1234567890")
        STORE.resolve_result = FakeArtifact(file_relpath="story.txt", deletable=True)
        r = env.post("/api/tasks/t1234567890/artifacts/creative:story/upload",
                     files={"file": ("story.txt", b"hello-content")})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["size"] == 13
        target = os.path.join(WORKING_DIR, "t1234567890", "story.txt")
        assert os.path.exists(target)
        assert STORE.write_ckpt_called
        assert "creative:story" in st.manual_config.modified_artifacts

    def test_success_without_manual_config(self, env):
        _register("t1234567890", manual=False)
        STORE.resolve_result = FakeArtifact(file_relpath="story.txt", deletable=True)
        r = env.post("/api/tasks/t1234567890/artifacts/creative:story/upload",
                     files={"file": ("story.txt", b"abc")})
        assert r.status_code == 200
        assert r.json()["size"] == 3


# ═════════════════════════════════════════════════════════
# 11. POST approve checkpoint
# ═════════════════════════════════════════════════════════

class TestApproveCheckpoint:
    def test_missing_task_404(self, env):
        r = env.post("/api/tasks/t999/checkpoints/videos/approve")
        assert r.status_code == 404

    def test_bad_modified_json_422(self, env):
        _register("t1234567890")
        r = env.post("/api/tasks/t1234567890/checkpoints/videos/approve",
                     data={"modified_artifact_ids": "{oops"})
        assert r.status_code == 422

    def test_bad_params_json_422(self, env):
        _register("t1234567890")
        r = env.post("/api/tasks/t1234567890/checkpoints/videos/approve",
                     data={"param_updates": "{oops"})
        assert r.status_code == 422

    def test_preview_not_confirmed(self, env):
        _register("t1234567890")
        STORE.graph = FakeGraph(FakeImpact(affected=["creative:video"], steps=["step_video_generation"]))
        r = env.post("/api/tasks/t1234567890/checkpoints/videos/approve",
                     data={"modified_artifact_ids": json.dumps(["creative:video"])})
        assert r.status_code == 200
        body = r.json()
        assert body["confirmed"] is False
        assert body["affected"] == ["creative:video"]

    def test_confirm_full_flow(self, env):
        st = _register("t1234567890")
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        video = os.path.join(task_dir, "video.mp4")
        with open(video, "wb") as fh:
            fh.write(b"v")
        STORE.resolve_result = FakeArtifact(file_relpath="video.mp4", deletable=True, exists=True)
        STORE.graph = FakeGraph(FakeImpact(affected=["creative:video"], steps=["step_video_generation"]))

        r = env.post("/api/tasks/t1234567890/checkpoints/videos/approve",
                     data={"modified_artifact_ids": json.dumps(["creative:video"]), "confirmed": "true"})
        assert r.status_code == 200
        assert r.json()["resumed"] is True
        # 文件被删除
        assert not os.path.exists(video)
        # 状态被重置为 PENDING
        assert st.status.value == "pending"
        # manual_config 更新
        assert "videos" in st.manual_config.approved_checkpoints
        assert st.manual_config.current_checkpoint == ""
        assert STORE.write_ckpt_called
        assert any(up.get("status") == StepStatus.PENDING for up in STORE.updates)

    def test_confirm_delete_oserror(self, env, monkeypatch):
        st = _register("t1234567890")
        task_dir = os.path.join(WORKING_DIR, "t1234567890")
        video = os.path.join(task_dir, "video.mp4")
        with open(video, "wb") as fh:
            fh.write(b"v")
        STORE.resolve_result = FakeArtifact(file_relpath="video.mp4", deletable=True, exists=True)
        STORE.graph = FakeGraph(FakeImpact(affected=["creative:video"], steps=["step_video_generation"]))
        monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(OSError("denied")))
        r = env.post("/api/tasks/t1234567890/checkpoints/videos/approve",
                     data={"confirmed": "true"})
        assert r.status_code == 200
        assert st.status.value == "pending"

    def test_confirm_without_manual_config(self, env):
        _register("t1234567890", manual=False)
        STORE.resolve_result = None
        STORE.graph = FakeGraph(FakeImpact(affected=["creative:video"], steps=["step_video_generation"]))
        r = env.post("/api/tasks/t1234567890/checkpoints/videos/approve",
                     data={"confirmed": "true"})
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════
# 12. POST regen checkpoint
# ═════════════════════════════════════════════════════════

class TestRegenCheckpoint:
    def test_missing_task_404(self, env):
        r = env.post("/api/tasks/t999/checkpoints/videos/regen")
        assert r.status_code == 404

    def test_checkpoint_not_found_404(self, env):
        _register("t1234567890")
        STORE.ckpt_manifest = {"checkpoints": {"videos": {"artifacts": []}}, "files": []}
        r = env.post("/api/tasks/t1234567890/checkpoints/audio/regen")
        assert r.status_code == 404

    def test_success_delegates_to_approve(self, env):
        st = _register("t1234567890")
        STORE.ckpt_manifest = {
            "checkpoints": {"videos": {"artifacts": [
                {"artifact_id": "creative:video", "path": "scene_0/video.mp4"}]}},
            "files": [],
        }
        # 提供受影响产物文件供 approve 删除
        STORE.resolve_result = FakeArtifact(file_relpath="scene_0/video.mp4", exists=True)
        STORE.graph = FakeGraph(FakeImpact(affected=["creative:video"], steps=["step_video_generation"]))
        r = env.post("/api/tasks/t1234567890/checkpoints/videos/regen")
        assert r.status_code == 200
        assert r.json()["resumed"] is True
        assert st.status.value == "pending"