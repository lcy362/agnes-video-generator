"""v6.4.8 网络异常诊断（utils.network）测试；v7.0（issue #64）追加双语断言。

覆盖 GitHub issue #56 / #57 的真实异常形态：本机 DNS 解析不了 Agnes 输出文件域名
`cos-platform-outputs.agnes-ai.cn`，tenacity RetryError 包着 requests ConnectionError
包着 socket.gaierror(11004)。要求：
- 这类故障翻译成人话（含域名 + DNS 自助步骤），不再只抛 RetryError[...]；
- 429 / 5xx / 超时等偶发故障**不得**被误判成本地网络问题（否则引导文案会误导用户）；
- v7.0：翻译文案必须按 ``lang`` 参数输出中/英文，英文界面用户不再看到中文诊断。
"""

import socket
from concurrent.futures import Future

import pytest
import requests
from tenacity import RetryError

from utils.network import describe_network_error, is_network_infra_error

# issue #57 里的原始异常文本（截断保留关键部分）
_DNS_TEXT = (
    "HTTPSConnectionPool(host='cos-platform-outputs.agnes-ai.cn', port=443): "
    "Max retries exceeded with url: /videos/agnes-video-v2.0/video_ca26a36d.mp4 "
    "(Caused by NameResolutionError(\"HTTPSConnection(host='cos-platform-outputs.agnes-ai.cn', "
    "port=443): Failed to resolve 'cos-platform-outputs.agnes-ai.cn' "
    "([Errno 11004] getaddrinfo failed)\"))"
)


def _dns_retry_error() -> RetryError:
    """复刻 issue #56/#57 的异常链：tenacity → requests → urllib3 → socket.gaierror。"""
    gai = socket.gaierror(11004, "getaddrinfo failed")
    conn_error = requests.exceptions.ConnectionError(_DNS_TEXT)
    conn_error.__cause__ = gai
    future: Future = Future()
    future.set_exception(conn_error)
    return RetryError(future)


def test_dns_failure_is_recognized_as_local_network_issue():
    exc = _dns_retry_error()
    assert is_network_infra_error(exc) is True


def test_dns_failure_message_is_actionable_and_names_host():
    message = describe_network_error(_dns_retry_error())
    assert message, "DNS 解析失败必须给出可读提示，不能回退成 RetryError[...]"
    assert "cos-platform-outputs.agnes-ai.cn" in message, "提示应包含解析失败的域名"
    assert "DNS" in message
    assert "223.5.5.5" in message, "应给出可切换的 DNS 建议"
    assert "重试任务" in message, "应引导网络恢复后从失败环节续传"


def test_connection_refused_is_recognized():
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.agnes-ai.cn', port=443): "
        "Max retries exceeded with url: /v1/videos (Caused by "
        "NewConnectionError('<urllib3.connection.HTTPSConnection object>: "
        "Failed to establish a new connection: [Errno 111] Connection refused'))"
    )
    message = describe_network_error(exc)
    assert "无法连接" in message
    assert "api.agnes-ai.cn" in message


@pytest.mark.parametrize(
    "text",
    [
        "HTTP 429: Too Many Requests",
        "HTTP 502: Bad Gateway",
        "HTTPSConnectionPool(host='apihub.agnes-ai.com', port=443): "
        "Read timed out. (read timeout=30)",
        "Video generation failed: content policy violation",
    ],
)
def test_transient_and_deterministic_errors_are_not_mislabeled(text):
    """限流 / 5xx / 超时 / 内容审核不能被归成本地网络故障（引导会完全错误）。"""
    exc = requests.exceptions.HTTPError(text)
    assert is_network_infra_error(exc) is False
    assert describe_network_error(exc) == ""


def test_plain_exception_returns_empty_for_caller_fallback():
    assert describe_network_error(ValueError("bad prompt")) == ""
    assert is_network_infra_error(ValueError("bad prompt")) is False


