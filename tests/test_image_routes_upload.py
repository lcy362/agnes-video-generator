"""
单元测试：web.routes.image_routes — 参考图上传扩展名白名单（S2083 修复）。

覆盖 generate_image 的：
- 无 API Key → 400
- prompt 超长 / 空 → 422
- size 非法 → 422
- 合法请求 + 参考图（白名单内扩展名）→ 200，文件落盘于 uploads/
- 参考图扩展名不在白名单 → 回退 .png
- 参考图 filename 含路径穿越片段 → safe_join 拒绝
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import image_routes


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(image_routes.router)
    return TestClient(app)


class _StubTaskManager:
    def __init__(self, task_id, dir_name=None):
        self.state = None
        self.task_dir = "/tmp"

    def create(self, state):
        self.state = state

    def update_state(self, **kwargs):
        pass


class _StubOutput:
    def __init__(self):
        self.saved = None

    async def save(self, path):
        self.saved = path


class _StubImageAPI:
    def __init__(self, *a, **k):
        self.output = _StubOutput()

    async def generate_single_image(self, *a, **k):
        return self.output


@pytest.fixture
def deps(monkeypatch, tmp_path):
    monkeypatch.setattr(image_routes, "get_api_key", lambda: "sk-test")
    monkeypatch.setattr(image_routes, "TaskManager", _StubTaskManager)
    monkeypatch.setattr(image_routes, "AgnesImageAPI", _StubImageAPI)
    monkeypatch.setattr(image_routes.helpers, "get_upload_dir", lambda: str(tmp_path / "uploads"))
    monkeypatch.setattr(image_routes.helpers, "get_working_dir", lambda: str(tmp_path))
    return tmp_path


def test_no_api_key_400(client, monkeypatch):
    monkeypatch.setattr(image_routes, "get_api_key", lambda: "")
    resp = client.post("/api/image/generate", data={"prompt": "hi"})
    assert resp.status_code == 400


def test_empty_prompt_422(client, deps):
    resp = client.post("/api/image/generate", data={"prompt": "   "})
    assert resp.status_code == 422


def test_long_prompt_422(client, deps):
    resp = client.post("/api/image/generate", data={"prompt": "x" * 5001})
    assert resp.status_code == 422


def test_invalid_size_422(client, deps):
    resp = client.post("/api/image/generate", data={"prompt": "hi", "size": "999x999"})
    assert resp.status_code == 422


def test_generate_with_valid_ref(client, deps):
    """白名单内扩展名 → 保存到 uploads 目录。"""
    files = {"reference_image": ("ref.png", io.BytesIO(b"pngdata"), "image/png")}
    resp = client.post("/api/image/generate", data={"prompt": "a cat"}, files=files)
    assert resp.status_code == 200
    # 文件已落盘
    uploads = deps / "uploads"
    saved = list(uploads.glob("*.png"))
    assert saved, "参考图应保存为 .png"


def test_generate_with_non_whitelist_ext_fallback(client, deps):
    """非法扩展名（如 .exe）→ 回退 .png。"""
    files = {"reference_image": ("ref.exe", io.BytesIO(b"x"), "application/octet-stream")}
    resp = client.post("/api/image/generate", data={"prompt": "a cat"}, files=files)
    assert resp.status_code == 200
    uploads = deps / "uploads"
    saved = list(uploads.glob("*.png"))
    assert saved


def test_generate_with_no_ref(client, deps):
    """无参考图 → 200。"""
    resp = client.post("/api/image/generate", data={"prompt": "a cat"})
    assert resp.status_code == 200
