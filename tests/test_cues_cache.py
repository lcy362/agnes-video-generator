"""1.2 断点续传补全：词级 cues 持久化测试（续传免重采 TTS）。"""
import datetime
import os
from types import SimpleNamespace

import pytest

from core.pipelines import (
    BasePipeline,
    _cues_cache_path,
    _deserialize_sub_maker,
    _serialize_sub_maker,
)


def _make_sub_maker():
    """构造 edge_tts SubMaker 兼容对象（cues: start/end/content）。"""
    return SimpleNamespace(cues=[
        SimpleNamespace(
            start=datetime.timedelta(seconds=1.5),
            end=datetime.timedelta(seconds=2.0),
            content="你好",
        ),
        SimpleNamespace(
            start=datetime.timedelta(seconds=2.1),
            end=datetime.timedelta(seconds=2.8),
            content="世界",
        ),
    ])


class _DummyPipeline(BasePipeline):
    """最小实现（仅满足 ABC 抽象方法；_save/_load_cues_cache 不依赖 __init__）。"""

    async def run(self, state):
        return None


def _dummy_pipeline() -> BasePipeline:
    """绕过 __init__：_save/_load_cues_cache 不依赖实例属性。"""
    return object.__new__(_DummyPipeline)


# ── 序列化 / 反序列化往返 ───────────────────────────────────────────


def test_cues_serialize_roundtrip():
    sm = _make_sub_maker()
    raw = _serialize_sub_maker(sm)
    assert raw == [
        {"start": 1.5, "end": 2.0, "content": "你好"},
        {"start": 2.1, "end": 2.8, "content": "世界"},
    ]
    restored = _deserialize_sub_maker(raw)
    assert [c.content for c in restored.cues] == ["你好", "世界"]
    assert restored.cues[0].start == 1.5
    assert restored.cues[1].end == 2.8


def test_serialize_empty_sub_maker_returns_empty():
    assert _serialize_sub_maker(None) == []
    assert _serialize_sub_maker(SimpleNamespace(cues=[])) == []


# ── 缓存落盘 / 读取 ─────────────────────────────────────────────────


def test_cues_cache_save_load(tmp_path):
    p = _dummy_pipeline()
    audio = str(tmp_path / "narr.mp3")
    p._save_cues_cache(audio, _make_sub_maker())
    cache = _cues_cache_path(audio)
    assert os.path.exists(cache)
    restored = p._load_cues_cache(audio)
    assert restored is not None
    assert [c.content for c in restored.cues] == ["你好", "世界"]
    assert restored.cues[0].end == 2.0


def test_cues_cache_load_missing_returns_none(tmp_path):
    p = _dummy_pipeline()
    assert p._load_cues_cache(str(tmp_path / "missing.mp3")) is None


# ── _recover_sub_maker 优先读缓存，不重采 TTS ──────────────────────


async def test_recover_sub_maker_prefers_cache(monkeypatch, tmp_path):
    """有缓存时直接读缓存，harvest_cues（重新消费 TTS 流）不应被调用。"""
    p = _dummy_pipeline()
    audio = str(tmp_path / "narr.mp3")
    p._save_cues_cache(audio, _make_sub_maker())

    async def _fake_harvest(self, **kwargs):
        raise AssertionError("有缓存时不应调用 harvest_cues")

    monkeypatch.setattr("core.audio.tts.EdgeTTSEngine.harvest_cues", _fake_harvest)

    sub_cfg = SimpleNamespace(enabled=True, use_cue_timeline=True)
    audio_cfg = SimpleNamespace(voice="zh-CN-XiaoxiaoNeural", rate="+0%")
    sm = await p._recover_sub_maker("你好世界", audio_cfg, sub_cfg, audio_path=audio)
    assert sm is not None
    assert [c.content for c in sm.cues] == ["你好", "世界"]


async def test_recover_sub_maker_without_cache_calls_harvest(monkeypatch, tmp_path):
    """无缓存（旧产物）时回退 harvest_cues 采集。"""
    p = _dummy_pipeline()

    async def _fake_harvest(self, **kwargs):
        return _make_sub_maker()

    monkeypatch.setattr("core.audio.tts.EdgeTTSEngine.harvest_cues", _fake_harvest)

    sub_cfg = SimpleNamespace(enabled=True, use_cue_timeline=True)
    audio_cfg = SimpleNamespace(voice="zh-CN-XiaoxiaoNeural", rate="+0%")
    sm = await p._recover_sub_maker("你好世界", audio_cfg, sub_cfg, audio_path="")
    assert sm is not None
    assert [c.content for c in sm.cues] == ["你好", "世界"]
