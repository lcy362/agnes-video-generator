"""TTSEngines 与 SubtitleGenerator 覆盖率补充测试（自包含，不触网）。

覆盖：
  - core/audio/tts.py          EdgeTTSEngine(generate/harvest_cues 成功与重试降级) + SilentTTSEngine
  - core/audio/subtitle/generator.py  SRT 生成各分支（长句拆行/分块/词级细粒度/scene-aware/解析等）

ffmpeg / edge_tts / 文件 IO 均以 mock / tmp 目录实现，完全不触网、不慢。
"""
import datetime
import os
import sys
import asyncio
from types import SimpleNamespace

import pytest

PROJECT_ROOT = "/Users/lcy/video/agnes-video-generator"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core.audio.tts as tts_mod
from core.audio.subtitle import SubtitleGenerator


def run(coro):
    return asyncio.run(coro)


class _FastAsyncio:
    """替换 asyncio.sleep 为无等待，避免慢速测试。"""

    async def sleep(self, *a, **k):
        return None


# ── mock 构件 ──
class FakeSubMaker:
    def __init__(self, cues=None):
        self.cues = list(cues) if cues is not None else []
        self._feeds = []

    def feed(self, chunk):
        self._feeds.append(chunk)


def make_communicate(results):
    """构造 edge_tts.Communicate 假类。

    results 为行为序列：元素是 "chunk 列表"(成功) 或 Exception(抛错)，每次
    stream() 消费一个；耗尽后重复最后一个结果。暴露 last_rate/last_voice。
    """
    it = iter(results)
    last = results[-1]

    class FakeCommunicate:
        last_rate = None
        last_voice = None

        def __init__(self, text, voice=None, rate=None):
            self.text = text
            self.voice = voice
            self.rate = rate
            FakeCommunicate.last_rate = rate
            FakeCommunicate.last_voice = voice

        async def stream(self):
            try:
                r = next(it)
            except StopIteration:
                r = last
            if isinstance(r, Exception):
                raise r
            for c in r:
                yield c

    return FakeCommunicate


def mk_cue(start, end, content):
    return SimpleNamespace(
        start=datetime.timedelta(seconds=start),
        end=datetime.timedelta(seconds=end),
        content=content,
    )


# ═══════════════════════ core/audio/tts.py ═══════════════════════

class TestEdgeTTSEngineGenerate:
    def _chunks(self, words):
        chunks = []
        for w in words:
            chunks.append({"type": "WordBoundary", "data": w, "offset": 0, "duration": 1})
            chunks.append({"type": "audio", "data": b"x"})
        chunks.append({"type": "SentenceBoundary", "data": "sent", "offset": 0, "duration": 1})
        return chunks

    def test_generate_success(self, monkeypatch, tmp_path):
        FakeCommunicate = make_communicate([self._chunks(["你", "好"])])
        monkeypatch.setattr(tts_mod.edge_tts, "Communicate", FakeCommunicate)

        calls = {"sub": FakeSubMaker([mk_cue(0, 1, "你")])}
        monkeypatch.setattr(tts_mod.edge_tts, "SubMaker", lambda: calls["sub"])

        out = str(tmp_path / "a.mp3")
        path, subm = run(tts_mod.EdgeTTSEngine().generate("你好", out, voice="zh-CN-XiaoxiaoNeural", rate="+20%"))
        assert path == out
        assert os.path.exists(out)
        assert calls["sub"]._feeds  # 收到了 WordBoundary/SentenceBoundary
        assert FakeCommunicate.last_rate == "+20%"
        assert FakeCommunicate.last_voice == "zh-CN-XiaoxiaoNeural"

    def test_generate_retry_then_success(self, monkeypatch, tmp_path):
        FakeCommunicate = make_communicate([RuntimeError("boom"), self._chunks(["你"])])
        monkeypatch.setattr(tts_mod.edge_tts, "Communicate", FakeCommunicate)
        monkeypatch.setattr(tts_mod.edge_tts, "SubMaker", FakeSubMaker)
        monkeypatch.setattr(tts_mod, "asyncio", _FastAsyncio())

        out = str(tmp_path / "r.mp3")
        path, _ = run(tts_mod.EdgeTTSEngine().generate("你好", out))
        assert path == out
        assert os.path.exists(out)

    def test_generate_fails_after_retries(self, monkeypatch, tmp_path):
        FakeCommunicate = make_communicate([RuntimeError("e1"), RuntimeError("e2")])
        monkeypatch.setattr(tts_mod.edge_tts, "Communicate", FakeCommunicate)
        monkeypatch.setattr(tts_mod.edge_tts, "SubMaker", FakeSubMaker)
        monkeypatch.setattr(tts_mod, "asyncio", _FastAsyncio())

        out = str(tmp_path / "f.mp3")
        with pytest.raises(RuntimeError):
            run(tts_mod.EdgeTTSEngine().generate("你好", out))
        assert not os.path.exists(out)
        assert not os.path.exists(out + ".tmp")


