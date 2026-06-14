"""core.video_generator — 向后兼容别名（v2.0 迁移至 core.api.agnes_video）"""

from core.api.agnes_video import AgnesVideoAPI, VideoOutput

# 旧类名兼容
VideoGeneratorAgnesAPI = AgnesVideoAPI

__all__ = ["AgnesVideoAPI", "VideoOutput", "VideoGeneratorAgnesAPI"]
