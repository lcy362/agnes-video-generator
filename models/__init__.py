"""
models — Agnes Video Generator v2.0 数据模型层

导出所有任务模型、枚举、配置类和请求/响应模型。
"""

from models.task import (
    # 枚举
    StepStatus,
    TaskType,
    VideoMode,
    # 配置类
    AudioConfig,
    SubtitleStyle,
    # 子结构
    ManuscriptParagraph,
    SceneTask,
    # 任务状态模型
    AnchorVideoTask,
    AnyTaskState,
    BaseTaskState,
    CreativeVideoTask,
    ManuscriptVideoTask,
    SimpleImageTask,
    SimpleVideoTask,
    # 工厂函数
    parse_task_state,
    # 请求模型
    CreateAnchorTaskRequest,
    CreateCreativeTaskRequest,
    CreateManuscriptTaskRequest,
    CreateSimpleImageTaskRequest,
    CreateSimpleTaskRequest,
    # 向后兼容别名（Batch B/C 迁移完成后移除）
    CreateTaskRequest,
    TaskState,
    # 响应模型
    TaskResponse,
    WSMessage,
)

__all__ = [
    # 枚举
    "StepStatus",
    "TaskType",
    "VideoMode",
    # 配置
    "AudioConfig",
    "SubtitleStyle",
    # 子结构
    "ManuscriptParagraph",
    "SceneTask",
    # 任务模型
    "AnchorVideoTask",
    "AnyTaskState",
    "BaseTaskState",
    "CreativeVideoTask",
    "ManuscriptVideoTask",
    "SimpleImageTask",
    "SimpleVideoTask",
    # 工厂
    "parse_task_state",
    # 请求
    "CreateAnchorTaskRequest",
    "CreateCreativeTaskRequest",
    "CreateManuscriptTaskRequest",
    "CreateSimpleImageTaskRequest",
    "CreateSimpleTaskRequest",
    # 向后兼容
    "CreateTaskRequest",
    "TaskState",
    # 响应
    "TaskResponse",
    "WSMessage",
]
