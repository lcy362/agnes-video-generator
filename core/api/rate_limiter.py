"""core.api.rate_limiter — Agnes API 限速器（令牌桶算法）+ 429 换 Key 重试封装

所有 Agnes API 调用通过**共享令牌桶**限速（Chat / Image / 上传 / 轮询），
视频提交（``POST /videos``）走**独立令牌桶**（服务端 1/min 硬限制）。

多 Key 模式下，桶配额按 Key 数线性缩放：
- 共享桶：20 × Key 数 × 0.8（保留 20% 余量）
- 视频提交桶：1 × Key 数（不降额，429 换 Key 兜底）

用法::

    from core.api.rate_limiter import get_rate_limiter, get_video_submit_limiter

    # 共享桶：chat / image / 上传 / 轮询
    limiter = get_rate_limiter()
    limiter.acquire()
    resp = requests.post(url, ...)

    # 视频提交独立桶
    get_video_submit_limiter().acquire()

环境变量:
    AGNES_RATE_LIMIT: 共享桶每分钟最大调用次数，默认 20 × Key 数
    AGNES_RATE_BURST: 共享桶容量，默认 4 × Key 数
    AGNES_VIDEO_RATE_LIMIT: 视频提交桶速率，默认 1 × Key 数
    AGNES_VIDEO_RATE_BURST: 视频提交桶容量，默认 1 × Key 数
"""

import asyncio
import logging
import threading
import time
from typing import Optional

from core.api.key_manager import get_key_ring

logger = logging.getLogger(__name__)

# 单 Key 共享接口原始配额（Agnes 限制）
_KEY_BASE_RATE = 20
# 单 Key 视频提交配额（Agnes 独立限制 1/min）
_VIDEO_SUBMIT_RATE = 1
# 共享桶保留 20% 余量
_SAFETY_FACTOR = 0.8
# 视频提交桶不降额：服务端 1/min 已很严，且 429 换 Key 兜底
_VIDEO_SAFETY_FACTOR = 1.0


def _key_count() -> int:
    try:
        return len(get_key_ring())
    except Exception:
        return 1


def _effective_rate() -> float:
    """共享桶有效速率 = 单 Key 配额 × Key 数 × 安全系数。"""
    from core.config import get_settings
    limit = get_settings().agnes_rate_limit
    if limit is None or limit <= 0:
        limit = _KEY_BASE_RATE * _key_count()
    return limit * _SAFETY_FACTOR


def _video_submit_rate() -> float:
    """视频提交桶速率 = 1 × Key 数（AGNES_VIDEO_RATE_LIMIT 可覆盖）。

    注：若服务端对视频提交是全局限 1/min（而非 per-Key），
    设置 AGNES_VIDEO_RATE_LIMIT=1 即可，无需改代码。
    """
    from core.config import get_settings
    limit = get_settings().agnes_video_rate_limit
    if limit is None or limit <= 0:
        limit = _VIDEO_SUBMIT_RATE * _key_count()
    return limit * _VIDEO_SAFETY_FACTOR


def _max_burst() -> int:
    """共享桶容量随 Key 数上调：4 × Key 数，否则高并发被突发容量卡住。"""
    from core.config import get_settings
    burst = get_settings().agnes_rate_burst
    if burst is None or burst <= 0:
        burst = 4 * _key_count()
    return burst


def _video_max_burst() -> int:
    """视频提交桶容量 = 1 × Key 数：允许每 Key 立即提交一次，随后受 1/min 限制。"""
    from core.config import get_settings
    burst = get_settings().agnes_video_rate_burst
    if burst is None or burst <= 0:
        burst = _key_count()
    return burst


