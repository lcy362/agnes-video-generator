"""
test_ai_modify.py — 手动模式「通道 1：AI 帮我改」端点（ai-modify）测试

仅挂载 video_routes.router + TestClient，不触网：
- helpers.find_dir_name / TaskManager / resolve_artifact / get_api_key → 打桩
- AgnesChatAPI / AgnesImageAPI → 假实现
- 真实读写任务目录下的产物文件（体验路径安全 + 文件存在性守卫）

用法:
    .venv/bin/python -m pytest tests/test_ai_modify.py -v
"""

import base64
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api.agnes_image import ImageOutput
from web import app_state
from web.routes import video_routes

WORKING_DIR = None
TASK_ID = "t1234567890"


class StubTM:
    def __init__(self, task_id, dir_name=None):
        self.task_id = task_id
        self.dir_name = dir_name or task_id

    @property
    def task_dir(self):
        return os.path.join(WORKING_DIR, self.dir_name)

    def load(self):
        return SimpleNamespace(task_id=self.task_id, ui_language="zh")


class FakeArtifact:
    def __init__(self, rel, category="json", deletable=True):
        self.file_relpath = rel
        self.category = category
        self.deletable = deletable


class FakeChat:
    def __init__(self, **kwargs):
        pass

    def chat(self, system_prompt, user_prompt, max_tokens=4096):
        return "改写后的旁白文本"

    def chat_json(self, system_prompt, user_prompt, max_tokens=4096):
        return {"title": "新标题", "scenes": [{"prompt": "更电影感"}]}

    def chat_multimodal(self, system_prompt, text_prompt, image_paths, max_tokens=4096):
        return "把画面调得更明亮，强化电影感"


class FakeImage:
    def __init__(self, **kwargs):
        pass

    async def generate_single_image(self, prompt, reference_image_paths=[], size=None, **kwargs):
        b64 = base64.b64encode(b"\x89PNG-fake-image")
        return ImageOutput(fmt="b64", ext="png", data=b64.decode("utf-8"))


class _Stop:
    def is_set(self):
        return False


class _Pipe:
    def __init__(self):
        self._stop_event = _Stop()


@pytest.fixture
def env(monkeypatch, tmp_path):
    global WORKING_DIR
    WORKING_DIR = str(tmp_path)
    os.makedirs(os.path.join(WORKING_DIR, TASK_ID), exist_ok=True)

    app = FastAPI()
    app.include_router(video_routes.router)
    client = TestClient(app)

    resolved = {}

    monkeypatch.setattr(video_routes.helpers, "find_dir_name", lambda tid: tid)
    monkeypatch.setattr(video_routes, "TaskManager", StubTM)
    monkeypatch.setattr(video_routes, "get_api_key", lambda: "sk-test")

    def _resolve(aid, state, task_dir):
        return resolved.get(aid)

    monkeypatch.setattr(video_routes, "resolve_artifact", _resolve)

    # v7.0：ai_modify 改用文本供应商工厂构造聊天客户端（可接入自定义供应商），
    # 测试相应改为 patch 工厂而非削除的 AgnesChatAPI 模块属性。
    monkeypatch.setattr(video_routes, "get_or_build_text_chat_client", lambda **kw: FakeChat())
    monkeypatch.setattr(video_routes, "AgnesImageAPI", lambda **kw: FakeImage())

    return client, resolved


def _make_file(rel: str, content: bytes = b"", task_id: str = TASK_ID) -> str:
    p = os.path.join(WORKING_DIR, task_id, rel)
    os.makedirs(os.path.dirname(p) or p, exist_ok=True)
    with open(p, "wb") as f:
        f.write(content)
    return rel


def _url(checkpoint="scenes"):
    return f"/api/tasks/{TASK_ID}/checkpoints/{checkpoint}/ai-modify"


def _post(client, artifact_id, user_request="让第2段更口语化"):
    return client.post(_url(), data={"artifact_id": artifact_id, "user_request": user_request})


# ═════════════ 文本产物 ═════════════

def test_json_success_returns_rewritten_and_does_not_persist(env):
    client, resolved = env
    original = json.dumps({"title": "旧标题", "scenes": []}, ensure_ascii=False)
    rel = _make_file("script.json", original.encode("utf-8"))
    resolved["script"] = FakeArtifact(rel, category="json")

    resp = _post(client, "script")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["category"] == "json"
    parsed = json.loads(body["new_content"])
    assert parsed["title"] == "新标题"
    assert body["diff_summary"]
    # 未落盘：原文件保持不变
    with open(os.path.join(WORKING_DIR, TASK_ID, rel), encoding="utf-8") as f:
        assert f.read() == original


def test_text_success(env):
    client, resolved = env
    rel = _make_file("narration.txt", "旧旁白".encode("utf-8"))
    resolved["narration_txt"] = FakeArtifact(rel, category="text")

    resp = _post(client, "narration_txt")
    assert resp.status_code == 200
    assert resp.json()["new_content"] == "改写后的旁白文本"


def test_empty_user_request_422(env):
    client, _ = env
    resp = _post(client, "script", user_request="   ")
    assert resp.status_code == 422


# ═════════════ 图片产物 ═════════════

def test_image_success_returns_data_url(env):
    client, resolved = env
    rel = _make_file("character_reference.png", b"\x89PNG-bin")
    resolved["character_reference.png"] = FakeArtifact(rel, category="image")

    resp = _post(client, "character_reference.png")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "image"
    assert body["new_content"].startswith("data:image/png;base64,")
    assert body["diff_summary"]


# ═════════════ 不支持产物 / 守卫 ═════════════

def test_unsupported_category_400(env):
    client, resolved = env
    rel = _make_file("final_video.mp4", b"mp4")
    resolved["final_video"] = FakeArtifact(rel, category="video")

    resp = _post(client, "final_video")
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]


def test_missing_api_key_400(env, monkeypatch):
    client, resolved = env
    _make_file("script.json", b"{}")
    resolved["script"] = FakeArtifact("script.json", category="json")
    monkeypatch.setattr(video_routes, "get_api_key", lambda: "")
    resp = _post(client, "script")
    assert resp.status_code == 400


def test_artifact_not_found_404(env):
    client, _ = env
    resp = _post(client, "no_such_artifact")
    assert resp.status_code == 404


def test_not_editable_400(env):
    client, resolved = env
    rel = _make_file("script.json", b"{}")
    resolved["script"] = FakeArtifact(rel, category="json", deletable=False)
    resp = _post(client, "script")
    assert resp.status_code == 400


def test_artifact_file_missing_404(env):
    client, resolved = env
    rel = "script.json"  # 不创建文件
    resolved["script"] = FakeArtifact(rel, category="json")
    resp = _post(client, "script")
    assert resp.status_code == 404


def test_path_traversal_403(env):
    client, resolved = env
    resolved["evil"] = FakeArtifact("../evil.txt", category="text")
    resp = _post(client, "evil")
    assert resp.status_code == 403


def test_running_task_409(env):
    client, _ = env
    app_state.active_pipelines[TASK_ID] = _Pipe()
    try:
        resp = _post(client, "script")
        assert resp.status_code == 409
    finally:
        app_state.active_pipelines.pop(TASK_ID, None)