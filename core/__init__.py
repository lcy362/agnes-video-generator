"""core — Agnes Video Generator v2.0 核心模块

导出所有子包的核心类和工具函数。
"""

from core.api import AgnesChatAPI, AgnesImageAPI, AgnesVideoAPI
from core.audio import EdgeTTSEngine, SilentTTSEngine, SubtitleGenerator
from core.compositor import VideoConcatenator, VideoProcessor
from core.pipelines import (
    BasePipeline,
    CreativeVideoPipeline,
    ManuscriptVideoPipeline,
    PipelineShutdown,
    SimpleVideoPipeline,
)

__all__ = [
    # API 层
    "AgnesImageAPI",
    "AgnesVideoAPI",
    "AgnesChatAPI",
    # 音频层
    "EdgeTTSEngine",
    "SilentTTSEngine",
    "SubtitleGenerator",
    # 拼接层
    "VideoConcatenator",
    "VideoProcessor",
    # 流水线层
    "BasePipeline",
    "PipelineShutdown",
    "SimpleVideoPipeline",
    "CreativeVideoPipeline",
    "ManuscriptVideoPipeline",
]
