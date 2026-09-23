"""core.api.providers.base — 文本供应商协议客户端的共享底层

提供：
- 端点拼接纯函数 ``get_chat_endpoint`` / ``get_models_endpoint``（OpenAI 兼容 /
  Anthropic 兼容的 /v1 是否已含处理）；
- 受限速 + 指数退避的底层请求 ``request_with_retry``（不复用 Agnes KeyRing，
  仅共享全局令牌桶 `get_rate_limiter()`；5xx/429 最多 3 次指数退避，4xx 直接抛）；
- ``BaseProviderClient``：OpenAI / Anthropic 客户端共用的胶水（chat_json 解析、
  多模态拼装 header 等），具体协议差异在子类实现。
"""

from __future__ import annotations

import json
import logging
import time

import requests

from core.api.agnes_chat import (
    _JSON_BLOCK_RE,
    repair_json,
    strip_code_fence,
)
from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.rate_limiter import get_rate_limiter
from core.config import API_OPENAI

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 15  # 秒，指数退避基数


def get_chat_endpoint(base_url: str, api: str) -> str:
    """OpenAI 兼容 chat 端点：``{base}/chat/completions``（base_url 去除尾 `/`）。

    （Anthropic 聊天使用独立构造，见 ``_anthropic_messages_endpoint``；本函数对
    Anthropic 语义为 ``{base}/v1/messages``，供探测结果一致性参照。）
    """
    base = (base_url or "").rstrip("/")
    if api == "anthropic-messages":
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"
    return f"{base}/chat/completions"


def get_models_endpoint(base_url: str, api: str) -> str:
    """OpenAI 兼容模型列表端点：``{base}/models``。

    Anthropic 语义：base 以 ``/v1`` 结尾 → ``{base}/models``，否则 ``{base}/v1/models``。
    """
    base = (base_url or "").rstrip("/")
    if api == "anthropic-messages":
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"
    return f"{base}/models"


def request_with_retry(
    requester,
    url: str,
    headers: dict,
    *,
    payload: dict | None = None,
    json_body: bool = True,
    timeout: int = 120,
) -> dict:
    """受限速的指数退避请求（自定义供应商专用，不换 Key）。

    规则：
    1. 每次请求前 ``get_rate_limiter().acquire()``（共享桶）；
    2. 5xx / 429 → 指数退避（delay = 15 × (retries+1)），最多 3 次；
    3. 4xx（非 429）不重试，直接 ``raise requests.HTTPError``；
    4. 失败调用 ``collect_error`` / ``collect_error_from_exception`` 落盘。
    """
    prompt = ""
    if payload and json_body:
        prompt = _extract_prompt_from_payload(payload)
    retries = 0
    while True:
        get_rate_limiter().acquire()
        try:
            if json_body:
                resp = requester(url, headers=headers, json=payload, timeout=timeout)
            else:
                resp = requester(url, headers=headers, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            collect_error_from_exception(
                "chat", "chat", exc=e, prompt=prompt, retry_count=retries,
            )
            if retries < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (retries + 1)
                logger.warning(
                    f"[ChatProvider] {type(e).__name__}, 退避 {delay}s 后重试 "
                    f"({retries + 1}/{_MAX_RETRIES})"
                )
                time.sleep(delay)
                retries += 1
                continue
            raise
        if resp.status_code == 429 or resp.status_code >= 500:
            if retries < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (retries + 1)
                logger.warning(
                    f"[ChatProvider] HTTP {resp.status_code}, 退避 {delay}s 后重试 "
                    f"({retries + 1}/{_MAX_RETRIES})"
                )
                time.sleep(delay)
                retries += 1
                continue
            # 重试耗尽：记录最终失败
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
        if resp.status_code >= 400:
            # 4xx（含 429 已耗尽）不可重试
            try:
                collect_error(
                    "chat", "chat",
                    prompt=prompt,
                    error_type=f"HTTP{resp.status_code}",
                    error_message=f"HTTP {resp.status_code}: {resp.text[:500]}",
                    status_code=resp.status_code,
                    response_body=resp.text[:5000],
                    retry_count=retries,
                )
            except Exception:
                pass
            resp.raise_for_status()
        return resp.json()


def _extract_prompt_from_payload(payload: dict) -> str:
    """从 Chat payload 中提取 user prompt 文本（用于错误收集）。"""
    messages = payload.get("messages", [])
    for msg in reversed(messages):
        content = msg.get("content", "")
        if isinstance(content, list):
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if texts:
                return texts[0]
        elif isinstance(content, str) and content.strip():
            return content
    return ""


class BaseProviderClient:
    """协议客户端基类：持有 base_url/api_key/model，含共享的 chat_json 解析逻辑。

    子类必须实现：``_auth_headers()``、``chat()``、``chat_multimodal()``。
    """

    api = API_OPENAI

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model

    def _auth_headers(self) -> dict:
        raise NotImplementedError

    def _extract_content(self, data: dict) -> str:
        raise NotImplementedError

    def _request(self, payload: dict, timeout: int = 120) -> dict:
        url = get_chat_endpoint(self.base_url, self.api)
        headers = self._auth_headers()
        return request_with_retry(
            requests.post, url, headers, payload=payload, timeout=timeout,
        )

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> dict:
        """Chat 调用并解析 JSON 响应（与 agnes_chat.chat_json 一致的健壮流程）。"""
        for retry in range(2):
            content = self.chat(system_prompt, user_prompt, max_tokens=max_tokens)
            cleaned = strip_code_fence(content)
            try:
                return json.loads(cleaned)
            except ValueError:
                pass
            match = _JSON_BLOCK_RE.search(cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except ValueError:
                    pass
            if repair_json is not None:
                try:
                    repaired = repair_json(cleaned, return_objects=True)
                    if isinstance(repaired, dict):
                        logger.info(f"[{self._log_prefix}] JSON repaired via json_repair")
                        return repaired
                except Exception:
                    pass
            if retry == 0:
                logger.warning(f"[{self._log_prefix}] JSON parse failed, retrying chat call...")
                continue
            preview = content[:200]
            error_msg = (
                f"[{self._log_prefix}] Failed to parse JSON after 2 attempts. "
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
        raise ValueError(f"[{self._log_prefix}] Unexpected flow in chat_json")

    @property
    def _log_prefix(self) -> str:
        return self.__class__.__name__


def probe_text_models(base_url: str, api_key: str, api: str) -> list:
    """用传入的 base_url+key+api 探测模型列表（不落盘，用于 test 端点）。

    OpenAI 兼容用 ``Authorization: Bearer``；Anthropic 兼容用 ``x-api-key`` +
    ``anthropic-version``。成功返回模型 id 列表，失败抛出 ``requests.HTTPError``。

    Args:
        base_url: 用户输入的 base_url。
        api_key: 用户此刻输入的 key。
        api: 线协议（openai-completions / anthropic-messages）。

    Returns:
        模型 id 列表（``data[].id`` / ``data[].id``）。

    Raises:
        requests.HTTPError: 4xx/5xx/网络错误（由调用方捕获返回 ``{ok:false,error}``）。
    """
    url = get_models_endpoint(base_url, api)
    headers = {"Content-Type": "application/json"}
    if api == "anthropic-messages":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code >= 400:
        try:
            logger.warning(
                f"[ChatProvider] Probe models failed HTTP {resp.status_code}: {resp.text[:500]}"
            )
        except Exception:
            pass
        resp.raise_for_status()
    data = resp.json()
    models = data.get("data") or []
    ids = []
    for m in models:
        if isinstance(m, dict) and m.get("id"):
            ids.append(str(m["id"]))
    return ids