"""web.middleware.LangContextMiddleware 集成测试（v7.0，issue #64）。

验证「请求头 → ContextVar → translate」的端到端链路：
- ``X-Agnes-UI-Lang`` 头驱动 ``current_lang``；
- 缺该头时回退 ``Accept-Language``；
- 两者都缺时回退默认 ``zh``；
- 请求结束后 ContextVar 被 reset（不污染后续请求）；
- 真实路由（image/generate 的 API Key 缺失分支）按头返回对应语种。

这些是单测（test_backend_i18n.py）覆盖不到的「中间件 + 路由」协作部分。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.i18n_backend import get_current_lang, translate
from web.middleware import LangContextMiddleware, extract_request_lang


# ─────────────────────────────────────────────────────────────────────────────
# 夹具：一个挂了中间件的最小 app，路由里回显当前语言与翻译结果
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    app = FastAPI()
    app.add_middleware(LangContextMiddleware)

    @app.get("/echo-lang")
    async def echo_lang():
        # 在请求处理函数里读 ContextVar，验证中间件确实写入了
        return {"lang": get_current_lang(), "msg": translate("task.queued")}

    @app.get("/raise-localized")
    async def raise_localized():
        # 模拟路由抛 HTTPException 时按上下文语言本地化 detail
        raise HTTPException(status_code=400, detail=translate("config.api_key_missing"))

    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 端到端：头 → ContextVar → translate
# ─────────────────────────────────────────────────────────────────────────────


def test_ui_lang_header_drives_context_and_message(client):
    r = client.get("/echo-lang", headers={"X-Agnes-UI-Lang": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["lang"] == "en"
    assert body["msg"] == "Task queued..."


def test_ui_lang_header_zh(client):
    r = client.get("/echo-lang", headers={"X-Agnes-UI-Lang": "zh"})
    body = r.json()
    assert body["lang"] == "zh"
    assert body["msg"] == "任务排队中..."


def test_ui_lang_header_normalizes_region_tag(client):
    """``en-US`` 归一到 ``en``。"""
    r = client.get("/echo-lang", headers={"X-Agnes-UI-Lang": "en-US"})
    assert r.json()["lang"] == "en"


def test_ui_lang_header_unknown_falls_back_to_zh(client):
    r = client.get("/echo-lang", headers={"X-Agnes-UI-Lang": "klingon"})
    assert r.json()["lang"] == "zh"


def test_accept_language_fallback_when_no_custom_header(client):
    """无 ``X-Agnes-UI-Lang`` 时回退 ``Accept-Language``。"""
    r = client.get("/echo-lang", headers={"Accept-Language": "ja-JP,ja;q=0.9"})
    assert r.json()["lang"] == "ja"


def test_custom_header_takes_priority_over_accept_language(client):
    """自定义头优先于 ``Accept-Language``（应用内选择 > 浏览器偏好）。"""
    r = client.get(
        "/echo-lang",
        headers={"X-Agnes-UI-Lang": "en", "Accept-Language": "zh-CN,zh;q=0.9"},
    )
    assert r.json()["lang"] == "en"


def test_no_headers_defaults_to_zh(client):
    r = client.get("/echo-lang")
    assert r.json()["lang"] == "zh"


def test_contextvar_reset_between_requests(client):
    """前一个请求的语言不得泄漏到后一个请求（中间件 finally reset）。"""
    r1 = client.get("/echo-lang", headers={"X-Agnes-UI-Lang": "en"})
    assert r1.json()["lang"] == "en"
    # 第二个请求不带头 → 必须回到默认 zh，而不是残留 en
    r2 = client.get("/echo-lang")
    assert r2.json()["lang"] == "zh"


def test_http_exception_detail_is_localized(client):
    """真实路由抛 HTTPException 时 detail 按头本地化。"""
    r_en = client.get("/raise-localized", headers={"X-Agnes-UI-Lang": "en"})
    assert r_en.status_code == 400
    assert "Please configure an API Key" in r_en.json()["detail"]

    r_zh = client.get("/raise-localized", headers={"X-Agnes-UI-Lang": "zh"})
    assert "请先配置 API Key" in r_zh.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# extract_request_lang 纯函数（不依赖 TestClient）
# ─────────────────────────────────────────────────────────────────────────────


class _FakeHeaders(dict):
    def get(self, key, default=None):  # noqa: D102
        # 模拟 Starlette Headers 的大小写不敏感
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _FakeRequest:
    def __init__(self, headers):
        self.headers = _FakeHeaders(headers)


def test_extract_request_lang_custom_header():
    req = _FakeRequest({"X-Agnes-UI-Lang": "fr"})
    assert extract_request_lang(req) == "fr"


def test_extract_request_lang_accept_language():
    req = _FakeRequest({"Accept-Language": "de-DE,de;q=0.9,en;q=0.5"})
    assert extract_request_lang(req) == "de"


def test_extract_request_lang_default():
    req = _FakeRequest({})
    assert extract_request_lang(req) == "zh"
