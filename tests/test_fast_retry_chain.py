"""快速重试「两轮之间自动接力」（v8.4）回归测试。

需求（2026-11-19）：一轮快速重试到期后，回到常规节奏重试 X 分钟，
X 到点自动再开一轮；X 由快速重试开关的配套参数「两轮间隔（分钟）」控制。

覆盖：
- 到期 → 进入接力等待（chain_pending + chain_started_at）
- 未到 X 分钟 → 不接力；满 X 分钟 → 自动开新一轮（rounds+1、enabled=True、间隔沿用）
- 用户手动关闭 / 提交成功 → 停止接力
- 参数边界 clamp
- 端点：interval_minutes 透传、越界 422、关闭时清接力
"""
from datetime import datetime, timedelta

import pytest

from core.api.fast_retry import (
    FAST_RETRY_DEFAULT_INTERVAL_MINUTES,
    FAST_RETRY_MAX_INTERVAL_MINUTES,
    FAST_RETRY_MIN_INTERVAL_MINUTES,
    clamp_interval_minutes,
)
from core.pipelines import _PipelineFastRetryHook
from models.task import SimpleVideoTask

BUSY = {"status": 503, "code": "video_queue_full", "attempt": 0, "waited_s": 0.0}


@pytest.fixture(autouse=True)
def _isolate_global_auto(monkeypatch):
    """隔离开发机的全局配置：默认 auto=False、两轮间隔 5 分钟。"""
    import core.pipelines as pipelines_mod

    monkeypatch.setattr(
        pipelines_mod, "get_fast_retry_config",
        lambda: {"auto": False, "per_minute": 30, "minutes": 3, "interval_minutes": 5},
    )


class FakeTaskManager:
    def __init__(self):
        self.saved = 0

    def update_state(self, **kwargs):
        self.saved += 1


class FakePipeline:
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
    state = SimpleVideoTask(task_id="t_chain")
    for k, v in cfg.items():
        setattr(state.fast_retry, k, v)
    return state


def _ago(minutes: float) -> str:
    return (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")


# ── 参数边界 ──────────────────────────────────────────────────────


def test_clamp_interval_minutes():
    assert FAST_RETRY_DEFAULT_INTERVAL_MINUTES == 5
    assert clamp_interval_minutes(None) == 5
    assert clamp_interval_minutes(0) == 5
    assert clamp_interval_minutes("abc") == 5
    assert clamp_interval_minutes(1) == FAST_RETRY_MIN_INTERVAL_MINUTES
    assert clamp_interval_minutes(999) == FAST_RETRY_MAX_INTERVAL_MINUTES
    assert clamp_interval_minutes(12) == 12


# ── 状态机 ────────────────────────────────────────────────────────


def test_expire_enters_chain_wait():
    """到期后进入接力等待，并记录到期时刻用于计算 X 分钟。"""
    state = _state(enabled=True, minutes=1, started_at=_ago(2), interval_minutes=5)
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    assert hook.decide(3, BUSY) is None

    assert state.fast_retry.enabled is False
    assert state.fast_retry.finished_reason == "expired"
    assert state.fast_retry.chain_pending is True
    assert state.fast_retry.chain_started_at          # 已记录到期时刻
    assert p.emits[-1][0] == "progress.video.fast_retry.expired"
    assert p.emits[-1][1]["x"] == 5


def test_chain_waits_until_interval_elapsed():
    """未满 X 分钟：保持关闭状态，继续常规节奏。"""
    state = _state(
        enabled=False, chain_pending=True, chain_started_at=_ago(1),
        interval_minutes=5, per_minute=30, minutes=3,
    )
    hook = _PipelineFastRetryHook(FakePipeline(state))

    assert hook.decide(5, BUSY) is None
    assert state.fast_retry.enabled is False
    assert state.fast_retry.rounds == 0


def test_chain_starts_new_round_after_interval():
    """满 X 分钟：自动再开一轮，轮次 +1，参数沿用。"""
    state = _state(
        enabled=False, chain_pending=True, chain_started_at=_ago(6),
        interval_minutes=5, per_minute=30, minutes=3,
    )
    p = FakePipeline(state)
    hook = _PipelineFastRetryHook(p)

    interval = hook.decide(6, BUSY)

    assert interval == pytest.approx(2.0)        # 30 次/分钟 → 2s
    assert state.fast_retry.enabled is True
    assert state.fast_retry.rounds == 1
    assert state.fast_retry.chain_pending is False   # 本轮开始，等待状态清空
    assert state.fast_retry.auto is True
    assert p.emits[-1][0] == "progress.video.fast_retry.chain"
    assert p.emits[-1][1]["i"] == 5 and p.emits[-1][1]["n"] == 1


def test_chain_rounds_increment_on_each_round():
    state = _state(
        enabled=False, chain_pending=True, chain_started_at=_ago(10),
        interval_minutes=5, per_minute=60, minutes=3, rounds=2,
    )
    hook = _PipelineFastRetryHook(FakePipeline(state))

    hook.decide(7, BUSY)

    assert state.fast_retry.rounds == 3


def test_success_stops_chain():
    """提交成功：清 available / 接力等待，任务不再自动开新轮。"""
    state = _state(
        enabled=True, available=True, chain_pending=True,
        chain_started_at=_ago(9), interval_minutes=5, attempts=12,
    )
    p = FakePipeline(state)

    _PipelineFastRetryHook(p).on_success()

    assert state.fast_retry.available is False
    assert state.fast_retry.enabled is False
    assert state.fast_retry.chain_pending is False
    assert state.fast_retry.finished_reason == "success"


# ── 端点 ──────────────────────────────────────────────────────────


class TestFastRetryEndpointInterval:
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
                self.saved += 1

        monkeypatch.setattr(task_routes, "TaskManager", _TM)
        monkeypatch.setattr(task_routes.app_state, "active_pipelines", {})
        # 端点内部是惰性 import，需要打桩到 core.config 本体
        import core.config as config_mod
        monkeypatch.setattr(config_mod, "get_fast_retry_config", lambda: {
            "auto": False, "per_minute": 30, "minutes": 3, "interval_minutes": 5,
        })
        return TestClient(app)

    def test_enable_passes_interval(self, monkeypatch):
        state = _state(available=True)
        client = self._client(monkeypatch, state)

        r = client.post(
            "/api/tasks/t_chain/fast-retry",
            data={"enabled": "true", "per_minute": "30", "minutes": "3",
                  "interval_minutes": "10"},
        )

        assert r.status_code == 200
        assert state.fast_retry.interval_minutes == 10
        assert state.fast_retry.chain_pending is False

    def test_reject_out_of_range_interval(self, monkeypatch):
        state = _state(available=True)
        client = self._client(monkeypatch, state)

        r = client.post(
            "/api/tasks/t_chain/fast-retry",
            data={"enabled": "true", "interval_minutes": "999"},
        )

        assert r.status_code == 422
        assert state.fast_retry.enabled is False

    def test_disable_clears_chain(self, monkeypatch):
        state = _state(
            enabled=True, available=True, chain_pending=True,
            chain_started_at=_ago(3), interval_minutes=5,
        )
        client = self._client(monkeypatch, state)

        r = client.post("/api/tasks/t_chain/fast-retry", data={"enabled": "false"})

        assert r.status_code == 200
        assert state.fast_retry.enabled is False
        assert state.fast_retry.chain_pending is False
        assert state.fast_retry.chain_started_at == ""
