"""Unit tests for web.routes.voice_routes — 试听端点（含失败分支）。

不触发真实 edge_tts 网络调用：``helpers._get_or_generate_preview`` 一律打桩。
"""
import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web import helpers  # noqa: E402
from web.routes import voice_routes  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_missing_voice_raises_400():
    with pytest.raises(HTTPException) as exc:
        _run(voice_routes.preview_voice(""))
    assert exc.value.status_code == 400


def test_generation_failure_raises_400(monkeypatch):
    """生成失败时：voice 经 safe_log 清洗后写日志，并转成 400。

    覆盖 S5145 修复点——voice 是查询参数（用户可控），直接 f-string 进日志
    会被判为日志注入，故必须清洗后再写。
    """
    async def _boom(voice_id, text):
        raise RuntimeError("incompatible script")

    monkeypatch.setattr(helpers, "_get_or_generate_preview", _boom)

    with pytest.raises(HTTPException) as exc:
        _run(voice_routes.preview_voice("zh-CN-XiaoxiaoNeural\r\nFAKE", "你好"))
    assert exc.value.status_code == 400
    assert "incompatible script" in exc.value.detail


def test_success_returns_file_response(monkeypatch, tmp_path):
    cached = tmp_path / "preview.mp3"
    cached.write_bytes(b"ID3\x00")

    async def _ok(voice_id, text):
        return str(cached)

    monkeypatch.setattr(helpers, "_get_or_generate_preview", _ok)
    resp = _run(voice_routes.preview_voice("zh-CN-XiaoxiaoNeural", "你好"))
    assert resp.media_type == "audio/mpeg"
    assert resp.headers.get("Cache-Control") == "public, max-age=86400"
