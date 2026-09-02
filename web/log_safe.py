"""日志安全：清洗用户可控数据后再写入日志（Sonar ``pythonsecurity:S5145``）。

背景
----
HTTP 请求里的路径参数 / 查询串 / 表单字段完全由调用方控制。若直接把原值
拼进日志，攻击者可注入 ``\\r\\n`` 伪造出额外的日志行（日志注入 / CWE-117），
进而污染审计追踪、误导排查甚至投毒下游日志分析。

用法
----
凡是要把用户可控值写进日志的地方，统一用 :func:`safe_log` 包一层::

    logger.info("[Resume] Starting resume for task %s", safe_log(task_id))

日志消息本身仍建议用 ``%s`` 惰性格式化（避免无谓的字符串拼接开销）。
"""
from __future__ import annotations

import re

__all__ = ["safe_log"]

# CR/LF 及其余 C0、C1 控制字符：日志注入的核心载体，统一替换为空格
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# 单个值写入日志的最大长度，超出截断，避免超长 payload 淹没日志
_MAX_LOG_VALUE_LEN = 120


def safe_log(value: object, max_len: int = _MAX_LOG_VALUE_LEN) -> str:
    """把任意值转为可安全写入日志的单行片段。

    - ``None`` → ``"-"``；
    - 控制字符（含 ``\\n`` / ``\\r`` / 制表符）替换为空格，杜绝伪造日志行；
    - 超过 ``max_len`` 时截断并追加 ``...``。

    注意：本函数只处理**展示安全**，不改变业务逻辑——调用方仍需自行做
    业务校验与路径穿越防护。
    """
    if value is None:
        return "-"
    text = _CONTROL_CHARS_RE.sub(" ", str(value))
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text
