"""core.compositor.concatenator — 视频拼接器

支持纯视频拼接和带音频字幕的拼接。
"""

import logging
import os
import shutil
from typing import List, Optional, Tuple

import re as _re

import srt as srt_lib
from moviepy import AudioFileClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips

from models.task import SubtitleStyle

logger = logging.getLogger(__name__)

# ── 视频输出常量（对齐 MoneyPrinterTurbo，确保播放器兼容性）──
_AUDIO_CODEC = "aac"
_AUDIO_BITRATE = "192k"
_AUDIO_FPS = 44100
_VIDEO_FPS = 30


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
        # L7: 统一缩放到第一个视频的分辨率，避免 compose 模式 pad 黑边
        target_w, target_h = clips[0].w, clips[0].h
        resized_clips = []
        for c in clips:
            if c.w != target_w or c.h != target_h:
                resized_clips.append(c.resized((target_w, target_h)))
            else:
                resized_clips.append(c)
        final = None
        try:
            final = concatenate_videoclips(resized_clips, method="compose")
            final.write_videofile(
                output_path,
                codec="libx264",
                audio_codec=_AUDIO_CODEC,
                audio_bitrate=_AUDIO_BITRATE,
                audio_fps=_AUDIO_FPS,
                fps=_VIDEO_FPS,
                logger="bar",
            )
        finally:
            # P6: 关闭所有资源（clips + resized_clips + final）
            for c in clips:
                try:
                    c.close()
                except Exception:
                    pass
            for c in resized_clips:
                if c not in clips:  # 避免重复 close
                    try:
                        c.close()
                    except Exception:
                        pass
            if final is not None:
                try:
                    final.close()
                except Exception:
                    pass

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
            if os.path.exists(segment_output) and os.path.getsize(segment_output) > 0:
                # Validate cached _synth file has valid duration
                try:
                    probe = VideoFileClip(segment_output)
                    if probe.duration and probe.duration > 0:
                        probe.close()
                        logger.info(f"[Compositor] Reusing valid cached _synth: {segment_output}")
                        synthesized_paths.append(segment_output)
                        continue
                    probe.close()
                    logger.warning(f"[Compositor] Cached _synth has invalid duration, rebuilding: {segment_output}")
                except Exception as e:
                    logger.warning(f"[Compositor] Cached _synth validation failed, rebuilding: {segment_output} ({e})")

            synthesized = VideoConcatenator._synthesize_single(
                video_path, audio_path, srt_path, segment_output, subtitle_style
            )
            synthesized_paths.append(synthesized)

        # 拼接所有合成片段
        if len(synthesized_paths) == 1:
            shutil.copy2(synthesized_paths[0], output_path)
        else:
            VideoConcatenator.concat_videos(synthesized_paths, output_path)

        # 清理 _synth 中间文件
        for sp in synthesized_paths:
            if sp.endswith("_synth.mp4") and os.path.exists(sp):
                try:
                    os.remove(sp)
                except OSError:
                    pass

        logger.info(f"[Compositor] concat_with_audio complete: {output_path}")
        return output_path

    @staticmethod
    def _resolve_subtitle_position(pos, default=("center", "bottom"), video_height: int = 0) -> tuple:
        """将字幕位置配置归一化为 (horizontal, vertical) 元组。

        支持 "bottom-N" / "top+N" 格式（N 为像素偏移），
        返回 moviepy 可用的位置元组。
        """
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            h, v = pos[0], pos[1]
            if isinstance(v, str):
                v_lower = v.strip().lower()
                # 解析 "bottom-N" 格式
                m_bottom = _re.match(r'^bottom\s*[-–]\s*(\d+)$', v_lower)
                if m_bottom and video_height > 0:
                    offset = int(m_bottom.group(1))
                    return (h, max(video_height - offset, 0))
                # 解析 "top+N" 格式
                m_top = _re.match(r'^top\s*\+\s*(\d+)$', v_lower)
                if m_top:
                    offset = int(m_top.group(1))
                    return (h, offset)
                if "top" in v_lower:
                    return (h, "top")
                if "bottom" in v_lower:
                    return (h, "bottom")
            return (h, v)
        if isinstance(pos, str):
            pos_lower = pos.strip().lower()
            m_bottom = _re.match(r'^bottom\s*[-–]\s*(\d+)$', pos_lower)
            if m_bottom and video_height > 0:
                offset = int(m_bottom.group(1))
                return ("center", max(video_height - offset, 0))
            m_top = _re.match(r'^top\s*\+\s*(\d+)$', pos_lower)
            if m_top:
                offset = int(m_top.group(1))
                return ("center", offset)
            position_map = {
                "bottom": ("center", "bottom"),
                "top": ("center", "top"),
                "center": ("center", "center"),
                "middle": ("center", "center"),
            }
            return position_map.get(pos_lower, default)
        return default

    @staticmethod
    def _parse_srt_to_clips(
        srt_path: str,
        subtitle_style: SubtitleStyle,
        video_width: int,
        video_height: int = 0,
        video_duration: float = 0.0,
    ) -> list:
        """逐条解析 SRT，返回 TextClip 列表（支持多行自动换行）。"""
        from moviepy import TextClip as MpTextClip
        from core.config import resolve_font_path
        from core.audio.subtitle import SubtitleGenerator

        font_path = resolve_font_path(subtitle_style.font)

        # 兼容旧格式 bg_color 字符串
        bg = subtitle_style.bg_color
        if isinstance(bg, str):
            if "@" in bg:
                parts = bg.split("@", 1)
                rgb = {"black": (0, 0, 0), "white": (255, 255, 255)}.get(parts[0].strip().lower(), (0, 0, 0))
                bg = (*rgb, int(float(parts[1]) * 255))
            else:
                bg = (0, 0, 0, 128)

        # 根据视频宽度动态计算每行最大字符数（与 subtitle.py 一致）
        available_w = video_width - 40
        cjk_max_chars = max(8, available_w // subtitle_style.fontsize)

        subs_clips = []
        with open(srt_path, "r", encoding="utf-8") as f:
            for sub in srt_lib.parse(f):
                txt = sub.content
                start_s = sub.start.total_seconds()
                end_s = sub.end.total_seconds()
                dur = end_s - start_s

                # 长文本自动拆为多行，避免单行溢出屏幕
                wrapped = SubtitleGenerator._split_long_text(txt, cjk_max_chars)

                clip = MpTextClip(
                    text=wrapped,
                    font=font_path,
                    font_size=subtitle_style.fontsize,
                    color=subtitle_style.color,
                    stroke_color=subtitle_style.stroke_color,
                    stroke_width=subtitle_style.stroke_width,
                    bg_color=bg,
                    method="caption",
                    size=(available_w, None),
                    text_align="center",
                )
                # M10: 钳位字幕结束时间不超过视频时长
                if video_duration > 0:
                    end_s = min(end_s, video_duration - 0.01)
                    if end_s <= start_s:
                        continue
                    dur = end_s - start_s

                clip = (
                    clip.with_start(start_s)
                    .with_end(end_s)
                    .with_duration(dur)
                )
                clip = clip.with_position(
                    VideoConcatenator._resolve_subtitle_position(
                        subtitle_style.position, video_height=video_height
                    )
                )
                subs_clips.append(clip)
        return subs_clips

    @staticmethod
    def concat_videos_with_audio_overlay(
        video_paths: List[str],
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle] = None,
    ) -> str:
        """先拼接视频，再统一叠加单条音频 + 单条字幕。

        MoneyPrinterTurbo 方案：不按片段做逐段合成（避免 padding 累积），
        而是先把所有视频拼成完整时间轴，再把音频和字幕作为一个整体叠加上去。

        Args:
            video_paths: 按顺序的视频路径列表。
            audio_path: 整段音频文件路径（对应全部视频的总时间轴）。
            srt_path: 整段 SRT 字幕路径（可选）。
            output_path: 最终输出文件路径。
            subtitle_style: 字幕样式配置。

        Returns:
            输出文件路径。
        """
        logger.info(
            f"[Compositor] concat_videos_with_audio_overlay: "
            f"{len(video_paths)} videos + {audio_path} → {output_path}"
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        if not video_paths:
            raise RuntimeError("No videos to concatenate")

        naked_path = output_path.replace(".mp4", "_naked.mp4")
        freeze_path = output_path.replace(".mp4", "_freeze.mp4")
        video_clip = None
        audio_clip = None

        try:
            # ── Step 1: 拼接所有视频 ──────────────────────────────────────
            VideoConcatenator.concat_videos(video_paths, naked_path)

            # ── Step 2: 加载拼接视频 + 音频 ────────────────────────────────
            video_clip = VideoFileClip(naked_path)
            audio_clip = AudioFileClip(audio_path)

            # ── Step 2.5: 提升音频音量（M9: 降为 1.5x 避免削波）────────
            _AUDIO_VOLUME_FACTOR = 1.5
            audio_clip = audio_clip.with_volume_scaled(_AUDIO_VOLUME_FACTOR)

            # ── Step 3: 若音频比视频长，冻结尾帧补齐 ─────────────────────
            if video_clip.duration < audio_clip.duration:
                freeze_duration = audio_clip.duration - video_clip.duration
                from core.compositor.processor import VideoProcessor
                VideoProcessor.freeze_last_frame(naked_path, freeze_duration, freeze_path)
                video_clip.close()
                video_clip = VideoFileClip(freeze_path)

            # ── Step 4: 叠加音频 ──────────────────────────────────────────
            video_with_audio = video_clip.with_audio(audio_clip)

            # ── Step 5: 叠加字幕 ──────────────────────────────────────────
            if srt_path and os.path.exists(srt_path) and subtitle_style:
                try:
                    subs_clips = VideoConcatenator._parse_srt_to_clips(
                        srt_path, subtitle_style, video_clip.w,
                        video_height=video_clip.h,
                        video_duration=video_clip.duration,
                    )
                    if subs_clips:
                        final = CompositeVideoClip([video_with_audio, *subs_clips])
                        final.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                        final.close()
                    else:
                        video_with_audio.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                except Exception as e:
                    logger.warning(
                        f"[Compositor] Subtitle overlay failed: {e}, writing without subtitles"
                    )
                    video_with_audio.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec=_AUDIO_CODEC,
                        audio_bitrate=_AUDIO_BITRATE,
                        audio_fps=_AUDIO_FPS,
                        fps=_VIDEO_FPS,
                        logger="bar",
                    )
            else:
                video_with_audio.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec=_AUDIO_CODEC,
                    audio_bitrate=_AUDIO_BITRATE,
                    audio_fps=_AUDIO_FPS,
                    fps=_VIDEO_FPS,
                    logger="bar",
                )
        finally:
            if video_clip is not None:
                video_clip.close()
            if audio_clip is not None:
                audio_clip.close()
            for tmp in (naked_path, freeze_path):
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] concat_videos_with_audio_overlay done: {output_path}")
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

        video_clip = None
        audio_clip = None
        freeze_path = output_path.replace(".mp4", "_freeze.mp4")

        try:
            video_clip = VideoFileClip(video_path)
            audio_clip = AudioFileClip(audio_path)

            # 提升音频音量（M9: 降为 1.5x 避免削波）
            _AUDIO_VOLUME_FACTOR = 1.5
            audio_clip = audio_clip.with_volume_scaled(_AUDIO_VOLUME_FACTOR)

            # 若音频比视频长，冻结最后一帧补齐
            if video_clip.duration < audio_clip.duration:
                freeze_duration = audio_clip.duration - video_clip.duration
                from core.compositor.processor import VideoProcessor
                VideoProcessor.freeze_last_frame(video_path, freeze_duration, freeze_path)
                video_clip.close()
                video_clip = VideoFileClip(freeze_path)

            # 合成音频
            video_with_audio = video_clip.with_audio(audio_clip)

            # 叠加字幕
            if srt_path and os.path.exists(srt_path) and subtitle_style:
                try:
                    subs_clips = VideoConcatenator._parse_srt_to_clips(
                        srt_path, subtitle_style, video_clip.w,
                        video_height=video_clip.h,
                        video_duration=video_clip.duration,
                    )
                    if subs_clips:
                        final = CompositeVideoClip([video_with_audio, *subs_clips])
                        final.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                        final.close()
                    else:
                        video_with_audio.write_videofile(
                            output_path,
                            codec="libx264",
                            audio_codec=_AUDIO_CODEC,
                            audio_bitrate=_AUDIO_BITRATE,
                            audio_fps=_AUDIO_FPS,
                            fps=_VIDEO_FPS,
                            logger="bar",
                        )
                except Exception as e:
                    logger.warning(
                        f"[Compositor] Subtitle overlay failed: {e}, writing without subtitles"
                    )
                    video_with_audio.write_videofile(
                        output_path,
                        codec="libx264",
                        audio_codec=_AUDIO_CODEC,
                        audio_bitrate=_AUDIO_BITRATE,
                        audio_fps=_AUDIO_FPS,
                        fps=_VIDEO_FPS,
                        logger="bar",
                    )
            else:
                video_with_audio.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec=_AUDIO_CODEC,
                    audio_bitrate=_AUDIO_BITRATE,
                    audio_fps=_AUDIO_FPS,
                    fps=_VIDEO_FPS,
                    logger="bar",
                )
        finally:
            if video_clip is not None:
                video_clip.close()
            if audio_clip is not None:
                audio_clip.close()
            if os.path.exists(freeze_path):
                try:
                    os.remove(freeze_path)
                except OSError:
                    pass

        logger.info(f"[Compositor] Segment synthesized: {output_path}")
        return output_path