class TestHarvestCues:
    def _wordchunk(self, w):
        return {"type": "WordBoundary", "data": w, "offset": 0, "duration": 1}

    def test_harvest_success(self, monkeypatch):
        FakeCommunicate = make_communicate([[self._wordchunk("w"), self._wordchunk("x")]])
        monkeypatch.setattr(tts_mod.edge_tts, "Communicate", FakeCommunicate)
        sm = FakeSubMaker([mk_cue(0, 1, "w"), mk_cue(1, 2, "x")])
        monkeypatch.setattr(tts_mod.edge_tts, "SubMaker", lambda: sm)

        subm = run(tts_mod.EdgeTTSEngine().harvest_cues("测试", rate="-10%"))
        assert subm is sm
        assert len(sm._feeds) == 2

    def test_harvest_retry_then_success(self, monkeypatch):
        FakeCommunicate = make_communicate([RuntimeError("x"), [self._wordchunk("w")]])
        monkeypatch.setattr(tts_mod.edge_tts, "Communicate", FakeCommunicate)
        monkeypatch.setattr(tts_mod.edge_tts, "SubMaker", FakeSubMaker)
        monkeypatch.setattr(tts_mod, "asyncio", _FastAsyncio())
        run(tts_mod.EdgeTTSEngine().harvest_cues("你好"))

    def test_harvest_fails_after_retries(self, monkeypatch):
        FakeCommunicate = make_communicate([RuntimeError("e1"), RuntimeError("e2")])
        monkeypatch.setattr(tts_mod.edge_tts, "Communicate", FakeCommunicate)
        monkeypatch.setattr(tts_mod.edge_tts, "SubMaker", FakeSubMaker)
        monkeypatch.setattr(tts_mod, "asyncio", _FastAsyncio())
        with pytest.raises(RuntimeError):
            run(tts_mod.EdgeTTSEngine().harvest_cues("你好"))


class TestSilentTTSEngine:
    def _patch_ffmpeg(self, monkeypatch, returncode=0, stderr=b""):
        class FakeProc:
            def __init__(self):
                self.returncode = returncode

            async def communicate(self):
                return None, stderr

        created = {}

        async def _fake_exec(*args, **kwargs):
            created["args"] = args
            created["kwargs"] = kwargs
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        return created

    def test_with_duration_success(self, monkeypatch, tmp_path):
        created = self._patch_ffmpeg(monkeypatch)
        out = str(tmp_path / "s.mp3")
        path, cues = run(tts_mod.SilentTTSEngine().generate("x", out, duration_sec=3.0))
        assert path == out
        assert cues is None
        assert "-t" in created["args"]

    def test_estimate_duration(self, monkeypatch, tmp_path):
        self._patch_ffmpeg(monkeypatch)
        out = str(tmp_path / "e.mp3")
        path, _ = run(tts_mod.SilentTTSEngine().generate("一二三四五六七八", out))
        assert path == out

    def test_ffmpeg_failure(self, monkeypatch, tmp_path):
        self._patch_ffmpeg(monkeypatch, returncode=1, stderr=b"no codec")
        out = str(tmp_path / "bad.mp3")
        with pytest.raises(RuntimeError) as ei:
            run(tts_mod.SilentTTSEngine().generate("x", out, duration_sec=1.0))
        assert "ffmpeg silent generation failed" in str(ei.value)


# ═══════════════════ core/audio/subtitle/generator.py ═══════════════════

