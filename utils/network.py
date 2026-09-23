"""utils.network — 网络层异常的人话诊断（v6.4.8；v7.0 双语化）

把 ``requests`` / ``urllib3`` / ``socket`` 的底层网络异常（域名解析失败、连接被拒、
代理不通）翻译成用户能自助排查的提示。

背景（GitHub issue #56 / #57）：用户本机 DNS 解析不了 Agnes 的输出文件域名
``cos-platform-outputs.agnes-ai.cn``（腾讯云 COS），视频在服务端**已经生成成功**，
只差最后一步下载。此前这类失败只抛出 ``RetryError[<Future ... raised ConnectionError>]``，
用户无从判断是自己机器的网络问题还是服务故障，于是反复点「重试任务」而无效。

v7.0（GitHub issue #64）：翻译文案改走 ``core.i18n_backend.translate``，
根据调用方传入的 ``lang`` 或请求上下文输出中文/英文，避免英文 UI 用户看到
一段无法理解的中文诊断。其余 20 语言暂回退中文，见
``docs/plans/v7.0/backend_i18n_plan.md``。

设计约束：
- 只翻译**能确定归因**的两类（DNS 解析失败 / 连接无法建立），其余返回空串由调用方
  回退到 ``str(exc)``；绝不猜测性改写，避免把 429 / 5xx / 超时也套上网络文案。
- 返回值面向终端用户，会同时进入进度消息、失败面板与诊断报告，因此自包含：
  现象 + 影响 + 自助步骤 + 续传指引。
"""

import re
import socket
from typing import List, Optional

# 注意：``core.i18n_backend`` 的导入放在函数体内（惰性），不能在模块顶层。
# 顶层导入会触发循环：utils.network → core.i18n_backend → core/__init__ →
# core.pipelines → multi_scene → utils.network（此时本模块尚未定义
# describe_network_error，ImportError）。core.i18n_backend 本身只依赖标准库，
# 惰性导入没有性能顾虑。

__all__ = ["describe_network_error", "is_network_infra_error"]

# 异常链遍历深度上限（tenacity → requests → urllib3 → socket 一般 4~5 层）
_MAX_CHAIN_DEPTH = 12

# 目标主机提取：urllib3 的 host='xxx' 优先，其次异常文本里的完整 URL
_HOST_PATTERNS = (
    re.compile(r"host='([^']+)'"),
    re.compile(r"host=([^,\s]+)"),
    re.compile(r"https?://([^/:\s]+)"),
)

# DNS 解析失败（Windows 11004 / Linux -2、-3 / Temporary failure）
_DNS_MARKERS = (
    "getaddrinfo failed",
    "failed to resolve",
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname provided",
    "no address associated with hostname",
    "nameresolution",
    "gaierror",
    "11004",
)

# 连接被拒 / 无法建立连接（不含 timeout：超时多为服务端拥塞，不归因到本地环境）
# v7.0 追加 ``connection reset`` / ``connection aborted``：issue #64 里 macOS
# 到 Agnes 视频域名的 TLS 握手被对端 reset，之前只有 ``connection aborted``
# 命中不稳定（urllib3 会包成 NewConnectionError 或 ProtocolError 两种形态），
# 补上 reset 让归因更稳。
_CONNECT_MARKERS = (
    "connection refused",
    "connection aborted",
    "connection reset",
    "cannot connect to proxy",
    "tunnel connection failed",
    "newconnectionerror",
    "host unreachable",
    "network is unreachable",
)


def _chain_exceptions(exc: BaseException) -> List[BaseException]:
    """展开异常链（``__cause__`` / ``__context__`` + tenacity ``last_attempt``）。

    Args:
        exc: 顶层异常。

    Returns:
        链上的异常对象列表，按广度优先、去重、限深。
    """
    chain: List[BaseException] = []
    seen: set[int] = set()
    pending: List[BaseException] = [exc]
    while pending and len(chain) < _MAX_CHAIN_DEPTH:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        inner = _retryerror_cause(current)
        if inner is not None:
            pending.append(inner)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return chain


def _retryerror_cause(exc: BaseException) -> "BaseException | None":
    """取出 tenacity ``RetryError.last_attempt`` 内包着的真实异常（非 RetryError 返回 None）。"""
    last_attempt = getattr(exc, "last_attempt", None)
    if last_attempt is None:
        return None
    try:
        inner = last_attempt.exception()
    except Exception:
        return None
    return inner if isinstance(inner, BaseException) else None


def _chain_text(exc: BaseException) -> str:
    """拼接异常链的类型名与消息（小写），供关键词匹配。"""
    parts = [f"{type(item).__name__}: {item}" for item in _chain_exceptions(exc)]
    return "\n".join(parts).lower()


def _extract_host(text: str) -> str:
    """从异常文本里提取失败的目标主机名（提不到返回空串）。"""
    for pattern in _HOST_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def _has_gaierror(exc: BaseException) -> bool:
    """异常链里是否存在 socket.gaierror（DNS 失败的类型级证据）。"""
    return any(isinstance(item, socket.gaierror) for item in _chain_exceptions(exc))


def is_network_infra_error(exc: BaseException) -> bool:
    """判断异常是否属于「本机网络 / 域名解析」这一类环境故障。

    Args:
        exc: 待判定的异常。

    Returns:
        True 表示可归因为本地网络环境（DNS 解析失败或连接无法建立）。
    """
    text = _chain_text(exc)
    if _has_gaierror(exc):
        return True
    return any(marker in text for marker in _DNS_MARKERS + _CONNECT_MARKERS)


def describe_network_error(exc: BaseException, lang: Optional[str] = None) -> str:
    """把网络层异常翻译成用户可自助排查的提示（按 UI 语言）。

    Args:
        exc: 流水线捕获到的原始异常（可能是 tenacity ``RetryError`` 包装）。
        lang: 目标 UI 语言（2 字母代码，如 ``"en"``）。``None`` 时走
            ``core.i18n_backend.resolve_lang``：优先读请求级 ContextVar，
            未设置则回退 ``zh``。异步 Pipeline 应显式传入
            ``self._state.ui_language``，避免上下文丢失。

    Returns:
        用户可读提示；无法确定归因时返回空串，调用方应回退到原始异常文本。
    """
    # 惰性导入，打破 utils.network ↔ core.pipelines 的模块级循环（见文件头注释）
    from core.i18n_backend import translate

    text = _chain_text(exc)
    is_dns = _has_gaierror(exc) or any(marker in text for marker in _DNS_MARKERS)
    is_connect = any(marker in text for marker in _CONNECT_MARKERS)
    if not (is_dns or is_connect):
        return ""

    host = _extract_host(text)
    # 主机名提取失败时给一个本地化的兜底称呼（"Agnes 服务域名" / "the Agnes service domain"）
    target = f"`{host}`" if host else translate("network.default_target", lang)
    if is_dns:
        return translate("network.dns_failed", lang, target=target)
    return translate("network.connect_blocked", lang, target=target)
