"""core.api.error_taxonomy — 上游报错分类表（可重试 / 不可重试 + 用户结果文案）。

v8.3（长任务模式）：把「这个报错还值不值得重试」与「用户最终看到什么」收敛到一张
可维护的静态表，避免判定逻辑散落在重试循环各处。

设计要点：

- **唯一出处**：判定只看 :func:`classify`；新增规则只改本文件的 ``ERROR_RULES`` /
  ``CODE_RULES``，重试循环不需要动；
- **保守默认**：未知状态码、未知 body code 一律按**可重试**处理（不因分类表缺项而
  误杀本可成功的任务）；
- **可扩展**：每条规则带稳定 ``reason``（统计/日志用）与 ``message_key``
  （前端 22 语言契约，后端 :mod:`core.i18n_backend` 只给 zh/en 兜底句）。
  用户反馈新的上游报错时，补一条规则即可，详见
  ``docs/plans/v8.3/long_task_mode_PRD.md`` 第四节。

不做什么：不改忙轨/故障轨的**间隔**与**次数**（那是 :mod:`core.api.retry_policy`
的职责），也不碰轮询阶段的连续失败预算。
"""

from dataclasses import dataclass
from typing import Optional

__all__ = [
    "ErrorRule",
    "ERROR_RULES",
    "CODE_RULES",
    "classify",
    "is_retryable",
    "describe_rule",
]

#: 上游内容审核类 body code（命中即不可重试：改提示词才有意义）
CONTENT_BLOCK_CODES = frozenset({
    "content_policy_violation",
    "content_policy",
    "content_filter",
    "sensitive_content",
    "moderation_blocked",
    "inappropriate_content",
})


@dataclass(frozen=True)
class ErrorRule:
    """一条报错分类规则。

    Attributes:
        retryable: 是否值得继续重试。
        reason: 稳定 id（日志/统计/埋点用，不要翻译）。
        message_key: 用户可见最终结果的 i18n key（前端 22 语言）；
            ``None`` 表示该错误由既有链路负责文案（如忙轨的队列满提示）。
    """

    retryable: bool
    reason: str
    message_key: Optional[str] = None


#: 可重试：忙轨 / 故障轨都走既有节奏，只换时间预算
RETRYABLE_BUSY = ErrorRule(True, "service_busy")
RETRYABLE_RATE_LIMIT = ErrorRule(True, "rate_limited")
RETRYABLE_TIMEOUT = ErrorRule(True, "request_timeout")
RETRYABLE_SERVER = ErrorRule(True, "server_error")
RETRYABLE_QUEUE = ErrorRule(True, "queue_full")
RETRYABLE_UNKNOWN = ErrorRule(True, "unknown")

#: 不可重试：立即结束重试并返回最终结果
FATAL_AUTH = ErrorRule(False, "auth_invalid", "error.video.fatal_auth")
FATAL_FORBIDDEN = ErrorRule(False, "forbidden", "error.video.fatal_forbidden")
FATAL_NOT_FOUND = ErrorRule(False, "not_found", "error.video.fatal_not_found")
FATAL_TOO_LARGE = ErrorRule(False, "payload_too_large", "error.video.fatal_too_large")
FATAL_BAD_REQUEST = ErrorRule(False, "bad_request", "error.video.fatal_bad_request")
FATAL_CONTENT = ErrorRule(False, "content_blocked", "error.video.fatal_content")
FATAL_CLIENT = ErrorRule(False, "client_error", "error.video.fatal_client")


#: ``(status_code, code)`` 精确规则，优先级最高
ERROR_RULES: dict[tuple[int, str], ErrorRule] = {
    (400, "content_policy_violation"): FATAL_CONTENT,
    (400, "invalid_parameter"): FATAL_BAD_REQUEST,
    (400, "invalid_request"): FATAL_BAD_REQUEST,
    (400, "invalid_argument"): FATAL_BAD_REQUEST,
    (404, "task_not_exist"): FATAL_NOT_FOUND,   # 提交阶段；轮询阶段有独立的 U9 容忍逻辑
    (429, ""): RETRYABLE_RATE_LIMIT,
    (503, ""): RETRYABLE_BUSY,
}

#: 仅按 body code 判定（上游可能用 200 / 400 / 422 等不同状态码返回）
CODE_RULES: dict[str, ErrorRule] = {
    "video_queue_full": RETRYABLE_QUEUE,
    "fail_to_fetch_task": RETRYABLE_QUEUE,
    "rate_limit_exceeded": RETRYABLE_RATE_LIMIT,
    **{code: FATAL_CONTENT for code in CONTENT_BLOCK_CODES},
}

#: 仅按状态码判定（``(status, code)`` 与 code 规则都没命中时）
STATUS_RULES: dict[int, ErrorRule] = {
    400: FATAL_BAD_REQUEST,
    401: FATAL_AUTH,
    403: FATAL_FORBIDDEN,
    404: FATAL_NOT_FOUND,
    408: RETRYABLE_TIMEOUT,
    413: FATAL_TOO_LARGE,
    422: FATAL_BAD_REQUEST,
    425: RETRYABLE_TIMEOUT,
    429: RETRYABLE_RATE_LIMIT,
    451: FATAL_CONTENT,
    503: RETRYABLE_BUSY,
}


def classify(
    status_code: int,
    code: str = "",
    message: str = "",
    *,
    phase: str = "submit",
) -> ErrorRule:
    """给一次上游响应分类。

    判定顺序：``(status, code)`` 精确 → ``code`` → 状态码 → 区间兜底（4xx 不可重试，
    5xx / 429 / 超时可重试）→ 未知一律可重试。

    Args:
        status_code: HTTP 状态码（``0`` 表示网络层异常，无响应）。
        code: 响应体里提取的上游 code（可为空）。
        message: 响应体/异常文本（目前只用于日志与后续扩展，不参与判定）。
        phase: ``submit`` / ``poll``。轮询阶段的 404 有独立的入库延迟语义，
            此处保留参数但不改变分类（轮询侧不接本分类表）。

    Returns:
        命中的 :class:`ErrorRule`（永远不会返回 ``None``）。
    """
    del message, phase  # 预留：后续按报错原文补充规则时再用

    status = int(status_code or 0)
    c = (code or "").strip()

    if c:
        rule = ERROR_RULES.get((status, c))
        if rule is not None:
            return rule
        rule = CODE_RULES.get(c)
        if rule is not None:
            return rule

    # 空 code 的精确规则（429 / 503 的裸状态码）
    rule = ERROR_RULES.get((status, ""))
    if rule is not None and not c:
        return rule

    rule = STATUS_RULES.get(status)
    if rule is not None:
        return rule

    if 400 <= status < 500:
        return FATAL_CLIENT
    if status >= 500:
        return RETRYABLE_SERVER
    return RETRYABLE_UNKNOWN


def is_retryable(status_code: int, code: str = "", message: str = "", *,
                 phase: str = "submit") -> bool:
    """便捷判定：该响应是否值得继续重试。"""
    return classify(status_code, code, message, phase=phase).retryable


def describe_rule(rule: ErrorRule, status_code: int = 0, code: str = "") -> dict:
    """把规则摊平成可落盘/可下发的字典（诊断与埋点用）。"""
    return {
        "retryable": rule.retryable,
        "reason": rule.reason,
        "message_key": rule.message_key or "",
        "status": int(status_code or 0),
        "code": code or "",
    }
