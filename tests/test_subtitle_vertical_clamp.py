"""
字幕垂直钳位：高字幕（多行 / 阿文）不再越出画面底部，单行字幕位置保持原样。

背景：``bottom-80`` 解析出的 clip 顶部是 ``video_height - 80``，旧实现再被固定钳到
``video_height - 100``，于是 h>100 的字幕底部被画面裁掉（阿文两行 131px 丢约 30px，
长句丢更多）。修复按 clip 实际高度再收一次，只影响 h>80 的字幕。
"""

import tempfile

import pytest

from core.compositor.concatenator import VideoConcatenator
from core.compositor.concatenator.concat import _clamp_vertical_pixel
from models.task import SubtitleStyle


def test_single_line_keeps_previous_position():
    # 旧实现：min(640, 720-100) = 620；新实现对 h≈50 的字幕必须完全一致
    assert _clamp_vertical_pixel(640, 720, 50) == 620


@pytest.mark.parametrize("clip_height", [100, 131, 191, 300])
def test_tall_clips_stay_inside_frame(clip_height):
    top = _clamp_vertical_pixel(720 - 80, 720, clip_height)
    assert top + clip_height <= 720 - 20
    assert top >= 20


@pytest.mark.parametrize("clip_height,expected", [(100, 600), (131, 569)])
def test_clamp_uses_clip_height(clip_height, expected):
    assert _clamp_vertical_pixel(640, 720, clip_height) == expected


def test_non_pixel_position_passes_through():
    assert _clamp_vertical_pixel("center", 720, 131) == "center"


def test_unknown_clip_height_falls_back_to_old_behaviour():
    # clip 高度未知（0）时保持旧的 100px 安全区语义
    assert _clamp_vertical_pixel(640, 720, 0) == 620


def test_unknown_video_height_falls_back_to_top_margin():
    # video_height=0 时旧实现同样落到 20
    assert _clamp_vertical_pixel(640, 0, 131) == 20


def test_real_multiline_clip_is_clamped_inside_frame():
    """真实渲染的多行字幕：按实际 clip 高度钳位后不应出画（不依赖 khatt）。"""
    srt = (
        "1\n00:00:00,000 --> 00:00:02,000\n"
        "这是一段很长的中文字幕用来触发自动换行并产生多行高度\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False, encoding="utf-8") as f:
        f.write(srt)
        path = f.name

    clips = VideoConcatenator._parse_srt_to_clips(
        path, SubtitleStyle(), video_width=1280, video_height=720, video_duration=5
    )
    assert clips, "应至少生成一条字幕 clip"
    for clip in clips:
        top = _clamp_vertical_pixel(720 - 80, 720, clip.h)
        assert top + clip.h <= 720, f"字幕底部越界：top={top} h={clip.h}"
