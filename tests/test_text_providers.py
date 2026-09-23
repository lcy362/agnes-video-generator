"""可插拔文本模型供应商（v7.0）单元测试 — tests/test_text_providers.py

覆盖（对应 SonarCloud Quality Gate 新代码覆盖率缺口）：
- ``core.api.providers.base``：端点拼接、限速指数退避请求、prompt 提取、
  ``BaseProviderClient.chat_json`` 健壮解析、``probe_text_models``；
- ``core.api.providers.openai`` / ``anthropic``：两种线协议的 headers / 报文 /
  取结果 / 多模态（含 Anthropic 退回纯文本）；
- ``core.api.chat_providers``：按所选供应商分派客户端（agnes / OpenAI / Anthropic）；
- ``web/routes/config_routes.py`` 供应商 CRUD 端点：
  GET / POST / DELETE / POST …/sync / POST …/test。

写路径隔离：限速器、``time.sleep``、错误落盘、config 读写全部在 monkeypatch 中
打桩，绝不触碰真实配置、网络与工作区。

用法:
    .venv/bin/python -m pytest tests/test_text_providers.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api import chat_providers
from core.api.providers import base as base_mod
from core.api.providers.anthropic import AnthropicChatClient
from core.api.providers.base import (
    BaseProviderClient,
    _extract_prompt_from_payload,
    get_chat_endpoint,
    get_models_endpoint,
    probe_text_models,
    request_with_retry,
)
from core.api.providers.openai import OpenAIChatClient
from core.config import API_ANTHROPIC, API_OPENAI, TextProvider
from core.i18n_backend import current_lang, set_current_lang, translate
from web.routes import config_routes

# ─────────────────────────────────────────────────────────────────────────────
# 测试替身与公共 fixture
# ─────────────────────────────────────────────────────────────────────────────


class FakeResponse:
    """最小 requests.Response 替身（status_code / text / json / raise_for_status）。"""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}", response=self,
            )


class _DummyLimiter:
    """令牌桶替身：acquire 永远立即通过，避免测试被限速拖慢。"""

    def __init__(self):
        self.acquired = 0

    def acquire(self):
        self.acquired += 1


@pytest.fixture
def isolated(monkeypatch):
    """隔离限速 / sleep / 错误落盘，返回捕获容器。"""
    limiter = _DummyLimiter()
    monkeypatch.setattr(base_mod, "get_rate_limiter", lambda: limiter)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    captured = {"errors": [], "exc": []}
    monkeypatch.setattr(
        base_mod, "collect_error",
        lambda *a, **k: captured["errors"].append((a, k)),
    )
    monkeypatch.setattr(
        base_mod, "collect_error_from_exception",
        lambda *a, **k: captured["exc"].append((a, k)),
    )
    captured["limiter"] = limiter
    return captured


class _DummyClient(BaseProviderClient):
    """可控 chat 输出的 BaseProviderClient 子类（用于 chat_json 分支覆盖）。"""

    api = API_OPENAI

    def __init__(self, replies):
        super().__init__("http://dummy/v1", "sk-dummy", "dummy-model")
        self._replies = list(replies)
        self.chat_calls = 0

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def chat(self, system_prompt, user_prompt, max_tokens=4096):
        self.chat_calls += 1
        return self._replies.pop(0) if self._replies else ""


# ─────────────────────────────────────────────────────────────────────────────
# 端点拼接纯函数
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "base_url,api,expected",
    [
        ("https://api.x.com/v1", API_OPENAI, "https://api.x.com/v1/chat/completions"),
        ("https://api.x.com/v1/", API_OPENAI, "https://api.x.com/v1/chat/completions"),
        ("https://api.x.com", API_ANTHROPIC, "https://api.x.com/v1/messages"),
        ("https://api.x.com/v1", API_ANTHROPIC, "https://api.x.com/v1/messages"),
        ("https://api.x.com/v1/", API_ANTHROPIC, "https://api.x.com/v1/messages"),
        ("", API_OPENAI, "/chat/completions"),
    ],
)
def test_get_chat_endpoint(base_url, api, expected):
    assert get_chat_endpoint(base_url, api) == expected


@pytest.mark.parametrize(
    "base_url,api,expected",
    [
        ("https://api.x.com/v1", API_OPENAI, "https://api.x.com/v1/models"),
        ("https://api.x.com/v1/", API_OPENAI, "https://api.x.com/v1/models"),
        ("https://api.x.com", API_ANTHROPIC, "https://api.x.com/v1/models"),
        ("https://api.x.com/v1", API_ANTHROPIC, "https://api.x.com/v1/models"),
        ("", API_OPENAI, "/models"),
    ],
)
def test_get_models_endpoint(base_url, api, expected):
    assert get_models_endpoint(base_url, api) == expected


# ─────────────────────────────────────────────────────────────────────────────
# request_with_retry
# ─────────────────────────────────────────────────────────────────────────────


def test_request_with_retry_success(isolated):
    seen = []

    def requester(url, headers=None, json=None, timeout=None):
        seen.append((url, headers, json, timeout))
        return FakeResponse(200, {"ok": 1})

    payload = {"messages": [{"role": "user", "content": "hi"}]}
    assert request_with_retry(requester, "http://x", {"H": "1"}, payload=payload) == {"ok": 1}
    assert seen[0][0] == "http://x"
    assert seen[0][2] == payload
    assert isolated["limiter"].acquired == 1


def test_request_with_retry_json_body_false(isolated):
    seen = []

    def requester(url, headers=None, timeout=None):
        seen.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse(200, {})

    request_with_retry(requester, "http://x", {}, json_body=False, timeout=7)
    assert seen[0]["timeout"] == 7
    assert "json" not in seen[0]
    assert isolated["limiter"].acquired == 1


def test_request_with_retry_429_then_success(isolated):
    queue = [FakeResponse(429, text="slow down"), FakeResponse(200, {"ok": 2})]

    def requester(*_a, **_k):
        return queue.pop(0)

    assert request_with_retry(requester, "http://x", {}) == {"ok": 2}
    assert isolated["limiter"].acquired == 2


def test_request_with_retry_connection_error_then_success(isolated):
    queue = [requests.ConnectionError("boom"), FakeResponse(200, {"ok": 3})]

    def requester(*_a, **_k):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    assert request_with_retry(requester, "http://x", {}) == {"ok": 3}
    assert len(isolated["exc"]) == 1


def test_request_with_retry_5xx_exhausted_raises(isolated):
    def requester(*_a, **_k):
        return FakeResponse(503, text="unavailable")

    with pytest.raises(requests.HTTPError):
        request_with_retry(
            requester, "http://x", {},
            payload={"messages": [{"role": "user", "content": "p"}]},
        )
    # 重试耗尽后落盘一条最终失败记录，且 prompt 已从 payload 提取
    assert isolated["errors"][0][1]["prompt"] == "p"
    assert isolated["errors"][0][1]["error_type"] == "HTTP503"


def test_request_with_retry_429_exhausted_records_rate_limit(isolated):
    def requester(*_a, **_k):
        return FakeResponse(429, text="rate limited")

    with pytest.raises(requests.HTTPError):
        request_with_retry(requester, "http://x", {})
    assert isolated["errors"][0][1]["error_type"] == "RateLimit429"


def test_request_with_retry_timeout_exhausted_raises(isolated):
    def requester(*_a, **_k):
        raise requests.Timeout("too slow")

    with pytest.raises(requests.Timeout):
        request_with_retry(requester, "http://x", {})
    assert len(isolated["exc"]) == 4  # 初次 + 3 次重试


def test_request_with_retry_4xx_not_retried(isolated):
    calls = []

    def requester(*_a, **_k):
        calls.append(1)
        return FakeResponse(401, text="bad key")

    with pytest.raises(requests.HTTPError):
        request_with_retry(requester, "http://x", {})
    assert len(calls) == 1
    assert isolated["errors"][0][1]["error_type"] == "HTTP401"


def test_request_with_retry_4xx_error_report_swallowed(isolated, monkeypatch):
    """落盘本身失败不能掩盖原始 HTTP 错误（try/except pass 分支）。"""

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(base_mod, "collect_error", boom)

    def requester(*_a, **_k):
        return FakeResponse(400, text="bad request")

    with pytest.raises(requests.HTTPError):
        request_with_retry(requester, "http://x", {})


# ─────────────────────────────────────────────────────────────────────────────
# _extract_prompt_from_payload
# ─────────────────────────────────────────────────────────────────────────────


def test_extract_prompt_string_content():
    payload = {"messages": [{"role": "user", "content": "  hello  "}]}
    assert _extract_prompt_from_payload(payload) == "  hello  "


def test_extract_prompt_list_content_picks_first_text():
    payload = {
        "messages": [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:x"}},
                {"type": "text", "text": "describe it"},
            ]},
        ],
    }
    assert _extract_prompt_from_payload(payload) == "describe it"


def test_extract_prompt_reversed_and_empty():
    assert _extract_prompt_from_payload({}) == ""
    assert _extract_prompt_from_payload({"messages": [{"role": "user", "content": "   "}]}) == ""
    payload = {"messages": [{"role": "user", "content": "first"}, {"role": "user", "content": "last"}]}
    assert _extract_prompt_from_payload(payload) == "last"


# ─────────────────────────────────────────────────────────────────────────────
# BaseProviderClient
# ─────────────────────────────────────────────────────────────────────────────


def test_base_client_defaults_and_abstract_methods():
    client = BaseProviderClient("http://x/v1/", "k", "m")
    assert client.base_url == "http://x/v1"  # 去尾斜杠
    assert client.api == API_OPENAI
    with pytest.raises(NotImplementedError):
        client._auth_headers()
    with pytest.raises(NotImplementedError):
        client._extract_content({})


def test_base_client_request_uses_endpoint_and_headers(monkeypatch):
    client = BaseProviderClient("http://x", "k", "m")
    seen = {}

    def fake_retry(requester, url, headers, *, payload=None, timeout=120):
        seen.update(url=url, headers=headers, payload=payload, timeout=timeout)
        return {"ok": True}

    monkeypatch.setattr(base_mod, "request_with_retry", fake_retry)
    monkeypatch.setattr(client, "_auth_headers", lambda: {"H": "1"})
    assert client._request({"a": 1}) == {"ok": True}
    assert seen["url"] == "http://x/chat/completions"
    assert seen["headers"] == {"H": "1"}


def test_chat_json_log_prefix():
    assert _DummyClient([])._log_prefix == "_DummyClient"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('here you go: {"a": 1} thanks', {"a": 1}),
    ],
)
def test_chat_json_parses_variants(isolated, raw, expected):
    client = _DummyClient([raw])
    assert client.chat_json("sys", "usr") == expected
    assert client.chat_calls == 1


def test_chat_json_retries_then_succeeds(isolated):
    client = _DummyClient(["not json at all", '{"ok": true}'])
    assert client.chat_json("sys", "usr") == {"ok": True}
    assert client.chat_calls == 2
    assert isolated["errors"] == []


def test_chat_json_uses_repair_json_fallback(isolated, monkeypatch):
    monkeypatch.setattr(base_mod, "repair_json", lambda text, return_objects=True: {"fixed": 1})
    client = _DummyClient(["no braces here"])
    assert client.chat_json("sys", "usr") == {"fixed": 1}


def test_chat_json_repair_json_non_dict_falls_through(isolated, monkeypatch):
    """repair 结果非 dict → 忽略并继续重试，最终抛 ValueError。"""
    monkeypatch.setattr(base_mod, "repair_json", lambda text, return_objects=True: [1, 2, 3])
    client = _DummyClient(["nope", "nope"])
    with pytest.raises(ValueError):
        client.chat_json("sys", "usr")
    assert len(isolated["errors"]) == 1
    assert isolated["errors"][0][1]["error_type"] == "JSONParseError"


def test_chat_json_repair_json_raises_is_ignored(isolated, monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("cannot repair")

    monkeypatch.setattr(base_mod, "repair_json", boom)
    client = _DummyClient(["nope", '{"ok": 1}'])
    assert client.chat_json("sys", "usr") == {"ok": 1}


# ─────────────────────────────────────────────────────────────────────────────
# probe_text_models
# ─────────────────────────────────────────────────────────────────────────────


def test_probe_text_models_openai_headers(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return FakeResponse(200, {"data": [{"id": "m1"}, {"id": ""}, {"nope": 1}, {"id": 2}]})

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    assert probe_text_models("https://api.x.com/v1", "sk-1", API_OPENAI) == ["m1", "2"]
    assert seen["url"] == "https://api.x.com/v1/models"
    assert seen["headers"]["Authorization"] == "Bearer sk-1"


def test_probe_text_models_anthropic_headers(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return FakeResponse(200, {"data": []})

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    assert probe_text_models("https://api.x.com", "sk-2", API_ANTHROPIC) == []
    assert seen["url"] == "https://api.x.com/v1/models"
    assert seen["headers"]["x-api-key"] == "sk-2"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"


def test_probe_text_models_http_error(monkeypatch):
    monkeypatch.setattr(
        base_mod.requests, "get",
        lambda url, headers=None, timeout=None: FakeResponse(401, text="unauthorized"),
    )
    with pytest.raises(requests.HTTPError):
        probe_text_models("https://api.x.com", "bad", API_OPENAI)


# ─────────────────────────────────────────────────────────────────────────────
# OpenAIChatClient
# ─────────────────────────────────────────────────────────────────────────────


def test_openai_headers_and_extract():
    client = OpenAIChatClient("https://api.x.com/v1/", "sk-1", "gpt-x")
    assert client.base_url == "https://api.x.com/v1"
    assert client._auth_headers() == {
        "Authorization": "Bearer sk-1",
        "Content-Type": "application/json",
    }
    data = {"choices": [{"message": {"content": "hello"}}]}
    assert client._extract_content(data) == "hello"


def test_openai_chat_payload(monkeypatch):
    client = OpenAIChatClient("https://api.x.com/v1", "sk-1", "gpt-x")
    seen = {}

    def fake_request(payload, timeout=120):
        seen.update(payload=payload, timeout=timeout)
        return {"choices": [{"message": {"content": "out"}}]}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.chat("SYS", "USR", max_tokens=128) == "out"
    assert seen["payload"]["model"] == "gpt-x"
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen["payload"]["messages"][1] == {"role": "user", "content": "USR"}
    assert seen["payload"]["max_tokens"] == 128


def test_openai_image_to_b64_uri(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG-fake")
    uri = OpenAIChatClient("http://x", "k", "m")._image_to_b64_uri(str(img))
    assert uri.startswith("data:image/png;base64,")


def test_openai_chat_multimodal_mixed_sources(monkeypatch, tmp_path):
    client = OpenAIChatClient("http://x", "k", "m")
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG-fake")
    seen = {}

    def fake_request(payload, timeout=120):
        seen.update(payload=payload, timeout=timeout)
        return {"choices": [{"message": {"content": "seen"}}]}

    monkeypatch.setattr(client, "_request", fake_request)
    out = client.chat_multimodal(
        "SYS", "TXT",
        ["https://img.example/x.png", str(img), str(tmp_path / "missing.png")],
    )
    assert out == "seen"
    user_content = seen["payload"]["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "TXT"}
    urls = [c["image_url"]["url"] for c in user_content[1:]]
    assert len(urls) == 2  # 远程 URL + 本地文件；缺失文件被跳过
    assert urls[0] == "https://img.example/x.png"
    assert urls[1].startswith("data:image/png;base64,")
    assert seen["timeout"] == 300


# ─────────────────────────────────────────────────────────────────────────────
# AnthropicChatClient
# ─────────────────────────────────────────────────────────────────────────────


def test_anthropic_endpoint_and_headers():
    client = AnthropicChatClient("https://api.a.com", "sk-a", "claude-x")
    assert client._chat_endpoint() == "https://api.a.com/v1/messages"
    assert AnthropicChatClient("https://api.a.com/v1", "sk-a", "m")._chat_endpoint() == (
        "https://api.a.com/v1/messages"
    )
    assert client._auth_headers() == {
        "x-api-key": "sk-a",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def test_anthropic_extract_content_variants():
    client = AnthropicChatClient("https://api.a.com", "sk-a", "m")
    assert client._extract_content({"content": [{"text": "hi"}]}) == "hi"
    assert client._extract_content({"content": []}) == ""
    assert client._extract_content({}) == ""


def test_anthropic_chat_payload(monkeypatch):
    client = AnthropicChatClient("https://api.a.com", "sk-a", "claude-x")
    seen = {}

    def fake_request(payload, timeout=120):
        seen.update(payload=payload)
        return {"content": [{"text": "out"}]}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.chat("SYS", "USR") == "out"
    assert seen["payload"]["system"] == "SYS"
    assert seen["payload"]["messages"] == [{"role": "user", "content": "USR"}]


def test_anthropic_request_builds_url(monkeypatch):
    client = AnthropicChatClient("https://api.a.com", "sk-a", "m")
    seen = {}

    def fake_retry(requester, url, headers, *, payload=None, timeout=120):
        seen.update(url=url, headers=headers)
        return {}

    monkeypatch.setattr("core.api.providers.anthropic.request_with_retry", fake_retry)
    client._request({"a": 1})
    assert seen["url"] == "https://api.a.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-a"


def test_anthropic_multimodal_falls_back_to_text(monkeypatch):
    client = AnthropicChatClient("https://api.a.com", "sk-a", "m")
    calls = []

    def fake_chat(system_prompt, user_prompt, max_tokens=4096):
        calls.append((system_prompt, user_prompt, max_tokens))
        return "text-only"

    monkeypatch.setattr(client, "chat", fake_chat)
    assert client.chat_multimodal("SYS", "USR", ["a.png", "b.png"]) == "text-only"
    assert calls == [("SYS", "USR", 4096)]


# ─────────────────────────────────────────────────────────────────────────────
# chat_providers 工厂
# ─────────────────────────────────────────────────────────────────────────────


def test_factory_agnes_branch(monkeypatch):
    monkeypatch.setattr(
        chat_providers, "resolve_text_chat",
        lambda: {"kind": "agnes", "model": "agnes-3.0-flash"},
    )
    monkeypatch.setattr("core.config.get_api_key", lambda: "sk-agnes")
    client = chat_providers.get_or_build_text_chat_client()
    assert client.__class__.__name__ == "AgnesChatAPI"
    assert client.api_key == "sk-agnes"
    assert client.model == "agnes-3.0-flash"


def test_factory_agnes_branch_explicit_overrides(monkeypatch):
    monkeypatch.setattr(
        chat_providers, "resolve_text_chat",
        lambda: {"kind": "agnes", "model": "cfg-model"},
    )
    monkeypatch.setattr("core.config.get_api_key", lambda: "sk-agnes")
    client = chat_providers.get_or_build_text_chat_client(api_key="sk-x", model="m-x")
    assert client.api_key == "sk-x"
    assert client.model == "m-x"


@pytest.mark.parametrize(
    "api,expected_cls",
    [(API_OPENAI, "OpenAIChatClient"), (API_ANTHROPIC, "AnthropicChatClient")],
)
def test_factory_custom_branches(monkeypatch, api, expected_cls):
    monkeypatch.setattr(
        chat_providers, "resolve_text_chat",
        lambda: {
            "kind": "custom", "provider": "p1", "api": api,
            "base_url": "https://api.x.com/v1", "api_key": "sk-c", "model": "m-c",
        },
    )
    client = chat_providers.get_or_build_text_chat_client()
    assert client.__class__.__name__ == expected_cls
    assert client.base_url == "https://api.x.com/v1"
    assert client.api_key == "sk-c"
    assert client.model == "m-c"


def test_factory_custom_model_override(monkeypatch):
    monkeypatch.setattr(
        chat_providers, "resolve_text_chat",
        lambda: {
            "kind": "custom", "provider": "p1", "api": API_OPENAI,
            "base_url": "https://api.x.com", "api_key": "sk-c", "model": "cfg",
        },
    )
    assert chat_providers.get_or_build_text_chat_client(model="override").model == "override"


# ─────────────────────────────────────────────────────────────────────────────
# /api/config/text-providers 路由
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(config_routes.router)
    return TestClient(app)


class TestProbeEndpoint:
    def test_invalid_api_422(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])
        resp = client.post(
            "/api/config/text-providers/test",
            data={"api": "grpc", "base_url": "https://x"},
        )
        assert resp.status_code == 422

    def test_empty_base_url_422(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])
        resp = client.post(
            "/api/config/text-providers/test",
            data={"api": API_OPENAI, "base_url": "  "},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "base_url 不能为空"

    def test_probe_success(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])
        seen = {}

        def fake_probe(base_url, api_key, api):
            seen.update(base_url=base_url, api_key=api_key, api=api)
            return ["m1", "m2"]

        monkeypatch.setattr(config_routes, "probe_text_models", fake_probe)
        resp = client.post(
            "/api/config/text-providers/test",
            data={"api": API_OPENAI, "base_url": "https://x/v1 ", "api_key": " sk "},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "models": ["m1", "m2"]}
        assert seen == {"base_url": "https://x/v1", "api_key": "sk", "api": API_OPENAI}

    def test_probe_falls_back_to_stored_credentials(self, client, monkeypatch):
        stored = TextProvider(
            provider="p1", display_name="P1", api=API_ANTHROPIC,
            base_url="https://stored/v1", api_key="sk-stored", models=["m"],
        )
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [stored])
        seen = {}

        def fake_probe(base_url, api_key, api):
            seen.update(base_url=base_url, api_key=api_key, api=api)
            return []

        monkeypatch.setattr(config_routes, "probe_text_models", fake_probe)
        # 未指明合法协议（"auto"）→ base_url / key / api 全部回退用已存供应商的值
        resp = client.post(
            "/api/config/text-providers/test", data={"provider": "p1", "api": "auto"},
        )
        assert resp.status_code == 200
        assert seen == {
            "base_url": "https://stored/v1", "api_key": "sk-stored", "api": API_ANTHROPIC,
        }

    def test_probe_empty_api_field_uses_form_default(self, client, monkeypatch):
        """空 form 值等价于字段缺省 → 用 Form 默认协议（前端始终会传协议）。"""
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])
        seen = {}

        def fake_probe(base_url, api_key, api):
            seen.update(api=api)
            return []

        monkeypatch.setattr(config_routes, "probe_text_models", fake_probe)
        resp = client.post(
            "/api/config/text-providers/test",
            data={"api": "", "base_url": "https://x", "api_key": "sk"},
        )
        assert resp.status_code == 200
        assert seen["api"] == API_OPENAI

    @pytest.mark.parametrize(
        "exc",
        [
            requests.HTTPError("https://internal.example/secret", response=FakeResponse(401)),
            requests.ConnectionError("dns exploded: 10.0.0.1"),
            RuntimeError("/opt/app/core/internal.py line 42"),
        ],
    )
    def test_probe_failure_never_echoes_exception(self, client, monkeypatch, exc):
        """探测失败只回固定文案，异常原文绝不外泄（CodeQL py/stack-trace-exposure）。"""
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])

        def boom(base_url, api_key, api):
            raise exc

        monkeypatch.setattr(config_routes, "probe_text_models", boom)
        resp = client.post(
            "/api/config/text-providers/test",
            data={"api": API_OPENAI, "base_url": "https://x"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "ok": False, "error": translate(config_routes._PROBE_FAILED_KEY),
        }
        assert str(exc) not in json.dumps(body)

    def test_probe_failure_localized_by_ui_lang_header(self, client, monkeypatch):
        """探测失败提示按 X-Agnes-UI-Lang 本地化（en 请求回英文文案）。"""
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])

        def boom(base_url, api_key, api):
            raise requests.ConnectionError("dns exploded")

        monkeypatch.setattr(config_routes, "probe_text_models", boom)
        token = set_current_lang("en")
        try:
            resp = client.post(
                "/api/config/text-providers/test",
                data={"api": API_OPENAI, "base_url": "https://x"},
            )
        finally:
            current_lang.reset(token)
        assert resp.json()["error"] == translate("provider.probe_failed", "en")
        assert "probe failed" in resp.json()["error"]


class TestListEndpoint:
    def test_list_includes_builtin_first_and_masks(self, client, monkeypatch):
        monkeypatch.setattr(
            config_routes, "get_text_providers",
            lambda: [TextProvider(
                provider="p1", display_name="DeepSeek", api=API_OPENAI,
                base_url="https://x/v1", api_key="sk-1234567890abcdef", models=["a", "b"],
            )],
        )
        monkeypatch.setattr(config_routes, "get_selected_text_provider", lambda: "p1")
        monkeypatch.setattr(config_routes, "get_selected_models", lambda: {"text": "a"})
        resp = client.get("/api/config/text-providers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["selected"] == "p1"
        assert body["current_model"] == "a"
        assert body["providers"][0]["provider"] == "agnes"
        assert body["providers"][0]["builtin"] is True
        assert body["providers"][0]["selected"] is False
        custom = body["providers"][1]
        assert custom["display_name"] == "DeepSeek"
        assert custom["builtin"] is False
        assert custom["selected"] is True
        assert custom["api_key"] == "sk-123...cdef"  # 仅回掩码

    def test_list_builtin_selected_when_empty(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])
        monkeypatch.setattr(config_routes, "get_selected_text_provider", lambda: "")
        monkeypatch.setattr(config_routes, "get_selected_models", lambda: {})
        body = client.get("/api/config/text-providers").json()
        assert body["selected"] == "agnes"
        assert body["providers"][0]["selected"] is True
        assert body["current_model"] is None


class TestSaveEndpoint:
    def test_empty_provider_400(self, client):
        resp = client.post(
            "/api/config/text-providers",
            data={"provider": "  ", "api": API_OPENAI, "base_url": "https://x"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "provider 不能为空"

    def test_invalid_api_422(self, client):
        resp = client.post(
            "/api/config/text-providers",
            data={"provider": "p1", "api": "grpc", "base_url": "https://x"},
        )
        assert resp.status_code == 422

    def test_empty_base_url_422(self, client):
        resp = client.post(
            "/api/config/text-providers",
            data={"provider": "p1", "api": API_OPENAI, "base_url": ""},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "base_url 不能为空"

    def test_bad_models_json_422(self, client):
        resp = client.post(
            "/api/config/text-providers",
            data={
                "provider": "p1", "api": API_OPENAI,
                "base_url": "https://x", "models_json": "{not-an-array",
            },
        )
        assert resp.status_code == 422
        assert "models_json" in resp.json()["detail"]

    def test_save_success_sanitizes_models(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(config_routes, "save_text_provider", lambda p: saved.update(p=p))
        resp = client.post(
            "/api/config/text-providers",
            data={
                "provider": " p1 ", "display_name": " P1 ", "api": API_OPENAI,
                "base_url": " https://x/v1 ", "api_key": "sk-1",
                "models_json": json.dumps([" a ", "b", ""]),
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        p = saved["p"]
        assert p.provider == "p1"
        assert p.display_name == "P1"
        assert p.base_url == "https://x/v1"
        assert p.models == ["a", "b"]

    def test_save_empty_key_keeps_stored_key(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(config_routes, "save_text_provider", lambda p: saved.update(p=p))
        monkeypatch.setattr(
            config_routes, "load_config",
            lambda: {"text_providers": [{"provider": "p1", "api_key": "sk-stored"}]},
        )
        resp = client.post(
            "/api/config/text-providers",
            data={"provider": "p1", "api": API_OPENAI, "base_url": "https://x", "api_key": ""},
        )
        assert resp.status_code == 200
        assert saved["p"].api_key == "sk-stored"

    def test_save_empty_key_without_existing_keeps_empty(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(config_routes, "save_text_provider", lambda p: saved.update(p=p))
        monkeypatch.setattr(config_routes, "load_config", lambda: {"text_providers": []})
        resp = client.post(
            "/api/config/text-providers",
            data={"provider": "p2", "api": API_OPENAI, "base_url": "https://x", "api_key": ""},
        )
        assert resp.status_code == 200
        assert saved["p"].api_key == ""

    def test_save_ignores_non_dict_entries(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(config_routes, "save_text_provider", lambda p: saved.update(p=p))
        monkeypatch.setattr(
            config_routes, "load_config",
            lambda: {"text_providers": [
                "garbage",
                {"provider": "other", "api_key": "sk-other"},
            ]},
        )
        resp = client.post(
            "/api/config/text-providers",
            data={"provider": "p1", "api": API_OPENAI, "base_url": "https://x"},
        )
        assert resp.status_code == 200
        assert saved["p"].api_key == ""


class TestDeleteEndpoint:
    def test_builtin_agnes_400(self, client):
        resp = client.delete("/api/config/text-providers/agnes")
        assert resp.status_code == 400
        assert "不可删除" in resp.json()["detail"]

    def test_not_found_404(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "delete_text_provider", lambda p: False)
        resp = client.delete("/api/config/text-providers/nope")
        assert resp.status_code == 404

    def test_delete_selected_falls_back_to_agnes(self, client, monkeypatch):
        calls = {}
        monkeypatch.setattr(config_routes, "delete_text_provider", lambda p: True)
        monkeypatch.setattr(config_routes, "get_selected_text_provider", lambda: "p1")
        monkeypatch.setattr(
            config_routes, "set_selected_text_provider",
            lambda v: calls.update(provider=v),
        )
        monkeypatch.setattr(
            config_routes, "set_selected_models",
            lambda **k: calls.update(models=k),
        )
        resp = client.delete("/api/config/text-providers/p1")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "deleted": True}
        assert calls["provider"] == ""
        assert calls["models"] == {"text": config_routes.DEFAULT_TEXT_MODEL}

    def test_delete_unselected_keeps_selection(self, client, monkeypatch):
        calls = {}
        monkeypatch.setattr(config_routes, "delete_text_provider", lambda p: True)
        monkeypatch.setattr(config_routes, "get_selected_text_provider", lambda: "other")
        monkeypatch.setattr(
            config_routes, "set_selected_text_provider",
            lambda v: calls.update(provider=v),
        )
        resp = client.delete("/api/config/text-providers/p1")
        assert resp.status_code == 200
        assert "provider" not in calls


class TestSyncEndpoint:
    def test_builtin_agnes_400(self, client):
        resp = client.post("/api/config/text-providers/agnes/sync", data={"models_json": "[]"})
        assert resp.status_code == 400

    def test_empty_models_json_422(self, client):
        resp = client.post("/api/config/text-providers/p1/sync", data={"models_json": "  "})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "models_json 不能为空"

    def test_bad_models_json_422(self, client):
        resp = client.post(
            "/api/config/text-providers/p1/sync", data={"models_json": "[1,"},
        )
        assert resp.status_code == 422

    def test_not_found_404(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [])
        resp = client.post(
            "/api/config/text-providers/p1/sync", data={"models_json": '["m1"]'},
        )
        assert resp.status_code == 404

    def test_sync_success_keeps_other_fields(self, client, monkeypatch):
        stored = TextProvider(
            provider="p1", display_name="P1", api=API_ANTHROPIC,
            base_url="https://x/v1", api_key="sk-1", models=["old"],
        )
        monkeypatch.setattr(config_routes, "get_text_providers", lambda: [stored])
        saved = {}
        monkeypatch.setattr(config_routes, "save_text_provider", lambda p: saved.update(p=p))
        resp = client.post(
            "/api/config/text-providers/p1/sync",
            data={"models_json": json.dumps([" m1 ", "m2", ""])},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        p = saved["p"]
        assert p.provider == "p1"
        assert p.display_name == "P1"
        assert p.api == API_ANTHROPIC
        assert p.base_url == "https://x/v1"
        assert p.api_key == "sk-1"
        assert p.models == ["m1", "m2"]
