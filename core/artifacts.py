"""
core/artifacts.py — 中间产物注册表与级联删除计划

为 creative / manuscript / anchor 三种任务模式提供：
- list_artifacts(): 列举任务的所有中间产物（含存在性检测）
- resolve_artifact(): 根据 artifact_id 解析单个产物描述符
- get_cascade_plan(): 计算删除某产物后的级联删除计划

产物 ID 格式: {mode}:{artifact_type} 或 {mode}:{artifact_type}:{scope_index}
  例如: creative:story, creative:end_frame:2, manuscript:video:1, anchor:anchor_image
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.config import get_working_dir
from core.path_security import safe_join
from models.task import (
    AnchorVideoTask,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    PoetryVideoTask,
    StepStatus,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════


@dataclass
class ArtifactDescriptor:
    """单个中间产物的描述符。"""

    artifact_id: str           # "creative:end_frame:2"
    step_key: str              # 前端 STEPS key, 如 "end_frame_gen"
    step_field: Optional[str]  # state 步骤字段名, 如 "step_end_frame_generation" (None=无独立步骤)
    label_key: str             # i18n key, 如 "artEndFrame"
    category: str              # text/image/video/audio/json/subtitle
    scope: str                 # task/scene/paragraph
    scope_index: Optional[int] # 场景/段落索引, task 级为 None
    file_relpath: Optional[str]  # 相对于 task_dir 的路径
    state_fields: list[str]    # 删除时清空的顶层字段
    exists: bool = False       # 文件是否存在
    size: int = 0              # 文件大小(字节)
    deletable: bool = True     # 是否允许删除
    schema_hint: str = ""      # v5.x：人类可读字段说明（供外部 Agent/工具处理产物）


@dataclass
class CascadePlan:
    """级联删除计划。"""

    files_to_delete: list[str] = field(default_factory=list)     # 相对路径
    steps_to_reset: list[str] = field(default_factory=list)      # step 字段名
    fields_to_clear: dict[str, Any] = field(default_factory=dict)  # {顶层字段: 默认值}
    scene_updates: list[dict] = field(default_factory=list)      # scenes/paragraphs 字段更新
    # scene_updates 格式: {"list_field": "scenes", "from_index": 2, "field": "video_file", "value": ""}


# ═══════════════════════════════════════════════════════════════
# 步骤序列定义（有序，用于确定级联范围）
# ═══════════════════════════════════════════════════════════════

# Creative 步骤序列 (step_field, step_key)
_CREATIVE_STEPS = [
    ("step_scene_config", "scene_config"),
    ("step_image_analysis", "image_analysis"),
    ("step_story", "story"),
    ("step_character_ref", "character_ref"),
    ("step_script", "script"),
    ("step_end_frame_prompts", "end_frame_prompts"),
    ("step_end_frame_generation", "end_frame_gen"),
    ("step_video_generation", "video_gen"),
    ("step_audio", "audio"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]

# Manuscript 步骤序列
_MANUSCRIPT_STEPS = [
    ("step_split", "split_text"),
    ("step_scene_prompts", "scene_prompts"),
    ("step_video_generation", "video_gen"),
    ("step_audio", "audio"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]

# Anchor post_stitch 步骤序列
_ANCHOR_STEPS_POST_STITCH = [
    ("step_generate_anchor", "generate_anchor"),
    ("step_audio", "audio"),
    (None, "clip_prompts"),           # 无独立 step 字段
    ("step_clip_generation", "clip_gen"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]

# Anchor model 步骤序列
_ANCHOR_STEPS_MODEL = [
    ("step_generate_anchor", "generate_anchor"),
    (None, "clip_prompts"),
    ("step_clip_generation", "clip_gen"),
]

# Poetry 步骤序列（v6.0 P3：与 multi_scene 模板方法步骤对齐）
_POETRY_STEPS = [
    ("step_build_scenes", "build_scenes"),
    ("step_reference_images", "reference_images"),
    ("step_video_generation", "video_gen"),
    ("step_audio", "audio"),
    ("step_subtitle", "subtitle"),
    ("step_concatenation", "concatenate"),
]


# ═══════════════════════════════════════════════════════════════
# 产物定义（每种模式的产物模板）
# ═══════════════════════════════════════════════════════════════

def _creative_artifact_defs() -> list[dict]:
    """Creative 模式的产物定义模板。"""
    return [
        {"type": "image_analysis", "step_key": "image_analysis", "label": "artImageAnalysis",
         "category": "text", "scope": "task", "file": "image_analysis.txt", "fields": ["image_analysis_file"]},
        {"type": "story", "step_key": "story", "label": "artStory",
         "category": "text", "scope": "task", "file": "story.txt", "fields": ["story_file"]},
        {"type": "character_ref", "step_key": "character_ref", "label": "artCharacterRef",
         "category": "image", "scope": "task", "file": "character_reference.png",
         "fields": ["character_ref_file", "character_ref_prompt", "character_appearance"]},
        {"type": "script", "step_key": "script", "label": "artScript",
         "category": "json", "scope": "task", "file": "script.json",
         "fields": ["script_file", "narrations"], "extra_files": ["prompts.json"]},
        {"type": "end_frame_prompts", "step_key": "end_frame_prompts", "label": "artEndFramePrompts",
         "category": "json", "scope": "task", "file": "end_frame_prompts.json",
         "fields": ["end_frame_prompts_file"]},
        # 场景级产物
        {"type": "end_frame", "step_key": "end_frame_gen", "label": "artEndFrame",
         "category": "image", "scope": "scene", "file": "scene_{i}/end_frame.png",
         "scene_fields": ["end_frame_file"],
         # step_end_frame_generation 重置后 pregenerated_end_frames 也需清空（pipeline 会重建）
         "clear_top_fields": ["pregenerated_end_frames"]},
        {"type": "video", "step_key": "video_gen", "label": "artVideo",
         "category": "video", "scope": "scene", "file": "scene_{i}/video.mp4",
         "scene_fields": ["video_file", "video_id", "video_status"],
         "extra_files": ["scene_{i}/task.json", "scene_{i}/curl.sh"]},
        # 任务级音频/字幕
        {"type": "audio", "step_key": "audio", "label": "artAudio",
         "category": "audio", "scope": "task", "file": "combined_narration.mp3",
         "fields": [], "scene_fields_all": ["narration_audio"]},
        {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
         "category": "subtitle", "scope": "task", "file": "combined_narration.srt",
         "fields": ["subtitle_styles_path"], "scene_fields_all": ["subtitle_srt"],
         "extra_files": ["subtitle_styles.json"]},
        {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
         "category": "video", "scope": "task", "file": "final_video.mp4",
         "fields": ["final_video_file"]},
    ]


def _manuscript_artifact_defs() -> list[dict]:
    """Manuscript 模式的产物定义模板。"""
    return [
        {"type": "scene_prompts", "step_key": "scene_prompts", "label": "artScenePrompts",
         "category": "json", "scope": "task", "file": "prompts.json",
         "fields": [], "para_fields_all": ["scene_prompt"]},
        {"type": "video", "step_key": "video_gen", "label": "artParaVideo",
         "category": "video", "scope": "paragraph", "file": "para_{i}/video.mp4",
         "para_fields": ["video_file", "video_id"],
         "extra_files": ["para_{i}/task.json", "para_{i}/curl.sh"]},
        {"type": "audio", "step_key": "audio", "label": "artAudio",
         "category": "audio", "scope": "task", "file": "full_narration.mp3",
         "fields": ["combined_audio"]},
        {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
         "category": "subtitle", "scope": "task", "file": "full_subtitle.srt",
         "fields": ["combined_subtitle", "subtitle_styles_path"],
         "extra_files": ["subtitle_styles.json"]},
        {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
         "category": "video", "scope": "task", "file": "final_video.mp4",
         "fields": ["final_video_file"]},
    ]


def _poetry_artifact_defs() -> list[dict]:
    """Poetry 模式的产物定义模板（v6.0 P3）。

    诗词视频逐场景产物：scene_{i}/video.mp4、scene_{i}/narration.mp3、
    scene_{i}/subtitle.srt。无参考图阶段（空实现跳过）。
    """
    return [
        # 场景级：视频 / 配音 / 字幕
        {"type": "video", "step_key": "video_gen", "label": "artVideo",
         "category": "video", "scope": "scene", "file": "scene_{i}/video.mp4",
         "scene_fields": ["video_file", "video_id"],
         "extra_files": ["scene_{i}/task.json", "scene_{i}/curl.sh"]},
        {"type": "audio", "step_key": "audio", "label": "artAudio",
         "category": "audio", "scope": "scene", "file": "scene_{i}/narration.mp3",
         "scene_fields": ["narration_audio"]},
        {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
         "category": "subtitle", "scope": "scene", "file": "scene_{i}/subtitle.srt",
         "scene_fields": ["subtitle_srt"]},
        # 任务级：成片
        {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
         "category": "video", "scope": "task", "file": "final_video.mp4",
         "fields": ["final_video_file"]},
    ]


def _anchor_artifact_defs(is_model_mode: bool) -> list[dict]:
    """Anchor 模式的产物定义模板。"""
    artifacts = [
        {"type": "anchor_image", "step_key": "generate_anchor", "label": "artAnchorImage",
         "category": "image", "scope": "task", "file": "anchor.png",
         "fields": ["anchor_image_path", "anchor_image_url"]},
        {"type": "clip_prompts", "step_key": "clip_prompts", "label": "artClipPrompts",
         "category": "json", "scope": "task", "file": "prompts.json",
         "fields": []},
        {"type": "clip", "step_key": "clip_gen", "label": "artClip",
         "category": "video", "scope": "task", "file": "clip/clip.mp4",
         "fields": []},
    ]
    if not is_model_mode:
        # post_stitch 模式还有音频、字幕、最终视频
        artifacts.extend([
            {"type": "audio", "step_key": "audio", "label": "artAudio",
             "category": "audio", "scope": "task", "file": "full_narration.mp3",
             "fields": ["combined_audio"]},
            {"type": "subtitle", "step_key": "subtitle", "label": "artSubtitle",
             "category": "subtitle", "scope": "task", "file": "full_subtitle.srt",
             "fields": ["combined_subtitle", "subtitle_styles_path"],
             "extra_files": ["subtitle_styles.json"]},
            {"type": "final_video", "step_key": "concatenate", "label": "artFinalVideo",
             "category": "video", "scope": "task", "file": "final_video.mp4",
             "fields": ["final_video_file", "final_video_path"]},
        ])
    return artifacts


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _get_steps_for_state(state: BaseTaskState) -> list[tuple[Optional[str], str]]:
    """根据 state 类型返回步骤序列。"""
    if isinstance(state, CreativeVideoTask):
        return _CREATIVE_STEPS
    elif isinstance(state, ManuscriptVideoTask):
        return _MANUSCRIPT_STEPS
    elif isinstance(state, AnchorVideoTask):
        if state.audio_source == "model":
            return _ANCHOR_STEPS_MODEL
        return _ANCHOR_STEPS_POST_STITCH
    elif isinstance(state, PoetryVideoTask):
        return _POETRY_STEPS
    return []


# ═══════════════════════════════════════════════════════════════
# 产物 schema 说明（v5.x：产物规范前置工作）
# ═══════════════════════════════════════════════════════════════

# 按产物 type 的人类可读字段说明，供清单（manifest.json）、MANIFEST.md
# 与 artifacts 端点输出；外部 Agent / 手动工具依据此说明处理产物。
_SCHEMA_HINTS = {
    "image_analysis": "参考图分析文本（纯文本）。可修改，修改后影响故事与分镜生成。",
    "story": "故事文本（纯文本）。可修改，修改后影响角色参考图、分镜与旁白生成。",
    "character_ref": "角色参考图 PNG（建议 768x1152，主体居中）。可用外部工具处理后覆盖同名文件。",
    "script": ("分镜脚本 JSON 数组，UTF-8、缩进 2 空格。字段：scenes[].scene_prompt=画面描述；"
               "scenes[].end_frame_prompt=尾帧描述；scenes[].narration_text=旁白；scenes[].duration=时长(秒)。"
               "只修改 scene_prompt/end_frame_prompt 最安全，修改 narration_text 会触发重新配音与字幕。"),
    "end_frame_prompts": "尾帧描述 JSON：{scene_i: {prompt: 画面描述}}。可修改后影响对应场景尾帧图与视频。",
    "end_frame": "场景尾帧图 PNG（关键帧衔接用）。可替换后影响后续场景视频。",
    "video": "场景视频 MP4（H.264+AAC）。可用 ffmpeg 或外部 Agent 剪辑/调色后覆盖同名文件。",
    "audio": "配音音频 MP3。同名 .txt 为旁白纯文本，建议先修改文本再重新生成音频。",
    "subtitle": "标准 SubRip SRT（UTF-8，每条 ≤2 行）。可手动修正断句与时间轴。",
    "final_video": "最终成片 MP4（含配音与字幕）。",
    "scene_prompts": "段落场景 prompt JSON（prompts.json）。可修改后影响对应段落视频。",
    "anchor_image": "数字人形象 PNG。可替换后影响数字人视频。",
    "clip_prompts": "数字人视频 prompt JSON（prompts.json）。",
    "clip": "数字人循环视频 MP4。",
    "narration_audio": "诗词场景朗诵音频 MP3（scene_{i}/narration.mp3）。逐场景修改后重跑该场景字幕与成片。",
    "subtitle_srt": "诗词场景字幕 SRT（scene_{i}/subtitle.srt）。",
}


def _schema_hint_for(d: dict) -> str:
    """取产物定义的 schema_hint，缺省回退空串。"""
    return _SCHEMA_HINTS.get(d.get("type", ""), "")


def _get_artifact_defs(state: BaseTaskState) -> list[dict]:
    """根据 state 类型返回产物定义列表。"""
    if isinstance(state, CreativeVideoTask):
        return _creative_artifact_defs()
    elif isinstance(state, ManuscriptVideoTask):
        return _manuscript_artifact_defs()
    elif isinstance(state, AnchorVideoTask):
        return _anchor_artifact_defs(state.audio_source == "model")
    elif isinstance(state, PoetryVideoTask):
        return _poetry_artifact_defs()
    return []


def _step_key_to_field(steps: list[tuple[Optional[str], str]], step_key: str) -> Optional[str]:
    """根据 step_key 查找对应的 step_field。"""
    for field_name, key in steps:
        if key == step_key:
            return field_name
    return None


def _step_key_to_order(steps: list[tuple[Optional[str], str]], step_key: str) -> int:
    """根据 step_key 查找在步骤序列中的位置索引。"""
    for i, (_, key) in enumerate(steps):
        if key == step_key:
            return i
    return -1


def _format_path(template: str, index: int) -> str:
    """格式化路径模板中的 {i}。"""
    return template.replace("{i}", str(index))


# ═══════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════


def list_artifacts(state: BaseTaskState, task_dir: str) -> list[ArtifactDescriptor]:
    """列举任务的所有中间产物（含存在性检测）。

    Args:
        state: 任务状态（CreativeVideoTask / ManuscriptVideoTask / AnchorVideoTask）
        task_dir: 任务目录绝对路径

    Returns:
        产物描述符列表，按步骤顺序排列
    """
    defs = _get_artifact_defs(state)
    if not defs:
        return []

    # Path-injection hardening: ensure the task directory stays within the working
    # directory even if it originated from untrusted input downstream.
    task_dir = safe_join(get_working_dir(), task_dir)

    # 获取场景/段落数量
    if isinstance(state, CreativeVideoTask):
        scope_count = len(state.scenes)
    elif isinstance(state, ManuscriptVideoTask):
        scope_count = len(state.paragraphs)
    elif isinstance(state, AnchorVideoTask):
        scope_count = len(state.paragraphs) if state.paragraphs else 0
    elif isinstance(state, PoetryVideoTask):
        scope_count = len(state.scenes)
    else:
        scope_count = 0

    result: list[ArtifactDescriptor] = []

    for d in defs:
        if d["scope"] == "task":
            # 任务级产物
            file_relpath = d.get("file")
            exists = False
            size = 0
            if file_relpath:
                abs_path = os.path.join(task_dir, file_relpath)
                if os.path.exists(abs_path):
                    exists = True
                    size = os.path.getsize(abs_path)

            step_field = _step_key_to_field(_get_steps_for_state(state), d["step_key"])
            result.append(ArtifactDescriptor(
                artifact_id=f"{state.task_type.value}:{d['type']}",
                step_key=d["step_key"],
                step_field=step_field,
                label_key=d["label"],
                category=d["category"],
                scope="task",
                scope_index=None,
                file_relpath=file_relpath,
                state_fields=d.get("fields", []),
                exists=exists,
                size=size,
                deletable=True,
                schema_hint=_schema_hint_for(d),
            ))
        elif d["scope"] in ("scene", "paragraph"):
            # 场景/段落级产物
            for i in range(scope_count):
                file_relpath = _format_path(d["file"], i)
                abs_path = os.path.join(task_dir, file_relpath)
                exists = os.path.exists(abs_path)
                size = os.path.getsize(abs_path) if exists else 0

                step_field = _step_key_to_field(_get_steps_for_state(state), d["step_key"])
                result.append(ArtifactDescriptor(
                    artifact_id=f"{state.task_type.value}:{d['type']}:{i}",
                    step_key=d["step_key"],
                    step_field=step_field,
                    label_key=d["label"],
                    category=d["category"],
                    scope=d["scope"],
                    scope_index=i,
                    file_relpath=file_relpath,
                    state_fields=[],  # 场景级字段在 scene_updates 中处理
                    exists=exists,
                    size=size,
                    deletable=True,
                    schema_hint=_schema_hint_for(d),
                ))

    return result


def resolve_artifact(artifact_id: str, state: BaseTaskState, task_dir: str) -> Optional[ArtifactDescriptor]:
    """根据 artifact_id 解析单个产物描述符。

    Args:
        artifact_id: 产物 ID, 如 "creative:end_frame:2"
        state: 任务状态
        task_dir: 任务目录路径

    Returns:
        产物描述符, 或 None 如果未找到
    """
    artifacts = list_artifacts(state, task_dir)
    for art in artifacts:
        if art.artifact_id == artifact_id:
            return art
    return None


def get_cascade_plan(artifact_id: str, state: BaseTaskState, task_dir: str) -> Optional[CascadePlan]:
    """计算删除指定产物后的级联删除计划。

    级联原则:
    1. 删除该产物文件 + 清空对应字段
    2. 重置该产物所在步骤及之后所有步骤的状态为 PENDING
    3. 删除后续步骤的所有产物文件
    4. 对于场景级产物, 级联删除同类型后续场景(scene_N → scene_{N+1..})的产物
    5. 删除 video 时同时删除 task.json/curl.sh 缓存文件

    Args:
        artifact_id: 要删除的产物 ID
        state: 任务状态
        task_dir: 任务目录路径

    Returns:
        级联删除计划, 或 None 如果产物未找到
    """
    artifact = resolve_artifact(artifact_id, state, task_dir)
    if not artifact:
        return None

    steps = _get_steps_for_state(state)
    defs = _get_artifact_defs(state)
    plan = CascadePlan()

    # 1. 找到被删产物所在步骤的位置
    target_order = _step_key_to_order(steps, artifact.step_key)
    if target_order < 0:
        return None

    # 2. 收集所有 order >= target_order 的步骤字段（用于重置）
    for step_field, _ in steps[target_order:]:
        if step_field:  # None 的步骤没有状态字段
            plan.steps_to_reset.append(step_field)

    # 3. 收集所有 order >= target_order 的产物定义
    cascaded_defs = []
    for d in defs:
        d_order = _step_key_to_order(steps, d["step_key"])
        if d_order >= target_order:
            cascaded_defs.append(d)

    # 4. 对于场景级产物, 确定级联起始索引
    cascade_from_index = 0
    if artifact.scope in ("scene", "paragraph") and artifact.scope_index is not None:
        cascade_from_index = artifact.scope_index

    # 4a. 确定场景级产物的级联终止索引
    # keyframes/ti2vid 模式有视觉链依赖，删除 scene_N 会级联到 scene_{N+1..}
    # none 模式场景独立，删除 scene_N 只影响当前场景
    # Manuscript/Anchor 段落间独立，同 none 模式处理
    scene_cascade_to_end = True  # 默认级联到末尾
    if isinstance(state, CreativeVideoTask):
        if state.chaining_mode == "none" and artifact.scope == "scene":
            scene_cascade_to_end = False
    elif isinstance(state, (ManuscriptVideoTask, AnchorVideoTask)):
        if artifact.scope in ("scene", "paragraph"):
            scene_cascade_to_end = False

    # 5. 获取场景/段落数量
    if isinstance(state, CreativeVideoTask):
        scope_count = len(state.scenes)
    elif isinstance(state, ManuscriptVideoTask):
        scope_count = len(state.paragraphs)
    elif isinstance(state, AnchorVideoTask):
        scope_count = len(state.paragraphs) if state.paragraphs else 0
    else:
        scope_count = 0

    # 6. 遍历级联产物定义, 生成删除计划
    for d in cascaded_defs:
        if d["scope"] == "task":
            # 任务级产物
            file_relpath = d.get("file")
            if file_relpath:
                plan.files_to_delete.append(file_relpath)

            # 额外文件
            for ef in d.get("extra_files", []):
                plan.files_to_delete.append(ef)

            # 顶层字段清空
            for f in d.get("fields", []):
                plan.fields_to_clear[f] = ""

            # 场景字段全量清空 (如 narration_audio 对所有 scenes)
            for sf in d.get("scene_fields_all", []):
                for i in range(scope_count):
                    plan.scene_updates.append({
                        "list_field": "scenes",
                        "from_index": i,
                        "field": sf,
                        "value": "",
                    })

            # 段落字段全量清空
            for pf in d.get("para_fields_all", []):
                for i in range(scope_count):
                    plan.scene_updates.append({
                        "list_field": "paragraphs",
                        "from_index": i,
                        "field": pf,
                        "value": "",
                    })

        elif d["scope"] in ("scene", "paragraph"):
            # 场景/段落级产物 - 从 cascade_from_index 开始
            current_list_field = "scenes" if d["scope"] == "scene" else "paragraphs"
            # 确定终止索引：如果场景独立（none模式/manuscript/anchor），只删当前场景
            if scene_cascade_to_end:
                end_idx = scope_count
            else:
                end_idx = cascade_from_index + 1
            for i in range(cascade_from_index, end_idx):
                # 文件
                file_relpath = _format_path(d["file"], i)
                plan.files_to_delete.append(file_relpath)

                # 额外文件
                for ef in d.get("extra_files", []):
                    plan.files_to_delete.append(_format_path(ef, i))

                # 场景/段落字段清空
                for sf in d.get("scene_fields", d.get("para_fields", [])):
                    plan.scene_updates.append({
                        "list_field": current_list_field,
                        "from_index": i,
                        "field": sf,
                        "value": "",
                    })

                    # video_status 需要重置为 pending 而非空字符串
                    if sf == "video_status":
                        plan.scene_updates[-1]["value"] = StepStatus.PENDING

            # 额外顶层字段清空（如 pregenerated_end_frames）
            for f in d.get("clear_top_fields", []):
                if f not in plan.fields_to_clear:
                    plan.fields_to_clear[f] = {}  # dict 类型默认空字典

    # 7. 去重文件列表
    seen = set()
    unique_files = []
    for f in plan.files_to_delete:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    plan.files_to_delete = unique_files

    return plan


def apply_cascade_plan(state: BaseTaskState, plan: CascadePlan) -> dict:
    """将级联计划应用到 state 对象上（原地修改），返回 update_state 的参数字典。

    Args:
        state: 任务状态（将被原地修改）
        plan: 级联删除计划

    Returns:
        dict: 传递给 TaskManager.update_state() 的参数
    """
    update_kwargs: dict[str, Any] = {}

    # 1. 重置步骤状态
    for step_field in plan.steps_to_reset:
        setattr(state, step_field, StepStatus.PENDING)
        update_kwargs[step_field] = StepStatus.PENDING

    # 2. 清空顶层字段（根据字段类型选择正确的默认值）
    for field_name, default_val in plan.fields_to_clear.items():
        if hasattr(state, field_name):
            # 如果默认值已经是正确类型，直接使用
            current_val = getattr(state, field_name)
            if isinstance(current_val, list) and not isinstance(default_val, list):
                default_val = []
            elif isinstance(current_val, dict) and not isinstance(default_val, dict):
                default_val = {}
            setattr(state, field_name, default_val)
            update_kwargs[field_name] = default_val

    # 3. 更新 scenes/paragraphs 列表中的字段
    for su in plan.scene_updates:
        list_field = su["list_field"]
        idx = su["from_index"]
        field_name = su["field"]
        value = su["value"]

        items = getattr(state, list_field, None)
        if items and idx < len(items):
            if hasattr(items[idx], field_name):
                setattr(items[idx], field_name, value)

    # 4. 将更新后的 scenes/paragraphs 加入 update_kwargs
    if isinstance(state, CreativeVideoTask):
        update_kwargs["scenes"] = state.scenes
    elif isinstance(state, (ManuscriptVideoTask, AnchorVideoTask)):
        update_kwargs["paragraphs"] = state.paragraphs

    # 5. 设置任务状态为 PENDING
    state.status = StepStatus.PENDING
    update_kwargs["status"] = StepStatus.PENDING

    # 6. v6.1：删除前置环节产物后，重置受影响检查点的"已批准"状态
    #    级联重置了某检查点对应步骤 → 该检查点不再视为已确认，
    #    恢复执行时 _maybe_pause 会重新在此暂停等待用户（否则会静默跳过）。
    mc = getattr(state, "manual_config", None)
    if mc is not None:
        approved = list(mc.approved_checkpoints or [])
        removed: list[str] = []
        for cp in list(approved):
            step_field = _checkpoint_to_step_field(cp, state)
            if step_field and step_field in plan.steps_to_reset:
                approved.remove(cp)
                removed.append(cp)
        if removed:
            mc.approved_checkpoints = approved
            update_kwargs["manual_config"] = mc
            logger.info(
                "[Artifacts] Cascade reset un-approved checkpoints: %s", removed
            )

    return update_kwargs


# ═══════════════════════════════════════════════════════════════
# 僵尸任务磁盘清理（v5.0 Batch 5 / 5.1）
# ═══════════════════════════════════════════════════════════════

_DEFAULT_PROTECT_STATUSES = {StepStatus.RUNNING, StepStatus.QUEUED, StepStatus.PENDING}


def sweep_stale_tasks(age_days: int = 7,
                      protect_statuses: Optional[set] = None) -> dict:
    """扫描并清理僵尸任务目录（状态文件超龄且任务非活跃）。

    清理条件（全部满足才删除）：
    1. 工作区中存在 ``task_state.json`` 且可解析出 ``status`` 字段；
    2. ``status`` 不在保护集合中；
    3. ``task_state.json`` 的修改时间距今超过 ``age_days`` 天。

    默认保护 ``RUNNING``（运行中）/ ``QUEUED``（排队中）/ ``PENDING``（断点续传
    候选），保证活跃任务与可恢复任务永不误删；调用方可传 ``protect_statuses``
    显式覆盖（如仅保护活跃状态，放开 PENDING）。

    删除策略：整目录 ``shutil.rmtree``（等价于按级联计划删除全部产物 + 状态文件），
    删除前校验 realpath 必须位于工作区内，防符号链接逃逸。

    Args:
        age_days: 状态文件超龄阈值（天）
        protect_statuses: 保护的状态集合；None 时使用默认保护集合

    Returns:
        {"swept": [目录名], "protected": [目录名], "errors": [描述]}
    """
    working_dir = get_working_dir()
    protect = protect_statuses if protect_statuses is not None else _DEFAULT_PROTECT_STATUSES
    swept: list[str] = []
    protected: list[str] = []
    errors: list[str] = []

    if not os.path.isdir(working_dir):
        return {"swept": swept, "protected": protected, "errors": errors}

    real_working = os.path.realpath(working_dir)
    cutoff = time.time() - age_days * 86400

    for name in sorted(os.listdir(working_dir)):
        task_dir = os.path.join(working_dir, name)
        if not os.path.isdir(task_dir):
            continue
        task_file = os.path.join(task_dir, "task_state.json")
        if not os.path.isfile(task_file):
            continue  # 非任务目录（如 uploads/ 或普通文件目录）
        try:
            with open(task_file, "r", encoding="utf-8") as f:
                status_str = json.load(f).get("status")
        except (OSError, json.JSONDecodeError):
            errors.append(f"{name}: task_state.json 无法解析")
            continue
        if status_str in {s.value for s in protect}:
            protected.append(name)
            continue
        try:
            mtime = os.path.getmtime(task_file)
        except OSError:
            errors.append(f"{name}: 无法读取 task_state.json 修改时间")
            continue
        if mtime > cutoff:
            protected.append(name)  # 未超龄，保留
            continue
        # 路径穿越防护：任务目录 realpath 必须位于工作区内
        if not os.path.realpath(task_dir).startswith(real_working + os.sep):
            errors.append(f"{name}: 任务目录逃逸工作区，拒绝删除")
            continue
        try:
            shutil.rmtree(task_dir)
            swept.append(name)
        except OSError as e:
            errors.append(f"{name}: 删除失败 ({e})")

    return {"swept": swept, "protected": protected, "errors": errors}


# ═══════════════════════════════════════════════════════════════
# 产物清单（manifest.json / MANIFEST.md）— v5.x 产物规范前置工作
# ═══════════════════════════════════════════════════════════════

# 清单自身文件名（扫描文件树时排除）
_MANIFEST_FILES = {"manifest.json", "MANIFEST.md", "task_state.json", "checkpoint.json"}


# ═══════════════════════════════════════════════════════════════
# v6.0 检查点分组（PRD §4.3 产物矩阵）
# ═══════════════════════════════════════════════════════════════

# 产物 type → 检查点名（与 dependency_graph._TYPE_TO_CHECKPOINT 语义一致）
# creative：细粒度检查点（每个有产物的环节独立，v6.1）
_ARTIFACT_TO_CHECKPOINT_FINE: dict[str, str] = {
    "image_analysis": "image_analysis",
    "story": "story",
    "script": "script",
    "character_ref": "character_ref",
    "end_frame_prompts": "end_frame_prompts",
    "end_frame": "end_frame_gen",
    "video": "videos",
    "audio": "audio",
    "subtitle": "subtitle",
    "final_video": "final",
}
# 非 creative（manuscript/poetry/anchor）：粗粒度合并检查点
_ARTIFACT_TO_CHECKPOINT_COARSE: dict[str, str] = {
    "story": "scenes",
    "script": "scenes",
    "end_frame_prompts": "scenes",
    "character_ref": "references",
    "end_frame": "references",
    "video": "videos",
    "audio": "audio",
    "subtitle": "subtitle",
    "final_video": "final",
    "scene_prompts": "scenes",
    "anchor_image": "references",
    "clip_prompts": "scenes",
    "clip": "videos",
}

# 检查点展示顺序（creative 细粒度；其余粗粒度）
_CHECKPOINT_ORDER_FINE = [
    "image_analysis", "story", "script", "character_ref",
    "end_frame_prompts", "end_frame_gen", "videos", "audio", "subtitle", "final",
]
_CHECKPOINT_ORDER = ["scenes", "references", "videos", "audio", "subtitle", "final"]


def _checkpoint_order_for(state: BaseTaskState) -> list[str]:
    """按任务类型返回检查点展示顺序。"""
    if isinstance(state, CreativeVideoTask):
        return _CHECKPOINT_ORDER_FINE
    return _CHECKPOINT_ORDER


def checkpoint_for_artifact(artifact_id: str, task_type: Optional[str] = None) -> str:
    """返回产物 id 所属检查点名（未知产物 → "other"）。

    Args:
        artifact_id: 产物 id（含任务类型前缀，如 ``creative:script``）。
        task_type: 任务类型（缺省时从产物 id 前缀解析）。
    """
    parts = artifact_id.split(":")
    if len(parts) >= 2:
        t = task_type or parts[0]
        mapping = _ARTIFACT_TO_CHECKPOINT_FINE if t == "creative" else _ARTIFACT_TO_CHECKPOINT_COARSE
        return mapping.get(parts[1], "other")
    return "other"


def build_checkpoint_manifest(state: BaseTaskState, task_dir: str) -> dict:
    """构建检查点级产物清单（checkpoint.json 数据）。

    按检查点分组展示产物（PRD §4.3 / §4.8），供手动模式检查点等待页
    与外部 Agent 使用。每组含该检查点的产物列表（复用 manifest 的产物条目）。

    Returns:
        {
          "format_version": "1.0",
          "task_id": ...,
          "task_type": ...,
          "current_checkpoint": ...,
          "checkpoints": {
              "scenes":  { "artifacts": [ ...产物条目... ], "status": "completed|pending" },
              "videos":  { "artifacts": [ ... ], "status": ... },
              ...
          }
        }
    """
    task_dir = safe_join(get_working_dir(), task_dir)
    manifest = build_manifest(state, task_dir)
    order = _checkpoint_order_for(state)

    groups: dict[str, dict] = {cp: {"artifacts": []} for cp in order}
    for a in manifest.get("artifacts", []):
        cp = checkpoint_for_artifact(a["artifact_id"], state.task_type.value)
        if cp in groups:
            groups[cp]["artifacts"].append(a)

    # 状态：检查点对应的 step 字段状态（复用 step 状态）
    for cp in order:
        step_field = _checkpoint_to_step_field(cp, state)
        status = "pending"
        if step_field:
            val = getattr(state, step_field, None)
            if val is not None:
                status = val.value
        groups[cp]["status"] = status

    current = ""
    manual_cfg = getattr(state, "manual_config", None)
    if manual_cfg is not None:
        current = manual_cfg.current_checkpoint or ""

    return {
        "format_version": "1.0",
        "task_id": state.task_id,
        "task_type": state.task_type.value,
        "current_checkpoint": current,
        "checkpoints": groups,
        "files": manifest.get("files", []),
    }


def _checkpoint_to_step_field(checkpoint: str, state: BaseTaskState) -> Optional[str]:
    """检查点名 → 步骤字段名（按任务类型）。"""
    if isinstance(state, CreativeVideoTask):
        mapping = {
            "image_analysis": "step_image_analysis",
            "story": "step_story",
            "script": "step_script",
            "character_ref": "step_character_ref",
            "end_frame_prompts": "step_end_frame_prompts",
            "end_frame_gen": "step_end_frame_generation",
            "videos": "step_video_generation",
            "audio": "step_audio",
            "subtitle": "step_subtitle",
            "final": "step_concatenation",
        }
        return mapping.get(checkpoint)
    if isinstance(state, ManuscriptVideoTask):
        mapping = {
            "scenes": "step_scene_prompts",
            "videos": "step_video_generation",
            "audio": "step_audio",
            "subtitle": "step_subtitle",
            "final": "step_concatenation",
        }
        return mapping.get(checkpoint)
    if isinstance(state, AnchorVideoTask):
        mapping = {
            "scenes": "step_generate_anchor",
            "references": "step_generate_anchor",
            "videos": "step_clip_generation",
            "audio": "step_audio",
            "subtitle": "step_subtitle",
            "final": "step_concatenation",
        }
        return mapping.get(checkpoint)
    if isinstance(state, PoetryVideoTask):
        # 优化路线图 1.5c：此前缺 poetry 分支，poetry 检查点状态恒为 pending，
        # 级联删除的 approved_checkpoints 重置也因此失效。
        mapping = {
            "scenes": "step_build_scenes",
            "references": "step_reference_images",
            "videos": "step_video_generation",
            "audio": "step_audio",
            "subtitle": "step_subtitle",
            "final": "step_concatenation",
        }
        return mapping.get(checkpoint)
    return None


def write_checkpoint_manifest(state: BaseTaskState, task_dir: str) -> str:
    """将检查点清单落盘为 ``checkpoint.json``，返回路径；失败返回空串。"""
    try:
        manifest = build_checkpoint_manifest(state, task_dir)
        path = os.path.join(task_dir, "checkpoint.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return path
    except Exception as e:
        logger.warning("[Artifacts] failed to write checkpoint.json: %s", e)
        return ""


def _scan_task_files(task_dir: str) -> list[dict]:
    """通用文件树扫描：列出任务目录下全部文件（相对路径 + 大小）。

    对无结构化产物定义的类型（simple / poetry 等）同样有效，
    保证 manifest 对任何任务都可用。
    """
    files: list[dict] = []
    if not os.path.isdir(task_dir):
        return files
    for root, _dirs, names in os.walk(task_dir):
        for name in sorted(names):
            if name in _MANIFEST_FILES:
                continue
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, task_dir)
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                size = 0
            files.append({"path": rel_path, "size": size})
    return sorted(files, key=lambda f: f["path"])


def build_manifest(state: BaseTaskState, task_dir: str) -> dict:
    """构建任务产物清单（manifest 数据）。

    包含三部分：
    1. meta：任务 ID / 类型 / 状态 / 目录绝对路径
    2. artifacts：结构化产物（creative/manuscript/anchor），含路径、格式、
       schema_hint、可编辑性、预览 URL、生成步骤
    3. files：通用文件树（所有任务类型均有）

    该清单是 v6.0「手动模式」checkpoint.json 的数据基础。
    """
    # Path-injection hardening: ensure the task directory stays within the working
    # directory even if it originated from untrusted input downstream.
    task_dir = safe_join(get_working_dir(), task_dir)

    artifacts = []
    for art in list_artifacts(state, task_dir):
        artifacts.append({
            "artifact_id": art.artifact_id,
            "name_key": art.label_key,
            "category": art.category,
            "scope": art.scope,
            "scope_index": art.scope_index,
            "path": art.file_relpath,
            "exists": art.exists,
            "size": art.size,
            "editable": True,  # 文本/JSON 可编辑；图片/视频/音频可替换覆盖
            "schema_hint": art.schema_hint,
            "generated_by_step": art.step_key,
            "preview_url": (
                f"/api/tasks/{state.task_id}/artifacts/{art.artifact_id}/file"
                if art.file_relpath else ""
            ),
        })

    # v6.0 手动模式：暴露执行模式与当前检查点（供前端判断暂停态 / 渲染依赖图）
    manual_cfg = getattr(state, "manual_config", None)
    current_checkpoint = ""
    current_mode = "auto"
    if manual_cfg is not None:
        current_mode = "manual" if manual_cfg.enabled else "auto"
        current_checkpoint = manual_cfg.current_checkpoint or ""

    return {
        "format_version": "1.0",
        "task_id": state.task_id,
        "task_type": state.task_type.value,
        "task_status": state.status.value if state.status else "pending",
        "current_mode": current_mode,
        "current_checkpoint": current_checkpoint,
        "manual_config": (
            manual_cfg.model_dump() if manual_cfg is not None else {}
        ),
        "dir_name": os.path.basename(task_dir.rstrip(os.sep)),
        "working_dir": task_dir,
        "artifacts": artifacts,
        "files": _scan_task_files(task_dir),
    }


def write_manifest(state: BaseTaskState, task_dir: str) -> str:
    """将产物清单落盘为 ``manifest.json``（UTF-8、indent=2），返回路径。

    失败时静默返回空串（清单为辅助产物，不应阻塞主流程）。
    """
    try:
        manifest = build_manifest(state, task_dir)
        # 使用 build_manifest 归一化后的绝对路径写盘（兼容相对/绝对入参）
        path = os.path.join(manifest["working_dir"], "manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return path
    except Exception as e:
        logger.warning("[Artifacts] failed to write manifest.json: %s", e)
        return ""


def write_manifest_md(state: BaseTaskState, task_dir: str) -> str:
    """将任务目录说明落盘为 ``MANIFEST.md``（供用户与外部 Agent 阅读），返回路径。"""
    try:
        manifest = build_manifest(state, task_dir)
        lines = [
            "# 任务产物说明（自动生成）",
            "",
            "> 本文件由系统自动生成，说明任务目录内各产物的含义、格式与可修改性。",
            "> 修改产物后可通过网页操作或直接覆盖同名文件；修改 JSON / 文本 / SRT",
            "> 后需重新生成受影响的下游步骤（见各产物的「说明」）。",
            "",
            "## 任务信息",
            "",
            f"- 任务 ID：`{manifest['task_id']}`",
            f"- 任务类型：`{manifest['task_type']}`",
            f"- 任务状态：`{manifest['task_status']}`",
            f"- 工作目录：`{manifest['working_dir']}`",
            "",
        ]

        if manifest["artifacts"]:
            lines += [
                "## 产物清单",
                "",
                "| 文件（相对路径） | 类型 | 说明 |",
                "|---|---|---|",
            ]
            for a in manifest["artifacts"]:
                if not a["path"]:
                    continue
                marker = "✅" if a["exists"] else "—"
                lines.append(
                    f"| {marker} `{a['path']}` | {a['category']} | {a['schema_hint'] or ''} |"
                )
            lines.append("")

        if manifest["files"]:
            lines += [
                "## 目录文件树",
                "",
                "```",
            ]
            lines += [f["path"] for f in manifest["files"]]
            lines += ["```", ""]

        lines += [
            "## 协作提示",
            "",
            "- 文本 / JSON / SRT 产物可直接用编辑器或外部 AI Agent（如 TraeWork、opencode、workbuddy）修改。",
            "- 图片 / 视频产物可用 ffmpeg、Python 等外部工具处理后覆盖同名文件。",
            "- 产物字段说明见 `docs/dev/artifact_standard.md`。",
            "",
        ]

        path = os.path.join(manifest["working_dir"], "MANIFEST.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
    except Exception as e:
        logger.warning("[Artifacts] failed to write MANIFEST.md: %s", e)
        return ""


def write_task_manifests(state: BaseTaskState, task_dir: str) -> None:
    """一次性落盘 manifest.json + MANIFEST.md（任务运行开始/结束时调用）。"""
    write_manifest(state, task_dir)
    write_manifest_md(state, task_dir)
