"""
单元测试：core.compositor.ffmpeg_tool — ffmpeg/ffprobe 可执行文件解析。

覆盖 resolve_binary / resolve_ffmpeg / resolve_ffprobe / _resolve /
_resolve_builtin_ffmpeg / _sibling 的全部分支：
- 环境变量显式指定优先；
- 系统 PATH 兜底；
- imageio-ffmpeg 内置二进制；
- 全部不可用时返回 None；
- 未知二进制名抛 ValueError；
- 进程级缓存。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import core.compositor.ffmpeg_tool as ft


@pytest.fixture(autouse=True)
def _clear_cache():
    ft._cache.clear()
    yield
    ft._cache.clear()


def test_unknown_binary_raises():
    with pytest.raises(ValueError):
        ft.resolve_binary("unknown-prog")


def test_explicit_env_override(monkeypatch, tmp_path):
    """环境变量显式指定且存在 → 优先返回。"""
    fake = tmp_path / "ffmpeg-custom"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("FFMPEG_BINARY", str(fake))
    monkeypatch.setenv("FFPROBE_BINARY", "")
    # 确保 PATH 与内置不可干扰
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    monkeypatch.setattr(ft, "_resolve_builtin_ffmpeg", lambda: None)

    assert ft.resolve_ffmpeg() == str(fake)


def test_system_path_fallback(monkeypatch):
    """env 未指定 → 走系统 PATH。"""
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else "/usr/bin/ffprobe")
    monkeypatch.setattr(ft, "_resolve_builtin_ffmpeg", lambda: None)

    assert ft.resolve_ffmpeg() == "/usr/bin/ffmpeg"
    assert ft.resolve_ffprobe() == "/usr/bin/ffprobe"


def test_env_override_nonexistent_falls_back_to_path(monkeypatch):
    """env 指定但文件不存在 → 回退 PATH。"""
    monkeypatch.setenv("FFMPEG_BINARY", "/nonexistent/ffmpeg")
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(ft, "_resolve_builtin_ffmpeg", lambda: None)

    assert ft.resolve_ffmpeg() == "/usr/bin/ffmpeg"


def test_builtin_ffmpeg(monkeypatch):
    """无 env 无 PATH → imageio-ffmpeg 内置 ffmpeg。"""
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    monkeypatch.setattr(ft, "_resolve_builtin_ffmpeg", lambda: "/opt/venv/imageio_ffmpeg/bin/ffmpeg")

    assert ft.resolve_ffmpeg() == "/opt/venv/imageio_ffmpeg/bin/ffmpeg"


def test_builtin_ffprobe_sibling_found(monkeypatch, tmp_path):
    """ffmpeg 内置存在且同目录有 ffprobe → 返回兄弟程序。"""
    monkeypatch.delenv("FFPROBE_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    bin_dir = tmp_path
    fake_ff = bin_dir / "ffmpeg"
    fake_ff.write_text("x")
    fake_ffp = bin_dir / "ffprobe"
    fake_ffp.write_text("x")
    monkeypatch.setattr(ft, "_cache", {"ffmpeg": str(fake_ff)})

    assert ft.resolve_ffprobe() == str(fake_ffp)


def test_builtin_ffprobe_sibling_missing(monkeypatch, tmp_path):
    """ffmpeg 内置存在但无 ffprobe 兄弟 → ffprobe 返回 None。"""
    monkeypatch.delenv("FFPROBE_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    fake_ff = tmp_path / "ffmpeg"
    fake_ff.write_text("x")
    monkeypatch.setattr(ft, "_cache", {"ffmpeg": str(fake_ff)})

    assert ft.resolve_ffprobe() is None


def test_all_unavailable_returns_none(monkeypatch):
    """全部不可用 → None。"""
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    monkeypatch.setattr(ft, "_resolve_builtin_ffmpeg", lambda: None)

    assert ft.resolve_ffmpeg() is None


def test_builtin_unavailable_exception(monkeypatch):
    """内置 imageio_ffmpeg 导入失败 → _resolve_builtin_ffmpeg 捕获并返回 None。"""
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "imageio_ffmpeg":
            raise ImportError("no builtin")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert ft._resolve_builtin_ffmpeg() is None
    assert ft.resolve_ffmpeg() is None


def test_cache_hit(monkeypatch):
    """进程级缓存：第二次调用不再重新解析。"""
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(ft, "_resolve_builtin_ffmpeg", lambda: None)

    assert ft.resolve_ffmpeg() == "/usr/bin/ffmpeg"
    # 清空 PATH 解析，但缓存仍返回
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    assert ft.resolve_ffmpeg() == "/usr/bin/ffmpeg"
