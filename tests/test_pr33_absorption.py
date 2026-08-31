"""
PR #33 吸收功能单测 — tests/test_pr33_absorption.py

覆盖 v6.4（docs/plans/v6.0/companion_ui_absorption_PRD.md）吸收的后端功能：
- 1.3a 语速估算公共化：estimate_chars_per_sec / duration_len（core.audio.voices）
- 1.2/1.2a 阿拉伯语变音符号：strip_diacritics / add_tashkeel_safe（core.audio.tashkeel）
  （mishkal 可选依赖：缺失时 add_tashkeel_safe 静默回退原文，两种环境均断言不崩溃）
- 1.6 稿件拆分公共化：split_manuscript_text（core.pipelines.manuscript_video）
- 1.4 Screenwriter language pinning：is_prompt_language_explicit
- 1.1/1.1a preview 端点：content_lang 白名单 422 / preview-split 输出 / 并发闸
- 1.5 稿件参考图：ManuscriptVideoTask.reference_images 类型化落盘

用法:
    .venv/bin/python -m pytest tests/test_pr33_absorption.py -v
"""

import os
import sys

import pytest

sys_path_inserted = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys_path_inserted not in sys.path:
    sys.path.insert(0, sys_path_inserted)


# ═══════════════════════════════════════════════
# 1. 语速估算（PRD 1.3a）
# ═══════════════════════════════════════════════

class TestSpeechRateEstimate:
    def test_cjk_script_uses_4_per_sec(self):
        from core.audio.voices import estimate_chars_per_sec

        assert estimate_chars_per_sec("中文测试文本") == 4.0
        assert estimate_chars_per_sec("日本語のテスト") == 4.0
        assert estimate_chars_per_sec("한국어 테스트") == 4.0

    def test_alphabetic_script_uses_13_per_sec(self):
        from core.audio.voices import estimate_chars_per_sec

        assert estimate_chars_per_sec("English narration text") == 13.0
        # 阿拉伯语：字母文字（PR #33 实测 12-13 字符/秒）
        assert estimate_chars_per_sec("مرحبا بالعالم") == 13.0
        assert estimate_chars_per_sec("Русский текст") == 13.0

    def test_duration_len_strips_arabic_diacritics(self):
        from core.audio.tashkeel import strip_diacritics
        from core.audio.voices import duration_len

        diacritized = "مَرْحَبًا"  # 7 codepoints（含 2 个变音符号）
        assert len(diacritized) > 5
        assert duration_len(diacritized) == len(strip_diacritics(diacritized)) == 5
        # 无变音符号文本不受影响
        assert duration_len("中文文本") == 4


# ═══════════════════════════════════════════════
# 2. tashkeel（PRD 1.2 / 1.2a）
# ═══════════════════════════════════════════════

class TestTashkeel:
    def test_strip_diacritics_removes_harakat_only(self):
        from core.audio.tashkeel import strip_diacritics

        assert strip_diacritics("مَرْحَبًا") == "مرحبا"
        # 非阿拉伯文本无副作用
        assert strip_diacritics("Hello 世界") == "Hello 世界"
        assert strip_diacritics("") == ""

    def test_add_tashkeel_safe_roundtrip_and_fallback(self):
        """mishkal 缺失时静默回退原文；存在时 roundtrip 校验必须通过。

        断言只依赖「不崩溃 + 剥离后与输入一致」（mishkal 存在与否均可满足），
        避免 CI 环境未安装 mishkal 时测试失败。
        """
        from core.audio.tashkeel import add_tashkeel_safe, strip_diacritics

        text = "مرحبا بالعالم هذا اختبار"
        out = add_tashkeel_safe(text)
        # 校验门：剥离变音符号后与输入（同样剥离后）逐字符一致
        assert strip_diacritics(out) == strip_diacritics(text)
        # 非阿拉伯文本原样返回
        assert add_tashkeel_safe("plain text") == "plain text"
        assert add_tashkeel_safe("") == ""


# ═══════════════════════════════════════════════
# 3. 稿件拆分（PRD 1.6）
# ═══════════════════════════════════════════════

class TestSplitManuscriptText:
    def test_chinese_multi_segment(self):
        from core.pipelines.manuscript_video import split_manuscript_text

        text = (
            "清晨的小镇，一条小溪静静流过石桥。溪水清澈见底，映着蓝天白云的倒影。"
            "岸边的柳树轻轻摇摆，叶子随风飘动。阳光洒在水面上，泛起点点金光。"
            "微风吹过，带来泥土和青草的气息。"
        )
        parts = split_manuscript_text(text)
        assert isinstance(parts, list) and len(parts) >= 1
        assert all(isinstance(p, str) and p for p in parts)
        # 拆段结果应保留全部内容（拼接后等价）
        assert "".join(parts).replace("。", "。") == text or len("".join(parts)) == len(text)

    def test_empty_text(self):
        from core.pipelines.manuscript_video import split_manuscript_text

        assert split_manuscript_text("") == []
        assert split_manuscript_text("   ") == []


