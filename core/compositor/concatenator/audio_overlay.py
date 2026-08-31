"""core.compositor.concatenator.audio_overlay — 音频叠加拼接 + 数字人合成（v5.0 Batch 4 / 4.3 拆分）

AudioOverlayMixin：concat_videos_with_audio_overlay / composite_anchor_video；
跨组方法（_parse_srt_to_clips 等）经 MRO 由 ConcatMixin 解析。"""
import datetime
import itertools
import json
import logging
import os
import subprocess
from typing import List, Optional, Tuple

import srt as srt_lib
from moviepy import AudioFileClip, CompositeVideoClip, VideoFileClip

from core.compositor.ffmpeg_tool import resolve_binary
from models.task import SubtitleStyle

from .concat import _AUDIO_BITRATE, _AUDIO_CODEC, _AUDIO_FPS, _VIDEO_FPS

logger = logging.getLogger(__name__)

# ── 2.1c：ASS 字幕渲染辅助 ──
# moviepy TextClip 支持的命名颜色 → RGB（ASS 需要 BGR 十六进制）
_ASS_COLOR_NAMES = {
    "white": (255, 255, 255), "black": (0, 0, 0), "yellow": (255, 255, 0),
    "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "orange": (255, 165, 0),
    "pink": (255, 192, 203), "purple": (128, 0, 128), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "brown": (165, 42, 42), "navy": (0, 0, 128),
    "teal": (0, 128, 128), "silver": (192, 192, 192), "gold": (255, 215, 0),
    "lime": (0, 255, 0), "aqua": (0, 255, 255),
}


def _ass_fontname(font: str) -> str:
    """ASS Fontname：字体文件取文件名 stem；系统字体名原样返回。"""
    f = os.path.basename(str(font))
    if "." in f:
        return os.path.splitext(f)[0]
    return f


def _subtitle_ass_enabled() -> bool:
    """2.1c：字幕 ASS 单链开关（灰度）。关闭后回退 moviepy 字幕路径。"""
    from core.config import subtitle_ass_enabled as _enabled
    return _enabled()


