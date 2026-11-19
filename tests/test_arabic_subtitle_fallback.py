"""
khatt 缺失时的阿文字幕降级：只降级阿文行、不阻塞其他语种、告警只刷一次。

khatt 是可选依赖（requirements.txt 标注 optional-dependency）。历史上阿文整形是
分支内懒加载，因此字幕渲染不该因为「少装一个阿文库」而整体失败——本文件锁定该契约。
"""

import logging
import sys

import pytest
from moviepy import TextClip as MpTextClip

from core.compositor.concatenator import VideoConcatenator
from core.compositor.concatenator import concat as concat_mod
from models.task import SubtitleStyle

_LOGGER = "core.compositor.concatenator.concat"


@pytest.fixture
def no_khatt(monkeypatch):
    """模拟 khatt 未安装（不论本机是否真的装了），并清掉模块级解析缓存。"""
    monkeypatch.setitem(sys.modules, "khatt.video", None)
    monkeypatch.setattr(concat_mod, "_khatt_text_clip_cls", None)
    monkeypatch.setattr(concat_mod, "_khatt_import_failed", False)


def _clips(tmp_path, lines):
    srt = "\n".join(
        f"{n}\n00:00:{n:02d},000 --> 00:00:{n:02d},900\n{line}\n"
        for n, line in enumerate(lines, start=1)
    )
    path = tmp_path / "subs.srt"
    path.write_text(srt, encoding="utf-8")
    return VideoConcatenator._parse_srt_to_clips(
        str(path), SubtitleStyle(), video_width=1280, video_height=720, video_duration=10
    )


def test_arabic_falls_back_to_moviepy_clip(tmp_path, no_khatt, caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        clips = _clips(tmp_path, ["بِسْمِ اللَّهِ", "سعر القهوة 25 ريالا (عرض خاص)"])

    assert len(clips) == 2
    assert all(isinstance(clip, MpTextClip) for clip in clips)
    # 降级仍要画出内容，而不是空帧
    assert clips[0].get_frame(0).max() > 0
    assert "khatt" in caplog.text


def test_khatt_missing_warns_only_once(tmp_path, no_khatt, caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _clips(tmp_path, ["مرحبا", "شكرا لك", "أهلا وسهلا"])

    warnings = [r for r in caplog.records if "khatt" in r.getMessage()]
    assert len(warnings) == 1


def test_non_arabic_unaffected_without_khatt(tmp_path, no_khatt, caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        clips = _clips(tmp_path, ["Hello world", "你好世界", "สวัสดีชาวโลก", "नमस्ते दुनिया"])

    assert len(clips) == 4
    assert all(isinstance(clip, MpTextClip) for clip in clips)
    # 非阿文行不应触发 khatt 解析，也就不应产生告警
    assert "khatt" not in caplog.text
