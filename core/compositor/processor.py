"""core.compositor.processor — 视频处理器

提供缩放、帧提取、静音音频生成、尾帧冻结等工具方法。
"""

import logging
import os

from core.compositor.ffmpeg_tool import resolve_binary

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
            resolve_binary("ffmpeg"), "-y", "-i", input_path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "fast",
            output_path,
        ], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120)

        return output_path

    @staticmethod
    def extract_last_frame(video_path: str, output_path: str) -> str:
        """提取视频最后一帧为图片。"""
        logger.info(f"[Compositor] Extracting last frame: {video_path} → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess
        subprocess.run([
            resolve_binary("ffmpeg"), "-y",
            "-sseof", "-1",
            "-i", video_path,
            "-frames:v", "1",
            "-update", "1",
            output_path,
        ], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)

        return output_path

    @staticmethod
    def generate_silent_audio(duration_sec: float, output_path: str) -> str:
        """生成指定时长的静音音频文件。"""
        logger.info(f"[Compositor] Generating silent audio: {duration_sec:.1f}s → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess
        subprocess.run([
            resolve_binary("ffmpeg"), "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration_sec),
            "-c:a", "libmp3lame", "-q:a", "4",
            output_path,
        ], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)

        return output_path

    @staticmethod
    def freeze_last_frame(video_path: str, freeze_duration: float, output_path: str) -> str:
        """将视频最后一帧冻结指定时长，输出新视频。

        用于视频-音频对齐：当视频时长不足时，冻结尾帧补齐。
        输出时长 = 原视频时长 + freeze_duration。

        Args:
            video_path: 输入视频
            freeze_duration: 冻结时长（秒）
            output_path: 输出视频路径
        """
        logger.info(f"[Compositor] Freezing last frame: {freeze_duration:.1f}s → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        import subprocess

        # 方案 1（首选）：ffmpeg tpad 滤镜克隆尾帧。
        # 单输入单滤镜，输出 = 原视频 + freeze_duration 的尾帧定格，且保留音频轨。
        # 注意：勿再用 -t {freeze_duration}，那会把整个输出截断成只剩冻结段。
        try:
            subprocess.run([
                resolve_binary("ffmpeg"), "-y",
                "-i", video_path,
                "-vf", f"tpad=stop_mode=clone:stop_duration={freeze_duration}",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                output_path,
            ], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"[Compositor] freeze via tpad succeeded: {output_path}")
                return output_path
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace")[:500] if e.stderr else "no stderr"
            logger.warning(f"[Compositor] tpad freeze failed, trying moviepy fallback: {stderr}")
        except subprocess.TimeoutExpired:
            logger.warning("[Compositor] tpad freeze timed out, trying moviepy fallback")

        # 方案 2（回退）：moviepy 拼接原视频 + 尾帧定格。
        # 使用 get_frame + ImageClip 构造定格（moviepy 2.x 无 to_ImageClip(duration=...) API）。
        from moviepy import ImageClip, VideoFileClip, concatenate_videoclips

        clip = VideoFileClip(video_path)
        final = None
        try:
            # 取接近末尾的帧（duration-0.01 避免越界）
            last_frame_img = clip.get_frame(max(clip.duration - 0.01, 0))
            last_frame = ImageClip(last_frame_img, duration=freeze_duration)
            final = concatenate_videoclips([clip, last_frame], method="compose")
            final.write_videofile(output_path, logger=None, preset="fast")
        finally:
            clip.close()
            if final is not None:
                final.close()

        return output_path
