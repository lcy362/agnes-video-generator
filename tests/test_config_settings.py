"""
单元测试：core.config 类型化配置（v5.0 Batch 5 / 5.2）。

守护 AppSettings / load_settings 契约：
- 构造期类型校验（类型错误抛 ValidationError）；
- 缺省字段取默认值、未知键忽略（旧配置文件兼容）；
- load_settings 与访问函数（get_api_key / get_working_dir /
  get_watermark_config / get_selected_models / get_agnes_domain /
  get_workspaces）行为等价于旧 dict 路径；
- 写函数（set_*）仍走 dict 流，与类型化读一致。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError

import core.config as config
from core.config import AppSettings, WatermarkSettings, WorkspaceEntry

# ═══════════════════════════════════════════════
# 1. 模型默认值与构造期校验
# ═══════════════════════════════════════════════

def test_app_settings_defaults():
    s = AppSettings()
    assert s.api_key == ""
    assert s.active_workspace == ""
    assert s.workspaces == []
    assert s.watermark.enabled is False
    assert s.watermark.language == "auto"
    assert s.models == {}
    assert s.agnes_domain == "com"


def test_app_settings_type_errors_raise_at_construction():
    """配置类型错误在构造期抛错（验收标准）。"""
    with pytest.raises(ValidationError):
        AppSettings(watermark={"enabled": "yes"})  # 非 bool
    with pytest.raises(ValidationError):
        AppSettings(api_key=123)  # 非 str
    with pytest.raises(ValidationError):
        AppSettings(workspaces=[{"path": 42}])  # path 非 str


def test_app_settings_ignores_unknown_keys():
    """未知键自动忽略（旧配置文件含多余字段不报错）。"""
    s = AppSettings(api_key="k", legacy_field="x", watermark={"enabled": True})
    assert s.api_key == "k"
    assert s.watermark.enabled is True


def test_workspace_entry_and_watermark_models():
    ws = WorkspaceEntry(path="/tmp/a", is_default=True)
    assert ws.name == ""
    assert ws.is_default is True
    wm = WatermarkSettings()
    assert wm.enabled is False
    assert wm.language == "auto"


# ═══════════════════════════════════════════════
# 2. load_settings 与访问函数行为等价
# ═══════════════════════════════════════════════

@pytest.fixture
def conf_file(tmp_path, monkeypatch):
    """将 CONFIG_FILE 指向临时目录，返回写配置辅助函数。"""
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))

    def write(payload: dict):
        (tmp_path / "config.json").write_text(
            json.dumps(payload), encoding="utf-8")

    return write


def test_load_settings_reads_file(conf_file):
    conf_file({"api_key": "abc", "watermark": {"enabled": True, "language": "en"},
               "models": {"text": "m1"}, "agnes_domain": "cn",
               "active_workspace": "/tmp/w"})
    s = config.load_settings()
    assert s.api_key == "abc"
    assert s.watermark.enabled is True
    assert s.models == {"text": "m1"}
    assert s.agnes_domain == "cn"
    assert s.active_workspace == "/tmp/w"


def test_load_settings_missing_file_returns_defaults(conf_file):
    s = config.load_settings()
    assert s == AppSettings()


def test_load_settings_corrupt_json_raises(conf_file, tmp_path):
    (tmp_path / "config.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        config.load_settings()


def test_get_api_key_uses_settings(conf_file, monkeypatch):
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    assert config.get_api_key() == ""
    conf_file({"api_key": "k1"})
    assert config.get_api_key() == "k1"


def test_get_working_dir_uses_settings(conf_file, monkeypatch):
    monkeypatch.delenv(config.REGRESSION_WORKING_DIR_ENV, raising=False)
    assert config.get_working_dir() == config._default_working_dir()
    conf_file({"active_workspace": "/tmp/custom"})
    assert config.get_working_dir() == "/tmp/custom"


def test_get_watermark_config_uses_settings(conf_file):
    assert config.get_watermark_config() == {
        "enabled": False, "language": "auto"}
    conf_file({"watermark": {"enabled": True, "language": "zh"}})
    assert config.get_watermark_config() == {
        "enabled": True, "language": "zh"}


def test_get_selected_models_uses_settings(conf_file):
    assert config.get_selected_models() == {
        "text": config.DEFAULT_TEXT_MODEL,
        "image": config.DEFAULT_IMAGE_MODEL,
        "video": config.DEFAULT_VIDEO_MODEL,
    }
    conf_file({"models": {"video": "custom-v"}})
    result = config.get_selected_models()
    assert result["video"] == "custom-v"
    assert result["text"] == config.DEFAULT_TEXT_MODEL


def test_get_agnes_domain_uses_settings(conf_file):
    assert config.get_agnes_domain() == "com"
    conf_file({"agnes_domain": "cn"})
    assert config.get_agnes_domain() == "cn"


def test_get_workspaces_uses_settings(conf_file, monkeypatch):
    conf_file({"workspaces": [{"path": "/tmp/ws1", "name": "空间一"},
                              {"path": "/tmp/ws2"}]})
    workspaces = config.get_workspaces()
    assert workspaces[0]["is_default"] is True  # 默认空间恒在首位
    assert len(workspaces) == 3
    assert workspaces[1] == {"path": "/tmp/ws1", "name": "空间一",
                             "is_default": False}


# ═══════════════════════════════════════════════
# 3. 写函数与类型化读一致
# ═══════════════════════════════════════════════

def test_set_then_read_roundtrip(conf_file, monkeypatch):
    """set_* 写 dict 流后，load_settings 能正确读回。"""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    config.set_api_key("roundtrip-key")
    assert config.load_settings().api_key == "roundtrip-key"
    config.set_watermark_config(enabled=True, language="zh")
    s = config.load_settings()
    assert s.watermark.enabled is True
    assert s.watermark.language == "zh"
    config.set_agnes_domain("cn")
    assert config.load_settings().agnes_domain == "cn"
    config.delete_api_key()
    assert config.load_settings().api_key == ""


# ═══════════════════════════════════════════════════
# 3.5 RuntimeSettings（pydantic-settings 环境变量收敛）
# ═══════════════════════════════════════════════════

def test_runtime_settings_defaults(monkeypatch):
    """默认值：host/port/subtitle_ass/轮询超时等。"""
    from core.config import get_settings
    # 清掉可能存在的环境变量干扰
    for k in ("HOST", "PORT", "AGNES_SUBTITLE_ASS", "AGNES_VIDEO_POLL_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    s = get_settings()
    assert s.host == "0.0.0.0"
    assert s.port == 8765
    assert s.agnes_subtitle_ass is True
    assert s.agnes_video_poll_timeout == 1800
    assert s.agnes_rate_limit is None


def test_runtime_settings_env_override(monkeypatch):
    """环境变量覆盖默认值（大小写不敏感 + 类型转换）。"""
    from core.config import get_settings
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "0")
    monkeypatch.setenv("AGNES_VIDEO_POLL_TIMEOUT", "3000")
    monkeypatch.setenv("AGNES_RATE_LIMIT", "6")
    s = get_settings()
    assert s.host == "127.0.0.1"
    assert s.port == 9000
    assert s.agnes_subtitle_ass is False
    assert s.agnes_video_poll_timeout == 3000
    assert s.agnes_rate_limit == 6


def test_runtime_settings_extra_ignored(monkeypatch):
    """未声明环境变量（如 AGNES_API_KEY_2）不报错。"""
    from core.config import get_settings
    monkeypatch.setenv("AGNES_API_KEY_2", "sk-xxx")
    monkeypatch.setenv("UNRELATED_VAR", "1")
    s = get_settings()
    assert s.agnes_rate_limit is None


def test_subtitle_ass_enabled_uses_settings(monkeypatch):
    """subtitle_ass_enabled 与 RuntimeSettings 联动。"""
    from core.config import subtitle_ass_enabled
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "1")
    assert subtitle_ass_enabled() is True
    monkeypatch.setenv("AGNES_SUBTITLE_ASS", "0")
    assert subtitle_ass_enabled() is False


def test_rate_limiter_reads_settings(monkeypatch):
    """rate_limiter 从 RuntimeSettings 读取 AGNES_RATE_LIMIT（3.5 收敛）。"""
    monkeypatch.setenv("AGNES_RATE_LIMIT", "30")
    from core.api.rate_limiter import _effective_rate
    assert _effective_rate() == 30 * 0.8
    monkeypatch.setenv("AGNES_RATE_LIMIT", "0")
    # 0/未配置 → 回退动态计算（>0）
    assert _effective_rate() > 0


# ═══════════════════════════════════════════════════
# 4. per-Key 域名绑定（get_api_key_domains / set_api_key_domains / set_api_keys）
# ═══════════════════════════════════════════════════

def test_get_api_key_domains_empty(conf_file):
    """无配置 → 返回空 dict。"""
    conf_file({})
    assert config.get_api_key_domains() == {}


def test_get_api_key_domains_reads_bindings(conf_file):
    """从 api_keys 列表读取 key -> domain 绑定。"""
    conf_file({"api_keys": [
        {"key": "sk-a", "domain": "com"},
        {"key": "sk-b", "domain": "cn"},
    ]})
    assert config.get_api_key_domains() == {"sk-a": "com", "sk-b": "cn"}


def test_get_api_key_domains_dict_entry(conf_file):
    """api_keys 为 dict 结构（旧格式）时返回空——get_api_key_domains 仅识别列表结构，
    列表化兼容由 get_api_keys_with_sources 处理。"""
    conf_file({"api_keys": {"sk-a": "cn"}})
    assert config.get_api_key_domains() == {}


def test_set_api_key_domains_writes(conf_file):
    """set_api_key_domains 落盘 domain 绑定。"""
    conf_file({"api_keys": [{"key": "sk-a", "domain": ""}]})
    config.set_api_key_domains({"sk-a": "cn"})
    assert config.get_api_key_domains() == {"sk-a": "cn"}


def test_set_api_key_domains_invalid_domain_cleared(conf_file):
    """无效域名 → 清空为 ''。"""
    conf_file({"api_keys": [{"key": "sk-a", "domain": ""}]})
    config.set_api_key_domains({"sk-a": "evil"})
    assert config.get_api_key_domains() == {"sk-a": ""}


def test_set_api_key_domains_empty_clears(conf_file):
    """空串 domain → 清除绑定。"""
    conf_file({"api_keys": [{"key": "sk-a", "domain": "com"}]})
    config.set_api_key_domains({"sk-a": ""})
    assert config.get_api_key_domains() == {"sk-a": ""}


def test_set_api_key_domains_ignores_env_key(conf_file):
    """未提及的 config key 保留原绑定。"""
    conf_file({"api_keys": [
        {"key": "sk-a", "domain": "com"},
        {"key": "sk-b", "domain": "cn"},
    ]})
    config.set_api_key_domains({"sk-b": "com"})
    domains = config.get_api_key_domains()
    assert domains["sk-a"] == "com"  # 保留
    assert domains["sk-b"] == "com"  # 更新


def test_set_api_keys_preserves_domains(conf_file, monkeypatch):
    """set_api_keys 保留仍在列表中的 Key 的域名绑定。"""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    conf_file({"api_keys": [{"key": "sk-a", "domain": "cn"}]})
    config.set_api_keys(["sk-a", "sk-b"])
    assert config.get_api_key_domains() == {"sk-a": "cn", "sk-b": ""}


def test_set_api_keys_empty_removes_field(conf_file, monkeypatch):
    """空数组 → 移除 api_keys 字段。"""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    conf_file({"api_keys": [{"key": "sk-a", "domain": ""}]})
    config.set_api_keys([])
    assert config.get_api_key_domains() == {}


def test_remove_api_key_single(conf_file, monkeypatch):
    """remove_api_key_single 移除单个 Key，返回 (changed, still_active)。"""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    conf_file({"api_keys": [{"key": "sk-a", "domain": ""}, {"key": "sk-b", "domain": ""}]})
    changed, still_active = config.remove_api_key_single("sk-a")
    assert changed is True
    assert still_active is False
    assert config.get_api_keys() == ["sk-b"]


def test_remove_api_key_single_missing(conf_file, monkeypatch):
    """移除不存在的 Key → (False, False)。"""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    conf_file({"api_keys": [{"key": "sk-a", "domain": ""}]})
    changed, still_active = config.remove_api_key_single("sk-nope")
    assert changed is False
    assert still_active is False
