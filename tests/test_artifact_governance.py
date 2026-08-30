"""1.5 产物与日志治理测试（sweep 参数化 / error_logs 轮转 / poetry 检查点映射）。"""
import json
import os
import time

from models.task import PoetryVideoTask, StepStatus


# ── 1.5c poetry 检查点 → 步骤字段映射 ───────────────────────────────


def test_checkpoint_to_step_field_poetry_mapping():
    """poetry 检查点映射（此前缺分支恒为 None，级联删除的 approved 重置失效）。"""
    from core.artifacts import _checkpoint_to_step_field

    state = PoetryVideoTask(task_id="t_poetry", poetry_text="床前明月光，疑是地上霜。")
    mapping = {
        "scenes": "step_build_scenes",
        "references": "step_reference_images",
        "videos": "step_video_generation",
        "audio": "step_audio",
        "subtitle": "step_subtitle",
        "final": "step_concatenation",
    }
    for cp, field in mapping.items():
        assert _checkpoint_to_step_field(cp, state) == field
    assert _checkpoint_to_step_field("unknown", state) is None


# ── 1.5b error_logs 数量轮转 ────────────────────────────────────────


def test_rotate_error_logs_keeps_newest(monkeypatch, tmp_path):
    """超过上限时按 mtime 删除最旧文件，保留最新。"""
    import core.api.error_collector as ec

    monkeypatch.setattr(ec, "_MAX_ERROR_LOGS", 3)
    for i in range(5):
        p = tmp_path / f"log_{i}.json"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (1000 + i, 1000 + i))  # 递增 mtime，log_0 最旧

    ec._rotate_error_logs(tmp_path)

    remaining = sorted(p.name for p in tmp_path.glob("*.json"))
    assert remaining == ["log_2.json", "log_3.json", "log_4.json"]


def test_rotate_error_logs_under_limit_noop(monkeypatch, tmp_path):
    """未超上限时不删除任何文件。"""
    import core.api.error_collector as ec

    monkeypatch.setattr(ec, "_MAX_ERROR_LOGS", 10)
    for i in range(3):
        (tmp_path / f"log_{i}.json").write_text("{}", encoding="utf-8")

    ec._rotate_error_logs(tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 3


# ── 1.5a sweep protect_statuses 参数化 ──────────────────────────────


def _make_task_dir(tmp_path, name, status, age_seconds):
    """构造一个超龄（或指定 age）的任务目录，返回 task_state.json 路径。"""
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    tf = d / "task_state.json"
    tf.write_text(json.dumps({"status": status}), encoding="utf-8")
    old = time.time() - age_seconds
    os.utime(tf, (old, old))
    return tf


def test_sweep_default_protects_pending(monkeypatch, tmp_path):
    """默认保护集 {running, queued, pending}：pending 保留、failed 清理。"""
    from core.artifacts import sweep_stale_tasks

    _make_task_dir(tmp_path, "t_pending", "pending", 10 * 86400)
    _make_task_dir(tmp_path, "t_failed", "failed", 10 * 86400)
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))

    r = sweep_stale_tasks(age_days=7)
    assert r["swept"] == ["t_failed"]
    assert "t_pending" in r["protected"]


def test_sweep_custom_protect_statuses(monkeypatch, tmp_path):
    """传 protect_statuses={failed} 时：failed 保护、pending 清理。"""
    from core.artifacts import sweep_stale_tasks

    _make_task_dir(tmp_path, "t_pending", "pending", 10 * 86400)
    _make_task_dir(tmp_path, "t_failed", "failed", 10 * 86400)
    monkeypatch.setattr("core.artifacts.get_working_dir", lambda: str(tmp_path))

    r = sweep_stale_tasks(age_days=7, protect_statuses={StepStatus.FAILED})
    assert r["swept"] == ["t_pending"]
    assert "t_failed" in r["protected"]
