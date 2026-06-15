"""core.pipeline — 向后兼容别名（v2.0 迁移至 core.pipelines.creative_video）"""

from core.pipelines import CreativeVideoPipeline, PipelineShutdown

# 旧类名兼容
VideoPipeline = CreativeVideoPipeline

__all__ = ["CreativeVideoPipeline", "VideoPipeline", "PipelineShutdown"]
