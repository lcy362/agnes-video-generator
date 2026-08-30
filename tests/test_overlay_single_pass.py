"""2.1b 视频+音频单条 ffmpeg 链一次编码测试（无字幕 fast path）。"""
import os
import subprocess

import pytest

from core.compositor.concatenator.audio_overlay import AudioOverlayMixin
from core.compositor.concatenator.concat import VideoConcatenator

ASSET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_regression", "assets", "test_video_5s.mp4",
)
_HAS_ASSET = os.path.exists(ASSET)


def _make_audio(tmp_path, seconds=3):
    ap = str(tmp_path / "audio.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", str(seconds), "-c:a", "libmp3lame", "-q:a", "4", ap],
        capture_output=True,
    )
    return ap


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_overlay_no_subtitle_single_pass(tmp_path, monkeypatch):
    """无字幕：视频+音频单条 ffmpeg 链一次编码（无 tpad/apad/moviepy 分步）。"""
    audio = _make_audio(tmp_path, 3)
    calls = []
    orig = VideoConcatenator._run_ffmpeg  # staticmethod 经类访问即函数本身

    def wrapped(cmd, desc=""):
        calls.append(desc)
        return orig(cmd, desc=desc)

    monkeypatch.setattr(VideoConcatenator, "_run_ffmpeg", staticmethod(wrapped))

    out = str(tmp_path / "final.mp4")
    AudioOverlayMixin.concat_videos_with_audio_overlay(
        [ASSET, ASSET], audio, None, out,
    )
    assert os.path.exists(out) and os.path.getsize(out) > 0
    # Step1 走 2.1a（独立 subprocess，不进 _run_ffmpeg）；此处应仅一次 mux
    assert len(calls) == 1, f"应仅一次单链 mux 编码，实际调用: {calls}"
    dur = VideoConcatenator._get_duration(out)
    assert dur > 4.5, f"输出时长应≈5s（视频更长），实际 {dur:.1f}s"


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_overlay_audio_longer_than_video(tmp_path):
    """音频长于视频：fast path 应 tpad 冻结尾帧补齐到音频时长。"""
    audio = _make_audio(tmp_path, 8)  # 8s > 视频 5s
    out = str(tmp_path / "final2.mp4")
    AudioOverlayMixin.concat_videos_with_audio_overlay(
        [ASSET], audio, None, out,
    )
    assert os.path.exists(out) and os.path.getsize(out) > 0
    dur = VideoConcatenator._get_duration(out)
    assert dur > 7, f"输出时长应≈8s（音频更长，尾帧冻结补齐），实际 {dur:.1f}s"
