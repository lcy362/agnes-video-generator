"""v8.0 简单视频优化：一键预设 / 官方接口能力对齐 / 模式素材校验。

覆盖：
1. ``SIMPLE_DEFAULT_PRESET`` 与 ``normalize_video_size``（含历史 960P 兼容）；
2. ``AgnesVideoAPI._submit_video_v25`` 的 payload 组装（text / keyframe / reference）；
3. ``POST /api/tasks/simple`` 只带 prompt 的一键路径、多图/首尾帧/音频透传、
   keyframe 与 reference 素材互斥、清晰度归一。

用法:
    .venv/bin/python -m pytest tests/test_simple_v8.py -q
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from core.api.agnes_video import AgnesVideoAPI
from core.config import (
    SIMPLE_DEFAULT_PRESET,
    get_simple_default_preset,
    normalize_video_size,
)
from models.task import SimpleVideoTask, parse_task_state
from web import helpers
from web.routes import task_creation_routes


# ═══════════════════════════════════════════════
# 1. 预设与清晰度归一
# ═══════════════════════════════════════════════

class TestPreset:
    def test_default_preset(self):
        p = get_simple_default_preset()
        assert p["model"] == "agnes-video-2.5-flash"  # 免费档
        assert p["duration"] == 5
        assert p["aspect_ratio"] == "16:9"  # 规避 2.5-flash 9:16 躺倒
        assert p["video_size"] == "720P"
        # 返回副本，调用方修改不应污染全局
        p["duration"] = 99
        assert SIMPLE_DEFAULT_PRESET["duration"] == 5

    def test_normalize_video_size(self):
        assert normalize_video_size(None) == "720P"
        assert normalize_video_size("960P", "agnes-video-2.5") == "1080P"
        assert normalize_video_size("1080P", "agnes-video-2.5") == "1080P"
        assert normalize_video_size("2K", "agnes-video-2.5-flash") == "720P"
        assert normalize_video_size("bogus") == "720P"

    def test_legacy_task_deserialization(self):
        """历史 task.json 缺新增字段时应自动补齐（不抛异常）。"""
        state = parse_task_state({
            "task_type": "simple",
            "prompt": "legacy",
            "reference_image": "/tmp/ref.png",
            "end_frame_image": "/tmp/end.png",
            "mode": "keyframes",
        })
        assert isinstance(state, SimpleVideoTask)
        assert state.reference_images == []
        assert state.first_frame_image == ""
        assert state.last_frame_image == ""
        assert state.reference_audio_urls == []


# ═══════════════════════════════════════════════
# 2. 上游提交 payload
# ═══════════════════════════════════════════════

@pytest.fixture
def api(monkeypatch):
    """AgnesVideoAPI + 打桩图片解析与提交，返回 (api, captured)。"""
    inst = AgnesVideoAPI(api_key="k", model="agnes-video-2.5-flash")
    captured = {}

    async def fake_resolve(src):
        return "https://cdn.example/" + os.path.basename(src)

    async def fake_submit(payload, desc, cb):
        captured.update(payload)
        captured["_desc"] = desc
        return "video_test"

    monkeypatch.setattr(inst, "_resolve_image_ref", fake_resolve)
    monkeypatch.setattr(inst, "_submit_with_retry", fake_submit)
    return inst, captured


@pytest.mark.asyncio
async def test_text_payload_has_no_media_fields(api):
    inst, captured = api
    await inst.submit_video(prompt="一只猫", duration=5, width=1280, height=720)
    assert captured["mode"] == "text"
    assert captured["seconds"] == "5"
    assert captured["aspect_ratio"] == "16:9"
    assert captured["size"] == "720P"
    for k in ("images", "audios", "first_frame", "last_frame"):
        assert k not in captured


@pytest.mark.asyncio
async def test_keyframe_payload_native(api):
    inst, captured = api
    await inst.submit_video(
        prompt="转身", first_frame="/tmp/first.png", last_frame="/tmp/last.png",
    )
    assert captured["mode"] == "keyframe"
    assert captured["first_frame"].endswith("first.png")
    assert captured["last_frame"].endswith("last.png")
    assert "images" not in captured and "audios" not in captured


@pytest.mark.asyncio
async def test_reference_images_and_audios(api):
    inst, captured = api
    await inst.submit_video(
        prompt="参考 <Picture 1> 与 <Audio 1>",
        reference_image_paths=["/tmp/a.png", "/tmp/b.png"],
        reference_audio_urls=["https://cdn.example/a.mp3"],
    )
    assert captured["mode"] == "reference"
    assert len(captured["images"]) == 2
    assert captured["audios"] == ["https://cdn.example/a.mp3"]


@pytest.mark.asyncio
async def test_flash_forces_720p(api):
    inst, captured = api
    await inst.submit_video(prompt="x", video_size="2K")
    assert captured["size"] == "720P"


@pytest.mark.asyncio
async def test_paid_model_keeps_requested_size(monkeypatch):
    inst = AgnesVideoAPI(api_key="k", model="agnes-video-2.5")
    captured = {}

    async def fake_submit(payload, desc, cb):
        captured.update(payload)
        return "vid"

    monkeypatch.setattr(inst, "_submit_with_retry", fake_submit)
    await inst.submit_video(prompt="x", video_size="960P")  # 历史值
    assert captured["size"] == "1080P"


# ═══════════════════════════════════════════════
# 3. 路由：一键路径与素材校验
# ═══════════════════════════════════════════════

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(task_creation_routes.router)
    return TestClient(app)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离写路径并捕获落盘的任务状态。"""
    monkeypatch.setattr(task_creation_routes, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        task_creation_routes, "get_selected_models",
        lambda: {"text": "t", "image": "i", "video": "agnes-video-2.5-flash"},
    )
    monkeypatch.setattr(helpers, "get_upload_dir", lambda: str(tmp_path / "uploads"))
    monkeypatch.setattr(
        task_creation_routes.deps, "create_pipeline_for_type",
        lambda *a, **kw: object(),
    )
    monkeypatch.setattr(
        task_creation_routes.app_state, "launch_background_task",
        lambda coro: coro.close(),
    )
    holder = {}

    class _TM:
        def __init__(self, task_id, dir_name=None):
            pass

        def create(self, state):
            holder["state"] = state

        def update_state(self, **kwargs):
            pass

    monkeypatch.setattr(task_creation_routes, "TaskManager", _TM)
    return holder


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _file(name):
    return (name, _png(), "image/png")


