"""core.image_generator — 向后兼容别名（v2.0 迁移至 core.api.agnes_image）"""

from core.api.agnes_image import AgnesImageAPI, ImageOutput

# 旧类名兼容
ImageGeneratorAgnesAPI = AgnesImageAPI

__all__ = ["AgnesImageAPI", "ImageOutput", "ImageGeneratorAgnesAPI"]
