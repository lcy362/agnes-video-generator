"""
单元测试：web.routes.image_routes — 参考图上传扩展名白名单（S2083 修复）。

覆盖 generate_image 的：
- 无 API Key → 400
- prompt 超长 / 空 → 422
- size 非法 → 422
- 合法请求 + 参考图（白名单内扩展名）→ 200，文件落盘于 uploads/
- 参考图扩展名不在白名单 → 400（v8.1 起不再「后缀撒谎」改名为 .png）
- 多参考图（v8.1）→ 全部落盘且顺序保持；超过上限 → 422
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from web.routes import image_routes


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


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
    """白名单内扩展名 + 可解码字节 → 保存到 uploads 目录。"""
    files = {"reference_image": ("ref.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = client.post("/api/image/generate", data={"prompt": "a cat"}, files=files)
    assert resp.status_code == 200
    # 文件已落盘
    uploads = deps / "uploads"
    saved = list(uploads.glob("*.png"))
    assert saved, "参考图应保存为 .png"


def test_generate_with_non_whitelist_ext_rejected(client, deps):
    """非法扩展名（如 .exe）→ 400（v8.1 起与任务创建侧同口径，不再改名放行）。"""
    files = {"reference_image": ("ref.exe", io.BytesIO(_png_bytes()), "application/octet-stream")}
    resp = client.post("/api/image/generate", data={"prompt": "a cat"}, files=files)
    assert resp.status_code == 400


def test_generate_with_multiple_refs(client, deps):
    """v8.1：多参考图全部落盘，序号递增且顺序与上传一致。"""
    files = [
        ("reference_images", ("a.png", io.BytesIO(_png_bytes()), "image/png")),
        ("reference_images", ("b.png", io.BytesIO(_png_bytes()), "image/png")),
    ]
    resp = client.post("/api/image/generate", data={"prompt": "a cat"}, files=files)
    assert resp.status_code == 200
    saved = sorted(p.name for p in (deps / "uploads").glob("img_ref_*.png"))
    assert len(saved) == 2
    assert saved[0].endswith("_0.png") and saved[1].endswith("_1.png")


def test_generate_with_too_many_refs_422(client, deps):
    """v8.1：超过图片侧上限 → 422，不进入生成环节。"""
    files = [
        ("reference_images", (f"r{i}.png", io.BytesIO(_png_bytes()), "image/png"))
        for i in range(6)
    ]
    resp = client.post("/api/image/generate", data={"prompt": "a cat"}, files=files)
    assert resp.status_code == 422


def test_generate_with_no_ref(client, deps):
    """无参考图 → 200。"""
    resp = client.post("/api/image/generate", data={"prompt": "a cat"})
    assert resp.status_code == 200
