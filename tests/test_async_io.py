"""Unit tests for core.async_io — 异步文件读写辅助（Sonar S7493 修复配套）。

不依赖网络 / API Key / ffmpeg，仅用 tmp_path 做真实文件读写。
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.async_io import async_open, read_bytes, read_text, write_bytes, write_text  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════
# write_text / read_text
# ═══════════════════════════════════════════════════

def test_write_then_read_text_roundtrip(tmp_path):
    path = str(tmp_path / "story.txt")
    _run(write_text(path, "第一段\n第二段"))
    assert _run(read_text(path)) == "第一段\n第二段"


def test_write_text_overwrites_existing(tmp_path):
    path = str(tmp_path / "srt.txt")
    _run(write_text(path, "old"))
    _run(write_text(path, "new"))
    assert _run(read_text(path)) == "new"


def test_write_text_creates_missing_parent_only_when_exists(tmp_path):
    """父目录不存在时由调用方负责创建；这里只验证已存在目录内的写入。"""
    d = tmp_path / "sub"
    d.mkdir()
    path = str(d / "a.txt")
    _run(write_text(path, "x"))
    assert os.path.exists(path)


def test_read_text_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        _run(read_text(str(tmp_path / "nope.txt")))


# ═══════════════════════════════════════════════════
# write_bytes / read_bytes
# ═══════════════════════════════════════════════════

def test_write_then_read_bytes_roundtrip(tmp_path):
    path = str(tmp_path / "ref.png")
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    _run(write_bytes(path, payload))
    assert _run(read_bytes(path)) == payload


def test_write_bytes_overwrites_existing(tmp_path):
    path = str(tmp_path / "up.png")
    _run(write_bytes(path, b"aaaa"))
    _run(write_bytes(path, b"bb"))
    assert _run(read_bytes(path)) == b"bb"


# ═══════════════════════════════════════════════════
# async_open（流式写入场景，如 TTS 分块落盘）
# ═══════════════════════════════════════════════════

def test_async_open_streaming_write(tmp_path):
    path = str(tmp_path / "audio.mp3")

    async def _main():
        async with await async_open(path, "wb") as f:
            for chunk in (b"ID3", b"\x01\x02", b"\xff\xfb"):
                await f.write(chunk)
        return await read_bytes(path)

    assert _run(_main()) == b"ID3\x01\x02\xff\xfb"


def test_async_open_read_lines(tmp_path):
    path = str(tmp_path / "lines.txt")
    _run(write_text(path, "a\nb\nc"))

    async def _main():
        async with await async_open(path, "r", encoding="utf-8") as f:
            return [line.strip() async for line in f]

    assert _run(_main()) == ["a", "b", "c"]
