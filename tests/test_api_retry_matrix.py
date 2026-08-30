"""API 重试矩阵测试（优化路线图 1.6 测试补齐）。

覆盖此前被 mock 回归「整类替换」而零覆盖的重试/轮询路径：
- ``_submit_with_retry``：单 Key 429 退避、多 Key 429 换 Key、5xx 退避、400 降帧、
  停止穿透、重试耗尽
- ``_poll_task``：轮询 429 换 Key、连续失败放弃、服务端失败判定
- ``is_remote_video_failure`` 语义

约定：测试在协议边界 mock ``requests``（HTTP 层），保留 API 类全部内部逻辑。
"""
import asyncio
import json

import pytest
import requests as _requests

import core.api.agnes_video as av


class FakeResponse:
    """最小化的 requests.Response 桩（仅含本模块使用的属性）。"""

    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text if text is not None else json.dumps(self._json, ensure_ascii=False)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(f"HTTP {self.status_code}")


class FakeLimiter:
    """限速器桩：acquire / acquire_async 立即返回，避免真实令牌桶 sleep 拖慢测试。"""

    def acquire(self):
        return True

    async def acquire_async(self, stop_event=None):
        return None


class FakeRing:
    """KeyRing 桩：与真实实现相同的语义（rotate 钉住下一个 next 的 Key）。"""

    def __init__(self, keys):
        self._keys = list(keys)
        self._i = -1
        self._force = None

    def next(self):
        if self._force is not None:
            i, self._force = self._force, None
            return self._keys[i]
        self._i = (self._i + 1) % len(self._keys)
        return self._keys[self._i]

    def rotate(self):
        self._i = (self._i + 1) % len(self._keys)
        self._force = self._i
        return self._keys[self._i]

    def has_multiple(self):
        return len(self._keys) > 1

    def __len__(self):
        return len(self._keys)


