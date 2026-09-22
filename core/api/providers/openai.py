"""core.api.providers.openai — OpenAI 兼容线协议客户端

协议：``POST {base}/chat/completions``，Header ``Authorization: Bearer <key>``，
body 与 Agnes 相同结构；多模态 content 为列表 + image_url（base64 data URI 透传）。
取结果 ``data.choices[0].message.content``。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os

import requests

from core.api.providers.base import (
    BaseProviderClient,
    get_chat_endpoint,
    get_models_endpoint,
    request_with_retry,
)

logger = logging.getLogger(__name__)


class OpenAIChatClient(BaseProviderClient):
    """OpenAI 兼容协议客户端（text + multimodal）。"""

    api = "openai-completions"

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _image_to_b64_uri(self, path: str) -> str:
        """将本地图片转为 OpenAI ``data:`` URI（与 agnes_chat 一致）。"""
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    def _extract_content(self, data: dict) -> str:
        return data["choices"][0]["message"]["content"]

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        logger.info(
            f"[OpenAIProvider] Calling chat ({self.model}), prompt: {len(user_prompt)} chars..."
        )
        data = self._request(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
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
        messages = [{"role": "system", "content": system_prompt}]
        user_content = [{"type": "text", "text": text_prompt}]
        for img_path in image_paths:
            if img_path.startswith(("http://", "https://")):
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_path},
                })
            elif os.path.exists(img_path):
                b64_uri = self._image_to_b64_uri(img_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": b64_uri},
                })
        messages.append({"role": "user", "content": user_content})
        logger.info(
            f"[OpenAIProvider] Calling multimodal ({self.model}), "
            f"{len(image_paths)} image(s), prompt: {len(text_prompt)} chars..."
        )
        data = self._request(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=300,
        )
        return self._extract_content(data)