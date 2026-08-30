"""2.3 限速器异步化测试（_try_acquire 解耦 / acquire_async / 除零防护）。"""
import asyncio
import time

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