class AudioOverlayMixin:
    """音频叠加拼接与数字人合成方法，v5.0 Batch 4（4.3）拆分。"""

    @staticmethod
    def concat_videos_with_audio_overlay(
        video_paths: List[str],
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle] = None,
        subtitle_styles_path: Optional[str] = None,
    ) -> str:
        """先拼接视频，再统一叠加单条音频 + 单条字幕。

        使用 ffmpeg 做音视频时长对齐（tpad/apad），确保音画精确同步。

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

        # ── Step 1: 拼接视频（无声）──
        silent_path = output_path.replace(".mp4", "_silent.mp4")
        VideoConcatenator.concat_videos(video_paths, silent_path)

        # ── Step 2: 获取音视频时长 ──
        video_dur = VideoConcatenator._get_duration(silent_path)
        audio_dur = VideoConcatenator._get_duration(audio_path)
        final_dur = max(video_dur, audio_dur)
        logger.info(
            f"[Compositor] durations: video={video_dur:.2f}s, "
            f"audio={audio_dur:.2f}s, final={final_dur:.2f}s"
        )

        # ── 2.1b/2.1c：视频+音频（+字幕）在一条 ffmpeg filter 链一次编码完成 ──
        # 无字幕走 2.1b；有字幕时优先走 2.1c（SRT→ASS + subtitles 滤镜，句级样式），
        # 失败自动回退 moviepy（Step 3/4/5）——词级动效与逐条样式完整保真仍在 moviepy 路径。
        has_sub = bool(srt_path and os.path.exists(srt_path) and subtitle_style)
        if not has_sub or _subtitle_ass_enabled():
            try:
                ass_path = None
                fonts_dir = None
                if has_sub:
                    video_w, video_h = AudioOverlayMixin._get_video_size(silent_path)
                    ass_path, fonts_dir = AudioOverlayMixin._srt_to_ass(
                        srt_path, subtitle_style, video_w, video_h, subtitle_styles_path,
                    )
                    if not ass_path:
                        raise RuntimeError("SRT→ASS conversion returned None")
                result = AudioOverlayMixin._ffmpeg_mux_aligned(
                    silent_path, audio_path, output_path, final_dur,
                    subtitle_ass_path=ass_path, fonts_dir=fonts_dir,
                )
                # fast path 自行清理拼接中间产物（原 finally 不经过此分支）
                if os.path.exists(silent_path):
                    os.remove(silent_path)
                if ass_path and os.path.exists(ass_path):
                    try:
                        os.remove(ass_path)
                    except OSError:
                        pass
                return result
            except Exception as e:
                logger.warning(
                    f"[Compositor] ffmpeg single-pass mux (subtitle ass) failed, "
                    f"fallback moviepy chain: {e}"
                )

        video_input = silent_path
        tmp_files = [silent_path]

        # ── Step 3: 若视频 < 音频，冻结尾帧补齐 ──
        if video_dur < final_dur - 0.3:
            extend_path = output_path.replace(".mp4", "_vext.mp4")
            tmp_files.append(extend_path)
            pad_dur = final_dur - video_dur
            VideoConcatenator._run_ffmpeg(
                [resolve_binary("ffmpeg"), "-y",
                 "-i", silent_path,
                 "-vf", f"tpad=stop_mode=clone:stop_duration={pad_dur:.2f}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-preset", "fast",
                 extend_path],
                desc=f"extend video by {pad_dur:.1f}s (freeze last frame)",
            )
            video_input = extend_path

        # ── Step 4: 若音频 < 视频，补齐静音 ──
        audio_input = audio_path
        if audio_dur < final_dur - 0.3:
            apad_path = audio_path.replace(".mp3", "_apad.mp3")
            tmp_files.append(apad_path)
            pad_dur = final_dur - audio_dur
            VideoConcatenator._run_ffmpeg(
                [resolve_binary("ffmpeg"), "-y",
                 "-i", audio_path,
                 "-af", f"apad=pad_dur={pad_dur:.2f},volume=1.5",
                 "-c:a", "libmp3lame", "-q:a", "2",
                 apad_path],
                desc=f"pad audio by {pad_dur:.1f}s + volume 1.5x",
            )
            audio_input = apad_path
        else:
            # 只做音量放大
            vol_path = audio_path.replace(".mp3", "_vol.mp3")
            tmp_files.append(vol_path)
            VideoConcatenator._run_ffmpeg(
                [resolve_binary("ffmpeg"), "-y",
                 "-i", audio_path,
                 "-af", "volume=1.5",
                 "-c:a", "libmp3lame", "-q:a", "2",
                 vol_path],
                desc="boost audio volume 1.5x",
            )
            audio_input = vol_path

        # ── Step 5: moviepy 合成视频+音频+字幕 ──
        video_clip = None
        audio_clip_obj = None
        try:
            video_clip = VideoFileClip(video_input)
            audio_clip_obj = AudioFileClip(audio_input)

            # 掐头去尾确保完全对齐
            target_dur = min(video_clip.duration, audio_clip_obj.duration)
            video_clip = video_clip.subclipped(0, target_dur)
            audio_clip_obj = audio_clip_obj.subclipped(0, target_dur)

            video_with_audio = video_clip.with_audio(audio_clip_obj)

            # ── 叠加字幕 ──
            if srt_path and os.path.exists(srt_path) and subtitle_style:
                try:
                    per_entry_styles = None
                    if subtitle_styles_path and os.path.exists(subtitle_styles_path):
                        with open(subtitle_styles_path, "r", encoding="utf-8") as f:
                            per_entry_styles = json.load(f)

                    subs_clips = VideoConcatenator._parse_srt_to_clips(
                        srt_path, subtitle_style, video_clip.w,
                        video_height=video_clip.h,
                        video_duration=target_dur,
                        subtitle_styles=per_entry_styles,
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
            if audio_clip_obj is not None:
                audio_clip_obj.close()
            for tmp in tmp_files:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] concat_videos_with_audio_overlay done: {output_path}")
        return output_path

    @staticmethod
    def _ffmpeg_mux_aligned(
        silent_path: str, audio_path: str, output_path: str, final_dur: float,
        subtitle_ass_path: Optional[str] = None, fonts_dir: Optional[str] = None,
    ) -> str:
        """2.1b/2.1c：视频+音频（+字幕）在一条 ffmpeg filter 链中完成对齐与合成（一次编码）。

        - 视频不足 ``final_dur`` → ``tpad stop_mode=clone`` 冻结尾帧补齐
        - 音频不足 ``final_dur`` → ``apad=whole_dur`` 补静音 + ``volume=1.5``
          补偿 edge_tts 默认低音量（与既有语义一致）
        - 传入 ``subtitle_ass_path`` 时追加 ``subtitles`` 滤镜烧录 ASS 字幕（2.1c）
        - ``-t final_dur`` 强制截断对齐

        Returns:
            输出文件路径。失败抛 RuntimeError（调用方回退 moviepy）。
        """
        if subtitle_ass_path:
            esc_path = AudioOverlayMixin._escape_filter_path(subtitle_ass_path)
            esc_dir = AudioOverlayMixin._escape_filter_path(fonts_dir or "")
            v_chain = (
                f"[0:v]tpad=stop_mode=clone:stop_duration={final_dur:.2f}[v0];"
                f"[v0]subtitles={esc_path}:fontsdir='{esc_dir}'[v]"
            )
        else:
            v_chain = f"[0:v]tpad=stop_mode=clone:stop_duration={final_dur:.2f}[v]"
        cmd = [
            resolve_binary("ffmpeg"), "-y",
            "-i", silent_path,
            "-i", audio_path,
            "-filter_complex",
            f"{v_chain};[1:a]apad=whole_dur={final_dur:.2f},volume=1.5[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "fast",
            "-c:a", _AUDIO_CODEC, "-b:a", _AUDIO_BITRATE,
            "-t", f"{final_dur:.2f}",
            output_path,
        ]
        VideoConcatenator._run_ffmpeg(
            cmd, desc=f"mux video+audio+subtitle (single-pass, {final_dur:.1f}s)",
        )
        return output_path

    # ─────────────────────────────────────────────────────────────
    # 2.1c：SRT → ASS 转换辅助
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _get_video_size(video_path: str) -> Tuple[int, int]:
        """ffprobe 获取视频宽高，失败回退 (768, 1152)。"""
        try:
            r = subprocess.run(
                [resolve_binary("ffprobe"), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=s=x:p=0", video_path],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                w, h = r.stdout.strip().split("x")
                return int(w), int(h)
        except Exception as e:
            logger.warning(f"[Compositor] probe video size failed: {e}")
        return 768, 1152

    @staticmethod
    def _escape_filter_path(p: str) -> str:
        """转义 ffmpeg filter 参数内的路径（\\ : ' 特殊字符）。"""
        return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    @staticmethod
    def _parse_ass_color(c) -> Optional[Tuple[int, int, int]]:
        """颜色（名称/#RRGGBB/rgb tuple）→ RGB 三元组；无法解析返回 None。"""
        if isinstance(c, (tuple, list)) and len(c) >= 3:
            return tuple(int(x) for x in c[:3])
        if isinstance(c, str):
            s = c.strip()
            if s.startswith("#") and len(s) == 7:
                try:
                    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
                except ValueError:
                    return None
            if s.lower() in _ASS_COLOR_NAMES:
                return _ASS_COLOR_NAMES[s.lower()]
        return None

    @staticmethod
    def _ass_color(rgb: Tuple[int, int, int]) -> str:
        """RGB → ASS 颜色 &H00BBGGRR&。"""
        r, g, b = rgb
        return f"&H00{b:02X}{g:02X}{r:02X}&"

    @staticmethod
    def _parse_ass_bg(c) -> Optional[Tuple[Tuple[int, int, int], int]]:
        """bg_color → ((r,g,b), alpha 0-255)；兼容 tuple/旧式 "black@0.5" 字符串。"""
        if isinstance(c, (tuple, list)):
            rgb = AudioOverlayMixin._parse_ass_color(c)
            alpha = int(c[3]) if len(c) >= 4 else 0
            return (rgb, alpha) if rgb else None
        if isinstance(c, str):
            s = c.strip()
            if "@" in s:
                name, _, a = s.partition("@")
                rgb = AudioOverlayMixin._parse_ass_color(name)
                if rgb:
                    try:
                        return (rgb, int(float(a.strip()) * 255))
                    except ValueError:
                        return None
            rgb = AudioOverlayMixin._parse_ass_color(s)
            return (rgb, 0) if rgb else None
        return None

    @staticmethod
    def _pos_to_ass_margins(
        pos: Tuple, video_width: int, video_height: int,
    ) -> Tuple[int, int, int, int]:
        """moviepy 位置 (h, v) → ASS (alignment, margin_l, margin_r, margin_v)。

        h/v 可为 "left/center/right"、"top/center/bottom" 或像素（离顶部距离）。
        """
        h_part, v_part = pos
        # 水平锚点
        if isinstance(h_part, (int, float)):
            ml = max(0, min(int(h_part), max(0, video_width - 40)))
            mr = 0
            h_anchor = "left"
        else:
            ml = mr = 0
            h_anchor = str(h_part).strip().lower()
            if h_anchor not in ("left", "right"):
                h_anchor = "center"
        # 垂直锚点
        if isinstance(v_part, (int, float)):
            mv = max(0, min(int(video_height - v_part), video_height))
            v_anchor = "bottom"
        else:
            mv = 0
            v_anchor = str(v_part).strip().lower()
            if v_anchor not in ("top", "center"):
                v_anchor = "bottom"
        # ASS alignment（1-9）：7 8 9 / 4 5 6 / 1 2 3（顶/中/底）
        col = {"left": 1, "center": 2, "right": 3}[h_anchor]
        row = {"top": 0, "center": 1, "bottom": 2}[v_anchor]
        alignment = col + (2 - row) * 3
        return alignment, ml, mr, mv

    @staticmethod
    def _ass_escape_text(txt: str) -> str:
        """转义 ASS Dialogue 文本（反斜杠 / 花括号 / 换行转义为 \\\\N）。"""
        txt = txt.replace("\\", "\\\\")
        txt = txt.replace("{", "\\{").replace("}", "\\}")
        txt = txt.replace("\n", "\\N")
        return txt

    @staticmethod
    def _srt_to_ass(
        srt_path: str,
        subtitle_style: SubtitleStyle,
        video_width: int,
        video_height: int,
        subtitle_styles_path: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        """2.1c：SRT + 样式 → ASS 文件（句级样式灰度）。

        保留字体/字号/主色/描边/位置/半透明底，放弃 moviepy 词级逐字动效
        （词级动效仍走 moviepy 兜底路径）。逐条样式（subtitle_styles_path）按
        index 覆盖字号/主色/位置。

        Returns:
            (ass_path, fonts_dir)；失败返回 None（调用方回退 moviepy）。
        """
        try:
            from core.audio.subtitle import SubtitleGenerator
            from core.audio.voices import (
                _ARABIC_RE,
                _BENGALI_RE,
                _DEVANAGARI_RE,
                _THAI_RE,
            )
            from core.config import (
                DEFAULT_ARABIC_FONT,
                DEFAULT_BENGALI_FONT,
                DEFAULT_DEVANAGARI_FONT,
                DEFAULT_THAI_FONT,
                font_dir,
                resolve_font_path,
            )

            with open(srt_path, "r", encoding="utf-8") as f:
                subs = list(srt_lib.parse(f))
            if not subs:
                return None

            font_path = resolve_font_path(subtitle_style.font)
            fonts_dir = font_dir()
            fontname = _ass_fontname(font_path)
            # 逐条按文本脚本回退字体（阿/泰/印地/孟加拉 → 内置对应字体），
            # 与 moviepy 字幕路径（concat.py）保持一致，避免方块（tofu）。
            script_font_map = {
                _ARABIC_RE: resolve_font_path(DEFAULT_ARABIC_FONT),
                _THAI_RE: resolve_font_path(DEFAULT_THAI_FONT),
                _DEVANAGARI_RE: resolve_font_path(DEFAULT_DEVANAGARI_FONT),
                _BENGALI_RE: resolve_font_path(DEFAULT_BENGALI_FONT),
            }

            # 主色 / 描边 / 背景
            primary = AudioOverlayMixin._ass_color(
                AudioOverlayMixin._parse_ass_color(subtitle_style.color) or (255, 255, 255)
            )
            stroke = AudioOverlayMixin._ass_color(
                AudioOverlayMixin._parse_ass_color(subtitle_style.stroke_color) or (0, 0, 0)
            )
            bg = AudioOverlayMixin._parse_ass_bg(subtitle_style.bg_color)
            if bg is not None:
                (br, bg_, bb), balpha = bg
                back = f"&H{balpha:02X}{bb:02X}{bg_:02X}{br:02X}&"
                border_style = 3  # opaque box（半透明底）
                outline = 0
            else:
                back = "&H00000000&"
                border_style = 1  # outline + shadow
                outline = max(1, int(subtitle_style.stroke_width or 2))

            # 全局位置 → 默认样式 alignment/margins
            pos_resolved = VideoConcatenator._resolve_subtitle_position(
                subtitle_style.position, video_height=video_height, video_width=video_width,
            )
            g_al, g_ml, g_mr, g_mv = AudioOverlayMixin._pos_to_ass_margins(
                pos_resolved, video_width, video_height,
            )

            fs = max(8, int(subtitle_style.fontsize or 48))

            # 逐条样式查找表（index → 覆盖字段）
            style_map: dict[int, dict] = {}
            if subtitle_styles_path and os.path.exists(subtitle_styles_path):
                with open(subtitle_styles_path, "r", encoding="utf-8") as f:
                    for s in json.load(f):
                        idx = s.get("index", 0)
                        if idx > 0:
                            style_map[idx] = s

            lines = []
            for sub in subs:
                txt = (sub.content or "").strip()
                if not txt:
                    continue
                entry = style_map.get(sub.index, {})
                entry_fs = max(8, int(entry.get("fontsize", fs)))
                entry_color = entry.get("color", subtitle_style.color)
                entry_pos = entry.get("position", subtitle_style.position)

                # 长文本多行换行（与 moviepy 路径同一算法）
                available_w = max(80, video_width - 40)
                cjk_max = max(8, available_w // entry_fs)
                wrapped = SubtitleGenerator._split_long_text(
                    txt, cjk_max, video_width=video_width, fontsize=entry_fs,
                )

                # 条目位置 → 独立 margins（该条覆盖全局）
                e_pos = VideoConcatenator._resolve_subtitle_position(
                    entry_pos, video_height=video_height, video_width=video_width,
                )
                e_al, e_ml, e_mr, e_mv = AudioOverlayMixin._pos_to_ass_margins(
                    e_pos, video_width, video_height,
                )

                # override tags：仅在与全局不同时输出
                overrides = []
                # 文本脚本 → 强制回退内置字体（与 moviepy 路径一致）
                entry_fontname = fontname
                for script_re, script_font in script_font_map.items():
                    if script_re.search(txt):
                        entry_fontname = _ass_fontname(script_font)
                        break
                if entry_fontname != fontname:
                    overrides.append(f"\\fn{entry_fontname}")
                if entry_fs != fs:
                    overrides.append(f"\\fs{entry_fs}")
                c_rgb = AudioOverlayMixin._parse_ass_color(entry_color)
                if c_rgb and AudioOverlayMixin._ass_color(c_rgb) != primary:
                    overrides.append(f"\\c{AudioOverlayMixin._ass_color(c_rgb)}")

                # 位置：条目与全局一致 → Dialogue margins 全零（继承 Style）；
                # 不一致 → 显式 \an + 非零 margins 覆盖（避免 \pos 文本宽度估算误差）
                if (e_al, e_ml, e_mr, e_mv) == (g_al, g_ml, g_mr, g_mv):
                    line_ml = line_mr = line_mv = 0
                else:
                    overrides.append(f"\\an{e_al}")
                    line_ml, line_mr, line_mv = e_ml, e_mr, e_mv

                start_s = sub.start.total_seconds()
                end_s = sub.end.total_seconds()
                start = AudioOverlayMixin._ass_time(start_s)
                end = AudioOverlayMixin._ass_time(end_s)
                text = AudioOverlayMixin._ass_escape_text(wrapped)
                tag_str = "".join(overrides)
                if tag_str:
                    text = "{" + tag_str + "}" + text

                lines.append(
                    f"Dialogue: 0,{start},{end},Default,,{line_ml},{line_mr},{line_mv},,{text}"
                )

            ass_path = srt_path + ".ass"
            header = (
                "[Script Info]\n"
                "ScriptType: v4.00+\n"
                f"PlayResX: {video_width}\n"
                f"PlayResY: {video_height}\n"
                "WrapStyle: 2\n"
                "\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                f"Style: Default,{fontname},{fs},{primary},&H000000FF&,{stroke},"
                f"{back},0,0,0,0,100,100,0,0,{border_style},{outline},0,"
                f"{g_al},{g_ml},{g_mr},{g_mv},1\n"
                "\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                "Effect, Text\n"
            )
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(header + "\n".join(lines) + "\n")
            logger.info(
                f"[Compositor] SRT→ASS done: {len(lines)} entries → {ass_path}"
            )
            return ass_path, fonts_dir
        except Exception as e:
            logger.warning(f"[Compositor] SRT→ASS conversion failed: {e}")
            return None

    @staticmethod
    def _ass_time(seconds: float) -> str:
        """秒 → ASS 时间 H:MM:SS.cc。"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # ─────────────────────────────────────────────────────────────
    # 2.2：poetry 多场景一次合成（视频 -c copy 拼接 + 音频合并 + 总字幕）
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def concat_scenes_single_pass(
        video_paths: List[str],
        audio_paths: List[str],
        srt_paths: List[Optional[str]],
        output_path: str,
        subtitle_style: Optional[SubtitleStyle],
        subtitle_styles_path: Optional[str] = None,
    ) -> Optional[str]:
        """2.2：多场景「视频拼接 + 音频合并 + 字幕」一次编码合成。

        - 场景视频 ``concat_videos``（2.1a ``-c copy`` fast path）→ 0 次视频重编码
        - 各场景音频按视频实际时间轴 ``adelay+amix+apad`` 合并 → 单音频（一次音频编码）
        - 各场景 SRT 偏移合并为总 SRT
        - 最终 ``concat_videos_with_audio_overlay`` 一次编码（无字幕走 2.1b /
          有字幕走 2.1c ASS 单链）

        任何一步失败返回 None（调用方回退逐场景合成），不抛异常。

        Args:
            video_paths: 各场景视频路径（有序）。
            audio_paths: 各场景音频路径（有序，需与视频一一对应）。
            srt_paths: 各场景 SRT 路径（可为 None/空串，有序）。
            output_path: 最终输出。
            subtitle_style: 全局字幕样式（None 表示无字幕）。
            subtitle_styles_path: 逐条样式 JSON（透传 2.1c）。

        Returns:
            输出路径；失败返回 None。
        """
        try:
            n = len(video_paths)
            if n < 1 or len(audio_paths) != n or len(srt_paths) != n:
                return None
            for vp, ap in zip(video_paths, audio_paths):
                if not vp or not ap or not os.path.exists(vp) or not os.path.exists(ap):
                    return None

            base = output_path.replace(".mp4", "")
            # 1) 场景视频 -c copy 拼接（2.1a fast path，失败自动回退 moviepy compose）
            total_silent = base + "_total_silent.mp4"
            VideoConcatenator.concat_videos(video_paths, total_silent)
            # 偏移按视频实际时长累积（模型产出与规划时长可能有偏差）
            real_durs = [VideoConcatenator._get_duration(v) for v in video_paths]
            offsets = list(itertools.accumulate(real_durs, initial=0.0))[:-1]
            total_dur = sum(real_durs)

            # 2) 音频合并（adelay+amix+apad，一次音频编码）
            total_audio = base + "_total_audio.mp3"
            if not AudioOverlayMixin._merge_scene_audios(
                audio_paths, offsets, total_audio, total_dur,
            ):
                return None

            # 3) 总 SRT（偏移合并）
            total_srt = None
            has_srt = subtitle_style is not None and any(
                s and os.path.exists(s) for s in srt_paths
            )
            if has_srt:
                total_srt = base + "_total.srt"
                if not AudioOverlayMixin._merge_scene_srts(srt_paths, offsets, total_srt):
                    total_srt = None

            # 4) 一次合成（无字幕 2.1b / 有字幕 2.1c ASS 单链）
            AudioOverlayMixin.concat_videos_with_audio_overlay(
                [total_silent], total_audio, total_srt, output_path,
                subtitle_style, subtitle_styles_path,
            )
            for tmp in (total_silent, total_audio, total_srt):
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            logger.info(
                f"[Compositor] concat_scenes_single_pass done: "
                f"{n} scenes → {output_path}"
            )
            return output_path
        except Exception as e:
            logger.warning(f"[Compositor] single-pass scenes composite failed: {e}")
            return None

    @staticmethod
    def _merge_scene_audios(
        audio_paths: List[str], offsets: List[float], output_path: str, total_dur: float,
    ) -> bool:
        """各场景音频按偏移 adelay+amix+apad 合并为单音频（含场景间静音）。

        Returns:
            True=成功；False=失败（调用方回退）。
        """
        try:
            n = len(audio_paths)
            cmd = [resolve_binary("ffmpeg"), "-y"]
            for ap in audio_paths:
                cmd += ["-i", ap]
            filters = []
            mixins = []
            for i, (ap, off) in enumerate(zip(audio_paths, offsets)):
                off_ms = max(0, int(round(off * 1000)))
                filters.append(
                    f"[{i}:a]aresample=44100,adelay={off_ms}:all=1[a{i}]"
                )
                mixins.append(f"[a{i}]")
            filters.append(
                "".join(mixins)
                + f"amix=inputs={n}:normalize=0:dropout_transition=0,"
                + f"apad=whole_dur={total_dur:.2f}[a]"
            )
            cmd += [
                "-filter_complex", ";".join(filters),
                "-map", "[a]",
                "-c:a", "libmp3lame", "-q:a", "2",
                "-t", f"{total_dur:.2f}",
                output_path,
            ]
            VideoConcatenator._run_ffmpeg(
                cmd, desc=f"merge {n} scene audios (adelay+amix, {total_dur:.1f}s)",
            )
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            logger.warning(f"[Compositor] merge scene audios failed: {e}")
            return False

    @staticmethod
    def _merge_scene_srts(
        srt_paths: List[Optional[str]], offsets: List[float], output_path: str,
    ) -> bool:
        """各场景 SRT 按偏移合并为总 SRT（重新编号）。

        Returns:
            True=成功；False=失败。
        """
        try:
            out_subs = []
            idx = 1
            for sp, off in zip(srt_paths, offsets):
                if not sp or not os.path.exists(sp):
                    continue
                with open(sp, "r", encoding="utf-8") as f:
                    for sub in srt_lib.parse(f):
                        out_subs.append(srt_lib.Subtitle(
                            index=idx,
                            start=sub.start + datetime.timedelta(seconds=off),
                            end=sub.end + datetime.timedelta(seconds=off),
                            content=sub.content,
                        ))
                        idx += 1
            if not out_subs:
                return False
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(srt_lib.compose(out_subs))
            return True
        except Exception as e:
            logger.warning(f"[Compositor] merge scene srts failed: {e}")
            return False

    @staticmethod
    def composite_anchor_video(
        clip_path: str,
        audio_path: str,
        srt_path: Optional[str],
        output_path: str,
        audio_duration: float,
        subtitle_style: Optional[SubtitleStyle] = None,
        subtitle_styles_path: Optional[str] = None,
        video_width: int = 768,
        video_height: int = 1344,
    ) -> str:
        """将 5 秒主播动态视频片段循环拼接为覆盖完整音频时长，再叠加音频和字幕。

        核心思路：循环拼接 + 裁剪 + 统一叠加音频/字幕。
        接缝处用 ffmpeg xfade 做 0.3 秒交叉淡入淡出过渡。

        Args:
            clip_path: 5 秒主播动态视频片段路径。
            audio_path: TTS 读稿音频路径。
            srt_path: SRT 字幕文件路径（可选）。
            output_path: 最终输出视频路径。
            audio_duration: 音频总时长（秒）。
            subtitle_style: 字幕样式配置。
            subtitle_styles_path: LLM 样式 JSON 路径（可选）。
            video_width: 视频宽度。
            video_height: 视频高度。

        Returns:
            输出文件路径。
        """
        import math

        logger.info(
            f"[Compositor] composite_anchor_video: {clip_path} + {audio_path} "
            f"(audio={audio_duration:.1f}s) → {output_path}"
        )
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Step 1: Get clip duration
        probe = subprocess.run(
            [resolve_binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", clip_path],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=15,
        )
        clip_duration = float(probe.stdout.strip() or 5.0)
        if clip_duration <= 0:
            clip_duration = 5.0

        # Step 2: Calculate loop count
        needed = audio_duration + 2.0  # extra 2s padding
        n = math.ceil(needed / clip_duration) + 1

        # Step 3: Build concat file list for ffmpeg
        loop_dir = os.path.dirname(output_path)
        concat_file = os.path.join(loop_dir, "_anchor_concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for _ in range(n):
                f.write(f"file '{clip_path}'\n")

        looped_path = output_path.replace(".mp4", "_looped.mp4")

        # Step 4: Concatenate with xfade cross-fade transitions
        try:
            subprocess.run(
                [resolve_binary("ffmpeg"), "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_file,
                 "-c", "copy",
                 "-t", str(needed),
                 looped_path],
                stdin=subprocess.DEVNULL,
                check=True, capture_output=True, timeout=300,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"[Compositor] Simple concat failed: {e.stderr[:200]}, trying xfade")

            # xfade filter 构建已由上方 trim 循环拼接替代（死代码，3.3 清理）

            subprocess.run(
                [resolve_binary("ffmpeg"), "-y",
                 "-stream_loop", str(n - 1), "-i", clip_path,
                 "-filter_complex",
                 f"[0:v]trim=duration={needed}[v]",
                 "-map", "[v]",
                 "-c:v", "libx264",
                 "-preset", "fast",
                 "-t", str(needed),
                 looped_path],
                stdin=subprocess.DEVNULL,
                check=True, capture_output=True, timeout=300,
            )

        # Step 5: Overlay audio and subtitles
        concat_video_clip = None
        audio_clip_obj = None
        try:
            concat_video_clip = VideoFileClip(looped_path)
            audio_clip_obj = AudioFileClip(audio_path)

            _AUDIO_VOLUME_FACTOR = 1.5
            audio_clip_obj = audio_clip_obj.with_volume_scaled(_AUDIO_VOLUME_FACTOR)

            video_with_audio = concat_video_clip.with_audio(audio_clip_obj)

            if srt_path and os.path.exists(srt_path) and subtitle_style:
                per_entry_styles = None
                if subtitle_styles_path and os.path.exists(subtitle_styles_path):
                    with open(subtitle_styles_path, "r", encoding="utf-8") as f:
                        per_entry_styles = json.load(f)

                subs_clips = VideoConcatenator._parse_srt_to_clips(
                    srt_path, subtitle_style,
                    video_width, video_height,
                    video_duration=concat_video_clip.duration,
                    subtitle_styles=per_entry_styles,
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
            if concat_video_clip is not None:
                concat_video_clip.close()
            if audio_clip_obj is not None:
                audio_clip_obj.close()
            for tmp in (looped_path, concat_file):
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        logger.info(f"[Compositor] composite_anchor_video done: {output_path}")
        return output_path
