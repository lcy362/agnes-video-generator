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
from typing import List, Literal, Optional, Union

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
    POETRY = "poetry"


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
    # v2.0 字幕对齐：启用 edge_tts cues 精确时间线（False=回退 legacy 启发式）
    use_cue_timeline: bool = True
    # v2.0 路径 B：音频关但字幕开时，仍采集 cues（丢弃音频字节）；False=退回纯估算
    harvest_cues_when_audio_off: bool = True


class AudioConfig(BaseModel):
    """音频配置（TTS 语音，不再包含字幕样式）"""

    enabled: bool = True
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"


class ManualConfig(BaseModel):
    """手动模式配置（v6.0）。

    enabled 时流水线在 pause_points 指定的检查点暂停，等待用户确认产物。
    运行中可随时在自动/手动间切换（POST /api/tasks/{id}/mode）：
    - 切手动：复用 stop 链路挂起，enabled=true + current_checkpoint 落盘；
    - 切自动：清空 pause_points（= 永不暂停），暂停中切自动立即继续跑完。
    """

    enabled: bool = False                 # 是否手动模式
    pause_points: list[str] = []          # 空 = 全部检查点暂停；清空 = 切回自动
    approved_checkpoints: list[str] = []  # 已确认的检查点（恢复执行时跳过暂停）
    modified_artifacts: list[str] = []    # 最近一次回填的产物 id（脏标记）
    current_checkpoint: str = ""          # 当前暂停/待展示的检查点（空 = 无暂停）
    timeout_minutes: int = 0              # 0 = 不超时

    @property
    def is_manual(self) -> bool:
        """手动模式 = enabled 且存在暂停点（pause_points 非空）。"""
        return self.enabled and bool(self.pause_points)


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
    # v4.0 重构：场景视频 prompt（链式/循环模式下用作 i2v/t2v 主提示词）
    scene_prompt: str = ""
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

    # 实时进度（轮询模式：pipeline _emit 时更新，前端通过 GET /api/tasks/{id} 读取）
    current_step: str = ""        # 当前步骤 key，如 "story"、"video_gen"
    current_status: str = ""      # "running" | "completed" | "failed"
    current_progress: float = 0.0  # 0.0 ~ 1.0
    current_message: str = ""     # 人类可读消息

    # ── v5.0 Batch 3（S4）：音频/字幕配置上提为共享字段 ──
    # Creative/Manuscript/Anchor/Poetry 统一继承，消除子类重复声明与
    # multi_scene.py 中的 hasattr 探测。旧 JSON 缺字段时自动取默认值（向后兼容）。
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)

    # ── v6.0：手动模式配置（默认自动模式，向后兼容）──
    manual_config: ManualConfig = Field(default_factory=ManualConfig)

    # ── v6.1 二期：任务时间戳（诊断端点时间窗口匹配兜底用）──
    # 默认值保证旧 task_state.json 加载时向后兼容（无字段 → 自动补齐）。
    created_at: str = ""
    updated_at: str = ""


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
    # v6.2：2.5 系列模型分辨率档位（720P/960P/2K；v2.0 忽略，默认 720P）
    video_size: str = "720P"
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

    # ── v5.0 优化 5：用户上传分镜场景图（按场景顺序存储参考图路径）──
    # 某场景存在用户图时，视频生成以用户图为参考（跳过该场景的 AI 分镜图生成）
    scene_reference_images: List[str] = Field(default_factory=list)

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

    # v4.0 重构：MultiScenePipeline 规范步骤字段
    step_build_scenes: StepStatus = StepStatus.PENDING
    step_reference_images: StepStatus = StepStatus.PENDING
    step_video_generation: StepStatus = StepStatus.PENDING

    # ── v2.0 新增：音频 + 字幕 ──
    step_audio_subtitle: StepStatus = StepStatus.PENDING
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
    # v4.0 重构：通用场景列表（由 _build_scenes 填充，供模板与下游步骤引用）
    scenes: List[SceneTask] = Field(default_factory=list)
    video_duration: int = 10

    combined_audio: str = ""
    combined_subtitle: str = ""
    subtitle_styles_path: str = ""      # LLM 样式 JSON 路径（Phase 2）

    step_split: StepStatus = StepStatus.PENDING
    step_scene_prompts: StepStatus = StepStatus.PENDING
    # v4.0 重构：MultiScenePipeline 规范步骤字段
    step_build_scenes: StepStatus = StepStatus.PENDING
    step_reference_images: StepStatus = StepStatus.PENDING
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

    # 步骤状态
    step_generate_anchor: StepStatus = StepStatus.PENDING
    step_split: StepStatus = StepStatus.PENDING
    step_clip_prompts: StepStatus = StepStatus.PENDING
    step_clip_generation: StepStatus = StepStatus.PENDING
    # v4.0 重构：MultiScenePipeline 规范步骤字段
    step_build_scenes: StepStatus = StepStatus.PENDING
    step_reference_images: StepStatus = StepStatus.PENDING
    step_video_generation: StepStatus = StepStatus.PENDING
    step_audio: StepStatus = StepStatus.PENDING
    step_subtitle: StepStatus = StepStatus.PENDING
    step_concatenation: StepStatus = StepStatus.PENDING

    # 产物
    anchor_image_url: str = ""
    anchor_image_path: str = ""
    paragraphs: List[ManuscriptParagraph] = Field(default_factory=list)
    # v4.0 重构：通用场景列表（单段 clip，由 _build_scenes 填充，供模板与下游步骤引用）
    scenes: List[SceneTask] = Field(default_factory=list)
    combined_audio: str = ""
    combined_subtitle: str = ""
    subtitle_styles_path: str = ""
    final_video_path: str = ""


