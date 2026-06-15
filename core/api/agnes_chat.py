"""core.api.agnes_chat — Agnes Chat API 封装（从 core/screenwriter.py 提取）"""

import base64
import json
import logging
import mimetypes
import os
from typing import List

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"


class AgnesChatAPI:
    """Agnes LLM Chat API 封装（text + multimodal）。"""

    def __init__(self, api_key: str, model: str = "agnes-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _image_to_b64_uri(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        """纯文本 Chat 调用。"""
        logger.info(f"[AgnesChat] Calling chat ({self.model}), prompt: {len(user_prompt)} chars...")
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=self.headers,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> dict:
        """Chat 调用并解析 JSON 响应。"""
        content = self.chat(system_prompt, user_prompt, max_tokens=max_tokens)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
        return json.loads(content)

    def chat_multimodal(
        self,
        system_prompt: str,
        text_prompt: str,
        image_paths: List[str],
        max_tokens: int = 4096,
    ) -> str:
        """多模态 Chat 调用（文本 + 图片）。"""
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
            f"[AgnesChat] Calling multimodal ({self.model}), "
            f"{len(image_paths)} image(s), prompt: {len(text_prompt)} chars..."
        )
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=self.headers,
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
