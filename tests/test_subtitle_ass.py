"""2.1c 字幕 ASS 单链合成测试（灰度路径 + 回退开关）。"""
import os

import pytest

from core.compositor.concatenator.audio_overlay import (
    AudioOverlayMixin,
    _ass_fontname,
    _subtitle_ass_enabled,
)
from core.compositor.concatenator.concat import VideoConcatenator
from core.config import subtitle_ass_enabled as config_subtitle_ass_enabled
from models.task import SubtitleStyle

ASSET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_regression", "assets", "test_video_5s.mp4",
)
_HAS_ASSET = os.path.exists(ASSET)

_SRT = """1
00:00:00,200 --> 00:00:02,500
一只猫在花园里追蝴蝶

2
00:00:02,600 --> 00:00:04,800
第二句字幕
"""


def _write_srt(tmp_path) -> str:
    p = os.path.join(str(tmp_path), "subs.srt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(_SRT)
    return p


def _style() -> SubtitleStyle:
    return SubtitleStyle(
        font="STHeitiMedium.ttc",
        color="white",
        position=("center", "bottom-80"),
        fontsize=48,
        stroke_color="black",
        stroke_width=2,
        bg_color=(0, 0, 0, 140),
    )


def test_srt_to_ass_content(tmp_path):
    """SRT→ASS：包含 Script Info / 样式 / Dialogue，时间与文本正确转义。"""
    srt = _write_srt(tmp_path)
    result = AudioOverlayMixin._srt_to_ass(srt, _style(), 768, 1152)
    assert result is not None
    ass_path, fonts_dir = result
    assert os.path.exists(ass_path)
    assert os.path.isdir(fonts_dir)
    with open(ass_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "[Script Info]" in content
    assert "PlayResX: 768" in content
    assert "PlayResY: 1152" in content
    assert "[V4+ Styles]" in content
    assert "Style: Default,STHeitiMedium,48" in content
    assert "Dialogue:" in content
    # 时间格式 H:MM:SS.cc
    assert "Dialogue: 0,0:00:00.20,0:00:02.50,Default" in content
    assert "一只猫在花园里追蝴蝶" in content
    # 半透明底 → BorderStyle=3（box）、Outline=0；全局位置 bottom-center → Alignment=2
    style_line = next(l for l in content.splitlines() if l.startswith("Style: Default,"))
    fields = style_line.split(",")
    assert fields[15] == "3", f"BorderStyle 应为 3（box），实际: {fields[15]}"
    assert fields[16] == "0", f"box 模式 Outline 应为 0，实际: {fields[16]}"
    assert fields[18] == "2", f"Alignment 应为 2（bottom-center），实际: {fields[18]}"


def test_srt_to_ass_failure_returns_none(tmp_path):
    """损坏/空 SRT 返回 None（调用方回退 moviepy）。"""
    p = os.path.join(str(tmp_path), "bad.srt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("not a valid srt\n")
    assert AudioOverlayMixin._srt_to_ass(p, _style(), 768, 1152) is None
    empty = os.path.join(str(tmp_path), "empty.srt")
    open(empty, "w").close()
    assert AudioOverlayMixin._srt_to_ass(empty, _style(), 768, 1152) is None


def test_ass_color_helpers():
    """颜色转换：#RRGGBB / 命名色 / rgb tuple → ASS 颜色。"""
    assert AudioOverlayMixin._ass_color((255, 255, 255)) == "&H00FFFFFF&"
    assert AudioOverlayMixin._ass_color((0, 0, 255)) == "&H00FF0000&"
    assert AudioOverlayMixin._parse_ass_color("white") == (255, 255, 255)
    assert AudioOverlayMixin._parse_ass_color("#00FF00") == (0, 255, 0)
    assert AudioOverlayMixin._parse_ass_color((1, 2, 3)) == (1, 2, 3)
    assert AudioOverlayMixin._parse_ass_color("unknown-color") is None


def test_pos_to_ass_margins():
    """位置 → ASS alignment/margins：bottom-80 → 底部对齐 + margin。"""
    # ("center", 1072) = 1152-80 bottom-80
    al, ml, mr, mv = AudioOverlayMixin._pos_to_ass_margins(("center", 1072), 768, 1152)
    assert al == 2  # bottom-center
    assert mv == 80
    # left top
    al2, ml2, _, mv2 = AudioOverlayMixin._pos_to_ass_margins(("left", "top"), 768, 1152)
    assert al2 == 7  # top-left
    assert ml2 == 0 and mv2 == 0


def test_ass_escape_text():
    assert AudioOverlayMixin._ass_escape_text("a\nb") == "a\\Nb"
    assert AudioOverlayMixin._ass_escape_text("{x}") == "\\{x\\}"
    assert AudioOverlayMixin._ass_escape_text("a\\b") == "a\\\\b"


def test_ass_enabled_switch(monkeypatch):
    """灰度开关：默认开启，AGNES_SUBTITLE_ASS=0 关闭。"""
    monkeypatch.delenv("AGNES_SUBTITLE_ASS", raising=False)
    assert _subtitle_ass_enabled() is True
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "0")
    assert _subtitle_ass_enabled() is False
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "false")
    assert config_subtitle_ass_enabled() is False
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "1")
    assert config_subtitle_ass_enabled() is True


