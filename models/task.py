from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SceneTask(BaseModel):
    index: int
    status: StepStatus = StepStatus.PENDING
    end_frame_prompt: str = ""
    end_frame_file: str = ""
    video_id: str = ""
    video_status: StepStatus = StepStatus.PENDING
    video_file: str = ""


class TaskState(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    creative_name: str = ""
    status: StepStatus = StepStatus.PENDING

    idea: str = ""
    user_requirement: str = ""
    style: str = ""
    chaining_mode: str = "none"
    video_width: int = 1152
    video_height: int = 768
    video_duration: int = 5

    reference_image: str = ""
    end_frame_images: List[str] = Field(default_factory=list)
    use_custom_end_frames: bool = False
    generate_end_frames_from_ref: bool = False

    step_story: StepStatus = StepStatus.PENDING
    story_file: str = ""

    step_character_ref: StepStatus = StepStatus.PENDING
    character_ref_prompt: str = ""
    character_ref_file: str = ""

    step_script: StepStatus = StepStatus.PENDING
    script_file: str = ""
    scene_count: int = 0

    step_end_frame_prompts: StepStatus = StepStatus.PENDING
    end_frame_prompts_file: str = ""

    step_image_analysis: StepStatus = StepStatus.PENDING
    image_analysis_file: str = ""

    step_end_frame_generation: StepStatus = StepStatus.PENDING
    pregenerated_end_frames: dict = Field(default_factory=dict)

    scenes: List[SceneTask] = Field(default_factory=list)

    step_video_generation: StepStatus = StepStatus.PENDING

    step_concatenation: StepStatus = StepStatus.PENDING
    final_video_file: str = ""

    def all_scenes_completed(self) -> bool:
        return all(s.status == StepStatus.COMPLETED for s in self.scenes)

    def all_videos_completed(self) -> bool:
        return all(s.video_status == StepStatus.COMPLETED for s in self.scenes)

    def get_pending_scenes(self) -> List[SceneTask]:
        return [s for s in self.scenes if s.status != StepStatus.COMPLETED]

    def get_pending_videos(self) -> List[SceneTask]:
        return [s for s in self.scenes if s.video_status != StepStatus.COMPLETED]


class CreateTaskRequest(BaseModel):
    idea: str
    user_requirement: str = "3个场景，每个场景10秒，电影质感"
    style: str = "电影质感写实风格"
    chaining_mode: str = "keyframes"
    video_width: int = 768
    video_height: int = 1152
    video_duration: int = 5


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