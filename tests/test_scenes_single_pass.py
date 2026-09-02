"""2.2 poetry 多场景单链合成测试（视频 -c copy 拼接 + 音频合并 + 总字幕一次编码）。"""
import os
import subprocess

import pytest

# 真实调用 subprocess/ffmpeg 进行视频合成，属慢速集成测试，默认排除，CI 全量执行。
pytestmark = pytest.mark.slow

from core.compositor.concatenator.audio_overlay import AudioOverlayMixin
from core.compositor.concatenator.concat import VideoConcatenator

ASSET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_regression", "assets", "test_video_5s.mp4",
)
_HAS_ASSET = os.path.exists(ASSET)

_SRT = """1
00:00:00,200 --> 00:00:02,000
第一句
"""


def _write_srt(tmp_path, name, content):
    p = os.path.join(str(tmp_path), name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def _make_audio(tmp_path, name, seconds=2):
    ap = os.path.join(str(tmp_path), name)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", str(seconds), "-c:a", "libmp3lame", "-q:a", "4", ap],
        capture_output=True,
    )
    return ap


def test_merge_scene_srts_offset(tmp_path):
    """两场景 SRT 按偏移合并 → 时间轴平移 + 重新编号。"""
    s1 = _write_srt(tmp_path, "s1.srt", _SRT)
    s2 = _write_srt(tmp_path, "s2.srt", _SRT.replace("第一句", "第二句"))
    out = os.path.join(str(tmp_path), "total.srt")
    ok = AudioOverlayMixin._merge_scene_srts([s1, s2], [0.0, 5.0], out)
    assert ok
    with open(out, "r", encoding="utf-8") as f:
        content = f.read()
    assert "00:00:00,200" in content  # 场景1 起点不变
    assert "00:00:05,200" in content  # 场景2 起点 +5s
    assert "第一句" in content
    assert "第二句" in content
    # 重新编号：共 2 条
    assert content.count("\n\n") >= 1


def test_merge_scene_srts_missing_input(tmp_path):
    """SRT 全缺失 → 返回 False。"""
    out = os.path.join(str(tmp_path), "total.srt")
    assert AudioOverlayMixin._merge_scene_srts([None, ""], [0.0, 5.0], out) is False


def test_single_pass_asset_missing_returns_none(tmp_path):
    """素材缺失 → 返回 None（调用方回退逐场景）。"""
    result = AudioOverlayMixin.concat_scenes_single_pass(
        ["/nonexistent/a.mp4", "/nonexistent/b.mp4"],
        ["/nonexistent/a.mp3", "/nonexistent/b.mp3"],
        [None, None],
        os.path.join(str(tmp_path), "out.mp4"),
        None,
    )
    assert result is None


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_single_pass_no_subtitle(tmp_path):
    """无字幕：两场景单链一次合成，输出时长 = 两视频之和。"""
    a1 = _make_audio(tmp_path, "a1.mp3", 2)
    a2 = _make_audio(tmp_path, "a2.mp3", 2)
    out = os.path.join(str(tmp_path), "final.mp4")
    result = AudioOverlayMixin.concat_scenes_single_pass(
        [ASSET, ASSET], [a1, a2], [None, None], out, None,
    )
    assert result == out
    assert os.path.exists(out) and os.path.getsize(out) > 0
    dur = VideoConcatenator._get_duration(out)
    assert dur > 9, f"输出时长应≈10s（两段 5s 视频），实际 {dur:.1f}s"


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_single_pass_with_subtitle(tmp_path):
    """有字幕：两场景单链一次合成，含偏移合并后的字幕。"""
    a1 = _make_audio(tmp_path, "a1.mp3", 2)
    a2 = _make_audio(tmp_path, "a2.mp3", 2)
    s1 = _write_srt(tmp_path, "s1.srt", _SRT)
    s2 = _write_srt(tmp_path, "s2.srt", _SRT.replace("第一句", "第二句"))
    out = os.path.join(str(tmp_path), "final.mp4")
    from models.task import SubtitleStyle

    style = SubtitleStyle(
        font="STHeitiMedium.ttc", color="white",
        position=("center", "bottom-80"), fontsize=48,
        stroke_color="black", stroke_width=2,
    )
    result = AudioOverlayMixin.concat_scenes_single_pass(
        [ASSET, ASSET], [a1, a2], [s1, s2], out, style,
    )
    assert result == out
    assert os.path.exists(out) and os.path.getsize(out) > 0
    dur = VideoConcatenator._get_duration(out)
    assert dur > 9, f"输出时长应≈10s，实际 {dur:.1f}s"
