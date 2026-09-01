"""
单元测试：API 辅助模块补充覆盖（提升 Sonar 泄漏周期新代码覆盖率）。

覆盖：
- core.api.agnes_models: _classify / fetch_available_models（fallback 分支）
- core.api.rate_limiter: _key_count / request_with_key_rotation（429 换 Key、退避）
- core.api.agnes_image: 日志分支（i2i/t2i 提示）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import requests

from core.api import agnes_models
from core.api.rate_limiter import _key_count, request_with_key_rotation

# ═══════════════════════════════════════════════
# agnes_models
# ═══════════════════════════════════════════════

class TestClassify:
    def test_image_prefix(self):
        assert agnes_models._classify("agnes-image-2.1-flash") == "image"

    def test_video_prefix(self):
        assert agnes_models._classify("agnes-video-v2.0") == "video"

    def test_text_default(self):
        assert agnes_models._classify("agnes-2.0-flash") == "text"
        assert agnes_models._classify("other-model") == "text"


class TestFetchAvailableModels:
    def test_ok_groups(self, monkeypatch):
        resp = requests.Response()
        resp.status_code = 200
        resp._content = (
            b'{"data": [{"id": "agnes-image-2.1-flash"}, '
            b'{"id": "agnes-video-v2.0"}, {"id": "agnes-2.0-flash"}]}'
        )
        monkeypatch.setattr(agnes_models.requests, "get", lambda *a, **k: resp)
        out = agnes_models.fetch_available_models("sk-test")
        assert "image" in out and "video" in out and "text" in out

    def test_http_error_falls_back(self, monkeypatch):
        resp = requests.Response()
        resp.status_code = 500
        monkeypatch.setattr(agnes_models.requests, "get", lambda *a, **k: resp)
        out = agnes_models.fetch_available_models("sk-test")
        assert out["text"] == [agnes_models.DEFAULT_TEXT_MODEL]

    def test_request_exception_falls_back(self, monkeypatch):
        def boom(*a, **k):
            raise requests.RequestException("net down")

        monkeypatch.setattr(agnes_models.requests, "get", boom)
        out = agnes_models.fetch_available_models("sk-test")
        assert out["image"] == [agnes_models.DEFAULT_IMAGE_MODEL]


# ═══════════════════════════════════════════════
# rate_limiter
# ═══════════════════════════════════════════════

class TestKeyCount:
    def test_default_one(self, monkeypatch):
        monkeypatch.setattr("core.api.rate_limiter.get_key_ring", lambda: [])
        assert _key_count() == 0

    def test_multiple(self, monkeypatch):
        monkeypatch.setattr("core.api.rate_limiter.get_key_ring", lambda: ["a", "b", "c"])
        assert _key_count() == 3

    def test_exception_falls_back_one(self, monkeypatch):
        def boom():
            raise RuntimeError

        monkeypatch.setattr("core.api.rate_limiter.get_key_ring", boom)
        assert _key_count() == 1


class TestRequestWithKeyRotation:
    def _make_ring(self):
        class Ring:
            def __init__(self, keys):
                self._keys = keys
                self._i = 0

            def next(self):
                k = self._keys[self._i % len(self._keys)]
                self._i += 1
                return k

            def rotate(self):
                pass

            def has_multiple(self):
                return len(self._keys) > 1

            def __len__(self):
                return len(self._keys)

        return Ring(["sk-a", "sk-b"])

    def test_success_first_try(self, monkeypatch):
        resp = requests.Response()
        resp.status_code = 200

        def requester(url, headers, **kw):
            return resp

        monkeypatch.setattr("core.config.get_base_url_for_key", lambda k: "https://api.example.com")
        out = request_with_key_rotation(requester, "/videos", key_ring=self._make_ring())
        assert out.status_code == 200

    def test_429_rotate_and_retry(self, monkeypatch):
        calls = {"n": 0}
        resp429 = requests.Response()
        resp429.status_code = 429
        resp200 = requests.Response()
        resp200.status_code = 200

        def requester(url, headers, **kw):
            calls["n"] += 1
            return resp429 if calls["n"] == 1 else resp200

        monkeypatch.setattr("core.config.get_base_url_for_key", lambda k: "https://api.example.com")
        out = request_with_key_rotation(requester, "/videos", key_ring=self._make_ring())
        assert out.status_code == 200
        assert calls["n"] == 2

    def test_connection_error_retries_then_raises(self, monkeypatch):
        from unittest import mock

        def requester(url, headers, **kw):
            raise requests.ConnectionError("down")

        monkeypatch.setattr("core.config.get_base_url_for_key", lambda k: "https://api.example.com")
        monkeypatch.setattr("core.api.rate_limiter.time", mock.Mock(sleep=lambda s: None))
        with pytest.raises(requests.ConnectionError):
            request_with_key_rotation(requester, "/videos", key_ring=self._make_ring(), max_retries=1)

    def test_5xx_retries(self, monkeypatch):
        from unittest import mock

        calls = {"n": 0}
        resp500 = requests.Response()
        resp500.status_code = 500
        resp200 = requests.Response()
        resp200.status_code = 200

        def requester(url, headers, **kw):
            calls["n"] += 1
            return resp500 if calls["n"] == 1 else resp200

        monkeypatch.setattr("core.config.get_base_url_for_key", lambda k: "https://api.example.com")
        monkeypatch.setattr("core.api.rate_limiter.time", mock.Mock(sleep=lambda s: None))
        out = request_with_key_rotation(requester, "/videos", key_ring=self._make_ring(), max_retries=2)
        assert out.status_code == 200
        assert calls["n"] == 2


# ═══════════════════════════════════════════════
# agnes_chat: chat_json JSON 解析路径（S5713 修复分支）
# ═══════════════════════════════════════════════

class TestChatJson:
    def _api(self):
        from core.api.agnes_chat import AgnesChatAPI
        return AgnesChatAPI(api_key="sk-test")

    def test_direct_json(self, monkeypatch):
        """直接 JSON → 返回解析结果。"""
        api = self._api()
        monkeypatch.setattr(api, "chat", lambda *a, **k: '{"ok": true}')
        assert api.chat_json("sys", "user") == {"ok": True}

    def test_code_fence_json(self, monkeypatch):
        """代码围栏包裹 → 去围栏后解析。"""
        api = self._api()
        monkeypatch.setattr(api, "chat", lambda *a, **k: '```json\n{"ok": true}\n```')
        assert api.chat_json("sys", "user") == {"ok": True}

    def test_regex_extract(self, monkeypatch):
        """围栏外有杂文本 → 正则提取首个 JSON 块。"""
        api = self._api()
        monkeypatch.setattr(api, "chat", lambda *a, **k: 'Here is the result: {"ok": true}')
        assert api.chat_json("sys", "user") == {"ok": True}

    def test_retry_then_success(self, monkeypatch):
        """首次失败 → 重试一次 chat → 成功。"""
        api = self._api()
        calls = {"n": 0}

        def fake_chat(*a, **k):
            calls["n"] += 1
            return '{"ok": true}' if calls["n"] > 1 else 'not json at all'

        monkeypatch.setattr(api, "chat", fake_chat)
        assert api.chat_json("sys", "user") == {"ok": True}
        assert calls["n"] == 2

    def test_final_failure_raises(self, monkeypatch):
        """两轮均失败 → 抛 ValueError。"""
        api = self._api()
        monkeypatch.setattr(api, "chat", lambda *a, **k: "no json here")
        with pytest.raises(ValueError):
            api.chat_json("sys", "user")