class TestSplitLongText:
    def test_empty_or_has_newline(self):
        assert SubtitleGenerator._split_long_text("") == ""
        assert SubtitleGenerator._split_long_text("a\nb") == "a\nb"

    def test_cjk_short(self):
        assert SubtitleGenerator._split_long_text("你好世界", 4) == "你好世界"

    def test_cjk_split_at_punct(self):
        txt = "来一大段很长的中文台词内容，需要被拆分出来"
        r = SubtitleGenerator._split_long_text(txt, 5)
        assert "\n" in r
        assert len(r.replace("\n", "")) == len(txt)

    def test_cjk_split_mid_no_punct(self):
        txt = "这是一段没有标点的很长中文文本需要强制拆分"
        r = SubtitleGenerator._split_long_text(txt, 6)
        assert "\n" in r
        parts = r.split("\n")
        assert "".join(parts) == txt

    def test_latin_short(self):
        assert SubtitleGenerator._split_long_text("hello world", 12) == "hello world"

    def test_latin_split_words(self):
        txt = "this is a very long english sentence that must be wrapped"
        r = SubtitleGenerator._split_long_text(txt, 14)
        assert "\n" in r
        assert all(len(p) > 0 for p in r.split("\n"))

    def test_latin_single_word_forced(self):
        r = SubtitleGenerator._split_long_text("supercalifragilistic", 4)
        assert "\n" not in r
        assert r == "supercalifragilistic"

    def test_width_aware_cjk(self):
        r = SubtitleGenerator._split_long_text("这是一段需要按视频宽度进行感知换行的中文字幕文本内容", video_width=768, fontsize=42)
        assert "\n" in r

    def test_width_aware_latin(self):
        r = SubtitleGenerator._split_long_text("this text needs width aware wrapping done for latin", video_width=768, fontsize=42)
        assert "\n" in r


class TestChunkText:
    def test_empty(self):
        assert SubtitleGenerator._chunk_text("   ", 5, True) == []

    def test_short(self):
        assert SubtitleGenerator._chunk_text("abc", 10, True) == ["abc"]

    def test_cjk_chunks(self):
        r = SubtitleGenerator._chunk_text("一二三四五六七八九", 4, True)
        assert "".join(r) == "一二三四五六七八九"
        assert all(len(c) <= 4 for c in r)

    def test_latin_chunks(self):
        r = SubtitleGenerator._chunk_text("one two three four five", 8, False)
        assert all(len(c) <= 8 for c in r)


