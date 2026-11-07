"""v7.9 轮询端点双轨回归测试。

对应实测（2026-11-07，任务 8363228b8a2d）：
国内站 ``api.agnes-ai.cn`` 的 ``GET /agnesapi?video_id=xxx`` 对任何任务都返回
404「任务不存在」，同一把 Key 打 ``GET /v1/videos/{id}`` 却返回 200
（``status=completed`` / ``progress=100`` / ``metadata.url`` 为成品地址）。
修复前只查老端点 → 国内站任务从第一轮就 404，被 U9 当成「入库延迟」白等到
``AGNES_VIDEO_POLL_TIMEOUT`` 超时，成品其实早已生成。

覆盖：
- 老端点 404 时自动改用 REST 端点并确认成功（结果可取到成品地址）
- 端点确认后只查该端点（不重复打另一个）
- REST 的 400 ``task_not_exist`` 语义等同 404（U9 中间态，不抛 HTTPError）
- ``wait_for_video`` 能从 REST 的 ``metadata.url`` 取成品地址
"""
import json

import pytest
import requests as _requests

import core.api.agnes_video as av
from tests.test_poll_key_binding import (
    VID,
    CountingLimiter,
    FakeRing,
)


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = json.dumps(self._data, ensure_ascii=False)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(f"HTTP {self.status_code}")


COMPLETED_REST = {
    "id": VID,
    "status": "completed",
    "progress": 100,
    "metadata": {"url": "https://cos.example/videos/task.mp4"},
}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(av, "get_rate_limiter", lambda: CountingLimiter())
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(av, "collect_error_from_exception", lambda *a, **k: None)
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing(("k1",)))
    return av.AgnesVideoAPI(api_key="k1", max_retries=2, retry_base_delay=0.001)


def _is_rest(url: str) -> bool:
    return "/v1/videos/" in url


async def test_poll_falls_back_to_rest_endpoint(api, monkeypatch):
    """老端点 404（国内站特性）→ 自动改用 REST 端点并拿到 completed。"""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append("rest" if _is_rest(url) else "legacy")
        if _is_rest(url):
            return FakeResponse(200, COMPLETED_REST)
        return FakeResponse(404, {"error": {"code": 404, "message": "任务不存在"}})

    monkeypatch.setattr(av.requests, "get", fake_get)

    result = await api._poll_task(VID, key="k1")

    assert result["status"] == "completed"
    assert result["metadata"]["url"].endswith("task.mp4")
    # 老端点先试 → 404 → 同一轮内立刻换 REST
    assert calls == ["legacy", "rest"]


async def test_poll_confirmed_endpoint_not_requeried(api, monkeypatch):
    """端点确认后后续轮次只查该端点（不重复打另一个，省配额）。"""
    calls = []
    round_no = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls.append("rest" if _is_rest(url) else "legacy")
        if _is_rest(url):
            round_no["n"] += 1
            if round_no["n"] == 1:
                return FakeResponse(200, {"status": "in_progress", "progress": 30})
            return FakeResponse(200, COMPLETED_REST)
        return FakeResponse(404, {"error": {"code": 404, "message": "task not found"}})

    monkeypatch.setattr(av.requests, "get", fake_get)
    monkeypatch.setattr(av, "_adaptive_poll_interval", lambda *a, **k: 0)

    result = await api._poll_task(VID, key="k1")

    assert result["status"] == "completed"
    # 第 1 轮：legacy + rest；第 2 轮起只打 rest
    assert calls == ["legacy", "rest", "rest"]


async def test_legacy_endpoint_ok_does_not_touch_rest(api, monkeypatch):
    """国际站老端点首轮就 200 → 不再多打 REST 端点（零回归）。"""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append("rest" if _is_rest(url) else "legacy")
        return FakeResponse(200, {"status": "completed", "url": "https://example/v.mp4"})

    monkeypatch.setattr(av.requests, "get", fake_get)

    result = await api._poll_task(VID, key="k1")

    assert result["status"] == "completed"
    assert calls == ["legacy"]


async def test_rest_task_not_exist_keeps_u9_semantics(api, monkeypatch, caplog):
    """两个端点都查不到 → 保持 U9 语义（不当失败，等到总超时）。"""
    import logging
    caplog.set_level(logging.INFO, logger="core.api.agnes_video")

    def fake_get(url, headers=None, timeout=None):
        if _is_rest(url):
            return FakeResponse(400, {"code": "task_not_exist", "message": "task not found"})
        return FakeResponse(404, {"error": {"code": 404, "message": "task not found"}})

    monkeypatch.setattr(av.requests, "get", fake_get)
    monkeypatch.setattr(av, "_adaptive_poll_interval", lambda *a, **k: 0)

    with pytest.raises(RuntimeError, match="Polling timed out"):
        await api._poll_task(VID, key="k1", max_poll_duration=0.1)

    assert "not yet visible" in caplog.text


async def test_probe_owner_key_tries_rest_endpoint(api, monkeypatch):
    """归属探测：老端点全 404 但 REST 端点 200 → 仍能找到归属 Key。"""
    def fake_get(url, headers=None, timeout=None):
        key = headers.get("Authorization", "").replace("Bearer ", "")
        if _is_rest(url) and key == "k2":
            return FakeResponse(200, COMPLETED_REST)
        return FakeResponse(404, {"error": {"code": 404, "message": "task not found"}})

    monkeypatch.setattr(av.requests, "get", fake_get)

    found = await api._probe_owner_key(VID, FakeRing(("k1", "k2")), "")

    assert found == "k2"


def test_wait_for_video_parses_metadata_url(api, monkeypatch):
    """REST 端点把成品地址放在 metadata.url，wait_for_video 必须能取到。"""
    import asyncio

    async def fake_poll(video_id, **kwargs):
        return dict(COMPLETED_REST)

    monkeypatch.setattr(api, "_poll_task", fake_poll)

    output = asyncio.run(api.wait_for_video(VID, key="k1"))

    assert output.data == "https://cos.example/videos/task.mp4"
