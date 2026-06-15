"""core.compositor — 视频拼接层"""

from core.compositor.concatenator import VideoConcatenator
from core.compositor.processor import VideoProcessor

__all__ = ["VideoConcatenator", "VideoProcessor"]