class AgnesRateLimiter:
    """令牌桶限速器（线程安全）。

    在多线程 / asyncio.to_thread / 纯同步场景下均可安全使用。
    当令牌不足时，``acquire()`` 会阻塞当前线程直到令牌可用。

    Attributes:
        max_tokens: 桶容量（突发上限）。
        refill_rate: 每秒补充的令牌数。
    """

    def __init__(self, rate_per_minute: float | None = None,
                 max_burst: int | None = None):
        """初始化限速器。

        Args:
            rate_per_minute: 每分钟允许的调用次数；None 时取当前 Key 数下的有效速率。
            max_burst: 令牌桶最大容量（允许短时突发）；None 时取当前 Key 数下的容量。
        """
        if rate_per_minute is None:
            rate_per_minute = _effective_rate()
        if max_burst is None:
            max_burst = _max_burst()
        self.rate_per_minute = rate_per_minute
        self.max_tokens = min(max_burst, rate_per_minute)
        self.refill_rate = rate_per_minute / 60.0  # tokens per second
        self.tokens = float(self.max_tokens)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._total_waits = 0
        self._total_wait_seconds = 0.0

    def _try_acquire(self) -> Optional[float]:
        """尝试获取令牌（线程安全）。返回 None=成功；否则返回需等待秒数。

        优化路线图 2.3：等待计算与阻塞解耦，供同步 ``acquire`` 与异步
        ``acquire_async`` 共用；速率 ≤ 0（如 ``AGNES_RATE_LIMIT=0``）时直接
        放行，避免此前 ``wait_time = 1/0`` 除零崩溃。
        """
        if self.refill_rate <= 0:
            return None
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(
                self.max_tokens,
                self.tokens + elapsed * self.refill_rate,
            )
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return None

            # 需要等待的时间
            wait_time = (1.0 - self.tokens) / self.refill_rate
            self.tokens = 0.0
            # 更新 refill 时间基准，防止 sleep 期间令牌被其他线程"偷走"
            self.last_refill = now + wait_time
            return wait_time

    def _record_wait(self, wait_time: float) -> None:
        if wait_time > 0.05:
            self._total_waits += 1
            self._total_wait_seconds += wait_time
            logger.info(
                f"[RateLimiter] 限速等待 {wait_time:.1f}s "
                f"(累计等待 {self._total_waits} 次, "
                f"{self._total_wait_seconds:.0f}s)"
            )

    def acquire(self) -> None:
        """阻塞式获取一个令牌（同步场景 / 脚本 / 测试用）。

        如果桶中有令牌，立即消耗并返回；否则 ``time.sleep()`` 直到令牌可用。
        """
        while True:
            wait_time = self._try_acquire()
            if wait_time is None:
                return
            self._record_wait(wait_time)
            time.sleep(wait_time)

    async def acquire_async(self, stop_event: asyncio.Event | None = None) -> None:
        """异步原生获取令牌（优化路线图 2.3）。

        等待在事件循环中执行（不再占线程池）；可被任务取消打断，或经
        ``stop_event`` 提前放行（停止后调用方不会再发请求，无需令牌）。
        """
        while True:
            wait_time = self._try_acquire()
            if wait_time is None:
                return
            self._record_wait(wait_time)
            remaining = wait_time
            while remaining > 0:
                if stop_event is not None and stop_event.is_set():
                    return
                await asyncio.sleep(min(0.1, remaining))
                remaining -= 0.1
            # 预支语义（与同步 acquire 一致）：等待完成即视为已获取令牌。
            # 注意不能再调用 _try_acquire()——last_refill 已被推进到
            # now+wait_time，再次计算会因 elapsed≈0 而永远不足。
            return

    @property
    def stats(self) -> dict:
        """返回限速器统计信息。"""
        return {
            "total_waits": self._total_waits,
            "total_wait_seconds": round(self._total_wait_seconds, 1),
            "effective_rate_per_min": round(self.rate_per_minute, 1),
            "max_burst": self.max_tokens,
            "key_count": _key_count(),
        }


# ═══════════════════════════════════════════════════
# 双单例
# ═══════════════════════════════════════════════════

_instance: AgnesRateLimiter | None = None
_video_instance: AgnesRateLimiter | None = None
_instance_lock = threading.Lock()


