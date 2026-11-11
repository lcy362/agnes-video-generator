"""v8.1 多参考图：槽位合并 / 上限单源 / 数据模型兼容。

覆盖：
1. ``merge_ref_images`` 优先级、去重（URL / 本地路径 / data URI）、截断与 dropped；
2. ``get_max_ref_images`` 唯一出处（视频能力表 / 图片环境变量）；
3. 新字段的向后兼容（旧 task.json 反序列化自动补齐）；
4. ``MultiScenePipeline._get_scene_ref_images`` 拼装顺序与截断；
5. 图片接口截断留痕。

用法:
    .venv/bin/python -m pytest tests/test_ref_slots.py -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.config import get_max_ref_images
from core.pipelines.ref_slots import (
    KIND_CHARACTER,
    KIND_CONTINUITY,
    KIND_STYLE,
    KIND_USER_SCENE,
    RefSlot,
    merge_ref_images,
    remaining_scene_slots,
    system_slot_usage,
)
from models.task import (
    CreativeVideoTask,
    ManuscriptVideoTask,
    PoetryVideoTask,
    SimpleImageTask,
    parse_task_state,
)


class TestMergeRefImages:
    def test_priority_order(self):
        """人物 > 风格 > 衔接 > 本段内容，且与传入顺序无关。"""
        slots = [
            RefSlot(KIND_USER_SCENE, ["u1"]),
            RefSlot(KIND_STYLE, ["s1"]),
            RefSlot(KIND_CHARACTER, ["c1"]),
            RefSlot(KIND_CONTINUITY, ["k1"]),
        ]
        images, dropped = merge_ref_images(slots, 10)
        assert images == ["c1", "s1", "k1", "u1"]
        assert dropped == []

    def test_same_priority_keeps_input_order(self):
        slots = [
            RefSlot(KIND_USER_SCENE, ["u1", "u2"]),
            RefSlot(KIND_USER_SCENE, ["u3"]),
        ]
        images, _ = merge_ref_images(slots, 10)
        assert images == ["u1", "u2", "u3"]

    def test_dedupe_url_and_data_uri(self):
        slots = [
            RefSlot(KIND_CHARACTER, ["https://a/x.png", "data:image/png;base64,AAA"]),
            RefSlot(KIND_STYLE, ["https://a/x.png", "data:image/png;base64,AAA"]),
        ]
        images, _ = merge_ref_images(slots, 10)
        assert images == ["https://a/x.png", "data:image/png;base64,AAA"]

    def test_dedupe_local_realpath(self, tmp_path):
        path = tmp_path / "p.png"
        path.write_bytes(b"x")
        alias = str(tmp_path / "." / "p.png")
        slots = [
            RefSlot(KIND_CHARACTER, [str(path)]),
            RefSlot(KIND_USER_SCENE, [alias, str(path)]),
        ]
        images, _ = merge_ref_images(slots, 10)
        assert images == [str(path)]

    def test_truncate_from_tail_and_report(self):
        """超限从末尾丢：先丢本段内容图，人物板保留。"""
        slots = [
            RefSlot(KIND_CHARACTER, ["c1"]),
            RefSlot(KIND_STYLE, ["s1"]),
            RefSlot(KIND_USER_SCENE, ["u1", "u2"]),
        ]
        images, dropped = merge_ref_images(slots, 3)
        assert images == ["c1", "s1", "u1"]
        assert dropped == ["user_scene x1"]

    def test_invisible_slot_skipped_and_empty_values(self):
        slots = [
            RefSlot(KIND_CHARACTER, ["c1"], visible=False),
            RefSlot(KIND_STYLE, ["", "s1"]),
        ]
        images, _ = merge_ref_images(slots, 5)
        assert images == ["s1"]

    def test_limit_zero(self):
        images, dropped = merge_ref_images([RefSlot(KIND_STYLE, ["s1"])], 0)
        assert images == []
        assert dropped == ["style x1"]

    def test_quota_helpers(self):
        assert system_slot_usage(["c1"], ["s1", "s2"]) == 3
        assert remaining_scene_slots(5, 2) == 3
        assert remaining_scene_slots(5, 9) == 0


class TestMaxRefImages:
    def test_video_models(self):
        assert get_max_ref_images("agnes-video-2.5-flash") == 5
        assert get_max_ref_images("agnes-video-2.5") == 8

    def test_unknown_model_falls_back(self):
        assert get_max_ref_images("no-such-model") == 5
        assert get_max_ref_images("") == 5

    def test_image_media_env(self, monkeypatch):
        monkeypatch.setenv("AGNES_IMAGE_MAX_REF_IMAGES", "2")
        assert get_max_ref_images(media="image") == 2

    def test_image_media_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("AGNES_IMAGE_MAX_REF_IMAGES", "abc")
        # pydantic 解析失败时不能把整条链路打死，兜底 5
        assert get_max_ref_images(media="image") >= 1


class TestModelCompatibility:
    def test_legacy_task_json_backfills_new_fields(self):
        state = parse_task_state({
            "task_type": "manuscript",
            "manuscript_text": "第一段。第二段。",
        })
        assert isinstance(state, ManuscriptVideoTask)
        assert state.character_plate == []
        assert state.style_plate == []
        assert state.link_shots is False
        assert state.pause_for_scene_refs is False

    def test_creative_scene_map_default(self):
        state = parse_task_state({"task_type": "creative", "idea": "太空探险"})
        assert isinstance(state, CreativeVideoTask)
        assert state.scene_reference_images_map == {}
        assert state.style_images == []

    def test_poetry_and_image_fields(self):
        poetry = parse_task_state({"task_type": "poetry", "poem_text": "床前明月光"})
        assert isinstance(poetry, PoetryVideoTask)
        assert poetry.scene_reference_images == {}
        image = parse_task_state({"task_type": "image", "prompt": "cat"})
        assert isinstance(image, SimpleImageTask)
        assert image.reference_images == []

    def test_scene_task_ref_images_roundtrip(self):
        from models.task import SceneTask

        scene = SceneTask(index=0, ref_images=["a.png", "b.png"])
        assert SceneTask(**scene.model_dump()).ref_images == ["a.png", "b.png"]


class TestTemplateMerge:
    def _pipeline(self):
        from core.pipelines.multi_scene import MultiScenePipeline

        class _Dummy(MultiScenePipeline):
            async def _build_scenes(self):  # pragma: no cover - 仅满足抽象方法
                return None

            async def _build_reference_images(self):  # pragma: no cover
                return None

            async def _composite_final(self):  # pragma: no cover
                return ""

        pipeline = _Dummy.__new__(_Dummy)

        class _State:
            character_plate = ["c1"]
            style_plate = ["s1", "s2"]

        class _API:
            model = "agnes-video-2.5-flash"

        pipeline._state = _State()
        pipeline.video_api = _API()
        return pipeline

    def test_scene_refs_merge_order(self):
        from models.task import SceneTask

        pipeline = self._pipeline()
        scene = SceneTask(index=0, ref_images=["u1"])
        assert pipeline._get_scene_ref_images(scene, 0) == ["c1", "s1", "s2", "u1"]

    def test_scene_refs_truncated_to_flash_limit(self):
        from models.task import SceneTask

        pipeline = self._pipeline()
        scene = SceneTask(index=0, ref_images=[f"u{i}" for i in range(10)])
        images = pipeline._get_scene_ref_images(scene, 0)
        assert len(images) == 5
        assert images[:3] == ["c1", "s1", "s2"]

    def test_keyframes_hook_default_none(self):
        from models.task import SceneTask

        pipeline = self._pipeline()
        assert pipeline._get_scene_keyframes(SceneTask(index=0), 0) is None


class TestImageApiTruncation:
    @pytest.mark.asyncio
    async def test_image_api_truncates_with_warning(self, monkeypatch, caplog):
        """图片接口超限只截断并留痕，不抛异常。"""
        from core.api import agnes_image

        # 隔离 KeyRing / 限速器：CI 无 AGNES_API_KEY 时二者都会抛错
        class _Ring(list):
            def __init__(self):
                super().__init__(["k"])

            def next(self):
                return self[0]

        class _Limiter:
            async def acquire_async(self):
                return None

        monkeypatch.setattr(agnes_image, "get_key_ring", lambda: _Ring())
        monkeypatch.setattr(agnes_image, "get_rate_limiter", lambda: _Limiter())
        api = agnes_image.AgnesImageAPI(api_key="k")
        captured = {}

        async def _fake_resolve(path):
            return path

        class _Resp:
            status_code = 200

            def json(self):
                return {"data": [{"url": "https://cdn/x.png"}]}

            def raise_for_status(self):
                return None

        def _fake_post(*args, **kwargs):
            captured["payload"] = kwargs.get("json")
            return _Resp()

        monkeypatch.setattr(agnes_image.requests, "post", _fake_post)
        monkeypatch.setattr(agnes_image, "normalize_reference_path", lambda p, w, h: p)
        monkeypatch.setattr(api, "_resolve_image_ref", _fake_resolve)
        monkeypatch.setenv("AGNES_IMAGE_MAX_REF_IMAGES", "2")

        await api.generate_single_image(prompt="x", reference_image_paths=["a", "b", "c"])
        assert captured["payload"]["extra_body"]["image"] == ["a", "b"]