# ═══════════════════════════════════════════════
# 4. Screenwriter language pinning（PRD 1.4）
# ═══════════════════════════════════════════════

class TestPromptLanguageExplicit:
    def test_unset_means_not_explicit(self, monkeypatch):
        from core.screenwriter import is_prompt_language_explicit

        monkeypatch.delenv("PROMPT_LANGUAGE", raising=False)
        assert is_prompt_language_explicit() is False

    def test_env_set_means_explicit(self, monkeypatch):
        from core.screenwriter import is_prompt_language_explicit

        monkeypatch.setenv("PROMPT_LANGUAGE", "zh")
        assert is_prompt_language_explicit() is True
        monkeypatch.setenv("PROMPT_LANGUAGE", "en")
        assert is_prompt_language_explicit() is True


# ═══════════════════════════════════════════════
# 5. Preview 端点（PRD 1.1 / 1.1a）
# ═══════════════════════════════════════════════

class TestPreviewGate:
    """并发闸：非阻塞获取，超限失败，释放后可再获取。"""

    async def test_gate_limits_concurrency(self):
        from web.routes.preview_routes import _PreviewGate

        gate = _PreviewGate(2)
        assert await gate.try_acquire() is True
        assert await gate.try_acquire() is True
        assert await gate.try_acquire() is False  # 已满
        await gate.release()
        assert await gate.try_acquire() is True

    async def test_gate_release_never_negative(self):
        from web.routes.preview_routes import _PreviewGate

        gate = _PreviewGate(1)
        await gate.release()  # 空释放不报错
        await gate.release()
        assert await gate.try_acquire() is True


class TestPreviewEndpoints:
    """preview 端点 HTTP 行为（TestClient，无真实 LLM/网络）。"""

    @pytest.fixture(autouse=True)
    def _stub_server_side_effects(self, monkeypatch):
        """打桩 lifespan 副作用（工作区初始化 / 音色目录网络加载）与 API key。"""
        import server as server_mod

        async def _noop(*args, **kwargs):
            return {}

        monkeypatch.setattr(server_mod, "init_runtime_state", lambda: None)
        monkeypatch.setattr(server_mod, "load_voice_catalog", _noop)
        monkeypatch.delenv("AGNES_SWEEP_AGE_DAYS", raising=False)
        monkeypatch.setattr(
            "web.routes.preview_routes.get_api_key", lambda: "test-key"
        )

    def test_creative_script_content_lang_whitelist(self):
        from fastapi.testclient import TestClient

        from server import app

        with TestClient(app) as client:
            # 非法 content_lang → 422（白名单，不再静默默认阿拉伯语）
            r = client.post(
                "/api/creative/preview-script",
                data={"idea": "a story", "content_lang": "xx"},
            )
            assert r.status_code == 422
            # 合法 content_lang → 通过白名单校验（无 key 时 400；此处 stub key，
            # 因 LLM 调用前仅做参数校验，会继续走到 Screenwriter 调用，
            # 这里不执行以避免真实请求——只断言白名单之外被拦截）
            assert "content_lang" in r.json()["detail"]

    def test_manuscript_preview_split_output(self):
        from fastapi.testclient import TestClient

        from server import app

        with TestClient(app) as client:
            r = client.post(
                "/api/manuscript/preview-split",
                data={"manuscript_text": "第一段话。第二段话。第三段话。"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert isinstance(body["paragraphs"], list)
            assert all(p["index"] >= 0 and p["est_duration_sec"] > 0 for p in body["paragraphs"])
            assert body["total_duration_sec"] > 0

    def test_manuscript_preview_split_empty_text(self):
        from fastapi.testclient import TestClient

        from server import app

        with TestClient(app) as client:
            r = client.post("/api/manuscript/preview-split", data={"manuscript_text": ""})
            assert r.status_code == 422  # Form 必填


# ═══════════════════════════════════════════════
# 6. 稿件参考图（PRD 1.5）
# ═══════════════════════════════════════════════

class TestManuscriptReferenceImages:
    def test_state_field_type(self):
        from models.task import ManuscriptVideoTask

        task = ManuscriptVideoTask(
            task_id="t1",
            manuscript_text="测试",
            reference_images={"0": ["/tmp/a.png"], "1": ["/tmp/a.png", "/tmp/b.png"]},
        )
        assert task.reference_images["0"] == ["/tmp/a.png"]
        # 缺省为空 dict，向后兼容
        task2 = ManuscriptVideoTask(task_id="t2", manuscript_text="x")
        assert task2.reference_images == {}

    def test_audio_config_add_tashkeel_default(self):
        from models.task import AudioConfig

        assert AudioConfig().add_tashkeel is False
        assert AudioConfig(add_tashkeel=True).add_tashkeel is True