class TestEnforceMaxLines:
    def test_empty(self):
        assert SubtitleGenerator.enforce_max_lines("") == ""
        assert SubtitleGenerator.enforce_max_lines("  ") == "  "

    def test_parse_error_returns_original(self):
        assert SubtitleGenerator.enforce_max_lines("not a valid srt !!") == "not a valid srt !!"

    def test_short_content_kept(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\n你好\n"
        assert "你好" in SubtitleGenerator.enforce_max_lines(srt)

    def test_long_cjk_split(self):
        srt = "1\n00:00:00,000 --> 00:00:05,000\n这是一段非常非常长的中文字幕内容需要被切分为多行来显示避免溢出屏幕\n"
        out = SubtitleGenerator.enforce_max_lines(srt, video_width=768, fontsize=42)
        assert "-->" in out
        assert out.count("-->") >= 1

    def test_multiple_entries_renumbered(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
            "2\n00:00:03,000 --> 00:00:08,000\n这是一段非常非常长的中文字幕需要被拆分成很多小块内容来显示\n"
        )
        out = SubtitleGenerator.enforce_max_lines(srt)
        assert out.count("-->") >= 2


class TestCueTimeHelpers:
    def test_cue_to_srt_time(self):
        assert SubtitleGenerator.cue_to_srt_time(0) == "00:00:00,000"
        assert SubtitleGenerator.cue_to_srt_time(1.5) == "00:00:01,500"
        assert SubtitleGenerator.cue_to_srt_time(3661.25) == "01:01:01,250"

    def test_cue_total_seconds(self):
        assert SubtitleGenerator._cue_total_seconds(datetime.timedelta(seconds=2.5)) == 2.5
        assert SubtitleGenerator._cue_total_seconds(7.0) == 7.0


class TestFineSrtFromWordCues:
    def test_empty(self):
        assert SubtitleGenerator._generate_fine_srt_from_word_cues([]) == ""

    def test_blank_content_dropped(self):
        assert SubtitleGenerator._generate_fine_srt_from_word_cues([mk_cue(0, 1, "  ")]) == ""

    def test_groups_produced(self):
        cues = [mk_cue(i * 0.5, i * 0.5 + 0.4, f"词{i}") for i in range(6)]
        out = SubtitleGenerator._generate_fine_srt_from_word_cues(cues)
        assert "-->" in out and out.strip()

    def test_diacritics_stripped(self):
        cues = [mk_cue(0, 0.5, "مُحَمَّد"), mk_cue(0.5, 1.0, "سَلَام")]
        out = SubtitleGenerator._generate_fine_srt_from_word_cues(cues)
        assert "\u064b" not in out
        assert "محم" in out


class TestGroupItemsToSrt:
    def test_empty(self):
        assert SubtitleGenerator._group_items_to_srt([]) == ""

    def test_no_break_single_group(self):
        items = [(0, 0.5, "你"), (0.5, 1.0, "好")]
        out = SubtitleGenerator._group_items_to_srt(items)
        assert "你好" in out
        assert out.count("-->") == 1

    def test_break_by_duration(self):
        items = []
        t = 0.0
        for i in range(20):
            items.append((t, t + 0.15, f"w{i}"))
            t += 0.2
        out = SubtitleGenerator._group_items_to_srt(items, max_duration=1.8, max_chars=14)
        assert out.count("-->") > 1

    def test_break_by_pause(self):
        # 每个词间大停顿，且组内已积累 >4 字 → 触发断句
        items = []
        t = 0.0
        for i in range(10):
            start = t + (0.6 if i > 0 else 0.0)
            items.append((start, start + 0.4, f"word{i}bb"))
            t = start + 0.4
        out = SubtitleGenerator._group_items_to_srt(items, max_duration=5.0, max_chars=100)
        assert out.count("-->") > 1

    def test_tail_merge(self):
        items = [(0, 3.0, "aaaa"), (3.0, 3.2, "bb"), (3.2, 4.5, "cc")]
        out = SubtitleGenerator._group_items_to_srt(items, max_duration=5.0, max_chars=100)
        assert out.count("-->") >= 1

    def test_prominence_extension(self):
        items = [(0, 1.0, "注意！")]
        out = SubtitleGenerator._group_items_to_srt(items)
        assert "-->" in out


class TestDetectProminence:
    def test_empty(self):
        assert SubtitleGenerator._detect_prominence("  ") == 1.0

    def test_short_exclaim(self):
        assert SubtitleGenerator._detect_prominence("小心！") == 1.5

    def test_short_plain(self):
        assert SubtitleGenerator._detect_prominence("okay") == 1.3

    def test_keyword(self):
        assert SubtitleGenerator._detect_prominence("这是非常重要的内容需要关注") == 1.3

    def test_attention(self):
        assert SubtitleGenerator._detect_prominence("Attention please careful here") == 1.3

    def test_normal_long(self):
        assert SubtitleGenerator._detect_prominence("这是一段普通的不算突出的较长内容文本") == 1.0


class TestSceneAwareSrt:
    def test_empty(self):
        assert SubtitleGenerator._generate_scene_aware_srt([], []) == ""

    def test_scene_start_times_provided(self):
        out = SubtitleGenerator._generate_scene_aware_srt(
            ["第一句台词。第二句！", "第三句，继续吧"],
            [4.0, 4.0],
            scene_start_times=[0.0, 4.0],
        )
        assert "-->" in out

    def test_accumulated_start_times(self):
        out = SubtitleGenerator._generate_scene_aware_srt(["你好世界", "再见世界"], [3.0, 3.0])
        assert "-->" in out

    def test_blank_scene_and_long_subsegment(self):
        out = SubtitleGenerator._generate_scene_aware_srt(
            ["   ", "这是一段特别特别长的第一句内容，需要拆分成子段，逗号后面的也要，继续追加文字来触发切分"],
            [2.0, 5.0],
        )
        assert "-->" in out


class TestSceneCharRanges:
    def test_empty(self):
        assert SubtitleGenerator._scene_char_ranges([]) is None

    def test_ranges_cjk(self):
        r = SubtitleGenerator._scene_char_ranges(["你好世界", "abc"])
        assert r == [(0, 4), (4, 7)]

    def test_zero_norm_word(self):
        r = SubtitleGenerator._scene_char_ranges(["!!!", "abc"])
        assert r == [(0, 0), (0, 3)]


class TestGenerateCueAwareSrt:
    def _cues(self, *c):
        return SimpleNamespace(cues=list(c))

    def test_no_cues(self):
        assert SubtitleGenerator.generate_cue_aware_srt(self._cues(), ["你好"]) == ""

    def test_no_object(self):
        assert SubtitleGenerator.generate_cue_aware_srt(object(), ["你好"]) == ""

    def test_no_text_items(self):
        assert SubtitleGenerator.generate_cue_aware_srt(self._cues(mk_cue(0, 1, "   ")), ["你好"]) == ""

    def test_strategy_a(self):
        cues = self._cues(
            mk_cue(0, 0.5, "你"), mk_cue(0.5, 1.0, "好"),
            mk_cue(1.0, 1.5, "世"), mk_cue(1.5, 2.0, "界"),
        )
        out = SubtitleGenerator.generate_cue_aware_srt(cues, ["你好", "世界"])
        assert "你好" in out
        assert "世界" in out
        assert out.count("-->") == 2

    def test_strategy_a_gap_nearest(self):
        cues = self._cues(mk_cue(0, 0.5, "兼容"))
        out = SubtitleGenerator.generate_cue_aware_srt(cues, ["  ", "  "], audio_duration=10.0)
        assert out

    def test_strategy_a_scene_else_nearest(self):
        # 累计字符位置超出全部场景区间 → 归属到中点最近的场景（line 645-646）
        cues = self._cues(mk_cue(0, 0.5, "苹果梨"), mk_cue(0.5, 1.0, "苹果梨"))
        out = SubtitleGenerator.generate_cue_aware_srt(cues, ["你好", "世界"], audio_duration=10.0)
        assert out

    def test_clamp_audio_duration(self):
        cues = self._cues(
            mk_cue(0, 0.5, "你"), mk_cue(0.5, 1.0, "好"),
            mk_cue(1.0, 3.5, "世"), mk_cue(3.5, 4.0, "界"),
        )
        out = SubtitleGenerator.generate_cue_aware_srt(cues, ["你好世界"], audio_duration=2.0)
        assert out.count("-->") >= 1

    def test_tail_cue_clamped_to_audio(self):
        cues = self._cues(mk_cue(0, 5.0, "你"))
        out = SubtitleGenerator.generate_cue_aware_srt(cues, ["你"], audio_duration=2.0)
        assert "00:00:02,000" in out


class TestCuesToSrt:
    def _read(self, p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_fine_grained_path(self, tmp_path):
        cues = [mk_cue(i * 0.5, i * 0.5 + 0.4, f"w{i}") for i in range(7)]
        out = SubtitleGenerator.cues_to_srt(SimpleNamespace(cues=cues), str(tmp_path / "s.srt"))
        assert os.path.exists(out)
        assert "-->" in self._read(out)

    def test_get_srt_fallback(self, tmp_path):
        class Cues:
            def get_srt(self):
                return "1\n00:00:00,000 --> 00:00:02,000\n你好\n"

        out = SubtitleGenerator.cues_to_srt(Cues(), str(tmp_path / "g.srt"))
        assert "你好" in self._read(out)

    def test_generate_subs_vtt(self, tmp_path):
        class Cues:
            def generate_subs(self):
                return (
                    "WEBVTT\n\n"
                    "00:00:00.000 --> 00:00:02.500\n你好 world\n\n"
                    "00:00:03.000 --> 00:00:05.000\n第二行\n"
                )

        out = SubtitleGenerator.cues_to_srt(Cues(), str(tmp_path / "v.srt"))
        assert "-->" in self._read(out)

    def test_no_attrs_empty(self, tmp_path):
        out = SubtitleGenerator.cues_to_srt(SimpleNamespace(), str(tmp_path / "e.srt"))
        assert os.path.exists(out)


class TestTextToSrt:
    def _read(self, p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    def test_empty_text(self, tmp_path):
        out = SubtitleGenerator.text_to_srt("", str(tmp_path / "a.srt"), 3.0)
        assert os.path.exists(out)
        assert self._read(out) == ""

    def test_zero_duration(self, tmp_path):
        out = SubtitleGenerator.text_to_srt("你好", str(tmp_path / "b.srt"), 0)
        assert self._read(out) == ""

    def test_normal(self, tmp_path):
        out = SubtitleGenerator.text_to_srt("第一句。第二句！第三句？", str(tmp_path / "c.srt"), 6.0)
        assert self._read(out).count("-->") == 3

    def test_no_sentence_breaks(self, tmp_path):
        out = SubtitleGenerator.text_to_srt("一段没有断句的文本内容", str(tmp_path / "d.srt"), 2.0)
        assert "-->" in self._read(out)


class TestParseVttToSrt:
    def test_parse(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.500\n第一行 text here\n\n"
            "00:00:03.000 --> 00:00:05.000\n第二行\n"
        )
        subs = SubtitleGenerator._parse_vtt_to_srt(vtt)
        assert len(subs) == 2
        assert subs[0].content == "第一行 text here"

    def test_no_timeline(self):
        assert SubtitleGenerator._parse_vtt_to_srt("WEBVTT\n\nnothing here") == []


class TestParseTime:
    def test_hms_comma(self):
        assert SubtitleGenerator._parse_time("00:01:02,500").total_seconds() == pytest.approx(62.5)

    def test_hms_dot(self):
        assert SubtitleGenerator._parse_time("01:02:03.250").total_seconds() == pytest.approx(3723.25)

    def test_ms(self):
        assert SubtitleGenerator._parse_time("01:30.000").total_seconds() == pytest.approx(90.0)

    def test_seconds_only(self):
        assert SubtitleGenerator._parse_time("12.5").total_seconds() == pytest.approx(12.5)