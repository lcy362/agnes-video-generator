"""
阿拉伯文字幕：由 khatt 绘制（连写、从右到左、保留变音符号），其他文字仍走 moviepy TextClip。

Pre-shaped text (arabic_reshaper + get_display) is shaped a second time by a Pillow
built with Raqm and comes out reversed; khatt lays Arabic out itself, so the clip is
the same either way.
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("khatt")

from khatt.video import TextClip as KhattTextClip  # noqa: E402
from moviepy import TextClip as MpTextClip  # noqa: E402

from core.compositor.concatenator import VideoConcatenator  # noqa: E402
from models.task import SubtitleStyle  # noqa: E402

LINES = [
    "بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ",
    "سعر القهوة 25 ريالا (عرض خاص)",
    "Hello world",
]


def _clips(tmp_path):
    srt = "\n".join(
        f"{n}\n00:00:{n:02d},000 --> 00:00:{n:02d},900\n{line}\n"
        for n, line in enumerate(LINES, start=1)
    )
    path = tmp_path / "subs.srt"
    path.write_text(srt, encoding="utf-8")
    return VideoConcatenator._parse_srt_to_clips(
        str(path), SubtitleStyle(), video_width=1280, video_height=720, video_duration=10
    )


def test_arabic_subtitles_are_drawn_by_khatt(tmp_path):
    vocalised, mixed, latin = _clips(tmp_path)
    assert isinstance(vocalised, KhattTextClip)
    assert isinstance(mixed, KhattTextClip)
    assert isinstance(latin, MpTextClip)


def test_arabic_text_is_kept_as_typed(tmp_path):
    vocalised, mixed, _ = _clips(tmp_path)
    # no presentation forms and no reordering: tashkeel and word order survive
    assert vocalised.text.replace("\n", " ") == LINES[0]
    assert mixed.text.replace("\n", " ") == LINES[1]


def test_characters_missing_from_the_arabic_font_fall_back(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # khatt warns about characters it cannot draw
        _, mixed, _ = _clips(tmp_path)
    frame = mixed.get_frame(0)
    assert frame.shape[0] > 0 and frame.max() > 0
