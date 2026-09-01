"""
单元测试：core.api.agnes_video 的 URL 缓存辅助函数。

覆盖（S7493 修复引入的模块级函数）：
- _read_json_cache：正常读取 / 文件缺失 / 无效 JSON
- _write_json_cache：原子写入 + 覆盖
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.api.agnes_video import _read_json_cache, _write_json_cache


def test_read_json_cache_ok(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"url": "https://x", "ts": 123}), encoding="utf-8")
    assert _read_json_cache(str(p)) == {"url": "https://x", "ts": 123}


def test_read_json_cache_invalid(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _read_json_cache(str(p))


def test_write_json_cache_creates(tmp_path):
    p = tmp_path / "c.json"
    _write_json_cache(str(p), {"url": "u", "ts": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"url": "u", "ts": 1}
    # 无残留临时文件
    assert not os.path.exists(str(p) + ".tmp")


def test_write_json_cache_overwrites(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"old": True}), encoding="utf-8")
    _write_json_cache(str(p), {"url": "new", "ts": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"url": "new", "ts": 2}
