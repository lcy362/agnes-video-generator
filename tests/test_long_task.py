"""长任务模式（v8.3）回归测试。

对应需求（2026-11-19）：
- 新增「长任务模式」开关 + 超时配置（默认 60 分钟），与快速重试开关放在一起；
- 开启后**保留现有重试频率**，只把总预算延长到配置时长；
- 明确不可重试的报错不再重试，直接返回最终结果；
- 重试能成功的场景一直重试到配置时间或任务成功。

覆盖：
- 参数边界（clamp / 默认 1 小时）
- 错误分类表（不可重试 vs 可重试的默认保守策略）
- 钩子状态机（累计等待、到期、不可重试收尾）
- API 层：忙轨次数耗尽后按钩子判定继续 / 失败；4xx 直接抛 UpstreamFatalError
- 端点：开关 / 越界 422 / 续传重置预算
"""
import asyncio
import json

import pytest
import requests as _requests

import core.api.agnes_video as av
from core.api.error_taxonomy import classify
from core.api.long_task import (
    LONG_TASK_DEFAULT_MINUTES,
    LONG_TASK_MAX_MINUTES,
    LONG_TASK_MIN_MINUTES,
    budget_seconds,
    clamp_timeout_minutes,
)
from core.pipelines import _PipelineLongTaskHook
from models.task import SimpleVideoTask, StepStatus


# ── 参数边界 ──────────────────────────────────────────────────────


def test_clamp_timeout_defaults_to_one_hour():
    assert LONG_TASK_DEFAULT_MINUTES == 60
    assert clamp_timeout_minutes(None) == 60
    assert clamp_timeout_minutes(0) == 60
    assert clamp_timeout_minutes("abc") == 60
    assert clamp_timeout_minutes(1) == LONG_TASK_MIN_MINUTES
    assert clamp_timeout_minutes(10000) == LONG_TASK_MAX_MINUTES
    assert budget_seconds(30) == 1800.0


# ── 错误分类表 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,code,retryable,reason",
    [
        (429, "", True, "rate_limited"),
        (503, "", True, "service_busy"),
        (503, "video_queue_full", True, "queue_full"),
        (408, "", True, "request_timeout"),
        (500, "", True, "server_error"),
        (502, "", True, "server_error"),
        (401, "", False, "auth_invalid"),
        (403, "", False, "forbidden"),
        (404, "", False, "not_found"),
        (413, "", False, "payload_too_large"),
        (422, "", False, "bad_request"),
        (400, "", False, "bad_request"),
        (400, "content_policy_violation", False, "content_blocked"),
        (418, "", False, "client_error"),
        (0, "", True, "unknown"),
    ],
)
def test_classify_rules(status, code, retryable, reason):
    rule = classify(status, code)
    assert rule.retryable is retryable
    assert rule.reason == reason


def test_classify_unknown_code_with_5xx_stays_retryable():
    """未知 body code + 5xx 必须保守地按可重试处理（不能误杀本该成功的任务）。"""
    rule = classify(503, "some_new_code_from_upstream")
    assert rule.retryable is True


def test_fatal_rule_carries_message_key():
    assert classify(401).message_key == "error.video.fatal_auth"
    assert classify(400, "content_policy").message_key == "error.video.fatal_content"


# ── 钩子状态机 ────────────────────────────────────────────────────


class FakeTaskManager:
    def __init__(self):
        self.saved = 0

    def update_state(self, **kwargs):
        self.saved += 1


class FakePipeline:
    """最小流水线桩：只提供长任务钩子需要的状态与副作用方法。"""

    def __init__(self, state):
        self.task_id = state.task_id
        self._state = state
        self.task_manager = FakeTaskManager()
        self.emits = []

    def _save_long_task(self):
        self.task_manager.update_state()

    def _emit_long_task(self, message_key, params):
        self.emits.append((message_key, dict(params)))


def _state(**cfg):
    state = SimpleVideoTask(task_id="t_long")
    for k, v in cfg.items():
        setattr(state.long_task, k, v)
    return state


def test_budget_accumulates_from_waited_delta():
    state = _state(enabled=True, timeout_minutes=60)
    p = FakePipeline(state)
    hook = _PipelineLongTaskHook(p)

    hook.notify_busy({"waited_s": 10})
    hook.notify_busy({"waited_s": 40})
    assert state.long_task.waited_s == pytest.approx(40)
    assert state.long_task.started_at      # 首次计入时落时间戳

    # 新一段 BusyTracker：waited_s 回绕到 5 → 只累加 5
    hook.notify_busy({"waited_s": 5})
    assert state.long_task.waited_s == pytest.approx(45)


