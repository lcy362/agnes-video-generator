"""core.pipelines.creative — Creative 长视频流水线（v5.0 Batch 4 / 4.2 拆分后的包入口）

CreativeVideoPipeline 由四个步骤 mixin（script/frames/video/audio）+ 本包主类
（pipeline.py）组合而成；对外保留全部原符号（creative_video.py 兼容 re-export）。"""

from .pipeline import CreativeVideoPipeline
from .steps_audio import AudioStepsMixin
from .steps_frames import FramesStepsMixin
from .steps_script import ScriptStepsMixin
from .steps_video import VideoStepsMixin

__all__ = [
    "CreativeVideoPipeline",
    "ScriptStepsMixin",
    "FramesStepsMixin",
    "VideoStepsMixin",
    "AudioStepsMixin",
]
