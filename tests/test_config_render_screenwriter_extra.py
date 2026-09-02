"""
补充覆盖 web/routes/config_routes.py、core/audio/subtitle/renderer.py 与
core/screenwriter/（story/scenes/characters/style）在既有测试中未覆盖的分支。

针对分支（相对 tests/test_routes.py / test_config_keys_routes.py /
test_screenwriter.py / test_screenwriter_package.py 的补盲）：
- config_routes：list_models（未配置 400 / 冷缓存拉取 / 热缓存）、GET /api/config/keys、
  save_models 成功分支、_mask_key 纯函数；
- renderer：resolve_position 各类字符串/二元组/百分比/像素/clamp 分支 +
  overlay_subtitles_to_video（成功 / 字符串 bg_color / 异常传播），全部以假 moviepy 打桩；
- story.py：clean_narration_text 纯标记行、develop_story requirement/image_context、
  write_script 全链路（mock _chat_json）；
- scenes.py：design_shots_for_scene、generate_scene_prompt_for_paragraph、空行跳过；
- characters.py：六方法 mock LLM 全链路；
- style.py：LLM 返回非常规格式回退、_validate_styles 非字符串 color。

原则：不触网、不写真实配置/工作区、mock moviepy/LLM/文件 IO，全部经 tmp_path。

用法:
    .venv/bin/python -m coverage run --source=web.routes.config_routes,core.audio.subtitle,core.screenwriter -m pytest tests/test_config_render_screenwriter_extra.py -q
    .venv/bin/python -m coverage report -m core/audio/subtitle/renderer.py core/screenwriter/story.py core/screenwriter/scenes.py core/screenwriter/characters.py core/screenwriter/style.py web/routes/config_routes.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import config_routes
from core.screenwriter import Screenwriter, clean_narration_text
from models.task import SubtitleStyle

# 加载 moviepy/numpy（经配置导入链先加载，避免 coverage C trace 下 numpy 二次导入崩溃）
import core.audio.subtitle  # noqa: F401  触发包 __init__，注入 renderer.SubtitleGenerator 全局
from core.audio.subtitle import renderer as subtitle_renderer
from core.audio.subtitle.renderer import SubtitleRenderMixin


# ═══════════════════════════════════════════════════════════
# 1. config_routes 补充（list_models / get_config_keys / save_models / _mask_key）
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(config_routes.router)
    return TestClient(app)


class TestListModels:
    def test_no_api_key_400(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_api_key", lambda: "")
        resp = client.get("/api/models")
        assert resp.status_code == 400

    def test_fresh_fetch(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_api_key", lambda: "sk-test")
        monkeypatch.setattr(config_routes, "_MODEL_CACHE", {"models": None, "ts": 0.0, "ttl": 300})
        monkeypatch.setattr(
            config_routes, "fetch_available_models",
            lambda key: {"text": ["a"], "image": ["b"], "video": ["c"]},
        )
        monkeypatch.setattr(config_routes, "get_video_model_capabilities", lambda: {"v20": ["s1"]})
        resp = client.get("/api/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is False
        assert body["video_capabilities"] == {"v20": ["s1"]}

    def test_cached(self, client, monkeypatch):
        import time as _time
        monkeypatch.setattr(config_routes, "get_api_key", lambda: "sk-test")
        monkeypatch.setattr(
            config_routes, "_MODEL_CACHE",
            {"models": {"text": ["x"]}, "ts": _time.time(), "ttl": 300},
        )
        monkeypatch.setattr(config_routes, "get_video_model_capabilities", lambda: {})
        resp = client.get("/api/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        assert body["models"] == {"text": ["x"]}


class TestGetConfigKeys:
    def test_masked_and_domains(self, client, monkeypatch):
        key = "sk-test-abcdef1234567890"
        items = [{"key": key, "source": "config"}, {"key": "sk-env-99", "source": "env"}]
        monkeypatch.setattr(config_routes, "get_api_keys_with_sources", lambda: items)
        monkeypatch.setattr(config_routes, "get_api_key_domains", lambda: {key: "cn"})
        monkeypatch.setattr(config_routes, "get_api_keys_source", lambda: "mixed")
        resp = client.get("/api/config/keys")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["key_count"] == 2
        assert body["source"] == "mixed"
        by_id = {k["id"]: k for k in body["keys"]}
        cfg = by_id[config_routes._key_id(key)]
        assert cfg["mask"] == f"{key[:6]}...{key[-4:]}"
        assert cfg["domain"] == "cn"
        assert cfg["persistable"] is True
        env = by_id[config_routes._key_id("sk-env-99")]
        assert env["persistable"] is False

    def test_mask_key_short(self):
        assert config_routes._mask_key("short-key") == "***"
        assert config_routes._mask_key("sk-abcdefghijklmnopq") == "sk-abc...nopq"


class TestSaveConfigKeys:
    def test_non_list_json_scalar(self, client, monkeypatch):
        """keys_json 解析为非 list（单个字符串）→ 命中 str 分支。"""
        seen = []
        monkeypatch.setattr(config_routes, "set_api_keys", lambda keys: seen.append(list(keys)))
        monkeypatch.setattr(config_routes, "reset_key_ring", lambda: None)
        monkeypatch.setattr(config_routes, "reset_rate_limiter", lambda: None)
        monkeypatch.setattr(config_routes, "get_api_keys", lambda: seen[-1] if seen else [])
        monkeypatch.setattr(config_routes, "get_api_keys_source", lambda: "config")
        resp = client.post("/api/config/keys", data={"keys_json": '"only-one"'})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert seen[-1] == ["only-one"]

    def test_append_uses_legacy_api_key(self, client, monkeypatch):
        """append 模式且配置仅有旧 api_key（无 api_keys）→ 从 api_key 追加。"""
        captured = {}
        monkeypatch.setattr(config_routes, "load_config", lambda: {"api_key": "old-key"})
        monkeypatch.setattr(config_routes, "set_api_keys", lambda keys: captured.__setitem__("keys", list(keys)))
        monkeypatch.setattr(config_routes, "reset_key_ring", lambda: None)
        monkeypatch.setattr(config_routes, "reset_rate_limiter", lambda: None)
        monkeypatch.setattr(config_routes, "get_api_keys", lambda: list(captured.get("keys", [])))
        monkeypatch.setattr(config_routes, "get_api_keys_source", lambda: "config")
        resp = client.post("/api/config/keys", data={"keys_json": "new-key", "append": "true"})
        assert resp.status_code == 200
        assert captured["keys"] == ["old-key", "new-key"]


class TestSaveModelsSuccess:
    def test_save_models_with_all_fields(self, client, monkeypatch):
        saved = {}
        monkeypatch.setattr(
            config_routes, "set_selected_models",
            lambda text=None, image=None, video=None: (
                saved.update({"text": text, "image": image, "video": video}) or
                {"text": text, "image": image, "video": video}
            ),
        )
        resp = client.post("/api/config/models", data={"text": "agnes-2.0-flash", "image": "img", "video": "vid"})
        assert resp.status_code == 200
        assert resp.json()["models"]["text"] == "agnes-2.0-flash"
        assert saved["image"] == "img"

    def test_save_models_blank_text_still_accepted(self, client, monkeypatch):
        """text 提供但为纯空白 → 仍 400（text.strip()=="" → 422/400）。"""
        resp = client.post("/api/config/models", data={"text": "   "})
        assert resp.status_code in (400,)


# ═══════════════════════════════════════════════════════════
# 2. renderer.resolve_position 分支
# ═══════════════════════════════════════════════════════════

class TestDomainDetect:
    def test_probe_fail_and_stale_domain(self, client, monkeypatch):
        """已有绑定域名但探测全部失败 → 告警 + 返回 ok=False 结果（409/418）。"""
        key = "sk-dom-123"
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: [{"key": key, "source": "config"}],
        )
        monkeypatch.setattr(config_routes, "get_api_key_domains", lambda: {key: "com"})
        monkeypatch.setattr(config_routes, "_probe_domain", lambda k, d: False)
        monkeypatch.setattr(config_routes, "set_api_key_domains", lambda m: None)
        resp = client.post("/api/config/keys/detect")
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] == 0
        assert body["results"][0]["ok"] is False

    def test_probe_success_sets_domain(self, client, monkeypatch):
        """候选域名探测成功 → 落盘映射并返回 ok=True。"""
        key = "sk-dom-456"
        monkeypatch.setattr(
            config_routes, "get_api_keys_with_sources",
            lambda: [{"key": key, "source": "config"}],
        )
        monkeypatch.setattr(config_routes, "get_api_key_domains", lambda: {})
        monkeypatch.setattr(config_routes, "_probe_domain", lambda k, d: d == "cn")
        saved = {}
        monkeypatch.setattr(config_routes, "set_api_key_domains",
                            lambda m: saved.update(m))
        resp = client.post("/api/config/keys/detect")
        assert resp.status_code == 200
        assert resp.json()["applied"] == 1
        assert saved == {key: "cn"}


class TestResolvePosition:
    def test_string_corners_and_cards(self):
        assert SubtitleRenderMixin.resolve_position("top-left", 1000, 1000) == ("left", "top")
        assert SubtitleRenderMixin.resolve_position("top-right", 1000, 1000) == ("right", "top")
        assert SubtitleRenderMixin.resolve_position("bottom-left", 1000, 1000) == ("left", "bottom")
        assert SubtitleRenderMixin.resolve_position("center", 1000, 1000) == ("center", "center")
        assert SubtitleRenderMixin.resolve_position("middle", 1000, 1000) == ("center", "center")
        assert SubtitleRenderMixin.resolve_position("top", 1000, 1000) == ("center", "top")
        assert SubtitleRenderMixin.resolve_position("left", 1000, 1000) == ("left", "center")

    def test_string_bottom_offset(self):
        assert SubtitleRenderMixin.resolve_position("bottom-80", 1000, 200) == ("center", 120)
        assert SubtitleRenderMixin.resolve_position("bottom-120", 1000, 100) == ("center", 0)

    def test_string_bottom_offset_no_height_defaults(self):
        # video_height<=0 时 bottom-N 分支跳过，落到 default
        assert SubtitleRenderMixin.resolve_position("bottom-80", 1000, 0) == ("center", "bottom")

    def test_string_top_offset(self):
        assert SubtitleRenderMixin.resolve_position("top+50", 1000, 1000) == ("center", 50)

    def test_string_unknown_defaults(self):
        assert SubtitleRenderMixin.resolve_position("diagonal", 1000, 1000) == ("center", "bottom")

    def test_non_2_tuple_defaults(self):
        assert SubtitleRenderMixin.resolve_position(["center"], 1000, 1000) == ("center", "bottom")
        assert SubtitleRenderMixin.resolve_position(("a", "b", "c"), 1000, 1000) == ("center", "bottom")

    def test_tuple_pixel_int(self):
        assert SubtitleRenderMixin.resolve_position((120, 240), 1000, 1000) == (120, 240)

    def test_tuple_percent(self):
        assert SubtitleRenderMixin.resolve_position(("50%", "30%"), 1000, 1000) == (500, 300)

    def test_tuple_left_plus(self):
        assert SubtitleRenderMixin.resolve_position(("left+120", "center"), 1000, 1000) == (120, "center")

    def test_tuple_right_minus(self):
        assert SubtitleRenderMixin.resolve_position(("right-40", "center"), 1000, 1000) == (960, "center")

    def test_tuple_bottom_v_offset(self):
        assert SubtitleRenderMixin.resolve_position(("center", "bottom-160"), 1000, 1000) == ("center", 840)

    def test_tuple_top_plus_v(self):
        assert SubtitleRenderMixin.resolve_position(("center", "top+90"), 1000, 1000) == ("center", 90)

    def test_tuple_token_fallbacks(self):
        assert SubtitleRenderMixin.resolve_position(("center", "top"), 1000, 1000) == ("center", "top")
        assert SubtitleRenderMixin.resolve_position(("left", "bottom"), 1000, 1000) == ("left", "bottom")
        assert SubtitleRenderMixin.resolve_position(("nonsense", "weird"), 1000, 1000) == ("center", "bottom")

    def test_clamping(self):
        # h=5 太靠左(<safe 40) → 40；v=9999 超底(>1000-80=920) → 920
        assert SubtitleRenderMixin.resolve_position((5, 9999), 1000, 1000) == (40, 920)


# ═══════════════════════════════════════════════════════════
# 3. renderer.overlay_subtitles_to_video（mock moviepy）
# ═══════════════════════════════════════════════════════════

class _FakeVideoClip:
    def __init__(self, path=None):
        self.path = path
        self.w = 768
        self.h = 1152

    def close(self):
        pass


class _FakeTextClip:
    def __init__(self, **kw):
        self.kw = kw


class _FakeSubtitlesClip:
    def __init__(self, srt_path, make_textclip=None):
        self.srt_path = srt_path
        if make_textclip:
            self._clip = make_textclip("测试字幕")
        self.positioned = None

    def with_position(self, pos):
        self.positioned = pos
        return self


class _FakeComposite:
    def __init__(self, clips):
        self.clips = clips
        self.output = None
        self.kw = None

    def write_videofile(self, output, **kw):
        self.output = output
        self.kw = kw

    def close(self):
        pass


class TestOverlaySubtitles:
    def _patch_moviepy(self, monkeypatch):
        monkeypatch.setattr(subtitle_renderer, "VideoFileClip", _FakeVideoClip)
        monkeypatch.setattr(subtitle_renderer, "SubtitlesClip", _FakeSubtitlesClip)
        monkeypatch.setattr(subtitle_renderer, "CompositeVideoClip", _FakeComposite)
        monkeypatch.setattr("moviepy.TextClip", _FakeTextClip)
        monkeypatch.setattr("core.config.resolve_font_path", lambda font: "/f/" + font)

    def test_success_tuple_bg(self, monkeypatch, tmp_path):
        self._patch_moviepy(monkeypatch)
        srt = tmp_path / "a.srt"
        srt.write_text("", encoding="utf-8")
        video = str(tmp_path / "in.mp4")
        out = str(tmp_path / "out.mp4")
        # bg_color 默认为 tuple
        style = SubtitleStyle()
        result = SubtitleRenderMixin.overlay_subtitles_to_video(video, str(srt), style, out)
        assert result == out

    def test_success_string_bg_with_at(self, monkeypatch, tmp_path):
        self._patch_moviepy(monkeypatch)
        srt = tmp_path / "b.srt"
        srt.write_text("", encoding="utf-8")
        out = str(tmp_path / "out2.mp4")
        style = SubtitleStyle()
        style.bg_color = "black@0.5"  # 原始赋值（validate_assignment 关闭）→ 命中字符串分支
        result = SubtitleRenderMixin.overlay_subtitles_to_video("in.mp4", str(srt), style, out)
        assert result == out

    def test_success_string_bg_no_at(self, monkeypatch, tmp_path):
        self._patch_moviepy(monkeypatch)
        srt = tmp_path / "c.srt"
        srt.write_text("", encoding="utf-8")
        out = str(tmp_path / "out3.mp4")
        style = SubtitleStyle()
        style.bg_color = "somecolor"
        result = SubtitleRenderMixin.overlay_subtitles_to_video("in.mp4", str(srt), style, out)
        assert result == out

    def test_error_propagates(self, monkeypatch, tmp_path):
        class _BoomClip:
            def __init__(self, path):
                raise OSError("no video reader")

        monkeypatch.setattr(subtitle_renderer, "VideoFileClip", _BoomClip)
        style = SubtitleStyle()
        with pytest.raises(OSError):
            SubtitleRenderMixin.overlay_subtitles_to_video(
                "in.mp4", str(tmp_path / "x.srt"), style, str(tmp_path / "out.mp4")
            )


# ═══════════════════════════════════════════════════════════
# 4. story.py 补充（clean_narration 标记行 / develop_story / write_script）
# ═══════════════════════════════════════════════════════════

class TestCleanNarrationMarkers:
    def test_heading_line_stripped(self):
        # 标题匹配需「#」后紧跟空白字符；strip 只去掉行首尾空白，正文前的标题会被剥离
        assert clean_narration_text("## 标题\n正文") == "标题正文"

    def test_pure_bullet_line_stripped(self):
        assert clean_narration_text("- 项\n正文") == "项正文"
        assert clean_narration_text("* 项\n正文") == "项正文"

    def test_pure_bold_line_skipped(self):
        assert clean_narration_text("**\n正文") == "正文"

    def test_collapses_whitespace_and_joins(self):
        assert clean_narration_text("第一句。第二句。") == "第一句。第二句。"
        # 单行内部 2+ 空白被压缩为 1 个
        assert clean_narration_text("甲    乙") == "甲 乙"

    def test_metadata_prefix_lines_dropped(self):
        assert clean_narration_text("故事标题：冒险\n正文") == "正文"
        assert clean_narration_text("story outline\n正文") == "正文"

    def test_bold_metadata_field_line_dropped(self):
        assert clean_narration_text("**受众**：16-35岁\n正文") == "正文"


class TestDevelopStoryBranches:
    def _build(self, monkeypatch, text="返回故事"):
        sw = Screenwriter(api_key="", language="zh")
        captured = {}
        monkeypatch.setattr(sw, "_chat", lambda s, u: (captured.__setitem__("user_prompt", u) or text))
        return sw, captured

    def test_with_scene_count_and_durations(self, monkeypatch):
        sw, captured = self._build(monkeypatch)
        sw.develop_story("创意", scene_count=3, scene_durations=[5, 8, 12])
        assert "共 3 个场景，时长分别为" in captured["user_prompt"]

    def test_with_scene_count_only(self, monkeypatch):
        sw, captured = self._build(monkeypatch)
        sw.develop_story("创意", scene_count=2)
        assert "共 2 个场景" in captured["user_prompt"]

    def test_with_user_requirement(self, monkeypatch):
        sw, captured = self._build(monkeypatch)
        sw.develop_story("创意", user_requirement="1个场景, 10秒")
        assert "1个场景, 10秒" in captured["user_prompt"]

    def test_default_requirement(self, monkeypatch):
        sw, captured = self._build(monkeypatch)
        sw.develop_story("创意")
        assert "3个场景，每场景5秒" in captured["user_prompt"]

    def test_with_image_context(self, monkeypatch):
        sw, captured = self._build(monkeypatch)
        result = sw.develop_story("创意", image_context="森林背景，主角穿红衣")
        assert result == "返回故事"
        assert "<image_context>" in captured["user_prompt"]
        assert "森林背景" in captured["user_prompt"]


class TestWriteScript:
    def test_writes_scenes_with_durations(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: {"scenes": ["镜头一", "镜头二", "镜头三"]},
        )
        scenes = sw.write_script("故事", scene_count=3, scene_durations=[5, 5, 5])
        assert scenes == ["镜头一", "镜头二", "镜头三"]

    def test_writes_scenes_scene_count_only(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: {"scenes": ["A"]})
        assert sw.write_script("故事", scene_count=1) == ["A"]

    def test_writes_scenes_user_requirement(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: {"scenes": []})
        assert sw.write_script("故事", user_requirement="2个场景") == []

    def test_writes_scenes_default(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: {"scenes": ["X"]})
        assert sw.write_script("故事") == ["X"]


# ═══════════════════════════════════════════════════════════
# 5. scenes.py 补充（design_shots / generate_scene_prompt / 空行跳过）
# ═══════════════════════════════════════════════════════════

class TestScenesMethods:
    def test_design_shots_for_scene(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(
            sw, "_chat_json",
            lambda s, u: {"shots": [{"visual_desc": "v"}]},
        )
        shots = sw.design_shots_for_scene("场景文本", "写实", max_shots=3)
        assert shots == [{"visual_desc": "v"}]

    def test_design_shots_defaults_empty(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: {})
        assert sw.design_shots_for_scene("场景文本", "") == []

    def test_generate_scene_prompt_for_paragraph(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "```\n金色麦田，慢镜头\n```")
        prompt = sw.generate_scene_prompt_for_paragraph("段落文本", "写实")
        assert prompt == "金色麦田，慢镜头"

    def test_generate_scene_prompt_no_style(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "prompt")
        assert sw.generate_scene_prompt_for_paragraph("段落") == "prompt"

    def test_parse_skips_blank_interior_line(self):
        sw = Screenwriter(api_key="", language="zh")
        scenes = sw._parse_poetry_scene_lines(
            "床前明月光 | 月光\n\n疑是地上霜 | 地面白霜"
        )
        assert len(scenes) == 2
        assert scenes[1]["narration"] == "疑是地上霜"


# ═══════════════════════════════════════════════════════════
# 6. characters.py 补充（六方法全链路）
# ═══════════════════════════════════════════════════════════

class TestCharactersMethods:
    def test_extract_character_description(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "```\n一位红衣少女\n```")
        assert sw.extract_character_description("故事", "写实") == "一位红衣少女"

    def test_get_character_appearance(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "短发，戴眼镜")
        assert sw.get_character_appearance("故事") == "短发，戴眼镜"

    def test_generate_end_frame_prompts_with_appearance(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        calls = {"n": 0}
        monkeypatch.setattr(
            sw, "_chat",
            lambda s, u: (calls.__setitem__("n", calls["n"] + 1) or f"尾帧{calls['n']}"),
        )
        frames = sw.generate_end_frame_prompts(["场景一", "场景二"], "写实", "红衣少女")
        assert len(frames) == 2
        assert calls["n"] == 2

    def test_generate_end_frame_prompts_without_appearance(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "尾帧")
        assert sw.generate_end_frame_prompts(["场景一"], "写实") == ["尾帧"]

    def test_generate_anchor_clip_prompt(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "点头并微笑")
        assert sw.generate_anchor_clip_prompt("段落", "主播形象", 0, 3) == "点头并微笑"

    def test_generate_anchor_smooth_loop_prompt(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "轻微呼吸")
        assert sw.generate_anchor_smooth_loop_prompt("主播形象") == "轻微呼吸"

    def test_generate_anchor_model_audio_prompt(self, monkeypatch):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat", lambda s, u: "对着稿件口播")
        assert sw.generate_anchor_model_audio_prompt("主播形象", "台词内容") == "对着稿件口播"


# ═══════════════════════════════════════════════════════════
# 7. style.py 补充（非常规格式回退 / 非字符串 color）
# ═══════════════════════════════════════════════════════════

class TestStyleFallbacks:
    def _srt(self, tmp_path):
        p = tmp_path / "subs.srt"
        p.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\n第一句\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\n第二句\n",
            encoding="utf-8",
        )
        return str(p)

    def test_unexpected_response_format_falls_back(self, monkeypatch, tmp_path):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: "just a string")
        styles = sw.generate_subtitle_styles(self._srt(tmp_path), 768, 1152)
        assert len(styles) == 2
        assert all(s["color"] == "white" for s in styles)

    def test_dict_without_styles_falls_back(self, monkeypatch, tmp_path):
        sw = Screenwriter(api_key="", language="zh")
        monkeypatch.setattr(sw, "_chat_json", lambda s, u: {"foo": "bar"})
        styles = sw.generate_subtitle_styles(self._srt(tmp_path), 768, 1152)
        assert len(styles) == 2

    def test_validate_styles_non_str_color(self):
        styles = [
            {"index": 1, "position": ["center", "top+80"], "color": 123, "fontsize": 48},
        ]
        result = Screenwriter(api_key="", language="zh")._validate_styles(styles, 1)
        assert result[0]["color"] == "white"