def test_disabled_hook_never_extends():
    state = _state(enabled=False)
    hook = _PipelineLongTaskHook(FakePipeline(state))

    hook.notify_busy({"waited_s": 999})
    assert state.long_task.waited_s == 0
    assert hook.allow_extend({"waited_s": 999}) is False


def test_allow_extend_until_budget_then_expire():
    state = _state(enabled=True, timeout_minutes=5)      # 300s 预算
    p = FakePipeline(state)
    hook = _PipelineLongTaskHook(p)

    hook.notify_busy({"waited_s": 120})
    assert hook.allow_extend({"waited_s": 120}) is True

    hook.notify_busy({"waited_s": 400})                  # 超过预算
    assert state.long_task.enabled is False
    assert state.long_task.finished_reason == "expired"
    assert hook.allow_extend({"waited_s": 400}) is False
    assert p.emits[-1][0] == "progress.video.long_task.expired"


def test_on_fatal_marks_reason():
    state = _state(enabled=True, timeout_minutes=60)
    p = FakePipeline(state)
    hook = _PipelineLongTaskHook(p)

    hook.on_fatal("auth_invalid")

    assert state.long_task.enabled is False
    assert state.long_task.finished_reason == "non_retryable"
    assert state.long_task.last_reason == "auth_invalid"
    assert p.emits[-1][0] == "progress.video.long_task.non_retryable"


# ── API 层 ────────────────────────────────────────────────────────


class FakeResponse:
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
    def __init__(self):
        self.acquired = 0

    def acquire(self):
        self.acquired += 1

    async def acquire_async(self, stop_event=None):
        self.acquired += 1


class FakeRing:
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


@pytest.fixture
def api(monkeypatch):
    """零退避 + 限速器/报错收集打桩的 AgnesVideoAPI（忙轨上限 2 次便于触发延长）。"""
    limiter = CountingLimiter()
    monkeypatch.setattr(av, "get_video_submit_limiter", lambda: limiter)
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(av, "collect_error_from_exception", lambda *a, **k: None)
    monkeypatch.setattr(av, "_QUEUE_RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(av, "_QUEUE_RETRY_JITTER", 0.0)
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing())
    monkeypatch.setattr(av, "_QUEUE_RETRY_MAX_ATTEMPTS", 2)

    class _Settings:
        agnes_video_busy_retry_attempts = 2

    import core.config as config_mod
    monkeypatch.setattr(config_mod, "get_settings", lambda: _Settings())

    client = av.AgnesVideoAPI(api_key="k1", max_retries=3, retry_base_delay=0.001)
    client._limiter = limiter
    return client


def _patch_sleep(monkeypatch):
    delays = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *a, **k):
        delays.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(av.asyncio, "sleep", fake_sleep)
    return delays


def _busy_then_success(monkeypatch, busy_times):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        if calls["n"] <= busy_times:
            return FakeResponse(503, {"code": "video_queue_full",
                                      "message": "video queue is full"})
        return FakeResponse(200, {"video_id": f"vid{calls['n']}"})

    monkeypatch.setattr(av.requests, "post", fake_post)
    return calls


async def test_long_task_keeps_retrying_beyond_busy_cap(api, monkeypatch):
    """忙轨次数耗尽后，长任务模式让重试继续（间隔不变），直到上游放行。"""
    calls = _busy_then_success(monkeypatch, busy_times=5)
    _patch_sleep(monkeypatch)
    seen = {"extend": 0}

    class Hook:
        def notify_busy(self, payload):
            pass

        def allow_extend(self, payload):
            seen["extend"] += 1
            return True

        def on_fatal(self, reason):
            pass

    api.long_task_hook = Hook()

    video_id = await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert video_id.startswith("vid")
    assert seen["extend"] >= 3          # 2 次额度用完后仍在延长
    # 节奏不变：延长跳仍按常规忙轨走令牌桶（每发一跳取一次），
    # 也就是说长任务模式只延长总时长，不改变提交频率
    assert api._limiter.acquired == calls["n"]


