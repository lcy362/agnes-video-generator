"""core.api.long_task — 长任务模式（v8.3）的协议、参数边界与默认值。

背景：队列饱和时忙轨默认按**次数**封顶（``AGNES_VIDEO_BUSY_RETRY_ATTEMPTS``，
默认 15 次，单 Key ≈15 分钟）。用户愿意为一个长视频任务等更久，但快速重试只能
加快节奏（3 分钟窗口），不能延长总预算。

本模式把「次数封顶」换成「累计等待时长封顶」：

- **节奏不变**：间隔仍由 ``core/api/retry_policy.py`` 与快速重试钩子决定；
- **预算口径**：累计**忙轨等待秒数**（不是墙钟），渲染/生成/TTS 等时间不计入，
  多段流水线跨段累计；
- **不可重试错误**：由 :mod:`core.api.error_taxonomy` 判定，命中即结束重试并
  返回结构化最终结果。

本模块只定义协议与边界，不持有任何状态：开关、已等待时长、收尾原因全部落在
任务状态（``models/task.py::LongTaskConfig``），由流水线实现钩子并落盘。

钩子协议（duck typing，不强制继承）::

    class Hook:
        def notify_busy(self, payload: dict) -> None:
            \"\"\"每次收到忙信号调用（payload 见下）。\"\"\"

        def allow_extend(self, payload: dict) -> bool:
            \"\"\"常规忙轨次数耗尽时调用：True = 继续重试；False = 走既有失败路径。\"\"\"

        def on_fatal(self, reason: str) -> None: ...   # 不可重试错误即将抛出
        def on_success(self) -> None: ...              # 提交成功

``payload`` 字段：``status`` / ``code`` / ``retries``（本次忙轨已重试次数）/
``waited_s``（本次忙轨累计等待秒数，单调递增）/ ``budget_s``（剩余预算，可选）。

日志约定：``[LongTask] ...`` 前缀，只在状态切换（首次累计、延长、到期）时打印，
不逐跳刷屏。
"""

from typing import Optional

__all__ = [
    "LONG_TASK_DEFAULT_MINUTES",
    "LONG_TASK_MIN_MINUTES",
    "LONG_TASK_MAX_MINUTES",
    "clamp_timeout_minutes",
    "budget_seconds",
]

#: 默认超时（分钟）：用户诉求「默认 1 小时」
LONG_TASK_DEFAULT_MINUTES = 60

#: 合法区间：太短没有意义（忙轨本身的 15 次就约 15 分钟），太长会长期占位
LONG_TASK_MIN_MINUTES = 5
LONG_TASK_MAX_MINUTES = 480


def clamp_timeout_minutes(value) -> int:
    """把用户输入收敛到 ``[MIN, MAX]``；非法输入回落默认值。

    Args:
        value: 分钟数（可能是字符串 / ``None`` / 0（表示用默认值））。

    Returns:
        合法的分钟数。
    """
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return LONG_TASK_DEFAULT_MINUTES
    if minutes <= 0:
        return LONG_TASK_DEFAULT_MINUTES
    return max(LONG_TASK_MIN_MINUTES, min(LONG_TASK_MAX_MINUTES, minutes))


def budget_seconds(minutes: Optional[int]) -> float:
    """预算秒数（非法/缺失时用默认值）。"""
    return float(clamp_timeout_minutes(minutes) * 60)
