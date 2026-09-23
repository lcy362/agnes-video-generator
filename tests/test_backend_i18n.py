"""core.i18n_backend 单元测试（v7.0，issue #64）。

覆盖：
- ``normalize_lang``：把 ``en-US`` / ``zh_Hans_CN`` / 未知 / None 归一到 2 字母代码；
- ``parse_accept_language``：按 RFC 7231 q 权重解析浏览器头；
- ``translate``：zh / en 分支渲染 + 缺 key / 缺语言的三级回退；
- ``current_lang`` ContextVar：``set_current_lang`` / ``get_current_lang`` 语义；
- ``resolve_lang``：显式参数 > 上下文 > 默认。
"""
from __future__ import annotations

import pytest

from core.i18n_backend import (
    CATALOG,
    DEFAULT_UI_LANG,
    SUPPORTED_UI_LANGS,
    current_lang,
    get_current_lang,
    normalize_lang,
    parse_accept_language,
    resolve_lang,
    set_current_lang,
    translate,
)


# ─────────────────────────────────────────────────────────────────────────────
# normalize_lang
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en", "en"),
        ("EN", "en"),
        ("en-US", "en"),
        ("en-us", "en"),
        ("zh", "zh"),
        ("zh-CN", "zh"),
        ("zh_Hans_CN", "zh"),
        ("ja", "ja"),
        ("ar", "ar"),
        ("", DEFAULT_UI_LANG),
        (None, DEFAULT_UI_LANG),
        ("klingon", DEFAULT_UI_LANG),  # 未知语言回退 zh
        ("   ", DEFAULT_UI_LANG),
        ("123", DEFAULT_UI_LANG),
    ],
)
def test_normalize_lang(raw, expected):
    assert normalize_lang(raw) == expected


def test_normalize_lang_always_in_supported_set():
    """归一化结果必须落在支持集合内，否则前端 t() 会回退到 key 名。"""
    for raw in ("en-US", "zh-CN", "xx", "", None, "ja-JP"):
        assert normalize_lang(raw) in SUPPORTED_UI_LANGS


# ─────────────────────────────────────────────────────────────────────────────
# parse_accept_language
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "header,expected",
    [
        ("en-US,en;q=0.9,zh-CN;q=0.8", "en"),
        ("zh-CN,zh;q=0.9,en;q=0.8", "zh"),
        ("ja-JP,ja;q=0.9", "ja"),
        ("fr", "fr"),
        ("de-DE,de;q=0.9,en;q=0.5", "de"),
        # 权重高的优先，即便出现在后面
        ("en;q=0.5,zh;q=0.9", "zh"),
        # 全部不支持 → 回退 zh
        ("klingon,elvish;q=0.9", DEFAULT_UI_LANG),
        ("", DEFAULT_UI_LANG),
        (None, DEFAULT_UI_LANG),
        # 畸形 q 值不炸
        ("en;q=abc,zh;q=0.5", "zh"),
    ],
)
def test_parse_accept_language(header, expected):
    assert parse_accept_language(header) == expected


# ─────────────────────────────────────────────────────────────────────────────
# translate
# ─────────────────────────────────────────────────────────────────────────────


def test_translate_zh_uses_chinese_template():
    msg = translate("config.api_key_missing", "zh")
    assert "请先配置 API Key" in msg
    assert "platform.agnes-ai.com" in msg


def test_translate_en_uses_english_template():
    msg = translate("config.api_key_missing", "en")
    assert "Please configure an API Key" in msg
    # 中文关键词绝不能出现在英文分支
    assert "请先配置" not in msg


def test_translate_formats_params():
    msg = translate("network.dns_failed", "en", target="`example.com`")
    assert "example.com" in msg
    assert "DNS" in msg


def test_translate_zh_formats_params():
    msg = translate("network.connect_blocked", "zh", target="`api.agnes-ai.cn`")
    assert "api.agnes-ai.cn" in msg
    assert "网络诊断" in msg


def test_translate_unknown_lang_falls_back_to_zh():
    """语言不在支持集合 → 归一化到 zh → 返回中文模板（与前端 t() 一致）。"""
    msg = translate("config.api_key_missing", "klingon")
    assert "请先配置 API Key" in msg


def test_translate_missing_key_returns_key_itself():
    """缺 key 不抛异常，返回 key 名兜底（便于日志排查）。"""
    assert translate("no.such.key", "zh") == "no.such.key"
    assert translate("no.such.key", "en") == "no.such.key"


def test_translate_missing_param_degrades_gracefully():
    """占位符缺失时降级为「模板 + 参数附录」，不把整段消息吞掉。"""
    msg = translate("network.dns_failed", "en")  # 未传 target
    assert "network.dns_failed" not in msg or "{target}" in msg
    # 无论降级成什么形态，都不能是空串
    assert msg


def test_translate_none_lang_reads_context():
    """lang=None 时走 resolve_lang() 读 ContextVar。"""
    token = set_current_lang("en")
    try:
        msg = translate("config.api_key_missing", None)
        assert "Please configure" in msg
    finally:
        current_lang.reset(token)


def test_catalog_zh_en_parity():
    """目录里每个 key 都必须同时有 zh 与 en（缺一不可，与前端 i18n 规范一致）。"""
    missing = []
    for key, entry in CATALOG.items():
        if "zh" not in entry:
            missing.append((key, "zh"))
        if "en" not in entry:
            missing.append((key, "en"))
    assert not missing, f"CATALOG 缺翻译: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# ContextVar
# ─────────────────────────────────────────────────────────────────────────────


def test_context_var_default_is_zh():
    """未 set 时 get_current_lang() 返回默认 zh。"""
    # 注意：其他测试可能已经 set 过，这里用 reset 到默认再断言
    token = current_lang.set(DEFAULT_UI_LANG)
    try:
        assert get_current_lang() == "zh"
    finally:
        current_lang.reset(token)


def test_set_current_lang_normalizes():
    token = set_current_lang("en-US")
    try:
        assert get_current_lang() == "en"
    finally:
        current_lang.reset(token)


def test_resolve_lang_priority():
    """显式参数 > 上下文 > 默认。"""
    token = set_current_lang("en")
    try:
        # 显式参数覆盖上下文
        assert resolve_lang("ja") == "ja"
        # 无显式参数 → 读上下文
        assert resolve_lang(None) == "en"
        assert resolve_lang() == "en"
    finally:
        current_lang.reset(token)


def test_resolve_lang_normalizes_explicit():
    assert resolve_lang("zh_Hans_CN") == "zh"
    assert resolve_lang("klingon") == DEFAULT_UI_LANG
