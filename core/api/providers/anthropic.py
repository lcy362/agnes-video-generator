"""core.api.providers.anthropic — Anthropic 兼容线协议客户端

协议：``POST {base}/v1/messages``（base 已含 /v1 则 ``{base}/messages``），Header
``x-api-key`` + ``anthropic-version: 2023-06-01``；body：``model / system(顶层) /
messages / max_tokens / temperature``。取结果 ``data.content[0].text``。

多模态本期不做：``chat_multimodal`` 告警并退回纯文本（忽略 images）。
"""

from __future__ import annotations

import logging

import requests

from core.api.providers.base import (
    BaseProviderClient,
    get_chat_endpoint,
    request_with_retry,
)

logger = logging.getLogger(__name__)

_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicChatClient(BaseProviderClient):
    """Anthropic Messages API 兼容客户端（text only）。"""

    api = "anthropic-messages"

    def _chat_endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    def _auth_headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _extract_content(self, data: dict) -> str:
        content = data.get("content") or []
        if content:
            return content[0].get("text", "")
        return ""

    def _request(self, payload: dict, timeout: int = 120) -> dict:
        url = self._chat_endpoint()
        headers = self._auth_headers()
        return request_with_retry(
            requests.post, url, headers, payload=payload, timeout=timeout,
        )

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        logger.info(
            f"[AnthropicProvider] Calling chat ({self.model}), prompt: {len(user_prompt)} chars..."
        )
        data = self._request(
            {
                "model": self.model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }
        )
        return self._extract_content(data)

    def chat_multimodal(
        self,
        system_prompt: str,
        text_prompt: str,
        image_paths: list,
        max_tokens: int = 4096,
    ) -> str:
        # 本期不支持 Anthropic 多模态：告警并退回纯文本（忽略 images）
        logger.warning(
            f"[AnthropicProvider] Multimodal not supported, falling back to text-only "
            f"({len(image_paths)} image(s) ignored)"
        )
        return self.chat(system_prompt, text_prompt, max_tokens=max_tokens)