def test_ffmpeg_mux_with_subtitle_filter(monkeypatch):
    """传入 ASS 路径时 filter 链含 subtitles 滤镜（tpad→subtitles→apad 单链）。"""
    captured = {}

    def wrapped(cmd, desc=""):
        captured["cmd"] = cmd
        raise RuntimeError("stop-exec")

    monkeypatch.setattr(VideoConcatenator, "_run_ffmpeg", staticmethod(wrapped))
    with pytest.raises(RuntimeError):
        AudioOverlayMixin._ffmpeg_mux_aligned(
            "a.mp4", "b.mp3", "o.mp4", 5.0,
            subtitle_ass_path="/tmp/subs.srt.ass", fonts_dir="/fonts",
        )
    joined = " ".join(map(str, captured["cmd"]))
    assert "tpad=stop_mode=clone:stop_duration=5.00[v0];[v0]subtitles=" in joined
    assert "fontsdir='/fonts'" in joined
    assert "apad=whole_dur=5.00,volume=1.5" in joined


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_ass_disabled_falls_back_to_moviepy(tmp_path, monkeypatch):
    """AGNES_SUBTITLE_ASS=0：关闭 ASS 单链 → 回退 moviepy 多步路径。"""
    import subprocess

    srt = _write_srt(tmp_path)
    audio = str(tmp_path / "audio.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", "3", "-c:a", "libmp3lame", "-q:a", "4", audio],
        capture_output=True,
    )
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "0")
    descs = []
    orig = VideoConcatenator._run_ffmpeg

    def wrapped(cmd, desc=""):
        descs.append(desc)
        return orig(cmd, desc=desc)

    monkeypatch.setattr(VideoConcatenator, "_run_ffmpeg", staticmethod(wrapped))
    out = str(tmp_path / "final.mp4")
    AudioOverlayMixin.concat_videos_with_audio_overlay(
        [ASSET], audio, srt, out, _style(),
    )
    assert os.path.exists(out) and os.path.getsize(out) > 0
    # 不出现 single-pass mux；走 tpad/apad 分步 + moviepy 合成
    assert not any("single-pass" in d for d in descs), f"应关闭单链: {descs}"


def test_ffmpeg_mux_no_subtitle_filter(tmp_path, monkeypatch):
    """无字幕参数时不生成 subtitles 滤镜。"""
    captured = {}
    orig = VideoConcatenator._run_ffmpeg

    def wrapped(cmd, desc=""):
        captured["cmd"] = cmd
        # 不实际执行（仅验证命令构造）
        raise RuntimeError("skip-exec")

    monkeypatch.setattr(VideoConcatenator, "_run_ffmpeg", staticmethod(wrapped))
    with pytest.raises(RuntimeError):
        AudioOverlayMixin._ffmpeg_mux_aligned("a.mp4", "b.mp3", "o.mp4", 5.0)
    joined = " ".join(map(str, captured["cmd"]))
    assert "subtitles=" not in joined
    assert "tpad=stop_mode=clone:stop_duration=5.00" in joined


def test_ass_fontname():
    assert _ass_fontname("/resource/fonts/STHeitiMedium.ttc") == "STHeitiMedium"
    assert _ass_fontname("Arial") == "Arial"
