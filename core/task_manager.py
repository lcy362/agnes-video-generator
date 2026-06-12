import json
import logging
import os
from typing import Optional

from core.config import get_task_dir
from models.task import TaskState, StepStatus, SceneTask

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.task_dir = get_task_dir(task_id)
        self._task_file = os.path.join(self.task_dir, "task_state.json")
        self._state: Optional[TaskState] = None

    def _ensure_dir(self):
        os.makedirs(self.task_dir, exist_ok=True)

    def create(self, state: TaskState) -> TaskState:
        self._ensure_dir()
        self._state = state
        self._state.task_id = self.task_id
        self._save()
        return self._state

    def load(self) -> Optional[TaskState]:
        self._ensure_dir()
        if os.path.exists(self._task_file):
            try:
                with open(self._task_file, "r") as f:
                    data = json.load(f)
                scenes_raw = data.pop("scenes", [])
                state = TaskState(**data)
                state.scenes = [SceneTask(**s) if isinstance(s, dict) else s for s in scenes_raw]
                self._state = state
                logger.info(f"[TaskManager] Loaded task {self.task_id}: status={self._state.status}")
                return self._state
            except Exception as e:
                logger.warning(f"[TaskManager] Failed to load task: {e}")
        return None

    def _save(self):
        self._ensure_dir()
        if self._state:
            with open(self._task_file, "w") as f:
                json.dump(self._state.model_dump(), f, ensure_ascii=False, indent=2)

    def update_step(self, step_name: str, status: StepStatus):
        if self._state:
            setattr(self._state, step_name, status)
            self._save()

    def update_scene(self, scene: SceneTask):
        if self._state:
            for i, s in enumerate(self._state.scenes):
                if s.index == scene.index:
                    self._state.scenes[i] = scene
                    self._save()
                    return

    def update_state(self, **kwargs):
        if self._state:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)
            self._save()

    def get_state(self) -> Optional[TaskState]:
        return self._state

    def exists(self) -> bool:
        return os.path.exists(self._task_file)

    def list_tasks(self) -> list:
        working_dir = os.path.dirname(self.task_dir)
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
                        "creative_name": data.get("creative_name", ""),
                        "status": data.get("status", "pending"),
                        "chaining_mode": data.get("chaining_mode", "none"),
                    })
                except Exception:
                    pass
        tasks.sort(key=lambda t: t.get("task_id", ""), reverse=True)
        return tasks