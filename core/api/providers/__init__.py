"""core.api.providers — 可插拔文本模型供应商的协议客户端包。

提供 OpenAI 兼容（``OpenAIChatClient``）与 Anthropic 兼容（``AnthropicChatClient``）
两种线协议实现，以及端点拼接纯函数（``get_chat_endpoint`` / ``get_models_endpoint``）。
"""

from core.api.providers.anthropic import AnthropicChatClient
from core.api.providers.base import (
    get_chat_endpoint,
    get_models_endpoint,
    probe_text_models,
    request_with_retry,
)
from core.api.providers.openai import OpenAIChatClient

__all__ = [
    "AnthropicChatClient",
    "OpenAIChatClient",
    "get_chat_endpoint",
    "get_models_endpoint",
    "probe_text_models",
    "request_with_retry",
]