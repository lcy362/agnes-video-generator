"""
core/task_manager.py — Agnes Video Generator v2.0 任务状态管理器

泛化支持三种任务类型（Simple / Creative / Manuscript），保持向后兼容。
D6：load() 自动将无 task_type 字段的旧数据识别为 CreativeVideoTask。
"""

import json
import logging
import os
from typing import Optional

from core.config import get_working_dir
from models.task import (
    AnyTaskState,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptParagraph,
    SceneTask,
    StepStatus,
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
        self.task_dir = os.path.join(get_working_dir(), self.dir_name)
        self._task_file = os.path.join(self.task_dir, "task_state.json")
        self._state: Optional[BaseTaskState] = None

    def _ensure_dir(self):
        os.makedirs(self.task_dir, exist_ok=True)

    def create(self, state: BaseTaskState) -> BaseTaskState:
        """创建新任务并持久化。"""
        self._ensure_dir()
        self._state = state
        self._state.task_id = self.task_id
        self._save()
        logger.info(f"[TaskManager] Created task {self.task_id}, type={self._state.task_type}")
        return self._state

    def load(self) -> Optional[BaseTaskState]:
        """加载任务状态。

        v2.0：使用 parse_task_state() 根据 task_type 字段反序列化为正确的子类。
        向后兼容：旧数据无 task_type → 自动视为 CreativeVideoTask（D6）。
        """
        self._ensure_dir()
        if not os.path.exists(self._task_file):
            return None

        try:
            with open(self._task_file, "r") as f:
                data = json.load(f)

            # v2.0：通过 parse_task_state 工厂函数反序列化
            # 旧数据没有 task_type，parse_task_state 会默认设为 CREATIVE
            self._state = parse_task_state(data)

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
        """持久化当前状态到 JSON 文件。"""
        self._ensure_dir()
        if self._state:
            with open(self._task_file, "w") as f:
                json.dump(self._state.model_dump(), f, ensure_ascii=False, indent=2)

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
        return os.path.exists(self._task_file)

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
                    with open(task_file, "r") as f:
                        data = json.load(f)
                    tasks.append({
                        "task_id": data.get("task_id", name),
                        "dir_name": name,
                        "task_type": data.get("task_type", TaskType.CREATIVE),
                        "creative_name": data.get("creative_name", ""),
                        "status": data.get("status", "pending"),
                        "chaining_mode": data.get("chaining_mode", "none"),
                    })
                except Exception:
                    pass
        tasks.sort(key=lambda t: t.get("task_id", ""), reverse=True)
        return tasks
