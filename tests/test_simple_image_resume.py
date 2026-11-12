"""issue #114 回归：图片任务的续传流水线。

背景：``POST /api/tasks/{id}/resume`` 按 ``task_type`` 选 Pipeline，历史实现
漏了 ``TaskType.IMAGE``，把简单图片任务兜到 ``CreativeVideoPipeline``，在
``step_build_scenes`` 处抛 ``SimpleImageTask has no field step_build_scenes``。
"""

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.pipelines import SimpleImagePipeline
from models.task import SimpleImageTask, StepStatus
from web.routes import task_routes

# 1x1 PNG（最小合法图片字节）
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _StubOutput:
    def __init__(self, payload: bytes = _PNG):
        self.payload = payload

    async def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.payload)


class _StubImageAPI:
    """记录调用参数的假 API。"""

    instances = []

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key
        self.model = model
        self.calls = []
        self.error = None
        _StubImageAPI.instances.append(self)

    async def generate_single_image(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return _StubOutput()


@pytest.fixture
def stub_api(monkeypatch):
    _StubImageAPI.instances = []
    import core.pipelines.simple_image as mod

    monkeypatch.setattr(mod, "AgnesImageAPI", _StubImageAPI)
    return _StubImageAPI


def _make_pipeline(task_id: str = "img1") -> SimpleImagePipeline:
    return SimpleImagePipeline(api_key="k", task_id=task_id, dir_name=task_id)


def _state(task_id: str = "img1", **kw) -> SimpleImageTask:
    state = SimpleImageTask(task_id=task_id, prompt="a cat on the moon", **kw)
    state.status = StepStatus.FAILED
    state.ui_language = "zh"
    return state


async def test_image_resume_generates_and_marks_completed(stub_api, tmp_path):
    """续传图片任务：重跑一次生成 → final_image.png 落盘 + COMPLETED。"""
    state = _state(size="1344x768", negative_prompt="blurry")
    pipeline = _make_pipeline()
    state.task_id = pipeline.task_id

    out = await pipeline.run(state)

    assert out == os.path.join(pipeline.working_dir, "final_image.png")
    assert os.path.exists(out)
    assert state.status == StepStatus.COMPLETED
    assert state.final_video_file == out

    call = stub_api.instances[-1].calls[-1]
    assert call["prompt"] == "a cat on the moon"
    assert call["size"] == "1344x768"
    assert call["negative_prompt"] == "blurry"
    assert call["reference_image_paths"] == []


async def test_image_resume_uses_persisted_system_prompt(stub_api):
    """system_prompt 落盘后仍按 base64 封装规则拼接（与创建路由同口径）。"""
    state = _state(system_prompt="You are a photographer")
    pipeline = _make_pipeline()

    await pipeline.run(state)

    prompt = stub_api.instances[-1].calls[-1]["prompt"]
    assert prompt.startswith("You are a photographer")
    encoded = prompt.split("Encrypted description:\n")[1]
    assert base64.b64decode(encoded).decode("utf-8") == "a cat on the moon"


async def test_image_resume_skips_missing_reference_images(stub_api, tmp_path):
    """参考图被清理后不把不存在路径塞给上游（否则上游按坏图直接失败）。"""
    good = tmp_path / "ref.png"
    good.write_bytes(_PNG)
    state = _state(reference_images=[str(good), str(tmp_path / "gone.png")])
    pipeline = _make_pipeline()

    await pipeline.run(state)

    assert stub_api.instances[-1].calls[-1]["reference_image_paths"] == [str(good)]


async def test_image_resume_failure_marks_failed_with_step(monkeypatch):
    """上游失败：状态 FAILED、真实环节 generate、traceback 落盘、异常上抛。"""
    import core.pipelines.simple_image as mod

    class _Boom(_StubImageAPI):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.error = RuntimeError("HTTP 500 boom")

    monkeypatch.setattr(mod, "AgnesImageAPI", _Boom)
    state = _state()
    pipeline = _make_pipeline()

    with pytest.raises(RuntimeError):
        await pipeline.run(state)

    assert state.status == StepStatus.FAILED
    assert state.current_step == "generate"
    assert state.current_status == "failed"
    assert "HTTP 500 boom" in state.current_message
    assert state.error_traceback


class TestResumeRouteMapping:
    """路由层：图片任务的 resume 必须构造图片流水线（issue #114 的直接回归）。"""

    def _client(self, monkeypatch, state):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(task_routes.router)

        monkeypatch.setattr(task_routes, "get_api_key", lambda: "k")
        monkeypatch.setattr(task_routes.helpers, "find_dir_name", lambda tid: "d_img")

        class _TM:
            def __init__(self, task_id, dir_name=None):
                self.state = state

            def load(self):
                return self.state

            def update_state(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self.state, k, v)

        monkeypatch.setattr(task_routes, "TaskManager", _TM)
        monkeypatch.setattr(
            task_routes.app_state, "launch_background_task", lambda coro: coro.close(),
        )
        return TestClient(app)

    def test_image_task_resumes_with_image_pipeline(self, monkeypatch):
        import web.deps as deps_mod

        monkeypatch.setattr(
            deps_mod, "get_selected_models",
            lambda: {"text": "t", "image": "i", "video": "v"},
        )
        state = _state()
        client = self._client(monkeypatch, state)

        r = client.post("/api/tasks/img1/resume")

        assert r.status_code == 200, r.text
        pipeline = task_routes.app_state.active_pipelines.get("img1")
        assert isinstance(pipeline, SimpleImagePipeline)
        task_routes.app_state.active_pipelines.pop("img1", None)
