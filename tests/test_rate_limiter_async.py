"""2.3 限速器异步化测试（_try_acquire 解耦 / acquire_async / 除零防护）。"""
import asyncio
import threading
import time

import pytest

from core.api.rate_limiter import AgnesRateLimiter


def test_rate_zero_does_not_divide_by_zero():
    """速率 0（如 AGNES_RATE_LIMIT=0）直接放行，不除零崩溃（2.3 边界修复）。"""
    limiter = AgnesRateLimiter(rate_per_minute=0, max_burst=1)
    assert limiter.refill_rate == 0
    assert limiter._try_acquire() is None  # 放行
    limiter.acquire()  # 同步路径不抛异常


def test_sync_acquire_math():
    """同步 acquire：桶满立即获取，消耗后令牌减少（向后兼容）。"""
    limiter = AgnesRateLimiter(rate_per_minute=60, max_burst=10)  # 1 token/s, 桶 10
    assert limiter.tokens == 10.0
    t0 = time.monotonic()
    limiter.acquire()
    assert time.monotonic() - t0 < 0.1
    assert limiter.tokens == 9.0


async def test_acquire_async_respects_stop_event():
    """acquire_async：停止事件置位时跳过等待立即放行，且不消耗令牌。"""
    limiter = AgnesRateLimiter(rate_per_minute=60, max_burst=1)
    limiter.acquire()  # 消耗桶中唯一令牌
    assert limiter.tokens == 0.0

    stop = asyncio.Event()
    stop.set()
    t0 = time.monotonic()
    await limiter.acquire_async(stop_event=stop)
    assert time.monotonic() - t0 < 0.5  # 未等待
    assert limiter.tokens == 0.0  # 停止时不消耗令牌


async def test_acquire_async_waits_without_stop():
    """无停止事件时正常等待令牌补充（分片睡眠，总量≈等待时长）。"""
    limiter = AgnesRateLimiter(rate_per_minute=60, max_burst=1)  # 1 token/s
    limiter.acquire()  # 消耗唯一令牌
    t0 = time.monotonic()
    await limiter.acquire_async()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.9, f"应等待约 1s 补令牌，实际 {elapsed:.2f}s"
    assert limiter.tokens == 0.0  # 获取成功后令牌被消耗


async def test_acquire_async_cancellable():
    """acquire_async 可被任务取消（asyncio.CancelledError），不遗留桶状态。"""
    limiter = AgnesRateLimiter(rate_per_minute=60, max_burst=1)
    limiter.acquire()

    task = asyncio.create_task(limiter.acquire_async())
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert limiter.tokens == 0.0  # 取消不消耗令牌、不破坏桶


@pytest.mark.slow  # 真实计时验证 6 线程按 32/min 排队（约 11s），默认排除，CI 全量执行
def test_sync_acquire_no_livelock_after_burst_exhausted():
    """回归：同步 acquire 在突发令牌耗尽、多并发等待下不活锁。

    复现现场：共享桶 32/min、突发 8、先耗尽突发令牌，再起 6 个并发等待者。
    修复前：每个等待者 sleep 后循环 re-acquire，因 ``last_refill`` 被预支到未来，
    ``elapsed≈0`` 令牌永不累积，所有等待者永久卡死（0 个成功）。
    修复后：同步 acquire 采用预支语义，sleep 足够 wait_time 后即视为已获取。
    6 个等待者应在约 6 × (60/32) ≈ 11.25s 内全部通过，故设 30s 硬上限。
    """
    limiter = AgnesRateLimiter(rate_per_minute=32, max_burst=8)  # 与回归现场一致
    # 耗尽 8 个突发令牌（模拟回归启动的 8 任务风暴）
    for _ in range(8):
        assert limiter._try_acquire() is None

    results = []
    done_evt = threading.Event()

    def worker(i):
        t0 = time.monotonic()
        limiter.acquire()
        results.append((i, time.monotonic() - t0))
        if len(results) == 6:
            done_evt.set()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()

    # 6 个等待者必须在 30s 内全部获取到令牌（修复前 6 个全部卡死 → 断言失败）
    assert done_evt.wait(timeout=30), (
        f"活锁复现：30s 后仅 {len(results)}/6 个等待者获得令牌"
    )
    for t in threads:
        t.join(15)
    assert len(results) == 6
