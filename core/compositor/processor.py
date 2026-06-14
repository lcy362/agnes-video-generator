"""core.compositor.processor — 视频处理器

提供缩放、帧提取、静音音频生成、尾帧冻结等工具方法。
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


class VideoProcessor:
    """视频处理工具集（缩放、帧提取、静音生成、尾帧冻结）。"""

    @staticmethod
    def resize_video(input_path: str, width: int, height: int, output_path: str) -> str:
        """缩放视频到指定分辨率。"""
        logger.info(f"[Compositor] Resizing: {input_path} → {width}x{height}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "fast",
            output_path,
        ], capture_output=True, check=True, timeout=120)

        return output_path

    @staticmethod
    def extract_last_frame(video_path: str, output_path: str) -> str:
        """提取视频最后一帧为图片。"""
        logger.info(f"[Compositor] Extracting last frame: {video_path} → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess
        subprocess.run([
            "ffmpeg", "-y",
            "-sseof", "-1",
            "-i", video_path,
            "-frames:v", "1",
            "-update", "1",
            output_path,
        ], capture_output=True, check=True, timeout=30)

        return output_path

    @staticmethod
    def generate_silent_audio(duration_sec: float, output_path: str) -> str:
        """生成指定时长的静音音频文件。"""
        logger.info(f"[Compositor] Generating silent audio: {duration_sec:.1f}s → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(duration_sec),
            "-c:a", "libmp3lame", "-q:a", "9",
            output_path,
        ], capture_output=True, check=True, timeout=30)

        return output_path

    @staticmethod
    def freeze_last_frame(video_path: str, freeze_duration: float, output_path: str) -> str:
        """将视频最后一帧冻结指定时长，输出新视频。

        用于视频-音频对齐：当视频时长不足时，冻结尾帧补齐。

        Args:
            video_path: 输入视频
            freeze_duration: 冻结时长（秒）
            output_path: 输出视频路径
        """
        logger.info(f"[Compositor] Freezing last frame: {freeze_duration:.1f}s → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess

        # 1. 提取最后一帧
        frame_path = output_path + "_frame.jpg"
        subprocess.run([
            "ffmpeg", "-y",
            "-sseof", "-1",
            "-i", video_path,
            "-frames:v", "1",
            "-update", "1",
            frame_path,
        ], capture_output=True, check=True, timeout=30)

        # 2. 从最后一帧生成冻结视频
        freeze_video_path = output_path + "_freeze.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", frame_path,
            "-i", video_path,  # 复用原视频参数
            "-filter_complex",
            f"[0:v]scale=iw:ih,trim=duration={freeze_duration},setpts=PTS-STARTPTS[freeze];"
            f"[1:v][freeze]concat=n=2:v=1:a=0[out]",
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast",
            "-t", str(freeze_duration),
            freeze_video_path,
        ], capture_output=True, check=False, timeout=60)

        # 如果复杂滤镜失败，回退到简单方案
        if not os.path.exists(freeze_video_path) or os.path.getsize(freeze_video_path) == 0:
            from moviepy import VideoFileClip, concatenate_videoclips, ImageClip

            clip = VideoFileClip(video_path)
            last_frame = clip.to_ImageClip(duration=freeze_duration)
            final = concatenate_videoclips([clip, last_frame], method="compose")
            final.write_videofile(output_path, logger=None)
            clip.close()
            final.close()
        else:
            import shutil
            shutil.move(freeze_video_path, output_path)

        # 清理临时文件
        for f in [frame_path, freeze_video_path]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

        return output_path
