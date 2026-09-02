"""task_creation_routes 富分支补测（上传文件 / 逐段参考图 / 手动模式 / v2.5 时长）

补充 tests/test_routes.py 未覆盖的成功路径分支：参考图上传、尾帧上传、
场景参考图上传、稿件逐段参考图 map 解析、execution_mode/pause_points 校验，以及
v2.5 视频模型时长档位分支。写路径全部隔离到 tmp_path，不触网不写真实工作区。

用法:
    .venv/bin/python -m pytest tests/test_task_creation_extra.py -q
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import task_creation_routes
from web import helpers


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(task_creation_routes.router)
    return TestClient(app)


class _StubTaskManager:
    def __init__(self, task_id, dir_name=None):
        self.task_id = task_id
        self.state = None

    def create(self, state):
        self.state = state

    def update_state(self, **kwargs):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    """写路径隔离：api key / 上传目录 / pipeline 工厂 / 后台任务 / TaskManager 全打桩。"""
    monkeypatch.setattr(task_creation_routes, "get_api_key", lambda: "test-api-key")
    up = str(tmp_path / "uploads")
    monkeypatch.setattr(helpers, "get_upload_dir", lambda: up)
    monkeypatch.setattr(
        task_creation_routes.deps,
        "create_pipeline_for_type",
        lambda task_type, api_key, task_id, dir_name: object(),
    )
    launched = []

    def fake_launch(coro):
        launched.append(coro)
        coro.close()

    monkeypatch.setattr(task_creation_routes.app_state, "launch_background_task", fake_launch)
    monkeypatch.setattr(task_creation_routes, "TaskManager", _StubTaskManager)
    return {"uploads": up, "launched": launched}


_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _file(name, content=_PNG):
    return (name, content, "image/png")


# ═══════════════════════════════════════════════
# simple：参考图 + 尾帧上传 + 各 mode + v2.5 时长
# ═══════════════════════════════════════════════

class TestSimpleRich:
    def test_uploads_reference_and_end_frame(self, client, env):
        resp = client.post(
            "/api/tasks/simple",
            data={"prompt": "test", "mode": "i2v", "duration": "5", "video_size": "1080P"},
            files=[("reference_image", _file("ref.png")), ("end_frame_image", _file("end.png"))],
        )
        assert resp.status_code == 200
        assert os.listdir(env["uploads"]), "应落盘上传文件"
        saved = sorted(os.listdir(env["uploads"]))
        assert any("_ref" in f for f in saved) and any("_end" in f for f in saved)

    def test_keyframes_mode(self, client, env):
        resp = client.post(
            "/api/tasks/simple",
            data={"prompt": "k", "mode": "keyframes", "duration": "5"},
        )
        assert resp.status_code == 200

    def test_ti2vid_mode(self, client, env):
        resp = client.post("/api/tasks/simple", data={"prompt": "k", "mode": "ti2vid", "duration": "5"})
        assert resp.status_code == 200

    def test_v25_video_model_duration(self, client, env, monkeypatch):
        """v2.5 视频模型走 VIDEO_25_DURATIONS（4-12 秒）档位。"""
        monkeypatch.setattr(task_creation_routes, "is_v25_video_model", lambda m: True)
        monkeypatch.setattr(task_creation_routes, "get_selected_models", lambda: {"video": "agnes-video-v2.5"})
        resp = client.post("/api/tasks/simple", data={"prompt": "k", "mode": "t2v", "duration": "8"})
        assert resp.status_code == 200

    def test_unknown_extension_upload_falls_back_png(self, client, env):
        resp = client.post(
            "/api/tasks/simple",
            data={"prompt": "t", "mode": "t2v", "duration": "5"},
            files=[("reference_image", _file("weird.svg"))],
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════
# creative：参考图 / 自定义尾帧 / 场景参考图
# ═══════════════════════════════════════════════

class TestCreativeRich:
    def test_with_reference_and_end_frames(self, client, env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "太空探险", "scene_count": "2", "scene_durations_json": "[5,5]",
                  "use_custom_end_frames": "true", "audio_enabled": "false"},
            files=[("reference_image", _file("r.png")),
                   ("end_frame_images", _file("e1.png")),
                   ("end_frame_images", _file("e2.png")),
                   ("scene_reference_images", _file("s1.png"))],
        )
        assert resp.status_code == 200
        assert any("_end_" in f for f in os.listdir(env["uploads"]))
        assert any("_scene_" in f for f in os.listdir(env["uploads"]))

    def test_duration_source_prompt_ok(self, client, env):
        resp = client.post("/api/tasks/creative", data={"idea": "x", "duration_source": "prompt"})
        assert resp.status_code == 200

    def test_manual_mode_pause_points(self, client, env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "x", "execution_mode": "manual", "pause_points": '["script"]'},
        )
        assert resp.status_code == 200

    def test_invalid_pause_point_422(self, client, env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "x", "execution_mode": "manual", "pause_points": '["not_a_checkpoint"]'},
        )
        assert resp.status_code == 422
        assert "非法暂停点" in resp.json()["detail"]

    def test_invalid_pause_points_json_422(self, client, env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "x", "execution_mode": "manual", "pause_points": "not-json"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════
# manuscript：逐段参考图 map
# ═══════════════════════════════════════════════

class TestManuscriptRich:
    def test_reference_images_map_valid(self, client, env):
        """地图 [[0,2],[1]] 按段落 index 归集到 ref_images_by_para。"""
        resp = client.post(
            "/api/tasks/manuscript",
            data={"manuscript_text": "第一段。第二段。第三段。",
                  "reference_images_map": "[[0,2],[1]]",
                  "audio_enabled": "false"},
            files=[("reference_images", _file("a.png")), ("reference_images", _file("b.png"))],
        )
        assert resp.status_code == 200
        saved = os.listdir(env["uploads"])
        assert len(saved) == 2

    def test_reference_images_map_invalid_element_422(self, client, env):
        resp = client.post(
            "/api/tasks/manuscript",
            data={"manuscript_text": "一二三。", "reference_images_map": "[[0],[\"x\"]]",
                  "audio_enabled": "false"},
            files=[("reference_images", _file("a.png"))],
        )
        assert resp.status_code == 422
        assert "reference_images_map" in resp.json()["detail"]

    def test_reference_images_map_not_list_422(self, client, env):
        resp = client.post(
            "/api/tasks/manuscript",
            data={"manuscript_text": "一二三。", "reference_images_map": "{\"a\":1}",
                  "audio_enabled": "false"},
            files=[("reference_images", _file("a.png"))],
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════
# poetry / anchor：手动模式 + 附加分支
# ═══════════════════════════════════════════════

class TestPoetryAnchorRich:
    def test_poetry_duration_prompt_and_scene_prompts(self, client, env):
        resp = client.post(
            "/api/tasks/poetry",
            data={"poem_text": "床前明月光", "duration_source": "prompt",
                  "user_scene_prompts_json": '["窗边月光", "地上寒霜"]', "audio_enabled": "false"},
        )
        assert resp.status_code == 200

    def test_poetry_bad_scene_prompts_422(self, client, env):
        resp = client.post(
            "/api/tasks/poetry",
            data={"poem_text": "床前明月光", "user_scene_prompts_json": "{oops}", "audio_enabled": "false"},
        )
        assert resp.status_code == 422
        assert "JSON 数组" in resp.json()["detail"]

    def test_poetry_manual_mode(self, client, env):
        resp = client.post(
            "/api/tasks/poetry",
            data={"poem_text": "床前明月光", "execution_mode": "manual", "pause_points": "[]",
                  "audio_enabled": "false"},
        )
        assert resp.status_code == 200

    def test_anchor_manual_mode(self, client, env):
        resp = client.post(
            "/api/tasks/anchor",
            data={"script_text": "大家好", "audio_enabled": "false", "execution_mode": "manual",
                  "pause_points": '["script"]'},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════
# 辅助函数分支
# ═══════════════════════════════════════════════

class TestHelpers:
    def test_parse_scene_durations_not_list_422(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            task_creation_routes._parse_scene_durations_json("{\"a\":1}")
        assert e.value.status_code == 422

    def test_build_manual_config_auto_default(self):
        from models.task import ManualConfig
        cfg = task_creation_routes._build_manual_config("auto", "")
        assert isinstance(cfg, ManualConfig)
        assert cfg.enabled is False

    def test_build_manual_config_manual_empty_means_all(self):
        from core.pipelines import ALL_CHECKPOINTS
        cfg = task_creation_routes._build_manual_config("manual", "")
        assert cfg.enabled is True
        assert cfg.pause_points == list(ALL_CHECKPOINTS)