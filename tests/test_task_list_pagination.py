"""1.4 任务列表分页测试（limit/offset/status 过滤）。

在协议层验证 /api/tasks 的轻量字段分页：过滤/截断应在完整状态加载之前，
避免为被丢弃的任务做 Pydantic 全量校验。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import task_routes


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """挂载 task_routes 并把工作区定向到 tmp_path（不触碰真实工作区）。"""
    app = FastAPI()
    app.include_router(task_routes.router)
    monkeypatch.setattr("core.task_manager.get_working_dir", lambda: str(tmp_path))
    return TestClient(app), tmp_path


def _make_task(working_dir: str, task_id: str, status: str = "pending"):
    d = os.path.join(working_dir, f"d_{task_id}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "task_state.json"), "w", encoding="utf-8") as f:
        json.dump({"task_id": task_id, "task_type": "simple", "status": status}, f)


def test_list_all_with_total(client):
    app_client, wd = client
    for i in range(5):
        _make_task(wd, f"t{i}", "pending" if i < 3 else "completed")

    r = app_client.get("/api/tasks")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["tasks"]) == 5


def test_status_filter(client):
    app_client, wd = client
    for i in range(3):
        _make_task(wd, f"t{i}", "pending")
    _make_task(wd, "t3", "failed")

    r = app_client.get("/api/tasks", params={"status": "pending"})
    data = r.json()
    assert data["total"] == 3
    assert {t["task_id"] for t in data["tasks"]} == {"t0", "t1", "t2"}

    r = app_client.get("/api/tasks", params={"status": "pending,failed"})
    data = r.json()
    assert data["total"] == 4


def test_limit_offset_pagination(client):
    app_client, wd = client
    for i in range(5):
        _make_task(wd, f"t{i}")

    # list_tasks 按 dir_name 倒序（d_t4 在前），分页取第 2 页
    r = app_client.get("/api/tasks", params={"limit": 2, "offset": 2})
    data = r.json()
    assert data["total"] == 5
    assert len(data["tasks"]) == 2

    r = app_client.get("/api/tasks", params={"limit": 2, "offset": 2, "status": "pending"})
    data = r.json()
    assert data["total"] == 5
    assert len(data["tasks"]) == 2


def test_pagination_beyond_range(client):
    app_client, wd = client
    for i in range(3):
        _make_task(wd, f"t{i}")

    r = app_client.get("/api/tasks", params={"limit": 10, "offset": 10})
    data = r.json()
    assert data["total"] == 3
    assert data["tasks"] == []
