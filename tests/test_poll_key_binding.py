"""v7.8 轮询健壮性回归测试。

对应实测（2026-11-06）：上游视频任务按「账号/Key」隔离，同一 ``video_id``
用提交时以外的 Key 查一律 404。此前绑定只存在内存 ``_task_keys``，进程重启
或 resume 后丢失 → 404 被 U9 当成「网关入库延迟」无限容忍 → 白等 1800s 超时。

覆盖：
- 提交时把 Key 指纹（非明文）落到任务状态，resume 时按指纹找回 Key
- 404 分流：绑定丢失时一次性探测「任务归属 Key」，命中即固定切换
- 全部 Key 都 404 时保持 U9 语义（不误伤真实入库延迟）
- 轮询状态透传（前端不再「一直等待」无反馈）
- 钩子未注入时零回归
"""
import json

import pytest
import requests as _requests

import core.api.agnes_video as av
import core.pipelines as pipelines
from core.pipelines import BasePipeline
from models.task import SimpleVideoTask


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text or json.dumps(self._data, ensure_ascii=False)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(f"HTTP {self.status_code}")


class FakeRing:
    def __init__(self, keys=("k1", "k2")):
        self.keys = list(keys)
        self._i = -1

    def next(self):
        self._i = (self._i + 1) % len(self.keys)
        return self.keys[self._i]

    def has_multiple(self):
        return len(self.keys) > 1

    def __len__(self):
        return len(self.keys)

    def mark_auth_failed(self, *a, **k):
        return {}


class CountingLimiter:
    async def acquire_async(self, stop_event=None):
        return None

    def acquire(self):
        return None


class FakeTM:
    def __init__(self):
        self.saved = 0
        self.kwargs = []

    def update_state(self, **kwargs):
        self.saved += 1
        self.kwargs.append(kwargs)


class FakePipeline:
    """只提供 BasePipeline 这几个方法需要的状态面。"""

    _on_task_key_bound = BasePipeline._on_task_key_bound
    _key_fingerprint = staticmethod(BasePipeline._key_fingerprint)
    _resolve_video_key_hint = BasePipeline._resolve_video_key_hint
    _on_poll_progress = BasePipeline._on_poll_progress
    _emit_fast_retry = BasePipeline._emit_fast_retry
    _save_fast_retry = BasePipeline._save_fast_retry

    def __init__(self, state):
        self.task_id = state.task_id
        self._state = state
        self.task_manager = FakeTM()
        self.emits = []

    def _emit_status_message(self, key, params):
        self.emits.append((key, dict(params)))


VID = "task_hlYHKOl86yNUTEVhOj8YiWuoSOPF9ep2"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(av, "get_rate_limiter", lambda: CountingLimiter())
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(av, "collect_error_from_exception", lambda *a, **k: None)
    monkeypatch.setattr(av, "get_api_root_for_key", lambda k: "https://apihub.example/v1")
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing())
    return av.AgnesVideoAPI(api_key="k1", max_retries=2, retry_base_delay=0.001)


# ── Key 绑定持久化 ──────────────────────────────────────────────────


def test_bind_persists_fingerprint_not_plaintext(monkeypatch):
    """提交成功：状态里只存 sha256 指纹，绝不落 Key 明文。"""
    state = SimpleVideoTask(task_id="t_bind")
    p = FakePipeline(state)
    monkeypatch.setattr(pipelines, "get_key_ring", lambda: FakeRing(("k1", "k2")))
    client = av.AgnesVideoAPI(api_key="k1", max_retries=2, retry_base_delay=0.001)
    BasePipeline._attach_fast_retry(p, client)
    assert client.on_task_key_bound is not None

    client._remember_task_key(VID, "k2")

    hints = state.video_key_hints
    assert len(hints) == 1
    assert hints[VID] == BasePipeline._key_fingerprint("k2")
    assert "k2" not in json.dumps(hints)  # 指纹不可逆推明文
    assert p.task_manager.saved == 1


def test_resolve_restores_key_after_restart(monkeypatch):
    """resume：按指纹在当前 Key 池里找回提交时那把 Key（顺序变化也能找回）。"""
    state = SimpleVideoTask(task_id="t_bind")
    state.video_key_hints[VID] = BasePipeline._key_fingerprint("k2")
    p = FakePipeline(state)
    # 顺序与提交时不同，指纹仍应命中
    monkeypatch.setattr(pipelines, "get_key_ring", lambda: FakeRing(("k3", "k2", "k1")))

    assert BasePipeline._resolve_video_key_hint(p, VID) == "k2"
    assert BasePipeline._resolve_video_key_hint(p, "unknown") is None


def test_resolve_missing_key_falls_back_to_probe(monkeypatch):
    """指纹对应的 Key 已从池中删除 → 返回 None，交给 404 归属探测。"""
    state = SimpleVideoTask(task_id="t_bind")
    state.video_key_hints[VID] = BasePipeline._key_fingerprint("k2")
    p = FakePipeline(state)
    monkeypatch.setattr(pipelines, "get_key_ring", lambda: FakeRing(("k1", "k3")))

    assert BasePipeline._resolve_video_key_hint(p, VID) is None


