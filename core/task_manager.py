"""
core/task_manager.py — Agnes Video Generator v2.0 任务状态管理器

泛化支持三种任务类型（Simple / Creative / Manuscript），保持向后兼容。
D6：load() 自动将无 task_type 字段的旧数据识别为 CreativeVideoTask。
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

from core.config import get_working_dir
from core.path_security import UnsafePathError, safe_join
from models.task import (
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptParagraph,
    ManuscriptVideoTask,
    SceneTask,
    StepStatus,
    SubtitleConfig,
    TaskType,
    parse_task_state,
)

logger = logging.getLogger(__name__)


class TaskManager:
    """任务状态持久化管理器。

    负责在文件系统（.working_dir/{dir_name}/task_state.json）中
    创建、加载、更新和列举任务状态。v2.0 支持三种任务类型的多态序列化。
    """

    def __init__(self, task_id: str, dir_name: str = None):
        self.task_id = task_id
        self.dir_name = dir_name or task_id
        # Path-injection hardening: ensure the task directory can never escape the
        # working directory, even if task_id/dir_name come from untrusted input
        # (e.g. a URL path parameter). Unsafe values make the task unresolvable
        # (load() returns None -> callers respond 404) instead of leaking files.
        try:
            self.task_dir = safe_join(get_working_dir(), self.dir_name)
        except UnsafePathError:
            self.task_dir = None
        self._task_file = (
            os.path.join(self.task_dir, "task_state.json") if self.task_dir else None
        )
        self._state: Optional[BaseTaskState] = None

    def _ensure_dir(self):
        if not self.task_dir:
            return
        os.makedirs(self.task_dir, exist_ok=True)

    def create(self, state: BaseTaskState) -> BaseTaskState:
        """创建新任务并持久化。"""
        self._ensure_dir()
        self._state = state
        self._state.task_id = self.task_id
        # v6.1 二期：任务创建时间戳（诊断端点时间窗口匹配兜底用）
        now = datetime.now().isoformat(timespec="seconds")
        if not self._state.created_at:
            self._state.created_at = now
        self._state.updated_at = now
        self._save()
        logger.info(f"[TaskManager] Created task {self.task_id}, type={self._state.task_type}")
        return self._state

    def load(self) -> Optional[BaseTaskState]:
        """加载任务状态。

        v2.0：使用 parse_task_state() 根据 task_type 字段反序列化为正确的子类。
        向后兼容：旧数据无 task_type → 自动视为 CreativeVideoTask（D6）。
        注意：load 是读操作，不调用 _ensure_dir()，避免为不存在的任务创建空目录。
        """
        if not self._task_file or not os.path.exists(self._task_file):
            return None

        try:
            with open(self._task_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # v2.0：通过 parse_task_state 工厂函数反序列化
            # 旧数据没有 task_type，parse_task_state 会默认设为 CREATIVE
            self._state = parse_task_state(data)

            # v3.0 向后兼容：旧数据 audio_config 中含有 subtitle_style（Pydantic v2
            # extra='ignore' 会静默丢弃，所以需从原始 data 中提取），迁移为独立
            # SubtitleConfig。
            if isinstance(self._state, (CreativeVideoTask, ManuscriptVideoTask)):
                state = self._state
                subtitle_cfg = getattr(state, "subtitle_config", None)
                if not subtitle_cfg or subtitle_cfg == SubtitleConfig():
                    # 检查原始数据中 audio_config.subtitle_style
                    raw_audio = data.get("audio_config", {})
                    raw_subtitle_style = raw_audio.get("subtitle_style")
                    if raw_subtitle_style:
                        from models.task import SubtitleStyle as _SS
                        state.subtitle_config = SubtitleConfig(
                            enabled=True,
                            style=_SS(**raw_subtitle_style) if isinstance(raw_subtitle_style, dict) else raw_subtitle_style,
                        )
                        self._save()

            # 对 CreativeVideoTask 确保 scenes 字段正确反序列化
            if isinstance(self._state, CreativeVideoTask):
                # Pydantic v2 已自动处理 List[SceneTask] 反序列化，
                # 这里做一次防御性校验
                self._state.scenes = [
                    SceneTask(**s) if isinstance(s, dict) else s
                    for s in (data.get("scenes") or self._state.scenes)
                ]

            logger.debug(
                f"[TaskManager] Loaded task {self.task_id}: "
                f"type={self._state.task_type}, status={self._state.status}"
            )
            return self._state

        except Exception as e:
            logger.warning(f"[TaskManager] Failed to load task: {e}")
            return None

    def _save(self):
        """持久化当前状态到 JSON 文件。

        使用原子写（唯一临时文件 + os.replace），避免写入中途进程被杀
        （如用户二次 Ctrl+C 触发的 os._exit、OOM、信号）留下截断的损坏 JSON
        导致任务无法断点续传。

        P13: 使用 tempfile.mkstemp 生成唯一临时文件名，避免多写者竞争。
        """
        self._ensure_dir()
        if self._state and self._task_file:
            # v6.1 二期：每次落盘刷新 updated_at（诊断端点时间窗口匹配用）
            self._state.updated_at = datetime.now().isoformat(timespec="seconds")
            task_dir = os.path.dirname(self._task_file)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=task_dir, suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    # 2.4：去掉 indent=2（体积减半、写盘更快）；可读性由
                    # 诊断端点 / 前端展示补偿，原始 JSON 不追求人工可读
                    json.dump(self._state.model_dump(), f, ensure_ascii=False)
                os.replace(tmp_path, self._task_file)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise

    def update_step(self, step_name: str, status: StepStatus):
        """更新某个步骤的状态并持久化。"""
        if self._state:
            setattr(self._state, step_name, status)
            self._save()

    def update_scene(self, scene: SceneTask):
        """更新某个场景的状态并持久化（仅 CreativeVideoTask）。"""
        if self._state and isinstance(self._state, CreativeVideoTask):
            for i, s in enumerate(self._state.scenes):
                if s.index == scene.index:
                    self._state.scenes[i] = scene
                    self._save()
                    return

    def update_state(self, **kwargs):
        """批量更新状态字段并持久化。"""
        if self._state:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    # Convert serialized dict lists back to model instances
                    if key == "scenes" and isinstance(value, list):
                        value = [
                            SceneTask(**s) if isinstance(s, dict) else s
                            for s in value
                        ]
                    elif key == "paragraphs" and isinstance(value, list):
                        value = [
                            ManuscriptParagraph(**p) if isinstance(p, dict) else p
                            for p in value
                        ]
                    setattr(self._state, key, value)
            self._save()

    def get_state(self) -> Optional[BaseTaskState]:
        """返回当前加载的任务状态。"""
        return self._state

    def exists(self) -> bool:
        """检查任务状态文件是否存在。"""
        return bool(self._task_file) and os.path.exists(self._task_file)

    def list_tasks(self) -> list:
        """列举所有任务（包含 task_type 字段，v2.0 增强）。"""
        working_dir = get_working_dir()
        if not os.path.exists(working_dir):
            return []
        tasks = []
        for name in os.listdir(working_dir):
            task_file = os.path.join(working_dir, name, "task_state.json")
            if os.path.exists(task_file):
                try:
                    with open(task_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    tasks.append({
                        "task_id": data.get("task_id", name),
                        "dir_name": name,
                        "task_type": data.get("task_type", TaskType.CREATIVE),
                        "creative_name": data.get("creative_name", ""),
                        "status": data.get("status", "pending"),
                        "chaining_mode": data.get("chaining_mode", "none"),
                    })
                except Exception as e:
                    logger.debug(f"[TaskManager] Failed to load task listing for {name}: {e}")
        tasks.sort(key=lambda t: t.get("dir_name", ""), reverse=True)
        return tasks
