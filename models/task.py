"""
Agnes Video Generator v2.0 — 数据模型层

定义所有任务类型的数据结构：
- TaskType 枚举、VideoMode 枚举
- SubtitleStyle、AudioConfig 配置类
- BaseTaskState（共享字段）+ 三种任务子类
- 请求/响应模型
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════


class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    SIMPLE = "simple"
    CREATIVE = "creative"
    MANUSCRIPT = "manuscript"
    ANCHOR = "anchor"
    IMAGE = "image"


class VideoMode(str, Enum):
    T2V = "t2v"
    I2V = "i2v"
    TI2VID = "ti2vid"
    KEYFRAMES = "keyframes"


# ═══════════════════════════════════════════════════
# 配置类
# ═══════════════════════════════════════════════════


class SubtitleStyle(BaseModel):
    """字幕样式配置（v3.0 Phase 2: 支持固定和 LLM 两种模式）"""

    font: str = "STHeitiMedium.ttc"
    color: str = "white"
    position: tuple = ("center", "bottom-80")
    fontsize: int = 48
    stroke_color: str = "black"
    stroke_width: int = 2
    bg_color: tuple = (0, 0, 0, 128)

    style_mode: str = "fixed"      # "fixed" | "llm"
    style_hints: str = ""          # 用户对 LLM 的样式偏好描述

    @field_validator("bg_color", mode="before")
    @classmethod
    def _coerce_bg_color(cls, v):
        if isinstance(v, tuple):
            return v
        if isinstance(v, str):
            if "@" in v:
                parts = v.split("@", 1)
                rgb = {"black": (0, 0, 0), "white": (255, 255, 255),
                       "red": (255, 0, 0), "blue": (0, 0, 255),
                       "yellow": (255, 255, 0)}.get(parts[0].strip().lower(), (0, 0, 0))
                return (*rgb, int(float(parts[1]) * 255))
            if v.lower() in ("none", "transparent", ""):
                return None
        return (0, 0, 0, 128)


class SubtitleConfig(BaseModel):
    """字幕配置（v3.0 从 AudioConfig 独立）"""

    enabled: bool = True
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class AudioConfig(BaseModel):
    """音频配置（TTS 语音，不再包含字幕样式）"""

    enabled: bool = True
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"


# ═══════════════════════════════════════════════════
# 子结构模型
# ═══════════════════════════════════════════════════


class ManuscriptParagraph(BaseModel):
    """稿件段落（类型 3 专用）"""

    index: int
    text: str
    scene_prompt: str = ""
    same_scene_as_prev: bool = False
    video_id: str = ""
    video_file: str = ""
    narration_audio: str = ""
    subtitle_srt: str = ""
    final_clip: str = ""


class SceneTask(BaseModel):
    """场景任务（类型 2 专用，v2.0 新增旁白/音频/字幕字段）"""

    index: int
    status: StepStatus = StepStatus.PENDING
    end_frame_prompt: str = ""
    end_frame_file: str = ""
    video_id: str = ""
    video_status: StepStatus = StepStatus.PENDING
    video_file: str = ""
    # v2.0 新增
    narration_text: str = ""
    narration_audio: str = ""
    subtitle_srt: str = ""
    final_clip: str = ""
    # v3.x 新增：每个场景独立时长
    duration: int = 5


# ═══════════════════════════════════════════════════
# 任务状态模型
# ═══════════════════════════════════════════════════


class BaseTaskState(BaseModel):
    """所有任务共享的基础字段（抽象父类）"""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    creative_name: str = ""
    task_type: TaskType
    status: StepStatus = StepStatus.PENDING
    video_width: int = 1152
    video_height: int = 768
    final_video_file: str = ""


class SimpleVideoTask(BaseTaskState):
    """简单视频任务（类型 1）

    用户直接输入 prompt，选择模式/时长/分辨率，调用 Agnes Video API 生成单个视频。
    """

    task_type: Literal[TaskType.SIMPLE] = TaskType.SIMPLE

    prompt: str = ""
    mode: VideoMode = VideoMode.T2V
    reference_image: str = ""
    end_frame_image: str = ""
    duration: int = 5
    seed: Optional[int] = None
    negative_prompt: Optional[str] = None
    system_prompt: str = ""
    video_id: str = ""


class CreativeVideoTask(BaseTaskState):
    """创意长视频任务（类型 2）

    保持现有 TaskState 全部字段向后兼容，v2.0 新增音频/字幕配置和旁白列表。
    """

    task_type: Literal[TaskType.CREATIVE] = TaskType.CREATIVE

    # ── 现有字段（保持兼容）──
    idea: str = ""
    style: str = ""
    chaining_mode: str = "none"
    video_duration: int = 5  # 兜底默认值，实际场景时长由 SceneTask.duration 控制

    # ── v3.x 场景配置（替代 user_requirement）──
    duration_source: str = "manual"  # "manual" | "prompt" — 场景数和时长来源
    scene_count: int = 3
    uniform_duration: bool = True
    scene_durations: List[int] = Field(default_factory=lambda: [5, 5, 5])

    # ── 向后兼容（已废弃，保留以兼容旧数据）──
    user_requirement: str = ""

    reference_image: str = ""
    end_frame_images: List[str] = Field(default_factory=list)
    use_custom_end_frames: bool = False
    generate_end_frames_from_ref: bool = True  # i2i 尾帧优化后默认开启

    # ── v3.x 场景配置步骤 ──
    step_scene_config: StepStatus = StepStatus.PENDING

    step_story: StepStatus = StepStatus.PENDING
    story_file: str = ""

    step_character_ref: StepStatus = StepStatus.PENDING
    character_ref_prompt: str = ""
    character_ref_file: str = ""
    character_appearance: str = ""  # i2i 尾帧一致性：角色外观文本持久化（批次3）

    step_script: StepStatus = StepStatus.PENDING
    script_file: str = ""

    step_end_frame_prompts: StepStatus = StepStatus.PENDING
    end_frame_prompts_file: str = ""

    step_image_analysis: StepStatus = StepStatus.PENDING
    image_analysis_file: str = ""

    step_end_frame_generation: StepStatus = StepStatus.PENDING
    pregenerated_end_frames: dict = Field(default_factory=dict)

    scenes: List[SceneTask] = Field(default_factory=list)

    step_video_generation: StepStatus = StepStatus.PENDING

    # ── v2.0 新增：音频 + 字幕 ──
    step_audio_subtitle: StepStatus = StepStatus.PENDING
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)
    narrations: List[str] = Field(default_factory=list)

    # ── v3.0 拆分：音频和字幕后向兼容字段 ──
    step_audio: StepStatus = StepStatus.PENDING
    step_subtitle: StepStatus = StepStatus.PENDING
    subtitle_styles_path: str = ""      # LLM 样式 JSON 路径（Phase 2）

    step_concatenation: StepStatus = StepStatus.PENDING

    # ── 辅助方法（保持向后兼容）──

    def all_scenes_completed(self) -> bool:
        return all(s.status == StepStatus.COMPLETED for s in self.scenes)

    def all_videos_completed(self) -> bool:
        return all(s.video_status == StepStatus.COMPLETED for s in self.scenes)

    def get_pending_scenes(self) -> List[SceneTask]:
        return [s for s in self.scenes if s.status != StepStatus.COMPLETED]

    def get_pending_videos(self) -> List[SceneTask]:
        return [s for s in self.scenes if s.video_status != StepStatus.COMPLETED]


class ManuscriptVideoTask(BaseTaskState):
    """稿件长视频任务（类型 3）

    用户粘贴长文本 → 按朗读时间拆段 → 每段生成视频 prompt → 视频生成 → TTS+字幕 → 拼接。
    """

    task_type: Literal[TaskType.MANUSCRIPT] = TaskType.MANUSCRIPT

    manuscript_text: str = ""
    paragraphs: List[ManuscriptParagraph] = Field(default_factory=list)
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)
    video_duration: int = 10

    combined_audio: str = ""
    combined_subtitle: str = ""
    subtitle_styles_path: str = ""      # LLM 样式 JSON 路径（Phase 2）

    step_split: StepStatus = StepStatus.PENDING
    step_scene_prompts: StepStatus = StepStatus.PENDING
    step_video_generation: StepStatus = StepStatus.PENDING
    step_audio_subtitle: StepStatus = StepStatus.PENDING
    step_audio: StepStatus = StepStatus.PENDING
    step_subtitle: StepStatus = StepStatus.PENDING
    step_concatenation: StepStatus = StepStatus.PENDING


class AnchorVideoTask(BaseTaskState):
    """数字人口播任务（类型 4 / Phase 3）

    用户提供主播形象 prompt 和口播稿件，系统生成主播形象图片，
    按朗读时长将稿件拆段（5-12 秒/段），每段生成不同动作的 i2v
    视频片段，配合 TTS 读稿音频和字幕，拼接合成最终视频。
    （v3.1 方案 B：分段生成 + 口型近似匹配）

    audio_source 支持两种模式：
      - "post_stitch": 生成一段短 i2v 视频循环 + TTS 后拼接音频（音频可控，嘴型较难匹配）
      - "model": 交由视频模型自身生成音频（音频由模型控制，效果不可控）
    """

    task_type: Literal[TaskType.ANCHOR] = TaskType.ANCHOR

    # 用户输入
    anchor_prompt: str = ""
    anchor_reference_image: str = ""
    script_text: str = ""

    # 配置
    audio_source: str = "post_stitch"  # "post_stitch" | "model"
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)

    # 步骤状态
    step_generate_anchor: StepStatus = StepStatus.PENDING
    step_split: StepStatus = StepStatus.PENDING
    step_clip_prompts: StepStatus = StepStatus.PENDING
    step_clip_generation: StepStatus = StepStatus.PENDING
    step_audio: StepStatus = StepStatus.PENDING
    step_subtitle: StepStatus = StepStatus.PENDING
    step_concatenation: StepStatus = StepStatus.PENDING

    # 产物
    anchor_image_url: str = ""
    anchor_image_path: str = ""
    paragraphs: List[ManuscriptParagraph] = Field(default_factory=list)
    combined_audio: str = ""
    combined_subtitle: str = ""
    subtitle_styles_path: str = ""
    final_video_path: str = ""


class SimpleImageTask(BaseTaskState):
    """简单图片任务（类型 5）

    用户输入 prompt 和尺寸，直调 Agnes Image API 生成单张图片，
    在 working_dir 中建任务并保存结果。
    """

    task_type: Literal[TaskType.IMAGE] = TaskType.IMAGE

    prompt: str = ""
    size: str = "1024x1024"
    negative_prompt: str = ""
    system_prompt: str = ""


# ═══════════════════════════════════════════════════
# 联合类型 + 反序列化工厂
# ═══════════════════════════════════════════════════

AnyTaskState = Union[SimpleVideoTask, CreativeVideoTask, ManuscriptVideoTask, AnchorVideoTask, SimpleImageTask]

# 用于 TaskManager.load()：根据 task_type 字段选择正确的模型类
_TASK_TYPE_MAP: dict[str, type[BaseTaskState]] = {
    TaskType.SIMPLE: SimpleVideoTask,
    TaskType.CREATIVE: CreativeVideoTask,
    TaskType.MANUSCRIPT: ManuscriptVideoTask,
    TaskType.ANCHOR: AnchorVideoTask,
    TaskType.IMAGE: SimpleImageTask,
}


def parse_task_state(data: dict) -> BaseTaskState:
    """根据 task_type 字段反序列化为正确的任务子类。

    向后兼容：如果 data 中没有 task_type 字段，默认视为 CREATIVE 类型（D6 决策）。
    """
    task_type_str = data.get("task_type", TaskType.CREATIVE)
    model_cls = _TASK_TYPE_MAP.get(task_type_str, CreativeVideoTask)
    return model_cls(**data)


# ═══════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════


class CreateSimpleTaskRequest(BaseModel):
    """创建简单视频任务的请求体"""

    prompt: str
    mode: str = "t2v"
    duration: int = 5
    video_width: int = 768
    video_height: int = 1152
    seed: Optional[int] = None
    negative_prompt: Optional[str] = None
    system_prompt: str = ""


class CreateCreativeTaskRequest(BaseModel):
    """创建创意长视频任务的请求体"""

    idea: str
    style: str = "电影质感写实风格"
    chaining_mode: str = "keyframes"
    video_width: int = 768
    video_height: int = 1152

    # ── 场景配置 ──
    duration_source: str = "manual"  # "manual" | "prompt"
    scene_count: int = 3
    uniform_duration: bool = True
    scene_durations: List[int] = Field(default_factory=lambda: [5, 5, 5])

    audio_config: Optional[AudioConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None


class CreateManuscriptTaskRequest(BaseModel):
    """创建稿件长视频任务的请求体"""

    manuscript_text: str
    video_width: int = 768
    video_height: int = 1152
    video_duration: int = 10
    audio_config: Optional[AudioConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None


class CreateAnchorTaskRequest(BaseModel):
    """创建数字人口播任务的请求体"""

    anchor_prompt: str = ""
    anchor_reference_image: str = ""
    script_text: str
    video_width: int = 768
    video_height: int = 1344
    audio_config: Optional[AudioConfig] = None
    subtitle_config: Optional[SubtitleConfig] = None


class CreateSimpleImageTaskRequest(BaseModel):
    """创建简单图片任务的请求体"""

    prompt: str
    size: str = "1024x1024"
    negative_prompt: Optional[str] = None
    system_prompt: str = ""


# ═══════════════════════════════════════════════════
# 响应模型
# ═══════════════════════════════════════════════════


class TaskResponse(BaseModel):
    task_id: str
    status: str
    progress: float = 0.0
    message: str = ""
    final_video_url: str = ""


class WSMessage(BaseModel):
    type: str
    task_id: str = ""
    step: str = ""
    status: str = ""
    message: str = ""
    progress: float = 0.0
    data: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════
# 向后兼容别名（Batch B/C 迁移完成后移除）
# ═══════════════════════════════════════════════════

# 旧代码中 TaskState 等同于 CreativeVideoTask（D6）
TaskState = CreativeVideoTask

# 旧请求模型映射到新的创意视频请求
CreateTaskRequest = CreateCreativeTaskRequest
