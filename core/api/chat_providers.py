"""core.api.chat_providers — 文本模型客户端工厂（v7.0 多文本模型）。

按当前所选文本供应商（``models.text_provider``）分派：
- 空 / ``agnes`` → ``AgnesChatAPI``（现有行为 100% 不变）；
- 自定义供应商 → ``OpenAIChatClient`` / ``AnthropicChatClient``。

供 screenwriter / video_routes 等取代硬编码的 ``AgnesChatAPI(...)`` 构造点。
"""

from __future__ import annotations

import logging

from core.config import API_ANTHROPIC, PROVIDER_AGNES, resolve_text_chat

logger = logging.getLogger(__name__)


def get_or_build_text_chat_client(api_key: str | None = None, model: str | None = None):
    """构造当前所选文本供应商的聊天客户端（与 AgnesChatAPI 相同接口）。

    Args:
        api_key: 显式 API Key。仅对 agnes 供应商生效（等价原 ``AgnesChatAPI``
            构造时 `api_key=api_key`）；自定义供应商使用其自身配置的 api_key。
        model: 显式模型；省略则使用当前所选配置（``models.text`` 或供应商首个模型）。

    Returns:
        满足 ``chat / chat_json / chat_multimodal`` 接口的客户端实例。
    """
    cfg = resolve_text_chat()
    if cfg["kind"] == "agnes":
        from core.api.agnes_chat import AgnesChatAPI
        from core.config import get_api_key

        return AgnesChatAPI(
            api_key=api_key or get_api_key(),
            model=model or cfg["model"],
        )
    # custom
    m = model or cfg["model"]
    if cfg["api"] == API_ANTHROPIC:
        from core.api.providers.anthropic import AnthropicChatClient

        return AnthropicChatClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=m,
        )
    from core.api.providers.openai import OpenAIChatClient

    return OpenAIChatClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=m,
    )