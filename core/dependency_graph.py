"""
core/dependency_graph.py — 产物依赖图（v6.0 手动模式）

独立、可复用的「修改产物 → 影响范围」决策模块，作为手动模式修改产物时的
决策依据（PRD §4.5 / implementation_plan §5.2）：

- PRODUCT_EDGES: 产物（类型/字段级）→ 受影响的下游产物类型集合
- PARAM_EDGES:   任务参数 → 受影响的下游产物类型集合
- compute_impact(): 核心决策：给定修改集合 → 返回 ImpactPlan{affected, retained, steps_to_reset}
- to_checkpoint_edges(): 生成检查点级依赖边（供前端渲染依赖图 / 高亮）

设计原则（PRD §4.5）：
1. 纯声明式 + 无 I/O：依赖规则全部是数据（边表），不碰文件系统 / state，可单测、可复用；
2. 字段级粒度：同一产物内不同字段（scene_prompt vs narration_text）影响不同下游；
3. scope 通配：scene:{i}/video.mp4 支持场景索引模板；
4. 与 core/artifacts.py 解耦：artifacts 负责产物枚举 + 物理删除计划（CascadePlan），
   本模块负责决策依据；impact 端点先调 compute_impact 得 affected，
   再逐产物调 artifacts.get_cascade_plan 拿物理清理计划。

产物 ID 格式与 artifacts.py 对齐: {task_type}:{type} 或 {task_type}:{type}:{index}
例如: creative:script, creative:end_frame:2, creative:video:1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from models.task import BaseTaskState, CreativeVideoTask, PoetryVideoTask, TaskType

logger = logging.getLogger(__name__)

# 场景级产物索引占位
_ANY = "{i}"


# ═══════════════════════════════════════════════════════════════
# 产物类型常量（与 artifacts.py 产物定义 type 对齐）
# ═══════════════════════════════════════════════════════════════

T_STORY = "story"
T_SCRIPT = "script"
T_END_FRAME_PROMPTS = "end_frame_prompts"
T_CHARACTER_REF = "character_ref"
T_END_FRAME = "end_frame"
T_VIDEO = "video"
T_AUDIO = "audio"
T_SUBTITLE = "subtitle"
T_FINAL_VIDEO = "final_video"
T_SCENE_PROMPTS = "scene_prompts"
T_ANCHOR_IMAGE = "anchor_image"
T_CLIP_PROMPTS = "clip_prompts"
T_CLIP = "clip"


# ═══════════════════════════════════════════════════════════════
# 产物级依赖边（node → downstream nodes）
# ═══════════════════════════════════════════════════════════════
#
# 规则：key 为「被修改的产物」，value 为「受影响的下游产物」集合。
# key 支持字段级声明 "script:scene_prompt"；value 支持场景级通配 "video:{i}"。
# 注意：受影响集合不含自身（自身由调用方显式声明为 modified）。
# 规则源自 PRD §4.5「具体规则」表。

_PRODUCT_EDGES: dict[str, dict[str, set[str]]] = {
    TaskType.CREATIVE.value: {
        # 改 scene_prompt / end_frame_prompt → ref 图(i2i 尾帧) / videos / final（audio/subtitle 保留）
        "script:scene_prompt": {T_END_FRAME, T_VIDEO, T_FINAL_VIDEO},
        "script:end_frame_prompt": {T_END_FRAME, T_VIDEO, T_FINAL_VIDEO},
        # 改 narration_text → audio / subtitle / final（ref 图 / videos 保留）
        "script:narration_text": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        # 改 story → 下游全部重建（角色/分镜/视频/音频/字幕/成片）
        T_STORY: {T_CHARACTER_REF, T_SCRIPT, T_END_FRAME, T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        # 改 character_reference.png → videos / final
        T_CHARACTER_REF: {T_END_FRAME, T_VIDEO, T_FINAL_VIDEO},
        # 改 end_frame_prompts.json → 对应尾帧图 / videos / final
        T_END_FRAME_PROMPTS: {T_END_FRAME, T_VIDEO, T_FINAL_VIDEO},
        # 改场景尾帧图 scene:{i}/end_frame.png → 该场景视频及后续（视觉链）/ final
        f"{T_END_FRAME}:{_ANY}": {T_VIDEO, T_FINAL_VIDEO},
        # 改场景视频 scene:{i}/video.mp4 → audio / subtitle / final
        f"{T_VIDEO}:{_ANY}": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        # 改音频 → subtitle / final
        T_AUDIO: {T_SUBTITLE, T_FINAL_VIDEO},
        # 改字幕 → final
        T_SUBTITLE: {T_FINAL_VIDEO},
    },
    TaskType.MANUSCRIPT.value: {
        # 稿件无参考图；改场景 prompt → videos / final
        T_SCENE_PROMPTS: {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        f"{T_VIDEO}:{_ANY}": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        T_AUDIO: {T_SUBTITLE, T_FINAL_VIDEO},
        T_SUBTITLE: {T_FINAL_VIDEO},
    },
    TaskType.ANCHOR.value: {
        # 改主播形象 → 循环视频 / final
        T_ANCHOR_IMAGE: {T_CLIP, T_VIDEO, T_FINAL_VIDEO},
        # 改循环 prompt → 视频 / final
        T_CLIP_PROMPTS: {T_CLIP, T_FINAL_VIDEO},
        T_CLIP: {T_FINAL_VIDEO},
        T_AUDIO: {T_SUBTITLE, T_FINAL_VIDEO},
        T_SUBTITLE: {T_FINAL_VIDEO},
    },
    TaskType.POETRY.value: {
        # 诗词场景 prompt 来自诗句拆分；改任一场景 → 该场景视频 / 全局成片
        T_SCRIPT: {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        f"{T_VIDEO}:{_ANY}": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        T_AUDIO: {T_SUBTITLE, T_FINAL_VIDEO},
        T_SUBTITLE: {T_FINAL_VIDEO},
    },
}


# ═══════════════════════════════════════════════════════════════
# 任务参数级依赖边（param → 受影响产物）
# ═══════════════════════════════════════════════════════════════

_PARAM_EDGES: dict[str, dict[str, set[str]]] = {
    TaskType.CREATIVE.value: {
        "resolution": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "video_width": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "video_height": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "audio_voice": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "subtitle_font": {T_SUBTITLE, T_FINAL_VIDEO},
        "subtitle_color": {T_SUBTITLE, T_FINAL_VIDEO},
        "subtitle_fontsize": {T_SUBTITLE, T_FINAL_VIDEO},
        "duration": {T_END_FRAME, T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "scene_count": {T_SCRIPT, T_END_FRAME, T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
    },
    TaskType.MANUSCRIPT.value: {
        "resolution": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "video_width": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "video_height": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "audio_voice": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "subtitle_font": {T_SUBTITLE, T_FINAL_VIDEO},
    },
    TaskType.ANCHOR.value: {
        "resolution": {T_CLIP, T_FINAL_VIDEO},
        "video_width": {T_CLIP, T_FINAL_VIDEO},
        "video_height": {T_CLIP, T_FINAL_VIDEO},
        "audio_voice": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
    },
    TaskType.POETRY.value: {
        "resolution": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "video_width": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "video_height": {T_VIDEO, T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
        "audio_voice": {T_AUDIO, T_SUBTITLE, T_FINAL_VIDEO},
    },
}


# ═══════════════════════════════════════════════════════════════
# 检查点级依赖（供前端渲染依赖图）
# ═══════════════════════════════════════════════════════════════

# 产物 type → 检查点名（与 core/pipelines _STEP_TO_CHECKPOINT 对齐）
# creative：细粒度检查点（v6.1，每个有产物的环节独立暂停）
_TYPE_TO_CHECKPOINT_FINE: dict[str, str] = {
    T_STORY: "story",
    T_SCRIPT: "script",
    T_END_FRAME_PROMPTS: "end_frame_prompts",
    T_CHARACTER_REF: "character_ref",
    T_END_FRAME: "end_frame_gen",
    T_VIDEO: "videos",
    T_AUDIO: "audio",
    T_SUBTITLE: "subtitle",
    T_FINAL_VIDEO: "final",
}
# 非 creative：粗粒度合并检查点
_TYPE_TO_CHECKPOINT_COARSE: dict[str, str] = {
    T_STORY: "scenes",
    T_SCRIPT: "scenes",
    T_END_FRAME_PROMPTS: "scenes",
    T_CHARACTER_REF: "references",
    T_END_FRAME: "references",
    T_VIDEO: "videos",
    T_AUDIO: "audio",
    T_SUBTITLE: "subtitle",
    T_FINAL_VIDEO: "final",
    T_SCENE_PROMPTS: "scenes",
    T_ANCHOR_IMAGE: "references",
    T_CLIP_PROMPTS: "scenes",
    T_CLIP: "videos",
}

# 检查点依赖链（PRD §4.3 简化版，供前端展示）
_CHECKPOINT_EDGES: dict[str, set[str]] = {
    "scenes": {"references", "videos", "audio", "subtitle", "final"},
    "references": {"videos", "final"},
    "videos": {"audio", "subtitle", "final"},
    "audio": {"subtitle", "final"},
    "subtitle": {"final"},
    "final": set(),
}
# creative 细粒度依赖链（v6.1）
_CHECKPOINT_EDGES_FINE: dict[str, set[str]] = {
    "image_analysis": {"story", "script", "character_ref", "end_frame_prompts",
                       "end_frame_gen", "videos", "audio", "subtitle", "final"},
    "story": {"script", "character_ref", "end_frame_prompts", "end_frame_gen",
              "videos", "audio", "subtitle", "final"},
    "script": {"character_ref", "end_frame_prompts", "end_frame_gen",
               "videos", "audio", "subtitle", "final"},
    "character_ref": {"end_frame_prompts", "end_frame_gen", "videos", "final"},
    "end_frame_prompts": {"end_frame_gen", "videos", "final"},
    "end_frame_gen": {"videos", "final"},
    "videos": {"audio", "subtitle", "final"},
    "audio": {"subtitle", "final"},
    "subtitle": {"final"},
    "final": set(),
}

_ALL_CHECKPOINTS = ["scenes", "references", "videos", "audio", "subtitle", "final"]
_ALL_CHECKPOINTS_FINE = [
    "image_analysis", "story", "script", "character_ref",
    "end_frame_prompts", "end_frame_gen", "videos", "audio", "subtitle", "final",
]


# ═══════════════════════════════════════════════════════════════
# 影响计划
# ═══════════════════════════════════════════════════════════════

@dataclass
class ImpactPlan:
    """修改产物的影响计划（PRD §4.5）。

    - affected: 将删除重跑的产物 id 集合（含自身 modified）
    - retained: 保留的产物 id 集合（不受影响）
    - steps_to_reset: 需重置的 step 字段（由 affected 推导）
    - affected_checkpoints: 受影响检查点（供前端展示）
    """

    affected: list[str] = field(default_factory=list)
    retained: list[str] = field(default_factory=list)
    steps_to_reset: list[str] = field(default_factory=list)
    affected_checkpoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "affected": self.affected,
            "retained": self.retained,
            "steps_to_reset": self.steps_to_reset,
            "affected_checkpoints": self.affected_checkpoints,
        }


# ═══════════════════════════════════════════════════════════════
# 核心决策
# ═══════════════════════════════════════════════════════════════

class DependencyGraph:
    """产物依赖图：改了什么 → 会影响什么。"""

    def __init__(self, task_type: TaskType):
        self.task_type = task_type
        self._type_key = task_type.value
        self.product_edges = _PRODUCT_EDGES.get(self._type_key, {})
        self.param_edges = _PARAM_EDGES.get(self._type_key, {})

    # ── 主入口 ──

    def compute_impact(
        self,
        state: BaseTaskState,
        modified_artifact_ids: list[str],
        param_updates: Optional[dict] = None,
    ) -> ImpactPlan:
        """核心决策：给定修改集合 → 返回影响计划。

        Args:
            state: 任务状态（含 scenes/paragraphs 数量，用于展开场景级产物）。
            modified_artifact_ids: 被修改的产物 id 列表（如 ["creative:script"]）
                - 可含字段级 id: "creative:script:scene_prompt"
                - 可含场景级 id: "creative:video:2"（仅影响该场景）或
                  "creative:video"（影响全部场景视频）
            param_updates: 任务参数修改（如 {"resolution": "768x1152"}）
        """
        # 1. 展开所有产物 id（含场景级）
        all_ids = self._expand_all_artifact_ids(state)

        # 2. 解析 modified → 受影响产物 id 集合（含场景级传播）
        affected_ids: set[str] = set()

        for mid in modified_artifact_ids:
            base_type, field, index = self._parse_artifact_id(mid, state)
            if base_type is None:
                continue
            # 未知产物类型（不在任何边表中）→ 忽略
            if not self._known_type(base_type):
                continue
            # 自身加入 affected
            if index is not None:
                affected_ids.add(self._normalize_id(base_type, index))
            elif self._is_scoped(base_type, state):
                affected_ids.update(self._expand_type(base_type, state))
            else:
                affected_ids.add(self._normalize_id(base_type, None))
            # 下游（字段级精确命中 / 产物级并集）
            for t in self._downstream(base_type, field, index):
                if index is not None and self._is_scoped(t, state):
                    # 场景级修改 → 同类型下游只影响该场景
                    affected_ids.add(self._normalize_id(t, index))
                else:
                    affected_ids.update(self._expand_type(t, state))

        # 3. 参数修改 → 受影响产物类型（无场景关联，全部展开）
        if param_updates:
            for param, _val in param_updates.items():
                for t in self.param_edges.get(param, set()):
                    affected_ids.update(self._expand_type(t, state))

        # 5. 计算 retained 与 steps_to_reset
        retained_ids = [aid for aid in all_ids if aid not in affected_ids]
        steps = self._steps_for_affected(affected_ids, state)

        # 6. 检查点维度
        cps = self._checkpoints_for_affected(affected_ids)

        plan = ImpactPlan(
            affected=sorted(affected_ids),
            retained=retained_ids,
            steps_to_reset=steps,
            affected_checkpoints=cps,
        )
        logger.info(
            "[DependencyGraph] %s impact: affected=%d retained=%d steps=%s",
            self.task_type.value, len(plan.affected), len(plan.retained), plan.steps_to_reset,
        )
        return plan

    # ── 下游解析 ──

    def _downstream(self, base_type: str, field: Optional[str], index: Optional[int]) -> set[str]:
        """返回修改某个产物后受影响的下游产物类型集合。

        匹配优先级：
        1. 字段级 id（如 "script:scene_prompt"）→ 仅命中该字段的边；
        2. 产物级 id（如 "script"）→ 命中该类型全部字段级边 + 类型级边；
        3. 场景级 id（如 "video:2" / "video"）→ 命中类型级或场景级通配边。
        """
        result: set[str] = set()

        # 1. 字段级精确命中
        if field:
            edge = self.product_edges.get(f"{base_type}:{field}")
            if edge:
                result |= edge
            return result

        # 2. 产物级：并集该类型全部字段级边
        for key, downstream in self.product_edges.items():
            if key.startswith(base_type + ":"):
                result |= downstream

        # 3. 类型级边 + 场景级通配边
        result |= self.product_edges.get(base_type, set())
        result |= self.product_edges.get(f"{base_type}:{_ANY}", set())
        return result

    def _expand_type(self, base_type: str, state: BaseTaskState) -> list[str]:
        """将产物类型展开为全部 id（任务级 1 个；场景级每个场景 1 个）。"""
        count = self._scope_count(state)
        if self._is_scoped(base_type, state):
            return [f"{self.task_type.value}:{base_type}:{i}" for i in range(count)]
        return [f"{self.task_type.value}:{base_type}"]

    def _expand_all_artifact_ids(self, state: BaseTaskState) -> list[str]:
        """枚举该任务全部可能的产物 id。"""
        # 从 PRODUCT_EDGES 的 value 收集所有下游类型 + 自身可修改类型
        types: set[str] = set()
        for key, downstream in self.product_edges.items():
            base = key.split(":")[0]
            types.add(base)
            for d in downstream:
                types.add(d.split(":")[0])
        # 排除 {i} 模板
        types = {t for t in types if t != _ANY}

        all_ids: list[str] = []
        for t in sorted(types):
            all_ids.extend(self._expand_type(t, state))
        return all_ids

    def _parse_artifact_id(
        self, artifact_id: str, state: BaseTaskState
    ) -> tuple[Optional[str], Optional[str], Optional[int]]:
        """解析产物 id → (base_type, field, index)。

        支持格式:
            "creative:script"                      → ("script", None, None)
            "creative:video:2"                     → ("video", None, 2)
            "creative:script:scene_prompt"         → ("script", "scene_prompt", None)
            "creative:end_frame:all"               → ("end_frame", None, None)
        """
        parts = artifact_id.split(":")
        if len(parts) < 2 or parts[0] != self.task_type.value:
            return None, None, None
        base_type = parts[1]
        if len(parts) >= 3 and parts[2].isdigit():
            return base_type, None, int(parts[2])
        if len(parts) >= 3:
            return base_type, parts[2], None
        return base_type, None, None

    def _normalize_id(self, base_type: str, index: Optional[int]) -> str:
        if index is not None:
            return f"{self.task_type.value}:{base_type}:{index}"
        return f"{self.task_type.value}:{base_type}"

    def _is_scoped(self, base_type: str, state: BaseTaskState) -> bool:
        """判断产物是否为场景级。"""
        if base_type == T_VIDEO and self.task_type in (TaskType.CREATIVE, TaskType.MANUSCRIPT, TaskType.POETRY):
            return True
        if base_type == T_END_FRAME and self.task_type == TaskType.CREATIVE:
            return True
        # poetry：audio/subtitle 为逐场景产物（scene_{i}/narration.mp3、scene_{i}/subtitle.srt）
        if base_type in (T_AUDIO, T_SUBTITLE) and self.task_type == TaskType.POETRY:
            return True
        return False

    def _known_type(self, base_type: str) -> bool:
        """判断产物类型是否在依赖图中已知（可修改）。"""
        for key, downstream in self.product_edges.items():
            if key == base_type or key.startswith(base_type + ":") or key == f"{base_type}:{_ANY}":
                return True
            for d in downstream:
                if d == base_type:
                    return True
        return False

    def _scope_count(self, state: BaseTaskState) -> int:
        if isinstance(state, CreativeVideoTask):
            return len(state.scenes)
        if isinstance(state, PoetryVideoTask):
            return len(state.scenes)
        # Manuscript / Anchor 用 paragraphs；Anchor 单段
        return len(getattr(state, "paragraphs", []) or [])

    # ── 步骤映射 ──

    def _steps_for_affected(self, affected_ids: set[str], state: BaseTaskState) -> list[str]:
        """由受影响产物 id → 需重置的 step 字段（按任务类型）。"""
        # 产物类型 → step 字段映射（与 artifacts.py 步骤序列对齐）
        type_to_step = {
            T_STORY: "step_story",
            T_SCRIPT: "step_script",
            T_END_FRAME_PROMPTS: "step_end_frame_prompts",
            T_CHARACTER_REF: "step_character_ref",
            T_END_FRAME: "step_end_frame_generation",
            T_VIDEO: "step_video_generation",
            T_AUDIO: "step_audio",
            T_SUBTITLE: "step_subtitle",
            T_FINAL_VIDEO: "step_concatenation",
            T_SCENE_PROMPTS: "step_scene_prompts",
            T_ANCHOR_IMAGE: "step_generate_anchor",
            T_CLIP_PROMPTS: "step_clip_generation",
            T_CLIP: "step_clip_generation",
        }
        if self.task_type == TaskType.CREATIVE:
            type_to_step[T_STORY] = "step_story"
        elif self.task_type == TaskType.MANUSCRIPT:
            type_to_step[T_SCENE_PROMPTS] = "step_scene_prompts"
            type_to_step[T_VIDEO] = "step_video_generation"

        steps: set[str] = set()
        for aid in affected_ids:
            parts = aid.split(":")
            if len(parts) < 2:
                continue
            base = parts[1]
            step = type_to_step.get(base)
            if step:
                steps.add(step)
        # 保持步骤顺序（按 task 的步骤序列）
        ordered = self._order_steps(steps, state)
        return ordered

    def _order_steps(self, steps: set[str], state: BaseTaskState) -> list[str]:
        """将步骤按流水线执行顺序排序。"""
        # 简化：按依赖链顺序
        order = [
            "step_scene_config", "step_image_analysis", "step_story", "step_character_ref",
            "step_script", "step_end_frame_prompts", "step_end_frame_generation",
            "step_video_generation", "step_audio", "step_subtitle", "step_concatenation",
        ]
        return [s for s in order if s in steps] + sorted(steps - set(order))

    def _checkpoints_for_affected(self, affected_ids: set[str]) -> list[str]:
        """受影响产物 → 检查点名（去重保序，按任务类型）。"""
        mapping = (
            _TYPE_TO_CHECKPOINT_FINE if self.task_type == TaskType.CREATIVE else _TYPE_TO_CHECKPOINT_COARSE
        )
        order = _ALL_CHECKPOINTS_FINE if self.task_type == TaskType.CREATIVE else _ALL_CHECKPOINTS
        cps: set[str] = set()
        for aid in affected_ids:
            parts = aid.split(":")
            if len(parts) < 2:
                continue
            cp = mapping.get(parts[1])
            if cp:
                cps.add(cp)
        return [c for c in order if c in cps]


# ═══════════════════════════════════════════════════════════════
# 便捷工厂
# ═══════════════════════════════════════════════════════════════

def get_dependency_graph(task_type) -> DependencyGraph:
    """获取任务类型对应的依赖图实例（可缓存）。"""
    return DependencyGraph(task_type)


def checkpoint_edges(task_type: Optional[TaskType] = None) -> dict[str, list[str]]:
    """返回检查点级依赖边（供前端渲染依赖图）。

    Args:
        task_type: 任务类型；creative 返回细粒度依赖链，其余返回粗粒度。
    """
    edges = _CHECKPOINT_EDGES_FINE if task_type == TaskType.CREATIVE else _CHECKPOINT_EDGES
    return {k: sorted(v) for k, v in edges.items()}