async def test_long_task_disabled_fails_after_busy_cap(api, monkeypatch):
    """未开启（或钩子拒绝延长）时，保持 v8.2 行为：次数耗尽即抛队列满。"""
    _busy_then_success(monkeypatch, busy_times=99)
    _patch_sleep(monkeypatch)

    class Hook:
        def notify_busy(self, payload):
            pass

        def allow_extend(self, payload):
            return False

    api.long_task_hook = Hook()

    with pytest.raises(av.AgnesQueueFullError):
        await api._submit_with_retry({"prompt": "x"}, "t2v")


async def test_non_retryable_400_raises_fatal_without_retry(api, monkeypatch):
    """400 参数错误不再走故障轨重试，直接抛结构化最终结果。"""
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return FakeResponse(400, {"code": "invalid_parameter",
                                  "message": "bad prompt"})

    monkeypatch.setattr(av.requests, "post", fake_post)
    _patch_sleep(monkeypatch)
    fatal = {"reason": ""}

    class Hook:
        def notify_busy(self, payload):
            pass

        def allow_extend(self, payload):
            return True

        def on_fatal(self, reason):
            fatal["reason"] = reason

    api.long_task_hook = Hook()

    with pytest.raises(av.UpstreamFatalError) as exc:
        await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert exc.value.fatal_reason == "bad_request"
    assert exc.value.fatal_message_key == "error.video.fatal_bad_request"
    assert calls["n"] == 1                     # 只打一次，不重试
    assert fatal["reason"] == "bad_request"


async def test_401_raises_auth_fatal(api, monkeypatch):
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return FakeResponse(401, {"message": "Invalid token"})

    monkeypatch.setattr(av.requests, "post", fake_post)
    _patch_sleep(monkeypatch)

    with pytest.raises(av.UpstreamFatalError) as exc:
        await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert exc.value.fatal_reason == "auth_invalid"
    assert calls["n"] == 1


async def test_hook_exception_falls_back_to_fail(api, monkeypatch):
    """钩子异常必须保守处理（按「不允许延长」），不能把异常抛给提交循环。"""
    _busy_then_success(monkeypatch, busy_times=99)
    _patch_sleep(monkeypatch)

    class Hook:
        def notify_busy(self, payload):
            raise RuntimeError("boom")

        def allow_extend(self, payload):
            raise RuntimeError("boom")

    api.long_task_hook = Hook()

    with pytest.raises(av.AgnesQueueFullError):
        await api._submit_with_retry({"prompt": "x"}, "t2v")


# ── 端点 ──────────────────────────────────────────────────────────


class TestLongTaskEndpoint:
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
        return TestClient(app)

    def test_enable_with_default_timeout(self, monkeypatch):
        state = _state()
        client = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_long/long-task", data={"enabled": "true"})

        assert r.status_code == 200
        body = r.json()
        assert body["long_task"]["enabled"] is True
        assert body["long_task"]["timeout_minutes"] == 60
        assert state.long_task.enabled is True
        assert state.long_task.waited_s == 0

    def test_enable_with_custom_timeout_and_reset_budget(self, monkeypatch):
        state = _state(waited_s=900.0, finished_reason="expired")
        client = self._client(monkeypatch, state)

        r = client.post(
            "/api/tasks/t_long/long-task",
            data={"enabled": "true", "timeout_minutes": "30"},
        )

        assert r.status_code == 200
        assert state.long_task.timeout_minutes == 30
        assert state.long_task.waited_s == 0
        assert state.long_task.finished_reason == ""

    def test_reject_out_of_range(self, monkeypatch):
        state = _state()
        client = self._client(monkeypatch, state)

        r = client.post(
            "/api/tasks/t_long/long-task",
            data={"enabled": "true", "timeout_minutes": "999"},
        )

        assert r.status_code == 422
        assert state.long_task.enabled is False

    def test_disable_sets_reason(self, monkeypatch):
        state = _state(enabled=True, timeout_minutes=60)
        client = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_long/long-task", data={"enabled": "false"})

        assert r.status_code == 200
        assert state.long_task.enabled is False
        assert state.long_task.finished_reason == "disabled"

    def test_reject_image_task(self, monkeypatch):
        """图片任务没有视频提交忙轨，端点直接拒绝（前端也已隐藏入口）。"""
        state = _state()
        state.task_type = "image"
        client = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_long/long-task", data={"enabled": "true"})

        assert r.status_code == 400
        assert state.long_task.enabled is False

    def test_resume_keeps_switch_but_resets_budget(self, monkeypatch):
        from web.routes import task_routes

        state = _state(
            enabled=True, timeout_minutes=90, waited_s=1200.0,
            finished_reason="expired", last_reason="service_busy",
        )
        state.status = StepStatus.FAILED
        client = self._client(monkeypatch, state)
        monkeypatch.setattr(task_routes, "get_api_key", lambda: "k")
        monkeypatch.setattr(
            task_routes.deps, "create_pipeline_for_type", lambda *a, **kw: object(),
        )
        monkeypatch.setattr(
            task_routes.app_state, "launch_background_task",
            lambda coro: coro.close(),
        )

        r = client.post("/api/tasks/t_long/resume")

        assert r.status_code == 200
        assert state.long_task.enabled is True          # 开关保留
        assert state.long_task.timeout_minutes == 90    # 配置保留
        assert state.long_task.waited_s == 0            # 预算重置
        assert state.long_task.finished_reason == ""


