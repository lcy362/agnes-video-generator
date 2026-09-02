"""Unit tests for web.log_safe — 日志注入防护（Sonar S5145 修复配套）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.log_safe import safe_log  # noqa: E402


# ═══════════════════════════════════════════════════
# 控制字符清洗
# ═══════════════════════════════════════════════════

def test_strips_crlf_injection():
    assert safe_log("abc\r\n[INFO] faked line") == "abc  [INFO] faked line"


def test_strips_newline_and_tab():
    assert safe_log("a\nb\tc") == "a b c"


def test_strips_other_control_chars():
    assert safe_log("a\x00b\x1bc\x7f") == "a b c "


def test_plain_value_unchanged():
    assert safe_log("task_abc123") == "task_abc123"


# ═══════════════════════════════════════════════════
# 长度截断
# ═══════════════════════════════════════════════════

def test_truncates_long_value():
    out = safe_log("x" * 500)
    assert len(out) == 120 + 3
    assert out.endswith("...")


def test_custom_max_len():
    assert safe_log("abcdef", max_len=3) == "abc..."


def test_value_at_limit_not_truncated():
    assert safe_log("x" * 120) == "x" * 120


# ═══════════════════════════════════════════════════
# 非字符串入参
# ═══════════════════════════════════════════════════

def test_none_becomes_dash():
    assert safe_log(None) == "-"


def test_non_string_coerced():
    assert safe_log(42) == "42"
    assert safe_log(True) == "True"


def test_result_is_always_str():
    assert isinstance(safe_log(["a", "b\n"]), str)