class PoetryVideoTask(BaseTaskState):
    """诗词视频任务（类型 6 / v4.0 Phase 5）

    用户提供古诗原文，LLM 依据诗歌意境与用户指定的总时长、分镜数
    拆分为若干场景（每段含朗诵文案 + 视频 prompt）。用户可可选提供
    逐段分镜 prompt（覆盖 LLM 生成）。逐段生成视频后拼接，叠加 TTS
    朗诵配音与通用诗歌字幕。
    """

    task_type: Literal[TaskType.POETRY] = TaskType.POETRY

    # 用户输入
    poem_text: str = ""
    # 可选：用户手动输入的分镜 prompt，按场景顺序每项一个；
    # 留空或某场景缺省时由 LLM 根据古诗生成。
    user_scene_prompts: List[str] = Field(default_factory=list)
    # 视觉风格（与创意视频保持一致，传入 LLM 分镜拆分）
    style: str = "电影质感写实风格"

    # 配置（分辨率等参数与创意视频保持一致）
    video_width: int = 768
    video_height: int = 1152
    # 默认总时长（秒），仅作 LLM 拆分节奏参考与「提取」模式均分兜底。
    video_duration: int = 30

    # ── v3.x 场景配置（与创意视频完全一致）──
    # 场景数与时长来源："manual"=用户指定 / "prompt"=从古诗+分镜描述提取
    duration_source: str = "manual"
    # 期望分镜数（与创意视频一致：默认 3，范围 1-30；提取模式忽略此值）
    scene_count: int = 3
    # 各场景时长是否统一（统一=每场景 uniform_duration 秒；独立=scene_durations 逐场景）
    uniform_duration: bool = True
    scene_durations: List[int] = Field(default_factory=lambda: [5, 5, 5])

    # v4.0 重构：MultiScenePipeline 规范步骤字段
    scenes: List[SceneTask] = Field(default_factory=list)
    step_build_scenes: StepStatus = StepStatus.PENDING
    step_reference_images: StepStatus = StepStatus.PENDING
    step_video_generation: StepStatus = StepStatus.PENDING
    step_audio: StepStatus = StepStatus.PENDING
    step_subtitle: StepStatus = StepStatus.PENDING
    step_concatenation: StepStatus = StepStatus.PENDING

    # 产物
    combined_audio: str = ""
    combined_subtitle: str = ""
    subtitle_styles_path: str = ""


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

AnyTaskState = Union[SimpleVideoTask, CreativeVideoTask, ManuscriptVideoTask, AnchorVideoTask, PoetryVideoTask, SimpleImageTask]

# 用于 TaskManager.load()：根据 task_type 字段选择正确的模型类
_TASK_TYPE_MAP: dict[str, type[BaseTaskState]] = {
    TaskType.SIMPLE: SimpleVideoTask,
    TaskType.CREATIVE: CreativeVideoTask,
    TaskType.MANUSCRIPT: ManuscriptVideoTask,
    TaskType.ANCHOR: AnchorVideoTask,
    TaskType.POETRY: PoetryVideoTask,
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