def test_wait_for_video_uses_resolver_when_memory_binding_lost(api, monkeypatch):
    """内存绑定丢失时，wait_for_video 会用 resolver 得到的 Key 启动轮询。"""
    captured = {}

    async def fake_poll(video_id, **kwargs):
        captured["key"] = kwargs.get("key")
        return {"status": "completed", "url": "https://example/v.mp4"}

    monkeypatch.setattr(api, "_poll_task", fake_poll)
    monkeypatch.setattr(api, "key_hint_resolver", lambda vid: "k2")

    import asyncio
    output = asyncio.run(api.wait_for_video(VID))
    assert captured["key"] == "k2"
    assert output.data == "https://example/v.mp4"


# ── 404 分流 / Key 归属探测 ─────────────────────────────────────────


async def test_poll_404_switches_to_owner_key_and_completes(api, monkeypatch):
    """首轮 404（用错 Key）→ 探测到归属 Key → 固定切换 → 拿到 completed。"""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        key = headers.get("Authorization", "").replace("Bearer ", "")
        calls.append(key)
        if key == "k1":
            return FakeResponse(404, {"error": {"code": 404, "message": "task not found"}})
        return FakeResponse(200, {"status": "completed", "url": "https://example/v.mp4"})

    monkeypatch.setattr(av.requests, "get", fake_get)
    progress = []
    api.poll_progress_hook = lambda vid, status, pr, elapsed: progress.append(status)

    result = await api._poll_task(VID, key=None)

    assert result["status"] == "completed"
    # k1 查不到 → 探测到归属 Key 是 k2 → 固定改用 k2 查出 completed
    # （v7.9 起每个 Key 会按「老端点 + REST 端点」逐个试，故 k1 的调用次数不再固定）
    assert set(calls[:4]) == {"k1"}
    assert calls[-1] == "k2"
    assert progress == ["completed"]


async def test_poll_all_keys_404_keeps_u9_semantics(api, monkeypatch, caplog):
    """所有 Key 都 404 = 真·入库延迟：不切换、不报错、继续等（不误伤 U9）。"""
    import logging
    caplog.set_level(logging.INFO, logger="core.api.agnes_video")

    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(404, {"error": {"code": 404, "message": "task not found"}})

    monkeypatch.setattr(av.requests, "get", fake_get)
    monkeypatch.setattr(av, "_adaptive_poll_interval", lambda *a, **k: 0.001)

    # 留出几轮时间让 404 分支与归属探测真正执行，再触发整体超时
    with pytest.raises(RuntimeError, match="Polling timed out"):
        await api._poll_task(VID, key=None, max_poll_duration=0.05)

    assert "均查不到" in caplog.text
    assert "入库延迟" in caplog.text


async def test_pinned_key_skips_owner_probe(api, monkeypatch):
    """已有绑定（含指纹恢复）时不做探测，404 仍按 U9 语义等待。"""
    probed = {"n": 0}

    async def fake_probe(*a, **k):
        probed["n"] += 1
        return "k2"

    monkeypatch.setattr(api, "_probe_owner_key", fake_probe)
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: FakeResponse(
        404, {"error": {"code": 404, "message": "task not found"}}))
    monkeypatch.setattr(av, "_adaptive_poll_interval", lambda *a, **k: 0)

    with pytest.raises(RuntimeError, match="Polling timed out"):
        await api._poll_task(VID, key="k1", max_poll_duration=0)

    assert probed["n"] == 0


# ── 轮询进度透传 ───────────────────────────────────────────────────


def test_poll_progress_hook_is_attached_and_throttled(monkeypatch):
    state = SimpleVideoTask(task_id="t_poll")
    p = FakePipeline(state)
    client = av.AgnesVideoAPI(api_key="k1", max_retries=2, retry_base_delay=0.001)
    BasePipeline._attach_fast_retry(p, client)

    client.poll_progress_hook(VID, "in_progress", 10, 32.0)
    client.poll_progress_hook(VID, "in_progress", 20, 40.0)  # 同状态 8s 内 → 节流
    client.poll_progress_hook(VID, "completed", 100, 90.0)   # 状态变化 → 推送

    assert len(p.emits) == 2
    assert p.emits[0][0] == "progress.video.polling"
    assert p.emits[0][1]["status"] == "in_progress"
    assert p.emits[0][1]["t"] == "0m32s"
    assert p.emits[1][1]["status"] == "completed"


def test_no_hooks_is_zero_regression():
    """未注入任何钩子时，API 保持原有默认（None）。"""
    client = av.AgnesVideoAPI(api_key="k1", max_retries=2, retry_base_delay=0.001)
    assert client.on_task_key_bound is None
    assert client.key_hint_resolver is None
    assert client.poll_progress_hook is None
    assert client.fast_retry_hook is None
