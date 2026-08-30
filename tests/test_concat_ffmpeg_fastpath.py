"""2.1a 拼接 ffmpeg 化测试（concat demuxer + -c copy fast path，失败回退）。"""
import os

import pytest

from core.compositor.concatenator.concat import ConcatMixin

ASSET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_regression", "assets", "test_video_5s.mp4",
)

_HAS_ASSET = os.path.exists(ASSET)


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_ffmpeg_copy_concat_same_resolution(tmp_path):
    """同分辨率/帧率片段 → fast path 成功，输出存在且非空。"""
    out = str(tmp_path / "concat_fast.mp4")
    assert ConcatMixin._try_ffmpeg_copy_concat([ASSET, ASSET], out) is True
    assert os.path.getsize(out) > 0


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_concat_videos_integration_duration(tmp_path):
    """集成：两段 ~5s 视频拼接后时长 ≈10s（fast path 或 moviepy 回退均需成立）。"""
    out = str(tmp_path / "concat.mp4")
    ConcatMixin.concat_videos([ASSET, ASSET], out)
    assert os.path.exists(out) and os.path.getsize(out) > 0
    dur = ConcatMixin._get_duration(out)
    assert dur > 8, f"拼接后时长应≈10s，实际 {dur:.1f}s"


@pytest.mark.skipif(not _HAS_ASSET, reason="mock 素材缺失")
def test_concat_single_video_copies(tmp_path):
    """单视频：直接 copy，不触发拼接。"""
    out = str(tmp_path / "single.mp4")
    ConcatMixin.concat_videos([ASSET], out)
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_concat_empty_raises():
    with pytest.raises(RuntimeError, match="No videos"):
        ConcatMixin.concat_videos([], "x.mp4")


def test_ffmpeg_copy_concat_missing_file_returns_false(tmp_path):
    """探针失败（文件不存在）→ 返回 False，走 moviepy 回退。"""
    out = str(tmp_path / "out.mp4")
    assert ConcatMixin._try_ffmpeg_copy_concat(
        [str(tmp_path / "nope1.mp4"), str(tmp_path / "nope2.mp4")], out,
    ) is False
