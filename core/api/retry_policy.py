"""core.api.retry_policy — 上游调用统一重试策略（忙轨 / 故障轨两轨模型）

v7.1 归拢：项目内**所有上游调用的重试**收敛到两条轨道，判定与间隔计算集中
在本模块，各 provider 只保留自己的间隔基数（视频提交/上传 30s、图片生成 20s、
Chat 15s）与预算/次数配置。

- **忙轨**（busy）：服务器繁忙类信号 —— HTTP 429、**所有 HTTP 503**（含 body
  无 code 的裸 503）、队列类 body code（``video_queue_full`` /
  ``fail_to_fetch_task``）。
  策略：**首跳 0s 贴着限流**（节奏交给令牌桶，不叠加人工等待）+ 之后**固定
  间隔**（不随次数增长，"勤敲"）+ **次数**封顶（v7.2 由总时长预算改为次数）。

- **故障轨**（fault）：服务侧故障 —— 非忙 5xx、超时、连接错误。
  策略：**间隔逐级加长** ``base × (attempt + 1)``（"少敲"）+ **次数**封顶。

事实依据：``docs/dev/agnes_video_upstream_behavior.md``（上游队列饱和实测返回
裸 503、失败以 HTTP 200 返回等）。

关于「首跳贴着限流」：人工退避与令牌桶等待是**接力关系**（每次重试都是先取令牌
再发请求），两者相加才是真实间隔。因此第 1 次重试不人工等待，真实间隔就等于
配额下限——单 Key 视频提交 ≈60s（1/min）、共享桶 ≈3.75s（20×0.8/min）；多 Key
时桶配额按 Key 数线性放大，重试会先连发用满各 Key 的突发额度，再按 60/N 秒推进。
"""

import random
import time

__all__ = [
    "QUEUE_FULL_CODES",
    "is_busy_signal",
    "busy_delay",
    "fault_delay",
    "BusyTracker",
]

# 上游队列类瞬时错误的 body code：以 503（或 200 + error 对象）形式返回
QUEUE_FULL_CODES = frozenset({"video_queue_full", "fail_to_fetch_task"})


def is_busy_signal(status_code: int, code: str = "") -> bool:
    """判定一次上游响应是否属于「服务器忙」——命中则走忙轨。

    命中条件（任一）：
    - ``status_code == 429``：触发限流 = 忙，换 Key 后配额即恢复；
    - ``status_code == 503``：Service Unavailable = 忙。**不做 body 判定**，
      实测上游队列饱和时正是返回 body 无 code 的裸 503，若按 code 判定会被
      误归故障轨（逐级加长、次数封顶）而在队列排空前就放弃；
    - ``code`` 命中 ``QUEUE_FULL_CODES``：以其他状态码形式返回的队列满信号。

    Args:
        status_code: HTTP 状态码。
        code: 响应体提取的上游 code（可为空）。

    Returns:
        True 表示应走忙轨（首跳 0s 贴着限流 + 之后固定间隔 + 次数封顶）。
    """
    if status_code in (429, 503):
        return True
    return code in QUEUE_FULL_CODES


def busy_delay(base: float, jitter: float = 0.0, attempt: int = 0) -> float:
    """忙轨间隔：**首跳 0s 贴着限流**，之后固定基数（不随次数增长）。

    Args:
        base: 间隔基数（秒）。
        jitter: 抖动上限（秒）；> 0 时在 ``[base, base + jitter)`` 均匀取值，
            用于打散多任务同时重试的尖峰。0 表示严格固定。
        attempt: 本次是第几次忙轨重试（从 0 起）。``0`` = 第 1 次重试 → 返回 0，
            真实节奏完全交给令牌桶（贴着上游配额下限，避免人工等待与桶等待叠加）。

    Returns:
        本次忙轨退避秒数。
    """
    if attempt <= 0:
        return 0.0
    if jitter > 0:
        return base + random.uniform(0, jitter)
    return base


def fault_delay(base: float, attempt: int) -> float:
    """故障轨间隔：``base × (attempt + 1)`` 逐级加长。

    Args:
        base: 间隔基数（秒）。
        attempt: 已重试次数（从 0 起）。

    Returns:
        本次故障轨退避秒数。
    """
    return base * (attempt + 1)


class BusyTracker:
    """忙轨重试次数封顶（v7.2：由「总时长预算」改为「次数」）。

    为什么用次数：人工退避与令牌桶等待是接力关系，单 Key 下真实间隔恒等于
    上游配额（视频提交 1/min → 60s/次），此时「15 次」与旧的「900s 预算」
    等价；而多 Key 下次数封顶让重试能真正打满各 Key 的合计配额，跑完同一
    次数所花的总时间随 Key 数缩短。

    调用方约定：``exhausted()`` 为 False 时，``retries += 1`` 后退避重试，
    并用 ``retries - 1`` 作为 ``busy_delay`` 的 ``attempt``（第 1 次重试 → 0s）。
    """

    def __init__(self, max_attempts: int):
        """初始化。

        Args:
            max_attempts: 忙轨最多重试次数（<1 时收敛为 1，避免完全不让重试）。
        """
        self.max_attempts = max(1, int(max_attempts))
        self.retries = 0
        self.started_at = time.monotonic()

    @property
    def waited_s(self) -> float:
        """已等待秒数（只用于日志与用户可见的等待时长，不参与封顶判定）。"""
        return time.monotonic() - self.started_at

    def exhausted(self) -> bool:
        """本次忙轨重试次数是否已用尽。"""
        return self.retries >= self.max_attempts