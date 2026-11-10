"""core.api.fast_retry — 快速重试模式（v7.7）的协议与参数约束。

背景（实测 2026-11-06）：上游 503 ``video_queue_full`` 阶段**不会触发 429**
——单 Key 背靠背连打 26 次全部 503、零限流；且被拒请求不建任务、不消耗渲染
配额。因此在队列饱和时段提高探测频率是安全的，只是现有忙轨固定 30–60s
间隔对多 Key 毫无加速（多 Key 只让「首跳 0s」受益，第 3 跳起仍恒定 30–60s）。

本模块只定义**可注入的钩子协议**与参数边界，不持有任何重试状态：

- 判定逻辑仍在 ``core/api/retry_policy.py``（忙轨/故障轨），本模式只替换
  忙轨的**等待节奏**；
- 是否开启、持续多久、剩余时间，全部由任务状态（``FastRetryConfig``）
  承载，由流水线实现钩子并落盘；
- ``AgnesVideoAPI`` 只持有可选的 ``fast_retry_hook``，默认 ``None`` 时
  行为与未引入本功能时**完全一致**（零回归）。

钩子协议（duck typing，不强制继承）::

    class Hook:
        def decide(self, busy_attempt: int, payload: dict) -> float | None:
            \"\"\"返回 None = 走常规忙轨；返回秒数 = 本跳快速模式间隔。\"\"\"

        def on_probe(self, probe: int) -> None:
            \"\"\"快速模式**每发出一跳**就回调（可选）。

            与 ``decide`` 的区别：decide 只在收到忙信号时才被调用，而连打期间
            上游可能回非忙响应（非队列 5xx / 多 Key 轮换 429 / 请求超时），
            那些跳不会进 decide。只靠 decide 同步「已打次数」会让面板上的
            「已发 N 次」冻结不动，因此 API 层在每跳发包后无条件调用本方法。

            ``probe`` = 本次提交循环累计发出的请求数（含本跳）。
            \"\"\"

        def on_success(self, probe: int = 0) -> None:
            \"\"\"提交成功时回调（用于把 enabled 置 False 并标记 success）。

            ``probe`` = 快速模式期间已发出的请求次数（含成功那跳）。
            \"\"\"

``payload`` 字段：``status`` / ``code`` / ``attempt``（常规忙轨已重试次数）/
``waited_s``（本次忙轨累计等待秒数）/ ``probe``（快速模式已打次数）。

日志约定：快速模式每一跳都打印请求原文与响应原文（``[FastRetry] probe #N
→ POST ...`` / ``[FastRetry] probe #N ← HTTP ...``），常规忙轨保持原日志量。
"""

__all__ = [
    "FAST_RETRY_AVAILABLE_AFTER",
    "FAST_RETRY_MIN_PER_MINUTE",
    "FAST_RETRY_MAX_PER_MINUTE",
    "FAST_RETRY_MIN_MINUTES",
    "FAST_RETRY_MAX_MINUTES",
    "clamp_params",
    "interval_seconds",
]

#: 连续多少次忙信号后向前端开放开关（用户需求：连续两次 503 之后出现开关）
FAST_RETRY_AVAILABLE_AFTER = 2

#: 每分钟次数 x 的合法区间（上限 120 ≈ 每 0.5s 一跳，再高没有意义且日志爆炸）
FAST_RETRY_MIN_PER_MINUTE = 1
FAST_RETRY_MAX_PER_MINUTE = 120

#: 持续分钟数 y 的合法区间
FAST_RETRY_MIN_MINUTES = 1
FAST_RETRY_MAX_MINUTES = 30


def clamp_params(per_minute: int, minutes: int) -> tuple[int, int]:
    """把用户输入的 (x, y) 收敛到合法区间。

    Args:
        per_minute: 每分钟重试次数。
        minutes: 持续分钟数。

    Returns:
        ``(per_minute, minutes)``，均在合法区间内（非法输入回落到下限）。
    """
    try:
        x = int(per_minute)
    except (TypeError, ValueError):
        x = FAST_RETRY_MIN_PER_MINUTE
    try:
        y = int(minutes)
    except (TypeError, ValueError):
        y = FAST_RETRY_MIN_MINUTES
    x = max(FAST_RETRY_MIN_PER_MINUTE, min(FAST_RETRY_MAX_PER_MINUTE, x))
    y = max(FAST_RETRY_MIN_MINUTES, min(FAST_RETRY_MAX_MINUTES, y))
    return x, y


def interval_seconds(per_minute: int) -> float:
    """快速模式两跳之间的间隔（秒），下限 0.5s 防止除零。"""
    x = max(1, int(per_minute or 1))
    return max(0.5, 60.0 / x)
