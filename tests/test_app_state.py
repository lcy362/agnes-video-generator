"""web/app_state.py 补测：加权信号量 / 并发上限 / per-task 锁 / 后台任务 / 启动清理。

自包含，不触网；异步用例依赖 pytest.ini 的 asyncio_mode=auto。

用法:
    .venv/bin/python -m pytest tests/test_app_state.py -q
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

import pytest

import web.app_state as app_state
from web.app_state import WeightedSemaphore


# ═══════════════════════════════════════════════
# WeightedSemaphore
# ═══════════════════════════════════════════════

class TestWeightedSemaphore:
    async def test_acquire_release(self):
        s = WeightedSemaphore(10)
        await s.acquire(3)
        assert s.current == 3
        await s.release(3)
        assert s.current == 0

    async def test_acquire_waits_when_over_capacity(self):
        s = WeightedSemaphore(5)
        await s.acquire(5)
        released = asyncio.Event()

        async def contender():
            await s.acquire(1)
            released.set()

        t = asyncio.create_task(contender())
        await asyncio.sleep(0)
        assert not released.is_set(), "容量不足时应阻塞"
        await s.release(5)
        await asyncio.wait_for(t, 1)
        assert released.is_set()

    async def test_acquire_over_max_weight_raises(self):
        s = WeightedSemaphore(5)
        with pytest.raises(ValueError, match="weight"):
            await s.acquire(6)

    async def test_update_max_weight_up_scales(self):
        s = WeightedSemaphore(5)
        await s.acquire(2)
        await s.update_max_weight(11)
        assert s.max_weight == 11  # ≥ current
        s2 = WeightedSemaphore(5)
        await s2.update_max_weight(0)  # ≤ 0 → no-op
        assert s2.max_weight == 5

    async def test_utilization(self):
        s = WeightedSemaphore(4)
        assert s.utilization == 0
        await s.acquire(2)
        assert s.utilization == 0.5
        s_zero = WeightedSemaphore(0)
        assert s_zero.utilization == 0


# ═══════════════════════════════════════════════
# 并发上限 / 信号量访问
# ═══════════════════════════════════════════════

class TestConcurrencyLimit:
    def test_get_rate_limit(self):
        assert app_state.get_rate_limit() > 0

    def test_effective_limit_from_rate_limiter(self, monkeypatch):
        class _FakeLimiter:
            stats = {"effective_rate_per_min": 24}

        monkeypatch.setattr(
            "core.api.rate_limiter.get_rate_limiter",
            lambda: _FakeLimiter(),
        )
        assert app_state._effective_concurrency_limit() == 12

    def test_effective_limit_zero_rate_falls_back(self, monkeypatch):
        class _Zero:
            stats = {"effective_rate_per_min": 0}

        monkeypatch.setattr("core.api.rate_limiter.get_rate_limiter", lambda: _Zero())
        assert app_state._effective_concurrency_limit() == app_state.get_rate_limit() // 2

    def test_effective_limit_exception_falls_back(self, monkeypatch):
        def boom():
            raise RuntimeError("no limiter")

        monkeypatch.setattr("core.api.rate_limiter.get_rate_limiter", boom)
        assert app_state._effective_concurrency_limit() == app_state.get_rate_limit() // 2

    def test_get_semaphore_no_loop_runtime_error(self, monkeypatch):
        def no_loop():
            raise RuntimeError("no running loop")

        monkeypatch.setattr(asyncio, "get_running_loop", no_loop)
        # 目标与当前不同但无法创建任务 → 直接返回全局信号量，不抛
        monkeypatch.setattr(app_state, "_effective_concurrency_limit", lambda: 99)
        assert app_state.get_semaphore() is app_state._pipeline_semaphore


# ═══════════════════════════════════════════════
# per-task 锁
# ═══════════════════════════════════════════════

class TestPipelineLocks:
    def test_get_and_release_lock(self):
        app_state._pipeline_locks.clear()
        lock = app_state.get_pipeline_lock("t1")
        assert isinstance(lock, asyncio.Lock)
        assert app_state.get_pipeline_lock("t1") is lock  # 复用
        app_state.release_pipeline_lock("t1")
        assert "t1" not in app_state._pipeline_locks
        # 释放不存在的锁不报错
        app_state.release_pipeline_lock("nope")
        app_state._pipeline_locks.clear()


# ═══════════════════════════════════════════════
# 后台任务
# ═══════════════════════════════════════════════

class TestBackgroundTask:
    async def test_launch_and_discard(self):
        app_state.background_tasks.clear()
        called = []

        async def coro():
            await asyncio.sleep(0)
            called.append(True)

        task = app_state.launch_background_task(coro())
        assert task in app_state.background_tasks
        await task
        # 回调已 discard
        await asyncio.sleep(0)
        assert task not in app_state.background_tasks
        app_state.background_tasks.clear()


# ═══════════════════════════════════════════════
# 启动初始化清理
# ═══════════════════════════════════════════════

class TestInitRuntimeState:
    def test_resets_stale_tasks_to_pending(self, tmp_path, monkeypatch):
        wd = str(tmp_path / "wd")
        os.makedirs(os.path.join(wd, "t_running"))
        os.makedirs(os.path.join(wd, "t_queued"))
        os.makedirs(os.path.join(wd, "t_done"))
        monkeypatch.setattr(app_state, "get_working_dir", lambda: wd)
        import json

        with open(os.path.join(wd, "t_running", "task_state.json"), "w") as f:
            json.dump({"status": "running", "step": "x"}, f)
        with open(os.path.join(wd, "t_queued", "task_state.json"), "w") as f:
            json.dump({"status": "queued"}, f)
        with open(os.path.join(wd, "t_done", "task_state.json"), "w") as f:
            json.dump({"status": "success"}, f)

        app_state.init_runtime_state()

        for t in ("t_running", "t_queued"):
            assert json.load(open(os.path.join(wd, t, "task_state.json")))["status"] == "pending"
        assert json.load(open(os.path.join(wd, "t_done", "task_state.json")))["status"] == "success"
        assert os.path.isdir(os.path.join(wd, "uploads"))

    def test_bad_json_task_is_skipped(self, tmp_path, monkeypatch):
        wd = str(tmp_path / "wd2")
        os.makedirs(os.path.join(wd, "t_bad"))
        with open(os.path.join(wd, "t_bad", "task_state.json"), "w") as f:
            f.write("{not json")
        monkeypatch.setattr(app_state, "get_working_dir", lambda: wd)
        app_state.init_runtime_state()  # 不抛异常

    def test_no_task_state_ignored(self, tmp_path, monkeypatch):
        wd = str(tmp_path / "wd3")
        os.makedirs(os.path.join(wd, "t_empty"))
        monkeypatch.setattr(app_state, "get_working_dir", lambda: wd)
        app_state.init_runtime_state()