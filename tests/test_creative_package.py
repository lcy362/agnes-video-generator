"""
CreativeVideoPipeline 包拆分（v5.0 Batch 4 / 4.2）组合与 re-export 契约测试。

core/pipelines/creative_video.py → core/pipelines/creative/ 包（pipeline 主类 +
steps_script/steps_frames/steps_video/steps_audio 四个步骤 mixin）。本文件守护拆分契约：
- CreativeVideoPipeline 经 mixin 组合后成员完整（31 个，与拆分前一致）；
- 四步 mixin 方法归属各自模块（职责划分正确）；
- Batch 3 契约不回退：coarse_skip=False、_execute_step 仍解析到 MultiScenePipeline；
- 兼容 re-export 与 mock 回归 patch 目标（core.pipelines.creative.pipeline 持有
  AgnesVideoAPI/AgnesImageAPI，实例化发生在该模块 __init__）。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import core.pipelines as pipelines
from core.pipelines import MultiScenePipeline
from core.pipelines.creative import (
    AudioStepsMixin,
    CreativeVideoPipeline,
    FramesStepsMixin,
    ScriptStepsMixin,
    VideoStepsMixin,
)
from core.pipelines.creative import pipeline as creative_pipeline
from core.pipelines.creative import steps_audio, steps_frames, steps_script, steps_video
import core.pipelines.creative_video as creative_reexport


# ═══════════════════════════════════════════════
# 1. mixin 组合：全部原成员经 MRO 可用
# ═══════════════════════════════════════════════

_CREATIVE_MEMBERS = [
    # pipeline.py 主类（10，含 state 属性）
    "__init__", "state",
    "_get_init_message", "_get_watermark_language_text",
    "_build_scenes", "_build_reference_images",
    "_generate_videos", "_generate_audio", "_generate_subtitles", "_composite_final",
    # steps_script.py（6）
    "_step_image_analysis", "_step_resolve_scene_config", "_step_story",
    "_step_character_reference", "_step_script", "_step_end_frame_prompts",
    # steps_frames.py（5）
    "_normalize_image_to_size", "_get_normalized_character_ref",
    "_step_pregenerate_end_frames", "_save_scene_task", "_load_scene_task",
    # steps_video.py（5）
    "_step_generate_videos", "_scene_duration",
    "_generate_independent_scenes", "_generate_chained_scenes", "_generate_keyframe_scenes",
    # steps_audio.py（6）
    "_is_narrative_para", "_populate_narrations", "_step_generate_narrations",
    "_step_audio", "_step_subtitle", "_step_concatenate",
]


def test_pipeline_composes_all_original_members():
    """拆分后 CreativeVideoPipeline 仍具备拆分前全部 31 个成员（mixin MRO 组合）。"""
    missing = [m for m in _CREATIVE_MEMBERS if not hasattr(CreativeVideoPipeline, m)]
    assert not missing, f"missing members after split: {missing}"


def test_mixin_classes_are_used_by_pipeline():
    """CreativeVideoPipeline 的 MRO 包含四个步骤 mixin 且顺序为 script→audio。"""
    mro_names = [c.__name__ for c in CreativeVideoPipeline.__mro__]
    assert mro_names[:5] == [
        "CreativeVideoPipeline",
        "ScriptStepsMixin",
        "FramesStepsMixin",
        "VideoStepsMixin",
        "AudioStepsMixin",
    ], mro_names[:6]
    assert MultiScenePipeline in CreativeVideoPipeline.__mro__


def test_mixin_methods_defined_in_respective_modules():
    """各 mixin 的方法定义在对应的拆分模块中（职责归属正确）。"""
    assert ScriptStepsMixin._step_story.__module__ == "core.pipelines.creative.steps_script"
    assert FramesStepsMixin._load_scene_task.__module__ == "core.pipelines.creative.steps_frames"
    assert VideoStepsMixin._generate_keyframe_scenes.__module__ == "core.pipelines.creative.steps_video"
    assert AudioStepsMixin._step_concatenate.__module__ == "core.pipelines.creative.steps_audio"
    assert CreativeVideoPipeline._build_scenes.__module__ == "core.pipelines.creative.pipeline"


# ═══════════════════════════════════════════════
# 2. Batch 3 契约不回退（方案 A）
# ═══════════════════════════════════════════════

def test_coarse_skip_disabled_and_execute_step_unoverridden():
    """coarse_skip=False 且 _execute_step 解析到 MultiScenePipeline（无覆写残留）。"""
    assert CreativeVideoPipeline.coarse_skip is False
    assert CreativeVideoPipeline._execute_step is MultiScenePipeline._execute_step


def test_state_property_semantics():
    """state 仍是 property（fget 为原函数），非普通方法。"""
    prop = CreativeVideoPipeline.__dict__["state"]
    assert isinstance(prop, property)
    assert prop.fget.__name__ == "state"
    assert prop.fget.__module__ == "core.pipelines.creative.pipeline"


# ═══════════════════════════════════════════════
# 3. 模块级 helpers / 常量
# ═══════════════════════════════════════════════

def test_module_level_helpers_present():
    """六个模块级 helper 按归属模块存在（供 mixin 方法直接调用）。"""
    assert callable(steps_frames._fallback_end_frame)
    assert callable(steps_frames._localize_preserve_tags)
    assert callable(steps_frames._run_ffmpeg_async)
    assert callable(steps_video._localize_transition_prompt)
    assert callable(steps_audio._trim_to_sentence)
    assert callable(steps_audio._split_narration_into_scenes)


def test_module_level_constants_values():
    """模块级常量按值保持（句子边界正则）。

    PRD 1.3a：语速估算收敛为 core.audio.voices 公共函数后，steps_audio 不再
    维护 _CHARS_PER_SEC 常量，改由 estimate_chars_per_sec() 提供（CJK 4.0）。
    """
    assert steps_audio._SENTENCE_BOUNDARY_RE.pattern == r"(?<=[。！？.!?])"
    from core.audio.voices import estimate_chars_per_sec

    assert estimate_chars_per_sec("中文测试") == 4.0
    assert estimate_chars_per_sec("English narration") == 13.0


# ═══════════════════════════════════════════════
# 4. 兼容 re-export 与 mock patch 目标
# ═══════════════════════════════════════════════

def test_reexport_identity():
    """creative_video.py 与 core.pipelines 的 CreativeVideoPipeline 指向同一类。"""
    assert creative_reexport.CreativeVideoPipeline is CreativeVideoPipeline
    assert pipelines.CreativeVideoPipeline is CreativeVideoPipeline
    for mixin in (ScriptStepsMixin, FramesStepsMixin, VideoStepsMixin, AudioStepsMixin):
        assert getattr(creative_reexport, mixin.__name__) is mixin


def test_mock_patch_targets_importable():
    """mock 回归 patch 目标位于实例化发生的模块（creative/pipeline.py）。"""
    assert creative_pipeline.AgnesVideoAPI is not None
    assert creative_pipeline.AgnesImageAPI is not None
    from core.api.agnes_video import AgnesVideoAPI
    from core.api.agnes_image import AgnesImageAPI
    assert creative_pipeline.AgnesVideoAPI is AgnesVideoAPI
    assert creative_pipeline.AgnesImageAPI is AgnesImageAPI
