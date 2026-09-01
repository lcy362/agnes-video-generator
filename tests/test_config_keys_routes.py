"""
config/keys 与 config/keys/domain 路由单测 — tests/test_config_keys_routes.py

覆盖（对应 SonarCloud Quality Gate 新代码覆盖率缺口）：
- DELETE /api/config/keys：remove_config_key
  - 400: key 与 id 均缺失
  - 404: 明文 key 不存在
  - 404: 掩码 id 未匹配
  - 400: env 来源 key 不可移除
  - 200: config 来源 key 正常移除（含 reset_key_ring / reset_rate_limiter 被调用）
- POST /api/config/keys/domain：save_config_key_domain
  - 422: domain 不在 AGNES_DOMAIN_MAP
  - 404: id 未匹配
  - 400: env 来源 key 不可持久化域名
  - 200: config 来源 key 正常保存域名

写路径隔离：config 写入函数、KeyRing/限速器重置均在 monkeypatch 中打桩，
绝不触碰真实配置与工作区。

用法:
    .venv/bin/python -m pytest tests/test_config_keys_routes.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import config_routes


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(config_routes.router)
    return TestClient(app)


def _make_items(*entries):
    """构造 get_api_keys_with_sources 的返回值。

    entry: ("key", "env"|"config")
    """
    return [{"key": k, "source": s} for k, s in entries]


class TestRemoveConfigKey:
    def test_missing_key_and_id_400(self, client, monkeypatch):
        """key 与 id 均缺失 → 400。"""
        monkeypatch.setattr(config_routes, "get_api_keys_with_sources", lambda: [])
        resp = client.request("DELETE", "/api/config/keys", data={})
        assert resp.status_code == 400
        assert "缺失" in resp.json()["detail"]

    def test_plain_key_not_found_404(self, client, monkeypatch):
        """明文 key 不存在 → 404。"""
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items(("sk-other", "config")),
        )
        resp = client.request("DELETE", "/api/config/keys", data={"key": "sk-nope"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Key 不存在"

    def test_id_not_matched_404(self, client, monkeypatch):
        """掩码 id 未匹配到任何 key → 404。"""
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items(("sk-test-1234567890", "config")),
        )
        resp = client.request("DELETE", "/api/config/keys", data={"id": "no-such-id"})
        assert resp.status_code == 404

    def test_env_source_rejected_400(self, client, monkeypatch):
        """只来自 env 的 key → 400（remove_api_key_single 未改动）。"""
        key = "sk-env-1234567890"
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "env")),
        )
        monkeypatch.setattr(config_routes, "remove_api_key_single", lambda k: (False, True))
        resp = client.request("DELETE", "/api/config/keys", data={"key": key})
        assert resp.status_code == 400
        assert "环境变量" in resp.json()["detail"]

    def test_remove_by_plain_key_ok(self, client, monkeypatch):
        """明文 key 正常移除 → 200，触发 ring/rate limiter 重置。"""
        key = "sk-test-1234567890"
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "config")),
        )
        monkeypatch.setattr(config_routes, "remove_api_key_single", lambda k: (True, False))
        calls = {"ring": 0, "limiter": 0}
        monkeypatch.setattr(config_routes, "reset_key_ring", lambda: calls.__setitem__("ring", calls["ring"] + 1))
        monkeypatch.setattr(config_routes, "reset_rate_limiter", lambda: calls.__setitem__("limiter", calls["limiter"] + 1))

        resp = client.request("DELETE", "/api/config/keys", data={"key": key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["removed"] == f"{key[:6]}...{key[-4:]}"
        assert calls["ring"] == 1 and calls["limiter"] == 1

    def test_remove_by_id_ok(self, client, monkeypatch):
        """按掩码 id 定位移除 → 200。"""
        key = "sk-test-abcdef1234567890"
        key_id = config_routes._key_id(key)
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "config")),
        )
        monkeypatch.setattr(config_routes, "remove_api_key_single", lambda k: (True, False))
        monkeypatch.setattr(config_routes, "reset_key_ring", lambda: None)
        monkeypatch.setattr(config_routes, "reset_rate_limiter", lambda: None)

        resp = client.request("DELETE", "/api/config/keys", data={"id": key_id})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_remove_env_key_by_id_400(self, client, monkeypatch):
        """按 id 定位到 env 来源 key → 400。"""
        key = "sk-env-abcdef1234567890"
        key_id = config_routes._key_id(key)
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "env")),
        )
        monkeypatch.setattr(config_routes, "remove_api_key_single", lambda k: (False, True))
        resp = client.request("DELETE", "/api/config/keys", data={"id": key_id})
        assert resp.status_code == 400


class TestSaveConfigKeyDomain:
    def test_invalid_domain_422(self, client, monkeypatch):
        """domain 不在 AGNES_DOMAIN_MAP → 422。"""
        monkeypatch.setattr(config_routes, "AGNES_DOMAIN_MAP", {"com": "url"})
        monkeypatch.setattr(config_routes, "get_api_keys_with_sources", lambda: [])
        resp = client.post("/api/config/keys/domain", data={"id": "x", "domain": "evil"})
        assert resp.status_code == 422

    def test_id_not_matched_404(self, client, monkeypatch):
        """id 未匹配 → 404。"""
        monkeypatch.setattr(config_routes, "AGNES_DOMAIN_MAP", {"com": "url"})
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items(("sk-test-abcdef1234567890", "config")),
        )
        resp = client.post("/api/config/keys/domain", data={"id": "no-such-id", "domain": "com"})
        assert resp.status_code == 404

    def test_env_source_rejected_400(self, client, monkeypatch):
        """env 来源 key → 400。"""
        key = "sk-env-abcdef1234567890"
        key_id = config_routes._key_id(key)
        monkeypatch.setattr(config_routes, "AGNES_DOMAIN_MAP", {"com": "url"})
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "env")),
        )
        resp = client.post("/api/config/keys/domain", data={"id": key_id, "domain": "com"})
        assert resp.status_code == 400

    def test_save_domain_ok(self, client, monkeypatch):
        """config 来源 key 正常保存域名 → 200。"""
        key = "sk-test-abcdef1234567890"
        key_id = config_routes._key_id(key)
        monkeypatch.setattr(config_routes, "AGNES_DOMAIN_MAP", {"com": "url", "cn": "url2"})
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "config")),
        )
        saved = {}

        def fake_set(mapping):
            saved.update(mapping)

        monkeypatch.setattr(config_routes, "set_api_key_domains", fake_set)

        resp = client.post("/api/config/keys/domain", data={"id": key_id, "domain": "cn"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["domain"] == "cn"
        assert saved.get(key) == "cn"

    def test_clear_domain_ok(self, client, monkeypatch):
        """domain 为空表示清除绑定 → 200 且写入空串。"""
        key = "sk-test-abcdef1234567890"
        key_id = config_routes._key_id(key)
        monkeypatch.setattr(config_routes, "AGNES_DOMAIN_MAP", {"com": "url"})
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: _make_items((key, "config")),
        )
        saved = {}

        def fake_set(mapping):
            saved.update(mapping)

        monkeypatch.setattr(config_routes, "set_api_key_domains", fake_set)

        resp = client.post("/api/config/keys/domain", data={"id": key_id, "domain": ""})
        assert resp.status_code == 200
        assert resp.json()["domain"] == ""
        assert saved.get(key) == ""