def get_rate_limiter() -> AgnesRateLimiter:
    """共享桶：chat / image / 上传 / 轮询（20 × Key 数 × 0.8 次/分）。"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AgnesRateLimiter()
                logger.info(
                    f"[RateLimiter] 共享桶初始化: {_instance.rate_per_minute:.0f} 次/分钟 "
                    f"(Key 数 {_key_count()}), 突发上限 {_instance.max_tokens}"
                )
    return _instance


def get_video_submit_limiter() -> AgnesRateLimiter:
    """视频提交独立桶：1 × Key 数 次/分。"""
    global _video_instance
    if _video_instance is None:
        with _instance_lock:
            if _video_instance is None:
                _video_instance = AgnesRateLimiter(
                    rate_per_minute=_video_submit_rate(),
                    max_burst=_video_max_burst(),
                )
                logger.info(
                    f"[RateLimiter] 视频提交桶初始化: {_video_instance.rate_per_minute:.0f} 次/分钟 "
                    f"(Key 数 {_key_count()}), 突发上限 {_video_instance.max_tokens}"
                )
    return _video_instance


def reset_rate_limiter() -> None:
    """重置限速器（Key 数变更或测试用），同时重建两个单例。"""
    global _instance, _video_instance
    with _instance_lock:
        _instance = None
        _video_instance = None


# ═══════════════════════════════════════════════════
# 429 换 Key + 指数退避统一封装
# ═══════════════════════════════════════════════════

def request_with_key_rotation(
    requester,
    url: str,
    *,
    max_retries: int = 3,
    retry_base_delay: float = 20.0,
    key_ring=None,
    **requester_kwargs,
):
    """429 换 Key 立即重试；全 Key 429 或 5xx/超时/连接错误才指数退避。

    规则：
    1. 每请求前 key_ring.next()（round-robin，均匀分摊），生成带当前 Key 的 headers
    2. 429 且 has_multiple() -> key_ring.rotate() 立即重试（不 sleep、不计入退避）
       —— Key 级隔离限速，换 Key 后配额是满的
    3. 所有 Key 均 429（rotation 计数达到 len(keys) × 退避上限）-> 指数退避
    4. 5xx / 超时 / 连接错误 -> 同 Key 指数退避（保持现状）

    Args:
        requester: 可调用 (url, headers, **kw) -> requests.Response。
        url: 请求 URL。
        max_retries: 退避重试上限。
        retry_base_delay: 指数退避基数（秒），delay = 基数 × (retries + 1)。
        key_ring: KeyRing 实例；None 时取全局单例。
        **requester_kwargs: 透传给 requester（json/timeout 等，不含 headers——
            headers 由本函数基于当前 Key 自动生成）。

    Returns:
        requests.Response（429 换 Key 重试可能返回最终成功的响应）。

    Raises:
        requests.exceptions.RequestException: 连接/超时错误在退避耗尽后抛出。
    """
    import requests

    ring = key_ring or get_key_ring()
    base_headers = requester_kwargs.pop("headers", None) or {}
    retries = 0
    rotations = 0
    max_rotations = len(ring) * max_retries
    while True:
        # 每请求前轮转 Key：round-robin 均匀分摊；429 换 Key（rotate 推进计数）后
        # 下次 next() 自然取到下一个 Key
        headers = {**base_headers, "Authorization": f"Bearer {ring.next()}"}
        try:
            resp = requester(url, headers=headers, **requester_kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            if retries < max_retries:
                delay = retry_base_delay * (retries + 1)
                logger.warning(f"[KeyRotation] {type(e).__name__}, 退避 {delay}s 后重试")
                time.sleep(delay)
                retries += 1
                continue
            raise
        if resp.status_code == 429:
            if ring.has_multiple() and rotations < max_rotations:
                rotations += 1
                ring.rotate()
                logger.warning(f"[KeyRotation] HTTP 429, 换 Key 立即重试 (rotation {rotations})")
                continue  # 换 Key 后无配额缺口，立即重发
            if retries < max_retries:
                delay = retry_base_delay * (retries + 1)
                logger.warning(f"[KeyRotation] 全 Key 429, 退避 {delay}s 后重试")
                time.sleep(delay)
                retries += 1
                continue
            return resp  # 全部耗尽，交给调用方 collect_error + raise
        if resp.status_code >= 500 and retries < max_retries:
            delay = retry_base_delay * (retries + 1)
            logger.warning(f"[KeyRotation] HTTP {resp.status_code}, 退避 {delay}s 后重试")
            time.sleep(delay)
            retries += 1
            continue
        return resp
