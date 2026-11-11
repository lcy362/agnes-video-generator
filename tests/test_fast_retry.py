"""快速重试模式（v7.7）回归测试。

对应需求：视频提交连续两次 503（队列满）后，进度页出现开关；用户开启后按
「每分钟 x 次、持续 y 分钟」连打，提交成功或到期后恢复正常模式，且**不干扰**
既有两轨重试逻辑。

覆盖：
- 状态机：连续 2 次忙信号 → available；开启 → 返回间隔；到期 → 回常规；成功 → 收尾
- API 层：快速模式跳过共享视频提交桶（否则 x 次/分钟无法兑现）且不消耗常规忙轨次数
- 零回归：未注入钩子时，提交循环与引入本功能前完全一致（每跳都取桶、忙轨次数照常递增）
- 参数边界：clamp / interval_seconds
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

import pytest
import requests as _requests

import core.api.agnes_video as av
from core.api.fast_retry import (
    FAST_RETRY_AVAILABLE_AFTER,
    FAST_RETRY_MAX_MINUTES,
    FAST_RETRY_MAX_PER_MINUTE,
    clamp_params,
    interval_seconds,
)
from core.pipelines import _PipelineFastRetryHook
from models.task import SimpleVideoTask, StepStatus


@pytest.fixture(autouse=True)
def _isolate_global_auto(monkeypatch):
    """默认关闭「设置页自动快速重试」，避免读到开发机真实 config.json。

    v8.0 起钩子的 ``decide()`` 会读全局设置（``auto=True`` 时到条件直接开跑）。
    单测必须与开发机配置隔离，否则本地开了自动模式后这些用例会莫名失败。
    需要验证自动行为的用例自行再 monkeypatch 成开启状态。
    """
    import core.pipelines as pipelines_mod

    monkeypatch.setattr(
        pipelines_mod, "get_fast_retry_config",
        lambda: {"auto": False, "per_minute": 30, "minutes": 3},
        raising=False,
    )


class FakeResponse:
    """最小化 requests.Response 桩。"""

    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = json.dumps(self._json, ensure_ascii=False)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(f"HTTP {self.status_code}")


class CountingLimiter:
    """记录 acquire 次数的限速器桩。"""

    def __init__(self):
        self.acquired = 0

    def acquire(self):
        self.acquired += 1

    async def acquire_async(self, stop_event=None):
        self.acquired += 1


class FakeRing:
    """KeyRing 桩（单 Key 即可）。"""

    def __init__(self, keys=("k1",)):
        self._keys = list(keys)
        self._i = -1

    def next(self):
        self._i = (self._i + 1) % len(self._keys)
        return self._keys[self._i]

    def rotate(self):
        return self.next()

    def has_multiple(self):
        return len(self._keys) > 1

    def __len__(self):
        return len(self._keys)

    def mark_auth_failed(self, *a, **k):
        return {}


class FakeTaskManager:
    """记录落盘次数的 TaskManager 桩。"""

    def __init__(self):
        self.saved = 0

    def update_state(self, **kwargs):
        self.saved += 1


class FakePipeline:
    """最小流水线桩：只提供钩子需要的状态与两个副作用方法。"""

    def __init__(self, state):
        self.task_id = state.task_id
        self._state = state
        self.task_manager = FakeTaskManager()
        self.emits = []

    def _save_fast_retry(self):
        self.task_manager.update_state()

    def _emit_fast_retry(self, message_key, params):
        self.emits.append((message_key, dict(params)))


def _state(**cfg):
    state = SimpleVideoTask(task_id="t_fast")
    for k, v in cfg.items():
        setattr(state.fast_retry, k, v)
    return state


BUSY = {"status": 503, "code": "video_queue_full", "attempt": 0, "waited_s": 0.0}


# ── 状态机（流水线钩子）──────────────────────────────────────────────


def test_available_after_two_consecutive_busy_signals():
    """连续 2 次忙信号后置 available 并落盘，前端据此显示开关。"""
    state = _state()
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(0, BUSY) is None
    assert state.fast_retry.available is False
    assert p.task_manager.saved == 0

    assert hook.decide(1, BUSY) is None
    assert state.fast_retry.available is True
    assert state.fast_retry.consecutive_busy == FAST_RETRY_AVAILABLE_AFTER
    assert p.task_manager.saved == 1
    assert p.emits[0][0] == "progress.video.fast_retry.available"
    assert p.emits[0][1]["n"] == FAST_RETRY_AVAILABLE_AFTER


def test_enabled_returns_interval_without_touching_busy_counter():
    """开启后返回 60/x 秒，且不再累计 consecutive_busy。"""
    state = _state(enabled=True, per_minute=30, minutes=3,
                   started_at=datetime.now().isoformat(timespec="seconds"),
                   consecutive_busy=2, available=True)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(2, BUSY) == pytest.approx(2.0)
    assert state.fast_retry.consecutive_busy == 2
    assert state.fast_retry.enabled is True


def test_expired_after_configured_minutes():
    """到达 y 分钟后恢复常规忙轨，并记录 expired。"""
    started = (datetime.now() - timedelta(minutes=4)).isoformat(timespec="seconds")
    state = _state(enabled=True, per_minute=60, minutes=3,
                   started_at=started, available=True)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(2, BUSY) is None
    assert state.fast_retry.enabled is False
    assert state.fast_retry.finished_reason == "expired"
    assert p.emits[-1][0] == "progress.video.fast_retry.expired"
    assert p.task_manager.saved == 1


def test_success_closes_fast_mode_and_clears_available():
    """提交成功：关闭快速模式、清空可开启标记、清零连续计数。"""
    state = _state(enabled=True, per_minute=60, minutes=3,
                   started_at=datetime.now().isoformat(timespec="seconds"),
                   available=True, consecutive_busy=5)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    hook.on_success()

    assert state.fast_retry.enabled is False
    assert state.fast_retry.available is False
    assert state.fast_retry.consecutive_busy == 0
    assert state.fast_retry.finished_reason == "success"
    assert p.emits[-1][0] == "progress.video.fast_retry.success"


def test_attempts_tracked_and_throttled():
    """面板「已发 N 次」：每跳同步内存值，落盘 0.8s 节流（略快于前端 1s 轮询）。"""
    state = _state(enabled=True, per_minute=30, minutes=3,
                   started_at=datetime.now().isoformat(timespec="seconds"),
                   available=True)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    # 首跳即落盘（上一轮 _last_attempts_save 初值 0）
    for n in range(1, 13):
        assert hook.decide(0, {**BUSY, "probe": n}) == pytest.approx(2.0)

    assert state.fast_retry.attempts == 12
    # 12 跳在 1 秒内完成 → 只有首跳落盘，避免把状态文件写成每秒 2 次
    assert p.task_manager.saved == 1

    # 模拟跨过 1 秒：下一跳再落盘一次
    hook._last_attempts_save -= 2.0
    hook.decide(0, {**BUSY, "probe": 13})
    assert state.fast_retry.attempts == 13
    assert p.task_manager.saved == 2


def test_expiry_keeps_attempts_for_review():
    """到期后 attempts 不清零，方便用户看到上一轮打了多少次。"""
    started = (datetime.now() - timedelta(minutes=4)).isoformat(timespec="seconds")
    state = _state(enabled=True, per_minute=60, minutes=3,
                   started_at=started, available=True, attempts=7)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(0, {**BUSY, "probe": 7}) is None
    assert state.fast_retry.finished_reason == "expired"
    assert state.fast_retry.attempts == 7


def test_success_with_probe_count():
    """成功那跳也算一次请求，on_success(probe) 把终值写进状态。"""
    state = _state(enabled=True, per_minute=60, minutes=3,
                   started_at=datetime.now().isoformat(timespec="seconds"),
                   available=True, consecutive_busy=3)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    hook.on_success(9)

    assert state.fast_retry.attempts == 9
    assert state.fast_retry.finished_reason == "success"


def test_on_probe_advances_attempts_outside_decide():
    """非忙响应（500 / 换 Key 的 429 / 超时）也要推进「已发 N 次」。

    这些跳不会进入 ``decide()``；若只靠 decide 同步，面板会冻结在旧值上
    —— 用户看到的就是「次数不自动刷新」。
    """
    state = _state(enabled=True, per_minute=120, minutes=3,
                   started_at=datetime.now().isoformat(timespec="seconds"),
                   available=True)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    for n in (1, 2, 3):
        hook.on_probe(n)

    assert state.fast_retry.attempts == 3
    assert p.task_manager.saved >= 1


def test_on_probe_ignored_when_mode_disabled():
    """未开启快速模式时，逐跳回调不得改动次数。"""
    state = _state(enabled=False, attempts=7)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    hook.on_probe(9)

    assert state.fast_retry.attempts == 7
    assert p.task_manager.saved == 0


def test_success_without_fast_mode_does_not_emit():
    """未开启快速模式时提交成功只清理计数，不额外推送消息。"""
    state = _state(available=True, consecutive_busy=2)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    hook.on_success()

    assert state.fast_retry.available is False
    assert p.emits == []


# ── API 层：节奏与配额隔离 ────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch):
    """零退避 + 限速器/报错收集打桩的 AgnesVideoAPI。"""
    limiter = CountingLimiter()
    monkeypatch.setattr(av, "get_video_submit_limiter", lambda: limiter)
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(av, "collect_error_from_exception", lambda *a, **k: None)
    monkeypatch.setattr(av, "_QUEUE_RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(av, "_QUEUE_RETRY_JITTER", 0.0)
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing())
    client = av.AgnesVideoAPI(api_key="k1", max_retries=3, retry_base_delay=0.001)
    client._limiter = limiter
    return client


def _patch_sleep(monkeypatch):
    """把 asyncio.sleep 换成记录器（不真正等待）。"""
    delays = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *a, **k):
        delays.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(av.asyncio, "sleep", fake_sleep)
    return delays


def _busy_then_success(monkeypatch, busy_times):
    """前 ``busy_times`` 次返回 503 队列满，之后返回成功。"""
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] <= busy_times:
            return FakeResponse(503, {"code": "video_queue_full",
                                      "message": "video queue is full"})
        return FakeResponse(200, {"video_id": f"vid{calls['n']}"})

    monkeypatch.setattr(av.requests, "post", fake_post)
    return calls


async def test_fast_mode_skips_submit_bucket_and_keeps_busy_quota(api, monkeypatch):
    """快速模式：不取共享提交桶、不消耗常规忙轨次数（否则 15 次额度会被烧光）。

    这里让前 4 次 503 走快速模式（间隔 2s），第 5 次成功。
    预期：桶只在首跳取 1 次；之后按 2.0s 节奏；hook 收到的 busy_attempt 恒为 0。
    """
    _busy_then_success(monkeypatch, busy_times=4)
    delays = _patch_sleep(monkeypatch)

    attempts_seen = []
    state = {"probes": 0}

    class Hook:
        def decide(self, busy_attempt, payload):
            attempts_seen.append(busy_attempt)
            state["probes"] += 1
            if state["probes"] > 4:      # 第 5 次起到期 → 回常规
                return None
            return 2.0

        def on_success(self):
            state["success"] = True

    api.fast_retry_hook = Hook()

    video_id = await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert video_id.startswith("vid")
    # 首跳取桶 1 次；快速模式的 4 跳自带节奏，不再取桶
    assert api._limiter.acquired == 1
    assert delays.count(2.0) == 4
    # 快速模式期间常规忙轨次数不递增（hook 收到的 attempt 恒为 0）
    assert set(attempts_seen[:4]) == {0}
    assert state.get("success") is True


async def test_fast_mode_logs_every_request_and_response(api, monkeypatch, caplog):
    """快速模式逐跳打印请求原文与响应原文，并累计「已打多少次」。"""
    caplog.set_level(logging.INFO, logger="core.api.agnes_video")
    _busy_then_success(monkeypatch, busy_times=3)
    _patch_sleep(monkeypatch)
    ticks = {"n": 0}

    class Hook:
        def decide(self, busy_attempt, payload):
            ticks["n"] += 1
            return 1.0 if ticks["n"] <= 3 else None

        def on_success(self, probe=0):
            ticks["success_probe"] = probe

    api.fast_retry_hook = Hook()
    await api._submit_with_retry(
        {"prompt": "a " * 80, "model": "agnes-video-2.5-flash", "seconds": "4"}, "t2v"
    )

    req = [r.message for r in caplog.records
           if "[FastRetry] probe #" in r.message and "→ POST" in r.message]
    res = [r.message for r in caplog.records
           if "[FastRetry] probe #" in r.message and "← HTTP" in r.message]
    assert len(req) == 3 and len(res) == 3
    assert "payload=" in req[0] and "len=" in req[0]      # prompt 截断防刷屏
    assert "body=" in res[0] and "video_queue_full" in res[0]  # 响应原文
    assert "← HTTP 200" in res[-1]                       # 成功那跳也有响应日志
    assert api._fast_retry_probes == 3
    assert ticks["success_probe"] == 3


async def test_fast_mode_logs_hide_key_material(api, monkeypatch, caplog):
    """逐跳日志只打印 Key 指纹，任何明文片段都不得落日志（CodeQL 高危项）。"""
    caplog.set_level(logging.INFO, logger="core.api.agnes_video")
    secret = "sk-" + "a1b2c3d4" * 5          # 42 字符，足以触发明文掩码分支
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing((secret,)))
    _busy_then_success(monkeypatch, busy_times=2)
    _patch_sleep(monkeypatch)

    class Hook:
        def decide(self, busy_attempt, payload):
            return 1.0

        def on_probe(self, probe):
            return None

        def on_success(self, probe=0):
            return None

    api.fast_retry_hook = Hook()
    await api._submit_with_retry({"prompt": "x"}, "t2v")

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "key_fp=" in text
    assert secret not in text
    assert secret[:8] not in text
    assert secret[-4:] not in text


async def test_fast_mode_counts_non_busy_probes(api, monkeypatch):
    """连打期间遇到非忙 500，这一跳也要计入「已发 N 次」。

    非忙 5xx 走故障轨、不经过 ``decide()``；旧实现下这一跳的计数会丢失，
    面板显示的次数停在上一次忙信号的值，看起来「不自动刷新」。
    """
    state = _state(enabled=True, per_minute=120, minutes=30,
                   started_at=datetime.now().isoformat(timespec="seconds"),
                   available=True)
    pipeline = FakePipeline(state)
    api.fast_retry_hook = _PipelineFastRetryHook(pipeline)
    _patch_sleep(monkeypatch)

    seen = []
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        seen.append(state.fast_retry.attempts)   # 本跳发出前已同步的次数
        if calls["n"] == 1:
            return FakeResponse(503, {"code": "video_queue_full",
                                      "message": "video queue is full"})
        if calls["n"] == 2:
            return FakeResponse(500, {"message": "boom"})
        return FakeResponse(200, {"video_id": "vidok"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    assert await api._submit_with_retry({"prompt": "x"}, "t2v") == "vidok"
    # 第 3 跳发出前，第 2 跳（非忙 500）已把次数同步为 1
    assert seen[-1] == 1
    # 成功那跳也计入，终值为 2
    assert state.fast_retry.attempts == 2


async def test_fast_mode_expiry_falls_back_to_normal_busy_track(api, monkeypatch):
    """快速模式到期（hook 返回 None）后原样回到常规忙轨：重新取桶并递增次数。"""
    _busy_then_success(monkeypatch, busy_times=2)
    delays = _patch_sleep(monkeypatch)
    ticks = {"n": 0}

    class Hook:
        def decide(self, busy_attempt, payload):
            ticks["n"] += 1
            return 1.0 if ticks["n"] == 1 else None   # 只快速一跳就到期

        def on_success(self):
            pass

    api.fast_retry_hook = Hook()
    await api._submit_with_retry({"prompt": "x"}, "t2v")

    # 第 1 跳取桶；第 2 跳走快速（不取桶）；到期后第 3 跳重新取桶
    assert api._limiter.acquired == 2
    assert delays.count(1.0) == 1


async def test_no_hook_keeps_original_busy_track(api, monkeypatch):
    """未注入钩子（默认）：每跳都取令牌桶，行为与引入本功能前一致。"""
    _busy_then_success(monkeypatch, busy_times=2)
    delays = _patch_sleep(monkeypatch)

    assert api.fast_retry_hook is None
    await api._submit_with_retry({"prompt": "x"}, "t2v")

    # 3 次请求 = 3 次取桶；只在 2 次忙信号后退避两次（成功那跳不退避）
    assert api._limiter.acquired == 3
    assert delays == [0.0, 0.0]


async def test_hook_errors_do_not_break_submission(api, monkeypatch):
    """钩子抛异常时不得打断提交：退化为常规忙轨。"""
    _busy_then_success(monkeypatch, busy_times=1)
    _patch_sleep(monkeypatch)

    class BrokenHook:
        def decide(self, busy_attempt, payload):
            raise RuntimeError("boom")

        def on_success(self):
            raise RuntimeError("boom")

    api.fast_retry_hook = BrokenHook()
    video_id = await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert video_id.startswith("vid")
    assert api._limiter.acquired == 2


# ── 参数边界 ─────────────────────────────────────────────────────────


def test_clamp_params_bounds():
    assert clamp_params(0, 0) == (1, 1)
    assert clamp_params(30, 3) == (30, 3)
    assert clamp_params(9999, 9999) == (FAST_RETRY_MAX_PER_MINUTE, FAST_RETRY_MAX_MINUTES)
    assert clamp_params(-5, -5) == (1, 1)


def test_interval_seconds_floor():
    assert interval_seconds(30) == pytest.approx(2.0)
    assert interval_seconds(120) == pytest.approx(0.5)
    assert interval_seconds(0) >= 0.5     # 防除零


# ── 端点：POST /api/tasks/{id}/fast-retry ────────────────────────────


class TestFastRetryEndpoint:
    """挂载 task_routes，打桩 TaskManager / app_state 验证开关端点。"""

    def _client(self, monkeypatch, state):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web.routes import task_routes

        app = FastAPI()
        app.include_router(task_routes.router)
        monkeypatch.setattr(task_routes.helpers, "find_dir_name", lambda tid: "d_test")

        class _TM:
            def __init__(self, task_id, dir_name=None):
                self.state = state
                self.saved = 0

            def load(self):
                return self.state

            def get_state(self):
                return self.state

            def update_state(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self.state, k, v)
                self.saved += 1

        monkeypatch.setattr(task_routes, "TaskManager", _TM)
        monkeypatch.setattr(task_routes.app_state, "active_pipelines", {})
        return TestClient(app), _TM

    def test_enable_available_task(self, monkeypatch):
        state = _state(available=True, consecutive_busy=2)
        client, _ = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_fast/fast-retry",
                        data={"enabled": "true", "per_minute": "20", "minutes": "2"})

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["fast_retry"]["enabled"] is True
        assert body["fast_retry"]["per_minute"] == 20
        assert body["fast_retry"]["minutes"] == 2
        assert body["fast_retry"]["started_at"]      # 记录开启时刻，供到期判定
        assert state.fast_retry.enabled is True

    def test_task_detail_disables_http_cache(self, monkeypatch):
        """1s 轮询端点必须禁缓存：浏览器启发式缓存会让「已发 N 次」不刷新。"""
        state = _state(enabled=True, available=True, per_minute=60, minutes=3,
                       started_at=datetime.now().isoformat(timespec="seconds"))
        client, _ = self._client(monkeypatch, state)

        r = client.get("/api/tasks/t_fast")

        assert r.status_code == 200
        assert "no-store" in r.headers.get("cache-control", "")

    def test_reject_when_not_available(self, monkeypatch):
        """未连续遇到 2 次忙信号时不允许开启（防止对健康任务高频空转）。"""
        state = _state(available=False)
        client, _ = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_fast/fast-retry", data={"enabled": "true"})

        assert r.status_code == 400
        assert state.fast_retry.enabled is False

    def test_reject_out_of_range_params(self, monkeypatch):
        state = _state(available=True)
        client, _ = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_fast/fast-retry",
                        data={"enabled": "true", "per_minute": "999", "minutes": "2"})

        assert r.status_code == 422

    def test_disable_sets_reason(self, monkeypatch):
        state = _state(enabled=True, available=True, per_minute=60, minutes=3,
                       started_at=datetime.now().isoformat(timespec="seconds"))
        client, _ = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_fast/fast-retry", data={"enabled": "false"})

        assert r.status_code == 200
        assert state.fast_retry.enabled is False
        assert state.fast_retry.finished_reason == "disabled"

    def test_resume_resets_fast_retry_state(self, monkeypatch):
        """续传是一次新运行：清掉上一轮残留的 available/attempts。

        否则上次失败前已连续 2 次 503 的任务，一点续传就显示快速重试开关。
        """
        from web.routes import task_routes

        state = _state(
            available=True, enabled=False, consecutive_busy=3, attempts=9,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )
        state.status = StepStatus.FAILED
        client, _ = self._client(monkeypatch, state)
        monkeypatch.setattr(task_routes, "get_api_key", lambda: "k")
        monkeypatch.setattr(
            task_routes.deps, "create_pipeline_for_type", lambda *a, **kw: object(),
        )
        monkeypatch.setattr(
            task_routes.app_state, "launch_background_task",
            lambda coro: coro.close(),
        )

        r = client.post("/api/tasks/t_fast/resume")

        assert r.status_code == 200
        assert state.fast_retry.available is False
        assert state.fast_retry.consecutive_busy == 0
        assert state.fast_retry.attempts == 0
        assert state.fast_retry.started_at == ""
        assert state.fast_retry.finished_reason == ""


# ── v8.0：设置页「自动快速重试」────────────────────────────────────────


def _auto_on(monkeypatch, per_minute: int = 60, minutes: int = 5) -> None:
    """把全局设置桩成「已开启自动模式」。"""
    import core.pipelines as pipelines_mod

    monkeypatch.setattr(
        pipelines_mod, "get_fast_retry_config",
        lambda: {"auto": True, "per_minute": per_minute, "minutes": minutes},
        raising=False,
    )


def test_auto_starts_at_threshold_without_user_click(monkeypatch):
    """设置页开启自动 → 第 2 次忙信号直接进入快速模式，不需要用户点开关。"""
    _auto_on(monkeypatch, per_minute=60, minutes=5)
    state = _state()
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(0, BUSY) is None          # 第 1 次：仍走慢速
    assert state.fast_retry.enabled is False

    gap = hook.decide(1, BUSY)                   # 第 2 次：自动开跑
    assert gap == pytest.approx(1.0)             # 60 次/分钟 → 1s
    assert state.fast_retry.enabled is True
    assert state.fast_retry.auto is True
    assert state.fast_retry.available is True    # 面板仍据此显示
    assert state.fast_retry.per_minute == 60
    assert state.fast_retry.minutes == 5
    assert state.fast_retry.started_at
    assert p.emits[-1][0] == "progress.video.fast_retry.auto"
    assert p.task_manager.saved == 1


def test_auto_respects_manual_disable_in_same_task(monkeypatch):
    """用户在本任务内手动关过（auto_off）→ 自动模式不得把它重新拉起。"""
    _auto_on(monkeypatch)
    state = _state(auto_off=True)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(0, BUSY) is None
    assert hook.decide(1, BUSY) is None
    assert state.fast_retry.enabled is False
    assert state.fast_retry.auto is False
    assert p.emits[-1][0] == "progress.video.fast_retry.available"


def test_auto_expiry_resets_counter_for_cooldown(monkeypatch):
    """自动模式到期后清零连续计数：需要重新累计 2 次忙信号才会再次开启。"""
    _auto_on(monkeypatch)
    started = (datetime.now() - timedelta(minutes=6)).isoformat(timespec="seconds")
    state = _state(
        enabled=True, auto=True, per_minute=60, minutes=5,
        started_at=started, available=True, consecutive_busy=4,
    )
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(0, BUSY) is None
    assert state.fast_retry.enabled is False
    assert state.fast_retry.auto is False
    assert state.fast_retry.consecutive_busy == 0
    assert state.fast_retry.finished_reason == "expired"


def test_global_settings_persist_and_clamp(tmp_path, monkeypatch):
    """全局设置读写：默认关闭；越界参数收敛；未传字段保留原值。"""
    import core.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(tmp_path / "config.json"))

    assert config_mod.get_fast_retry_config()["auto"] is False

    entry = config_mod.set_fast_retry_config(auto=True, per_minute=999, minutes=0)
    assert entry == {"auto": True, "per_minute": 120, "minutes": 1}
    assert config_mod.get_fast_retry_config() == entry

    # 只改 auto，x / y 保持上一次的值
    again = config_mod.set_fast_retry_config(auto=False)
    assert again == {"auto": False, "per_minute": 120, "minutes": 1}


class TestFastRetryRemember:
    """任务页「以后自动」：一次性开启 + 顺手把 x/y 记进全局设置。"""

    def _client(self, monkeypatch, state):
        return TestFastRetryEndpoint()._client(monkeypatch, state)

    def test_remember_writes_global_auto(self, monkeypatch):
        import core.config as config_mod

        saved = {}

        def fake_set(auto=None, per_minute=None, minutes=None):
            saved.update({"auto": auto, "per_minute": per_minute, "minutes": minutes})
            return {"auto": True, "per_minute": per_minute, "minutes": minutes}

        monkeypatch.setattr(config_mod, "set_fast_retry_config", fake_set, raising=False)
        monkeypatch.setattr(
            config_mod, "get_fast_retry_config",
            lambda: {"auto": True, "per_minute": 20, "minutes": 2}, raising=False,
        )
        state = _state(available=True, consecutive_busy=2)
        client, _ = self._client(monkeypatch, state)

        r = client.post(
            "/api/tasks/t_fast/fast-retry",
            data={"enabled": "true", "per_minute": "20", "minutes": "2",
                  "remember": "true"},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["fast_retry"]["enabled"] is True
        assert body["fast_retry"]["auto"] is False        # 本次是用户手动开启
        assert body["fast_retry"]["auto_off"] is False
        assert body["fast_retry_settings"]["auto"] is True
        assert saved == {"auto": True, "per_minute": 20, "minutes": 2}

    def test_disable_sets_auto_off_to_suppress_auto(self, monkeypatch):
        """手动关闭 → auto_off=True（本轮不再被自动模式重新拉起）。"""
        import core.config as config_mod

        monkeypatch.setattr(
            config_mod, "get_fast_retry_config",
            lambda: {"auto": True, "per_minute": 30, "minutes": 3}, raising=False,
        )
        state = _state(enabled=True, auto=True, available=True, per_minute=60,
                       minutes=3, started_at=datetime.now().isoformat(timespec="seconds"))
        client, _ = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_fast/fast-retry", data={"enabled": "false"})

        assert r.status_code == 200
        assert state.fast_retry.enabled is False
        assert state.fast_retry.auto is False
        assert state.fast_retry.auto_off is True
        assert state.fast_retry.finished_reason == "disabled"
