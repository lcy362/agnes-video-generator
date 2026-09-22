"""风格/提示词预设库单测 — tests/test_presets.py

覆盖（对应 SonarCloud Quality Gate 新代码覆盖率缺口 P0-1）：
- ``core/presets.py``：系统预设读取容错、用户预设读写/过滤、增删、只读判定、分组
- ``web/routes/preset_routes.py``：GET 列表、POST（422 / 200）、DELETE（400 系统只读 / 404 / 200）

隔离：系统预设源文件、用户预设持久化文件、CONFIG_DIR 全部重定向到 tmp_path，
绝不触碰真实 resource/ 与 .agnes_config/。

用法:
    .venv/bin/python -m pytest tests/test_presets.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import presets
from web.routes import preset_routes

# ═══════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════


@pytest.fixture()
def sandbox(monkeypatch, tmp_path):
    """把预设库的两个持久化路径 + CONFIG_DIR 全部指向 tmp_path。"""
    system_path = tmp_path / "styles.json"
    user_path = tmp_path / "user_presets.json"
    monkeypatch.setattr(presets, "_SYSTEM_PRESETS_PATH", str(system_path))
    monkeypatch.setattr(presets, "_USER_PRESETS_PATH", str(user_path))
    monkeypatch.setattr(presets, "CONFIG_DIR", str(tmp_path))
    return system_path, user_path


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(preset_routes.router)
    return TestClient(app)


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload if isinstance(payload, str) else json.dumps(payload))


# ═══════════════════════════════════════════════════
# core/presets.py — 系统预设
# ═══════════════════════════════════════════════════


def test_load_system_presets_skips_invalid_entries(sandbox):
    system_path, _ = sandbox
    _write(system_path, [
        {"id": "docu", "category": "photographic", "prompt": "documentary"},
        {"id": "", "category": "x", "prompt": "无 id 应被丢弃"},
        "not-a-dict",
        {"id": 123, "category": None, "prompt": None},  # 非字符串会被 str() 归一
    ])

    loaded = presets.load_system_presets()
    assert [p["id"] for p in loaded] == ["docu", "123"]
    assert loaded[0]["prompt"] == "documentary"
    assert loaded[1]["category"] == "None"


def test_load_system_presets_missing_file(sandbox):
    assert presets.load_system_presets() == []


def test_load_system_presets_non_list_payload(sandbox):
    system_path, _ = sandbox
    _write(system_path, {"id": "x"})
    assert presets.load_system_presets() == []


def test_load_system_presets_broken_json(sandbox):
    system_path, _ = sandbox
    _write(system_path, "{ not json")
    assert presets.load_system_presets() == []


def test_is_system_preset_and_ids(sandbox):
    system_path, _ = sandbox
    _write(system_path, [{"id": "docu", "category": "photographic", "prompt": "p"}])

    assert presets.is_system_preset("docu") is True
    assert presets.is_system_preset("u_1") is False
    assert presets.get_system_preset_ids() == {"docu"}


# ═══════════════════════════════════════════════════
# core/presets.py — 用户预设
# ═══════════════════════════════════════════════════


def test_load_user_presets_missing_file(sandbox):
    assert presets.load_user_presets() == []
    assert presets._load_user_raw() == []


def test_load_user_presets_broken_json_and_non_list(sandbox):
    _, user_path = sandbox
    _write(user_path, "{ broken")
    assert presets._load_user_raw() == []
    _write(user_path, {"id": "u_1"})
    assert presets._load_user_raw() == []


def test_load_user_presets_filters_and_defaults(sandbox):
    _, user_path = sandbox
    _write(user_path, [
        {"id": "u_1", "name": "我的风格", "prompt": "cinematic", "created_at": "2026-01-01T00:00:00"},
        {"id": "u_2", "prompt": "无名称"},   # name 缺省 → 未命名
        {"id": "", "name": "无 id"},          # 无 id → 丢弃
        "not-a-dict",
    ])

    loaded = presets.load_user_presets()
    assert [p["id"] for p in loaded] == ["u_1", "u_2"]
    assert loaded[0]["category"] == presets.USER_CATEGORY
    assert loaded[1]["name"] == "未命名"
    assert loaded[1]["created_at"] == ""


def test_create_user_preset_persists(sandbox):
    created = presets.create_user_preset("  夜景  ", "  neon city  ")

    assert created["id"].startswith("u_")
    assert created["name"] == "夜景"
    assert created["prompt"] == "neon city"
    assert created["category"] == presets.USER_CATEGORY
    assert created["created_at"]

    reloaded = presets.load_user_presets()
    assert [p["id"] for p in reloaded] == [created["id"]]


def test_create_user_preset_blank_name_and_prompt(sandbox):
    created = presets.create_user_preset("   ", "   ")
    assert created["name"] == "未命名"
    assert created["prompt"] == ""


def test_delete_user_preset(sandbox):
    first = presets.create_user_preset("a", "p1")
    second = presets.create_user_preset("b", "p2")

    assert presets.delete_user_preset(second["id"]) is True
    remaining = [p["id"] for p in presets.load_user_presets()]
    assert remaining == [first["id"]]
    assert presets.delete_user_preset("u_not_exist") is False


def test_grouped_presets_returns_system_and_user(sandbox):
    system_path, _ = sandbox
    _write(system_path, [{"id": "docu", "category": "photographic", "prompt": "p"}])
    presets.create_user_preset("自定义", "my prompt")

    system, user = presets.grouped_presets()
    assert [p["id"] for p in system] == ["docu"]
    assert [p["name"] for p in user] == ["自定义"]


# ═══════════════════════════════════════════════════
# web/routes/preset_routes.py
# ═══════════════════════════════════════════════════


def test_list_presets_route(client, monkeypatch):
    monkeypatch.setattr(preset_routes, "load_system_presets", lambda: [{"id": "s1"}])
    monkeypatch.setattr(preset_routes, "load_user_presets", lambda: [{"id": "u1"}])

    data = client.get("/api/presets").json()
    assert data == {"ok": True, "system": [{"id": "s1"}], "user": [{"id": "u1"}]}


def test_save_preset_rejects_blank_prompt(client, monkeypatch):
    called = []
    monkeypatch.setattr(preset_routes, "create_user_preset",
                        lambda name, prompt: called.append((name, prompt)) or {})

    resp = client.post("/api/presets", data={"name": "n", "prompt": "   "})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "prompt 不能为空"
    assert called == []  # 校验拦截，未写盘


def test_save_preset_ok(client, monkeypatch):
    monkeypatch.setattr(
        preset_routes, "create_user_preset",
        lambda name, prompt: {"id": "u_9", "name": name.strip(), "prompt": prompt.strip()},
    )

    resp = client.post("/api/presets", data={"name": " 我的 ", "prompt": " cinematic "})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "id": "u_9", "name": "我的", "prompt": "cinematic"}


def test_delete_preset_rejects_system_preset(client, monkeypatch):
    monkeypatch.setattr(preset_routes, "get_system_preset_ids", lambda: {"docu"})
    monkeypatch.setattr(preset_routes, "delete_user_preset", lambda _pid: True)

    resp = client.delete("/api/presets/docu")
    assert resp.status_code == 400
    assert "只读" in resp.json()["detail"]


def test_delete_preset_not_found(client, monkeypatch):
    monkeypatch.setattr(preset_routes, "get_system_preset_ids", lambda: set())
    monkeypatch.setattr(preset_routes, "delete_user_preset", lambda _pid: False)

    resp = client.delete("/api/presets/u_missing")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "预设不存在"


def test_delete_preset_ok(client, monkeypatch):
    monkeypatch.setattr(preset_routes, "get_system_preset_ids", lambda: set())
    monkeypatch.setattr(preset_routes, "delete_user_preset", lambda pid: pid == "u_keep")

    resp = client.delete("/api/presets/u_keep")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "preset_id": "u_keep"}


def test_presets_end_to_end_with_sandbox(client, sandbox):
    """走真实 core/presets（沙箱路径）验证路由 ↔ 存储闭环。"""
    system_path, _ = sandbox
    _write(system_path, [{"id": "docu", "category": "photographic", "prompt": "p"}])

    assert client.get("/api/presets").json()["system"][0]["id"] == "docu"

    created = client.post("/api/presets", data={"name": "夜景", "prompt": "neon"})
    assert created.status_code == 200
    preset_id = created.json()["id"]
    assert client.get("/api/presets").json()["user"][0]["name"] == "夜景"

    assert client.delete(f"/api/presets/{preset_id}").status_code == 200
    assert client.get("/api/presets").json()["user"] == []
    assert os.path.exists(sandbox[1])  # 用户预设文件确实落在沙箱内