@pytest.fixture
def api(monkeypatch):
    """最小化外部依赖的 AgnesVideoAPI（快退避 + 限速器/报错收集打桩）。"""
    monkeypatch.setattr(av, "get_video_submit_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(av, "get_rate_limiter", lambda: FakeLimiter())
    # 不落盘 error_logs，避免测试污染工作目录
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(av, "collect_error_from_exception", lambda *a, **k: None)
    return av.AgnesVideoAPI(api_key="k1", max_retries=3, retry_base_delay=0.001)


def _install_ring(monkeypatch, keys):
    ring = FakeRing(keys)
    monkeypatch.setattr(av, "get_key_ring", lambda: ring)
    return ring


# ── _submit_with_retry ──────────────────────────────────────────────


async def test_single_key_429_backoff_then_success(api, monkeypatch):
    """单 Key：429 → 退避重试 → 成功（无多 Key 时不换 Key）。"""
    _install_ring(monkeypatch, ["k1"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return FakeResponse(429)
        return FakeResponse(200, {"video_id": "vid-ok"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    vid = await api._submit_with_retry({"prompt": "x"}, "t2v")
    assert vid == "vid-ok"
    assert len(calls) == 2
    assert calls == ["Bearer k1", "Bearer k1"]  # 单 Key 不换 Key


async def test_multi_key_429_rotates_immediately(api, monkeypatch):
    """多 Key：429 → 立即换 Key 重试（不 sleep）→ 成功，且第二次使用不同 Key。"""
    _install_ring(monkeypatch, ["k1", "k2"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return FakeResponse(429)
        return FakeResponse(200, {"video_id": "vid-ok"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    vid = await api._submit_with_retry({"prompt": "x"}, "t2v")
    assert vid == "vid-ok"
    assert calls == ["Bearer k1", "Bearer k2"]  # 429 后轮换到了第二个 Key


async def test_5xx_backoff_then_success(api, monkeypatch):
    """5xx → 退避重试 → 成功。"""
    _install_ring(monkeypatch, ["k1"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            return FakeResponse(500)
        return FakeResponse(200, {"video_id": "vid-ok"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    vid = await api._submit_with_retry({"prompt": "x"}, "t2v")
    assert vid == "vid-ok"
    assert len(calls) == 3


async def test_400_num_frames_reduces_payload(api, monkeypatch):
    """400 num_frames 超限 → 按 0.7 降帧后重试 → 成功，payload 的 num_frames 变小。"""
    _install_ring(monkeypatch, ["k1"])
    seen_frames = []

    def fake_post(url, headers=None, json=None, timeout=None):
        seen_frames.append(json.get("num_frames"))
        if len(seen_frames) == 1:
            return FakeResponse(400, text='{"error": "num_frames too large"}')
        return FakeResponse(200, {"video_id": "vid-ok"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    vid = await api._submit_with_retry({"prompt": "x", "num_frames": 100}, "t2v")
    assert vid == "vid-ok"
    assert seen_frames == [100, int(100 * 0.7)]  # 降帧后重发


async def test_cancelled_stop_passthrough(api, monkeypatch):
    """停止信号 → 抛 VideoTaskCancelled，且不发起任何请求（优化路线图 0.2）。"""
    _install_ring(monkeypatch, ["k1"])
    called = []

    def fake_post(url, headers=None, json=None, timeout=None):
        called.append(1)
        return FakeResponse(200, {"video_id": "vid"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    api.shutdown_event = asyncio.Event()
    api.shutdown_event.set()
    with pytest.raises(av.VideoTaskCancelled):
        await api._submit_with_retry({"prompt": "x"}, "t2v")
    assert not called


async def test_submit_exhausted_raises(api, monkeypatch):
    """一直 5xx → 重试耗尽抛 RuntimeError（不静默吞掉）。"""
    _install_ring(monkeypatch, ["k1"])

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(503)

    monkeypatch.setattr(av.requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="max retries"):
        await api._submit_with_retry({"prompt": "x"}, "t2v")


# ── _poll_task ──────────────────────────────────────────────────────


async def test_poll_429_multi_key_rotates(api, monkeypatch):
    """轮询 429（多 Key）→ 换 Key 立即重试 → completed。"""
    _install_ring(monkeypatch, ["k1", "k2"])
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return FakeResponse(429)
        return FakeResponse(200, {"status": "completed", "video_id": "v"})

    monkeypatch.setattr(av.requests, "get", fake_get)

    result = await api._poll_task("vid", interval=0.01, max_consecutive_failures=3, max_poll_duration=600)
    assert result["status"] == "completed"
    assert calls == ["Bearer k1", "Bearer k2"]


async def test_poll_consecutive_failures_gives_up(api, monkeypatch):
    """网络异常连续 N 次 → 抛 RuntimeError（不无限轮询）。"""
    _install_ring(monkeypatch, ["k1"])

    def fake_get(url, headers=None, timeout=None):
        raise _requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(av.requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="consecutive"):
        await api._poll_task("vid", interval=0.01, max_consecutive_failures=3, max_poll_duration=600)


async def test_poll_service_failed_raises(api, monkeypatch):
    """服务端 status=failed → 抛「Video generation failed:」异常（0.2 判定为可丢弃 video_id）。"""
    _install_ring(monkeypatch, ["k1"])

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, {"status": "failed", "error": "bad prompt"})

    monkeypatch.setattr(av.requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="Video generation failed: bad prompt"):
        await api._poll_task("vid", interval=0.01, max_consecutive_failures=3, max_poll_duration=600)


# ── is_remote_video_failure 语义（0.2 核心判定） ────────────────────


def test_is_remote_video_failure_semantics():
    assert av.is_remote_video_failure(RuntimeError("Video generation failed: bad prompt"))
    assert not av.is_remote_video_failure(RuntimeError("[AgnesVideo] Polling timed out after 1800s"))
    assert not av.is_remote_video_failure(av.VideoTaskCancelled("Video generation cancelled by user"))
    assert not av.is_remote_video_failure(_requests.exceptions.ConnectionError("network down"))


# ── KeyRing 真实实现：rotate 钉住下一次 next（1.6 发现并修复） ───────


def test_keyring_rotate_pins_next_usage():
    """429 换 Key 后，紧接的重试请求必须真的使用新 Key。

    修复前 rotate() 与 next() 共享递增计数器：rotate 消费一个序号后 next 取模
    回到旧 Key（k1→rotate→k2(丢弃)→next→k1），导致换 Key 重试形同虚设。
    """
    from core.api.key_manager import KeyRing

    ring = KeyRing(["k1", "k2"])
    assert ring.next() == "k1"      # 请求 A
    assert ring.rotate() == "k2"    # 429 → 换 Key
    assert ring.next() == "k2"      # 重试请求真的用新 Key（修复点）
    assert ring.next() == "k1"      # 之后恢复正常 round-robin


def test_keyring_single_key_rotate_keeps_same_key():
    """单 Key 时 rotate 仍返回唯一 Key（不会越界）。"""
    from core.api.key_manager import KeyRing

    ring = KeyRing(["k1"])
    assert ring.next() == "k1"
    assert ring.rotate() == "k1"
    assert ring.next() == "k1"


# ── 1.3 自适应轮询间隔 ─────────────────────────────────────────────


def test_adaptive_poll_interval_progression():
    """轮询间隔 20s 起步，每 5 次 +5s，上限为调用方 interval。"""
    f = av._adaptive_poll_interval
    assert f(60, 0) == 20
    assert f(60, 4) == 20
    assert f(60, 5) == 25
    assert f(60, 9) == 25
    assert f(60, 10) == 30
    assert f(60, 40) == 60  # 20 + (40//5)*5 = 60，等于上限
    assert f(60, 100) == 60  # 封顶
    assert f(30, 0) == 20
    assert f(30, 100) == 30  # 上限受 interval 约束


def test_adaptive_poll_interval_small_interval_unchanged():
    """测试/自定义小间隔（<20）保持原样，不参与自适应。"""
    f = av._adaptive_poll_interval
    assert f(0.01, 0) == 0.01
    assert f(5, 100) == 5