# ── 设置页全局默认（v8.3）─────────────────────────────────────────


def _fake_config_file(monkeypatch):
    """把核心配置读写换成内存字典，避免读写开发机 config.json。"""
    import core.config as config_mod

    store = {"values": {}}

    def _load():
        return json.loads(json.dumps(store["values"]))

    def _save(cfg):
        store["values"] = json.loads(json.dumps(cfg))

    monkeypatch.setattr(config_mod, "load_config", _load)
    monkeypatch.setattr(config_mod, "save_config", _save)
    return store


def test_global_config_defaults_and_roundtrip(monkeypatch):
    import core.config as config_mod

    _fake_config_file(monkeypatch)
    cfg = config_mod.get_long_task_config()
    assert cfg == {"enabled": False, "minutes": 60}

    entry = config_mod.set_long_task_config(enabled=True, minutes=120)
    assert entry == {"enabled": True, "minutes": 120}
    assert config_mod.get_long_task_config() == entry

    # 越界收敛 + None 保留原值
    entry = config_mod.set_long_task_config(minutes=9999)
    assert entry["minutes"] == LONG_TASK_MAX_MINUTES
    assert entry["enabled"] is True


def test_create_applies_global_default(monkeypatch, tmp_path):
    """全局默认开启时，新建视频任务自动带上长任务模式（创建时应用一次）。"""
    import core.config as config_mod
    from core.task_manager import TaskManager

    monkeypatch.setattr(
        config_mod, "get_long_task_config",
        lambda: {"enabled": True, "minutes": 90},
    )
    import core.task_manager as tm_mod
    monkeypatch.setattr(tm_mod, "get_working_dir", lambda: str(tmp_path))

    state = TaskManager("t_default", dir_name="t_default").create(
        SimpleVideoTask(task_id="t_default")
    )

    assert state.long_task.enabled is True
    assert state.long_task.timeout_minutes == 90
    assert state.long_task.waited_s == 0


def test_create_skips_default_for_image_task(monkeypatch, tmp_path):
    """图片任务没有视频提交忙轨，不套用长任务默认。"""
    import core.config as config_mod
    import core.task_manager as tm_mod
    from core.task_manager import TaskManager
    from models.task import SimpleImageTask

    monkeypatch.setattr(
        config_mod, "get_long_task_config",
        lambda: {"enabled": True, "minutes": 60},
    )
    monkeypatch.setattr(tm_mod, "get_working_dir", lambda: str(tmp_path))

    state = TaskManager("t_img", dir_name="t_img").create(
        SimpleImageTask(task_id="t_img")
    )

    assert state.long_task.enabled is False


def test_config_endpoint_saves_long_task(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web.routes import config_routes

    app = FastAPI()
    app.include_router(config_routes.router)
    saved = {}

    def _set(enabled=None, minutes=None):
        saved.update({"enabled": bool(enabled), "minutes": minutes or 60})
        return dict(saved)

    monkeypatch.setattr(config_routes, "set_long_task_config", _set)
    client = TestClient(app)

    r = client.post("/api/config/long-task", data={"enabled": "true", "minutes": "120"})
    assert r.status_code == 200
    assert saved == {"enabled": True, "minutes": 120}

    r = client.post("/api/config/long-task", data={"enabled": "true", "minutes": "9999"})
    assert r.status_code == 422
