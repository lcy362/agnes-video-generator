"""core.api.agnes_chat — Agnes Chat API 封装（从 core/screenwriter.py 提取）

P5: 健壮 JSON 解析（strip_code_fence + 正则提取 + 降级重试）
P11: chat/chat_multimodal 统一重试（5xx/超时/连接错 3 次指数退避，4xx 不重试）
"""

import base64
import json
import logging
import mimetypes
import os
import re
from typing import List

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.rate_limiter import get_rate_limiter, request_with_key_rotation
from core.config import get_agnes_base_url

logger = logging.getLogger(__name__)

# json_repair 可选依赖（优化 4）：未安装时行为与现状完全一致
try:
    from json_repair import repair_json
except ImportError:
    repair_json = None

# 重试配置
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 15  # 秒，指数退避基数

# 正则：匹配首个 {…} 块（支持嵌套大括号）
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def strip_code_fence(text: str) -> str:
    """去除 LLM 响应中的代码围栏标记。

    处理常见变体：```json ... ```、``` ... ```、前后有多余空白/换行。

    Args:
        text: LLM 原始响应文本。

    Returns:
        去除围栏后的文本。
    """
    text = text.strip()
    # 去除首行 ``` 或 ```json 等
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1:]
    # 去除尾部 ```
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


class AgnesChatAPI:
    """Agnes LLM Chat API 封装（text + multimodal）。"""

    def __init__(self, api_key: str, model: str = "agnes-2.0-flash"):
        self.api_key = api_key
        self.model = model
        # 基础 headers（不含 Authorization）：每次请求前经 _auth_headers() 注入当前 Key
        self._base_headers = {
            "Content-Type": "application/json",
        }
        # 向后兼容：旧调用方可能读取 self.headers
        self.headers = dict(self._base_headers)

    def _auth_headers(self) -> dict:
        """每次请求前生成带当前 Key 的 headers 副本（从 KeyRing 轮转取 Key）。"""
        from core.api.key_manager import get_key_ring

        key = get_key_ring().next()
        h = dict(self._base_headers)
        h["Authorization"] = f"Bearer {key}"
        return h

    def _image_to_b64_uri(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _should_retry(resp: requests.Response) -> bool:
        """判断 HTTP 响应是否应重试（5xx 和 429 重试，4xx 不重试）。"""
        return resp.status_code >= 500 or resp.status_code == 429

    @staticmethod
    def _extract_prompt_from_payload(payload: dict) -> str:
        """从 Chat payload 中提取 user prompt 文本（用于错误收集）。"""
        messages = payload.get("messages", [])
        for msg in reversed(messages):
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态：提取 text 部分
                texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                if texts:
                    return texts[0]
            elif isinstance(content, str) and content.strip():
                return content
        return ""

    def _request_with_retry(self, payload: dict, timeout: int = 120) -> dict:
        """带重试的 API 请求（429 换 Key + 5xx/超时/连接错误指数退避）。

        经 ``request_with_key_rotation`` 统一封装：
        - 多 Key 下 429 换 Key 立即重试（不计入退避）；
        - 全 Key 429 / 5xx / 超时 / 连接错误 指数退避最多 3 次；
        - 4xx（非 429）不重试，直接抛出。
        每次请求前通过全局限速器控制调用频率。

        Args:
            payload: 请求 JSON body。
            timeout: 请求超时秒数。

        Returns:
            解析后的响应 JSON dict。

        Raises:
            requests.HTTPError: 4xx 客户端错误或重试耗尽。
        """
        prompt = self._extract_prompt_from_payload(payload)
        try:
            get_rate_limiter().acquire()
            resp = request_with_key_rotation(
                requests.post,
                f"{get_agnes_base_url()}/chat/completions",
                max_retries=_MAX_RETRIES,
                retry_base_delay=_RETRY_BASE_DELAY,
                json=payload,
                timeout=timeout,
            )
            if self._should_retry(resp):
                # helper 内部重试已耗尽（单 Key 429 或持续 5xx），记录最终失败
                collect_error(
                    "chat", "chat",
                    prompt=prompt,
                    error_type="RateLimit429" if resp.status_code == 429 else f"HTTP{resp.status_code}",
                    error_message=f"HTTP {resp.status_code}: retries exhausted",
                    status_code=resp.status_code,
                    response_body=resp.text,
                    retry_count=_MAX_RETRIES,
                )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code < 500 and resp.status_code != 429:
                # 4xx（非 429）不可重试
                collect_error(
                    "chat", "chat",
                    prompt=prompt,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    status_code=resp.status_code,
                    response_body=resp.text[:5000],
                    retry_count=_MAX_RETRIES,
                )
            raise
        except (requests.ConnectionError, requests.Timeout) as e:
            collect_error_from_exception(
                "chat", "chat",
                exc=e, prompt=prompt,
                retry_count=_MAX_RETRIES,
            )
            raise

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        """纯文本 Chat 调用（含重试）。"""
        logger.info(f"[AgnesChat] Calling chat ({self.model}), prompt: {len(user_prompt)} chars...")
        data = self._request_with_retry(
            {
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
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> dict:
        """Chat 调用并解析 JSON 响应（健壮版）。

        处理流程：
        1. 调用 chat 获取文本
        2. strip_code_fence 去除围栏
        3. 尝试直接 json.loads
        4. 失败则用正则提取首个 {…} 块
        5. 仍失败则重试一次 chat 调用
        6. 最终失败抛出 ValueError

        Args:
            system_prompt: System 提示词。
            user_prompt: User 提示词。
            max_tokens: 最大生成 token 数。

        Returns:
            解析后的 JSON dict。

        Raises:
            ValueError: JSON 解析最终失败。
        """
        for retry in range(2):
            content = self.chat(system_prompt, user_prompt, max_tokens=max_tokens)
            # Step 1: 去围栏
            cleaned = strip_code_fence(content)
            # Step 2: 直接解析
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                pass
            # Step 3: 正则提取首个 {…} 块
            match = _JSON_BLOCK_RE.search(cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            # Step 3.5: json_repair 修复（可选依赖，修复 LLM 常见缺冒号/尾随逗号/单引号）
            if repair_json is not None:
                try:
                    repaired = repair_json(cleaned, return_objects=True)
                    if isinstance(repaired, dict):
                        logger.info("[AgnesChat] JSON repaired via json_repair")
                        return repaired
                except Exception:
                    pass
            # Step 4: 首轮失败则重试一次 chat 调用
            if retry == 0:
                logger.warning("[AgnesChat] JSON parse failed, retrying chat call...")
                continue
            # 最终失败
            preview = content[:200]
            error_msg = (
                f"[AgnesChat] Failed to parse JSON after 2 attempts. "
                f"Response preview: {preview}..."
            )
            collect_error(
                "chat", "chat_json",
                prompt=user_prompt, system_prompt=system_prompt,
                error_type="JSONParseError",
                error_message=error_msg,
                response_body=content[:5000],
                retry_count=2,
            )
            raise ValueError(error_msg)
        # 不应到达此处，但保险起见
        raise ValueError("[AgnesChat] Unexpected flow in chat_json")

    def chat_multimodal(
        self,
        system_prompt: str,
        text_prompt: str,
        image_paths: List[str],
        max_tokens: int = 4096,
    ) -> str:
        """多模态 Chat 调用（文本 + 图片，含重试）。"""
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
        data = self._request_with_retry(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=300,
        )
        return data["choices"][0]["message"]["content"]