def test_one_click_only_prompt(client, env):
    """只传 prompt 即走一键预设（免费 flash / 5s / 16:9 / 720P）。"""
    resp = client.post("/api/tasks/simple", data={"prompt": "一只猫在花园里追蝴蝶"})
    assert resp.status_code == 200
    state = env["state"]
    assert state.duration == 5
    assert (state.video_width, state.video_height) == (1280, 720)
    assert state.video_size == "720P"


def test_multi_reference_images(client, env):
    resp = client.post(
        "/api/tasks/simple",
        data={"prompt": "p", "mode": "i2v"},
        files=[("reference_images", _file("a.png")), ("reference_images", _file("b.png"))],
    )
    assert resp.status_code == 200
    assert len(env["state"].reference_images) == 2


def test_keyframe_native_fields(client, env):
    resp = client.post(
        "/api/tasks/simple",
        data={"prompt": "p", "mode": "keyframes"},
        files=[("first_frame_image", _file("f.png")), ("last_frame_image", _file("l.png"))],
    )
    assert resp.status_code == 200
    state = env["state"]
    assert state.first_frame_image.endswith(".png")
    assert state.last_frame_image.endswith(".png")


def test_reference_audios(client, env):
    resp = client.post(
        "/api/tasks/simple",
        data={
            "prompt": "p", "mode": "i2v",
            "reference_audio_urls": "https://a.example/1.mp3\nhttps://a.example/2.mp3",
        },
        files=[("reference_images", _file("a.png"))],
    )
    assert resp.status_code == 200
    assert env["state"].reference_audio_urls == [
        "https://a.example/1.mp3", "https://a.example/2.mp3",
    ]


def test_keyframe_rejects_reference_images(client, env):
    """官方模式互斥：keyframe 不允许 images/audios。"""
    resp = client.post(
        "/api/tasks/simple",
        data={"prompt": "p", "mode": "keyframes"},
        files=[("reference_images", _file("a.png"))],
    )
    assert resp.status_code == 422


def test_audio_url_must_be_http(client, env):
    resp = client.post(
        "/api/tasks/simple",
        data={"prompt": "p", "mode": "i2v", "reference_audio_urls": "/local/a.mp3"},
        files=[("reference_images", _file("a.png"))],
    )
    assert resp.status_code == 422


def test_audio_count_limit(client, env):
    resp = client.post(
        "/api/tasks/simple",
        data={
            "prompt": "p", "mode": "i2v",
            "reference_audio_urls": "\n".join(f"https://a/{i}.mp3" for i in range(4)),
        },
        files=[("reference_images", _file("a.png"))],
    )
    assert resp.status_code == 422


def test_flash_size_is_normalized(client, env):
    """flash 档选 2K 时归一到 720P，不把非法值透传给上游。"""
    resp = client.post(
        "/api/tasks/simple",
        data={"prompt": "p", "video_size": "2K"},
    )
    assert resp.status_code == 200
    assert env["state"].video_size == "720P"
