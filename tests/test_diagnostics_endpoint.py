"""
v6.1 二期 — 任务诊断端点单元测试（PRD FR9 / implementation_plan P4）。

覆盖：
- models/task.py: BaseTaskState 新增 created_at / updated_at 默认值与向后兼容
- core/task_manager.py: create 设置 created_at / 每次 _save 刷新 updated_at
- core/api/error_collector.py: task_id ContextVar 关联落盘
- web/routes/task_routes.py: GET /api/tasks/{id}/diagnostics
    - 精确匹配优先 / 时间窗口兜底 / 无记录
    - 敏感字段（prompt / response_body / system_prompt）不返回
    - _sanitize_log 截断 error_message

用法:
    .venv/bin/python -m pytest tests/test_diagnostics_endpoint.py -v
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import task_routes

# ═══════════════════════════════════════════════
# 1. BaseTaskState 时间戳字段（P4-T1）
# ═══════════════════════════════════════════════

class TestTaskTimestamps:
    def test_defaults_empty(self):
        from models.task import CreativeVideoTask
        t = CreativeVideoTask()
        assert t.created_at == ""
        assert t.updated_at == ""

    def test_backward_compat_no_fields(self):
        """旧 task_state.json 无 created_at/updated_at 应能正常反序列化。"""
        from models.task import parse_task_state
        data = {"task_id": "t1", "task_type": "creative", "idea": "x"}
        state = parse_task_state(data)
        assert state.created_at == ""
        assert state.updated_at == ""


# ═══════════════════════════════════════════════
# 2. TaskManager 时间戳刷新（P4-T1）
# ═══════════════════════════════════════════════

class TestTaskManagerTimestamps:
    def test_create_sets_timestamps(self, tmp_path, monkeypatch):
        from core import task_manager as tm_mod
        from core.task_manager import TaskManager
        from models.task import CreativeVideoTask

        # TaskManager 在模块导入时就绑定了 get_working_dir，必须打桩它自己的符号
        # （打桩 core.config.get_working_dir 不会生效 → 会写进真实工作区）
        monkeypatch.setattr(tm_mod, "get_working_dir", lambda: str(tmp_path))
        tm = TaskManager("t_ts", dir_name="t_ts")
        state = tm.create(CreativeVideoTask())
        # 落盘位置必须在临时目录内（防止再次误写到真实工作区）
        assert os.path.isdir(os.path.join(str(tmp_path), "t_ts"))
        assert state.created_at  # 非空
        assert state.updated_at  # 非空
        # 落盘后重载仍保留
        loaded = tm.load()
        assert loaded.created_at == state.created_at

    def test_update_refreshes_updated_at(self, tmp_path, monkeypatch):
        from core import task_manager as tm_mod
        from core.task_manager import TaskManager
        from models.task import CreativeVideoTask, StepStatus

        monkeypatch.setattr(tm_mod, "get_working_dir", lambda: str(tmp_path))
        tm = TaskManager("t_ts2", dir_name="t_ts2")
        state = tm.create(CreativeVideoTask())
        old_created = state.created_at
        old_updated = state.updated_at
        # 更新状态 → updated_at 刷新、created_at 不变
        tm.update_state(status=StepStatus.RUNNING)
        assert state.updated_at >= old_updated
        assert state.created_at == old_created


# ═══════════════════════════════════════════════
# 3. error_collector 任务关联（P4-T2）
# ═══════════════════════════════════════════════

class TestErrorTaskId:
    def test_task_id_written_via_contextvar(self, tmp_path, monkeypatch):
        from core.api import error_collector

        monkeypatch.setattr(error_collector, "_get_workspace_root", lambda: tmp_path)
        error_collector.set_error_task_id("t_ctx_123")
        p = error_collector.collect_error(
            model_type="video", api_method="submit_video",
            error_type="HTTPError", error_message="boom",
        )
        assert p and os.path.exists(p)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["task_id"] == "t_ctx_123"

    def test_empty_task_id_when_unset(self, tmp_path, monkeypatch):
        from core.api import error_collector

        monkeypatch.setattr(error_collector, "_get_workspace_root", lambda: tmp_path)
        error_collector.set_error_task_id("")  # 清空上下文
        p = error_collector.collect_error(
            model_type="image", api_method="generate", error_type="X", error_message="y",
        )
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["task_id"] == ""


# ═══════════════════════════════════════════════
# 4. 诊断端点（P4-T3 / P4-T4）
# ═══════════════════════════════════════════════

@pytest.fixture
def diag_client(monkeypatch, tmp_path):
    """挂载 task_routes，并让 TaskManager 指向 tmp_path。"""
    from core import task_manager as tm_mod

    monkeypatch.setattr(tm_mod, "get_working_dir", lambda: str(tmp_path))
    # 用真实 TaskManager 落盘一个失败任务
    from core.task_manager import TaskManager
    from models.task import CreativeVideoTask, StepStatus

    tm = TaskManager("t_diag", dir_name="t_diag")
    state = CreativeVideoTask()
    state.current_step = "video_gen"
    state.current_message = "HTTP 400 Bad Request: content policy"
    state.status = StepStatus.FAILED
    tm.create(state)

    # error_logs 目录指向 tmp_path/error_logs（error_collector 一致）
    from core.api import error_collector
    monkeypatch.setattr(error_collector, "_get_workspace_root", lambda: tmp_path)

    app = FastAPI()
    app.include_router(task_routes.router)
    return TestClient(app)


class TestDiagnosticsEndpoint:
    def test_exact_match(self, diag_client, tmp_path):
        # 写一条带 task_id 的错误日志
        log = {
            "timestamp": datetime.now().isoformat(),
            "task_id": "t_diag",
            "model_type": "video",
            "api_method": "submit_video",
            "prompt": "SECRET_PROMPT",
            "response_body": "SECRET_BODY",
            "system_prompt": "SECRET_SYS",
            "error_type": "HTTPError",
            "error_message": "HTTP 400 Bad Request",
            "status_code": 400,
            "retry_count": 2,
            "extra": {"video_id": "v1"},
        }
        log_dir = tmp_path / "error_logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / "e1.json").write_text(json.dumps(log), encoding="utf-8")

        r = diag_client.get("/api/tasks/t_diag/diagnostics")
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["match_source"] == "exact"
        assert d["summary"]["status"] == "failed"
        assert d["summary"]["current_step"] == "video_gen"
        logs = d["error_logs"]
        assert len(logs) == 1
        entry = logs[0]
        # 敏感字段不返回
        assert "prompt" not in entry
        assert "response_body" not in entry
        assert "system_prompt" not in entry
        assert "extra" not in entry
        # 暴露字段
        assert entry["task_id"] == "t_diag"
        assert entry["model_type"] == "video"
        assert entry["error_message"] == "HTTP 400 Bad Request"
        assert entry["status_code"] == 400
        assert entry["retry_count"] == 2

    def test_no_logs(self, diag_client):
        r = diag_client.get("/api/tasks/t_diag/diagnostics")
        assert r.status_code == 200
        d = r.json()
        assert d["match_source"] == "none"
        assert d["error_logs"] == []

    def test_404_unknown_task(self, diag_client):
        r = diag_client.get("/api/tasks/not_exist/diagnostics")
        assert r.status_code == 404

    def test_sanitize_truncates_message(self):
        long_msg = "x" * 5000
        out = task_routes._sanitize_log({"error_message": long_msg})
        assert len(out["error_message"]) == task_routes._ERROR_LOG_MAX_MESSAGE

    def test_in_window_logic(self):
        now = datetime.now()
        start = now
        end = now + __import__("datetime").timedelta(hours=2)
        assert task_routes._in_window(now.isoformat(), start, end) is True
        assert task_routes._in_window((now - __import__("datetime").timedelta(hours=1)).isoformat(), start, end) is False
        assert task_routes._in_window("not-a-date", start, end) is False