def test_host_extraction_falls_back_to_url():
    exc = requests.exceptions.ConnectionError(
        "Failed to resolve https://platform-outputs.agnes-ai.space/images/x.png via DNS"
    )
    message = describe_network_error(exc)
    assert "platform-outputs.agnes-ai.space" in message


# ─────────────────────────────────────────────────────────────────────────────
# v7.0（issue #64）：双语断言 —— 英文 UI 用户必须拿到英文诊断
# ─────────────────────────────────────────────────────────────────────────────


def test_dns_failure_message_english_when_lang_en():
    """lang='en' 时返回英文诊断，且不含任何中文关键词。"""
    message = describe_network_error(_dns_retry_error(), lang="en")
    assert message, "DNS failure must produce a readable message"
    assert "cos-platform-outputs.agnes-ai.cn" in message
    assert "DNS" in message
    # 英文分支的核心引导词
    assert "cannot resolve" in message.lower()
    assert "Retry task" in message
    # 绝不能混入中文（此前硬编码中文会让英文界面用户看不懂）
    for zh_marker in ("网络诊断", "无法解析", "重试任务", "请依次检查"):
        assert zh_marker not in message, f"English branch leaked Chinese: {zh_marker}"


def test_connection_refused_message_english_when_lang_en():
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.agnes-ai.cn', port=443): "
        "Max retries exceeded with url: /v1/videos (Caused by "
        "NewConnectionError('<urllib3.connection.HTTPSConnection object>: "
        "Failed to establish a new connection: [Errno 111] Connection refused'))"
    )
    message = describe_network_error(exc, lang="en")
    assert "cannot reach" in message.lower()
    assert "api.agnes-ai.cn" in message
    for zh_marker in ("网络诊断", "无法连接", "重试任务"):
        assert zh_marker not in message


def test_connection_reset_by_peer_is_recognized_as_connect_error():
    """issue #64 的真实形态：TLS 握手阶段被对端 reset。

    此前 ``_CONNECT_MARKERS`` 只有 ``connection aborted``，macOS 上 urllib3
    会把 ``ConnectionResetError`` 包成 ``NewConnectionError`` 或 ``ProtocolError``，
    文案里出现 ``connection reset``；v7.0 补上该 marker，保证归因稳定。
    """
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.agnes-ai.cn', port=443): "
        "Max retries exceeded with url: /v1/videos (Caused by "
        "SSLError(SSLError(1, '[SSL: WRONG_VERSION_NUMBER]'),))"
    )
    # 直接构造一个带 "connection reset" 文本的异常，验证 marker 命中
    exc2 = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.agnes-ai.cn', port=443): "
        "Connection reset by peer during TLS handshake"
    )
    assert is_network_infra_error(exc2) is True
    msg_zh = describe_network_error(exc2, lang="zh")
    assert "无法连接" in msg_zh
    msg_en = describe_network_error(exc2, lang="en")
    assert "cannot reach" in msg_en.lower()


def test_lang_zh_returns_chinese_message():
    """显式 lang='zh' 与不传 lang（默认上下文 zh）行为一致。"""
    msg_explicit = describe_network_error(_dns_retry_error(), lang="zh")
    msg_default = describe_network_error(_dns_retry_error())
    assert "网络诊断" in msg_explicit
    assert msg_explicit == msg_default


def test_unknown_lang_falls_back_to_zh():
    """未知语言归一化到 zh（与前端 t() 回退策略一致）。"""
    message = describe_network_error(_dns_retry_error(), lang="klingon")
    assert "网络诊断" in message


def test_default_target_label_is_localized():
    """主机名提取失败时，兜底称呼也要按语言走。"""
    # 构造一个不含 host 信息的连接异常
    exc = requests.exceptions.ConnectionError("connection refused")
    msg_zh = describe_network_error(exc, lang="zh")
    msg_en = describe_network_error(exc, lang="en")
    assert "Agnes 服务域名" in msg_zh
    assert "Agnes service domain" in msg_en
