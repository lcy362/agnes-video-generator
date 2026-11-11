"""core.pipelines.ref_slots — 多参考图槽位合并（v8.1）

把所有任务类型的参考图统一为四类槽位，合并规则**唯一出处**：

    character  人物板（身份锁定）
    style      风格板（介质/调色/光线）
    continuity 衔接静帧（上一镜画面）
    user_scene 本段内容图（用户为该段上传）

优先级即列表顺序（数值越小越靠前、越不容易被截断）。所有子类与 API 层共用
``merge_ref_images``，避免「前端静默丢弃 / 路由 422 / API 静默截断」三套行为。

设计约束：
- 纯函数、无状态、无 IO 之外副作用（``os.path.realpath`` 只做字符串归一）；
- 去重：``http(s)`` / ``data:`` 按字符串比较，本地路径按 realpath 比较；
- 编号稳定性：同一角色的图在所有段里序号不变（按槽位顺序，不按上传先后）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

#: 槽位种类常量（用字符串而非 Enum，便于直接落盘进 task.json）
KIND_CHARACTER = "character"
KIND_STYLE = "style"
KIND_CONTINUITY = "continuity"
KIND_USER_SCENE = "user_scene"

#: 优先级：数值越小越靠前，越不容易被截断。
SLOT_PRIORITY: Dict[str, int] = {
    KIND_CHARACTER: 0,
    KIND_STYLE: 1,
    KIND_CONTINUITY: 2,
    KIND_USER_SCENE: 3,
}


@dataclass(frozen=True)
class RefSlot:
    """一类参考图槽位。

    Attributes:
        kind: 槽位种类（见 ``SLOT_PRIORITY``）。
        images: 该槽位内的图片路径 / URL 列表（顺序即 ``<Picture N>`` 顺序）。
        visible: 是否参与 ``<Picture N>`` 编号；False 时整槽被忽略。
        label: 可选的展示名（日志/进度用，默认取 kind）。
    """

    kind: str
    images: List[str] = field(default_factory=list)
    visible: bool = True
    label: str = ""

    def described_as(self) -> str:
        """返回日志用的槽位描述（``人物板[2]`` 之类）。"""
        return f"{self.label or self.kind}[{len(self.images)}]"


def _dedupe_key(path: str) -> str:
    """去重键：远程/内联资源按原字符串，本地路径按 realpath。"""
    value = (path or "").strip()
    if value.startswith(("http://", "https://", "data:")):
        return value
    try:
        return os.path.realpath(value)
    except OSError:  # pragma: no cover - realpath 在极端路径下可能抛错
        return value


def merge_ref_images(
    slots: Sequence[RefSlot],
    limit: int,
) -> Tuple[List[str], List[str]]:
    """按优先级拼接 → 去重 → 截断。

    Args:
        slots: 待合并的槽位（顺序不敏感，函数内部按 ``SLOT_PRIORITY`` 稳定排序）。
        limit: 模型允许的最大张数（来自 ``core.config.get_max_ref_images``）。

    Returns:
        ``(payload_images, dropped)``：
        - ``payload_images``：最终提交给上游的图片列表；
        - ``dropped``：被截断的槽位描述（供日志与进度提示，空列表 = 无截断）。
    """
    ordered = sorted(
        (s for s in slots if s and s.visible and s.images),
        key=lambda s: SLOT_PRIORITY.get(s.kind, 99),
    )

    max_images = max(int(limit), 0)
    seen: set[str] = set()
    images: List[str] = []
    dropped_counts: Dict[str, int] = {}

    for slot in ordered:
        for raw in slot.images:
            if not isinstance(raw, str) or not raw.strip():
                continue
            key = _dedupe_key(raw)
            if key in seen:
                continue
            seen.add(key)
            if len(images) >= max_images:
                dropped_counts[slot.kind] = dropped_counts.get(slot.kind, 0) + 1
                continue
            images.append(raw)

    dropped = [f"{kind} x{count}" for kind, count in dropped_counts.items()]
    return images, dropped


def system_slot_usage(
    character_images: Iterable[str] = (),
    style_images: Iterable[str] = (),
    continuity_images: Iterable[str] = (),
) -> int:
    """返回系统板（人物/风格/衔接）占用的张数，供前端展示剩余额度。"""
    return (
        len([x for x in character_images if x])
        + len([x for x in style_images if x])
        + len([x for x in continuity_images if x])
    )


def remaining_scene_slots(limit: int, system_used: int) -> int:
    """本段内容图剩余额度（下限 0）。"""
    return max(int(limit) - int(system_used), 0)
