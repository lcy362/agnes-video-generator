"""core.compositor.concatenator — 视频拼接器

支持纯视频拼接和带音频字幕的拼接。
"""

import logging
import os
import shutil
from typing import List, Optional, Tuple

from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips
from moviepy.video.tools.subtitles import SubtitlesClip

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)


class VideoConcatenator:
    """视频拼接器：纯拼接 + 带音频合成拼接。"""

    @staticmethod
    def concat_videos(video_paths: List[str], output_path: str) -> str:
        """纯视频拼接（无音频处理）。

        Args:
            video_paths: 视频文件路径列表
            output_path: 输出文件路径

        Returns:
            输出文件路径
        """
        logger.info(f"[Compositor] Concatenating {len(video_paths)} videos → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not video_paths:
            raise RuntimeError("No videos to concatenate")

        if len(video_paths) == 1:
            shutil.copy2(video_paths[0], output_path)
            logger.info("[Compositor] Single video, copied directly")
            return output_path

        clips = [VideoFileClip(p) for p in video_paths]
        try:
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_path, logger="bar")
        finally:
            for c in clips:
                c.close()

        logger.info(f"[Compositor] Concatenation complete: {output_path}")
        return output_path

    @staticmethod
    def concat_with_audio(
        clip_tuples: List[Tuple[str, str, Optional[str]]],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle] = None,
    ) -> str:
        """带音频合成的视频拼接。

        每段视频先与音频 + 字幕合成，再整体拼接。

        Args:
            clip_tuples: [(video_path, audio_path, srt_path_or_None), ...]
            output_path: 最终输出文件路径
            subtitle_style: 字幕样式配置

        Returns:
            输出文件路径
        """
        logger.info(f"[Compositor] concat_with_audio: {len(clip_tuples)} segments → {output_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not clip_tuples:
            raise RuntimeError("No clips to concatenate")

        synthesized_paths = []

        for i, (video_path, audio_path, srt_path) in enumerate(clip_tuples):
            segment_output = video_path.replace(".mp4", "_synth.mp4")
            if os.path.exists(segment_output):
                synthesized_paths.append(segment_output)
                continue

            synthesized = VideoConcatenator._synthesize_single(
                video_path, audio_path, srt_path, segment_output, subtitle_style
            )
            synthesized_paths.append(synthesized)

        # 拼接所有合成片段
        if len(synthesized_paths) == 1:
            shutil.copy2(synthesized_paths[0], output_path)
        else:
            VideoConcatenator.concat_videos(synthesized_paths, output_path)

        logger.info(f"[Compositor] concat_with_audio complete: {output_path}")
        return output_path

    @staticmethod
    def _synthesize_single(
        video_path: str,
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle] = None,
    ) -> str:
        """合成单段视频 + 音频 + 字幕。

        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            srt_path: SRT 字幕路径（可选）
            output_path: 输出路径
            subtitle_style: 字幕样式

        Returns:
            输出路径
        """
        logger.info(f"[Compositor] Synthesizing: {video_path} + {audio_path}")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)

        # 视频时长 = max(音频时长 + 1.0 padding, 原视频时长)
        target_duration = max(audio_clip.duration + 1.0, video_clip.duration)

        # 如果视频比目标短，冻结最后一帧补齐
        if video_clip.duration < target_duration:
            freeze_duration = target_duration - video_clip.duration
            from core.compositor.processor import VideoProcessor
            freeze_path = output_path.replace(".mp4", "_freeze.mp4")
            VideoProcessor.freeze_last_frame(video_path, freeze_duration, freeze_path)
            video_clip.close()
            video_clip = VideoFileClip(freeze_path)

        # 合成音频
        video_with_audio = video_clip.with_audio(audio_clip)

        # 叠加字幕
        if srt_path and os.path.exists(srt_path) and subtitle_style:
            try:
                from moviepy import CompositeVideoClip, TextClip
                from moviepy.video.tools.subtitles import SubtitlesClip

                def make_text(txt):
                    return TextClip(
                        text=txt,
                        font=subtitle_style.font,
                        font_size=subtitle_style.fontsize,
                        color=subtitle_style.color,
                        stroke_color=subtitle_style.stroke_color,
                        stroke_width=subtitle_style.stroke_width,
                        bg_color=subtitle_style.bg_color,
                        method="label",
                        size=(video_clip.w - 40, None),
                        text_align="center",
                    )

                subs = SubtitlesClip(srt_path, make_text)
                pos = subtitle_style.position
                if isinstance(pos, (list, tuple)) and len(pos) == 2:
                    position = pos
                else:
                    position = ("center", "bottom")
                final = CompositeVideoClip([video_with_audio, subs.with_position(position)])
                final.write_videofile(output_path, logger="bar")
                final.close()
            except Exception as e:
                logger.warning(f"[Compositor] Subtitle overlay failed: {e}, writing without subtitles")
                video_with_audio.write_videofile(output_path, logger="bar")
        else:
            video_with_audio.write_videofile(output_path, logger="bar")

        video_clip.close()
        audio_clip.close()

        logger.info(f"[Compositor] Segment synthesized: {output_path}")
        return output_path
