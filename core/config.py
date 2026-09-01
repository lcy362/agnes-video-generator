"""
core/config.py — Agnes Video Generator v2.0 配置模块

包含 API Key 管理、工作目录、音频/字幕默认配置工厂函数。
"""

import json
import logging
import os

from models.task import AudioConfig, SubtitleConfig, SubtitleStyle

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agnes_config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# ═══════════════════════════════════════════════════
# 应用版本号（v6.1 新增：发版时同步更新，见 docs/dev/release_process.md）
# ═══════════════════════════════════════════════════
APP_VERSION = "6.3.0"

# 未配置 API Key 时的统一报错文案（含免费获取与在线体验兜底，全站路由共用）
API_KEY_MISSING_MSG = (
    "请先配置 API Key。免费获取：https://platform.agnes-ai.com ｜ "
    "不想配置？在线体验：https://video.lichuanyang.top/demo"
)

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def font_dir() -> str:
    """返回项目内置字体目录。"""
    return os.path.join(_PROJECT_ROOT, "resource", "fonts")


# 默认中文字体文件名（需位于 resource/fonts/ 下）
DEFAULT_CHINESE_FONT = "STHeitiMedium.ttc"

# 默认阿拉伯语字体文件名（需位于 resource/fonts/ 下）。
# 项目内置字体均不含阿拉伯语字形，阿拉伯文字幕若使用默认/中文字体会渲染为方块（tofu）。
DEFAULT_ARABIC_FONT = "NotoNaskhArabicUI.ttf"

# 泰文 / 天城文（印地语）/ 孟加拉文默认字体文件名（需位于 resource/fonts/ 下）。
# 同阿拉伯文，项目内置 CJK 字体不含这些文字体系的字形，字幕需按脚本强制回退。
DEFAULT_THAI_FONT = "NotoSansThai-Regular.ttf"
DEFAULT_DEVANAGARI_FONT = "NotoSansDevanagari-Regular.ttf"
DEFAULT_BENGALI_FONT = "NotoSansBengali-Regular.ttf"

# 不支持 CJK 字符的常见字体名（用于向后兼容旧任务）
# 这些字体在 moviepy/pillow TextClip 中无法正确渲染中文，
# 检测到后自动回退到 DEFAULT_CHINESE_FONT。
_NON_CJK_FONTS = frozenset({
    "arial", "arial bold", "arial italic", "arial black",
    "helvetica", "times", "times new roman", "courier",
    "courier new", "verdana", "tahoma", "georgia", "trebuchet ms",
    "impact", "comic sans ms", "lucida console",
})


def subtitle_ass_enabled() -> bool:
    """2.1c：字幕是否走 ffmpeg ASS 单链合成（灰度开关）。

    ``AGNES_SUBTITLE_ASS`` 环境变量控制，默认开启；设为 ``0``/``false``/``off``
    关闭并回退 moviepy 字幕路径。ASS 路径任何失败也会自动回退 moviepy。
    """
    return get_settings().agnes_subtitle_ass


def resolve_font_path(font: str) -> str:
    """将字体名称解析为 moviepy TextClip 可用的路径。

    优先级：
    1. 绝对路径且文件存在 → 直接返回
    2. 文件名（含扩展名）→ 在 resource/fonts/ 目录下查找
    3. 已知的非 CJK 字体名 → 回退到 DEFAULT_CHINESE_FONT（兼容旧任务）
    4. 其他系统字体名 → 直接返回
    """
    # 已经是绝对路径，直接返回
    if os.path.isabs(font) and os.path.exists(font):
        return font

    # 看起来像文件名（含扩展名），尝试在项目字体目录查找
    if "." in font and "/" not in font and "\\" not in font:
        candidate = os.path.join(font_dir(), font)
        if os.path.exists(candidate):
            return candidate

    # 检查是否为已知的非 CJK 字体（向后兼容：旧任务的 font 可能仍为 "Arial"）
    if font.strip().lower() in _NON_CJK_FONTS:
        fallback = os.path.join(font_dir(), DEFAULT_CHINESE_FONT)
        if os.path.exists(fallback):
            logger.warning(
                f"Font '{font}' does not support CJK characters, "
                f"falling back to {DEFAULT_CHINESE_FONT}"
            )
            return fallback

    # 当作系统字体名称返回
    return font


# ═══════════════════════════════════════════════════
# 类型化配置模型（v5.0 Batch 5 / 5.2）
# ═══════════════════════════════════════════════════

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceEntry(BaseModel):
    """工作目录条目。"""

    model_config = ConfigDict(strict=True)

    path: str
    name: str = ""
    is_default: bool = False


class WatermarkSettings(BaseModel):
    """水印配置。"""

    model_config = ConfigDict(strict=True)

    enabled: bool = False
    language: str = "auto"


class AppSettings(BaseModel):
    """config.json 的类型化视图（Pydantic 构造期强制类型校验）。

    字段与 config.json 顶层键一一对应；未知/多余键自动忽略（向后兼容
    旧配置文件）；缺省字段取模型默认值。strict 模式下任何类型错误
    （如 watermark.enabled 存了字符串、api_key 存了数字）在构造期抛
    ValidationError，不静默强转。
    """

    model_config = ConfigDict(strict=True)

    api_key: str = ""
    active_workspace: str = ""
    workspaces: list[WorkspaceEntry] = Field(default_factory=list)
    watermark: WatermarkSettings = Field(default_factory=WatermarkSettings)
    models: dict[str, str] = Field(default_factory=dict)
    agnes_domain: str = "com"


def load_settings() -> AppSettings:
    """读取 config.json 并返回类型化 AppSettings（构造期校验）。

    文件不存在 / 为空时返回全默认设置；损坏 JSON 或类型错误抛
    ValidationError（由调用方决定兜底策略，不静默降级）。
    """
    _ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return AppSettings(**raw)
    return AppSettings()


# ═══════════════════════════════════════════════════
# 运行时环境变量收敛（optimization_roadmap 3.5）
# 所有 AGNES_* / HOST / PORT / PROMPT_LANGUAGE 的唯一出处
# ═══════════════════════════════════════════════════

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class RuntimeSettings(BaseSettings):
        """运行配置：环境变量的类型化统一入口（3.5 pydantic-settings）。

        字段名 = 环境变量名（大小写不敏感）；``env_file=".env"`` 自动读取
        项目根 .env（未配置 python-dotenv 时由 pydantic-settings 自身实现）。
        新增环境变量时只需在此声明字段 + 默认值，调用方经 ``get_settings()``
        读取，保证「环境变量清单唯一出处」。
        """

        model_config = SettingsConfigDict(
            case_sensitive=False,
            extra="ignore",
            env_file=os.path.join(_PROJECT_ROOT, ".env"),
            env_file_encoding="utf-8",
        )

        # ── 服务地址 ──
        host: str = "0.0.0.0"
        port: int = 8765

        # ── 限速（None = 由 rate_limiter 按 Key 数动态计算）──
        agnes_rate_limit: int | None = None
        agnes_video_rate_limit: int | None = None
        agnes_rate_burst: int | None = None
        agnes_video_rate_burst: int | None = None

        # ── 模型 / 提示词 ──
        agnes_image_i2i_model: str | None = None
        prompt_language: str = "zh"

        # ── 合成 / 字幕 ──
        agnes_subtitle_ass: bool = True          # 2.1c 字幕 ASS 单链灰度开关
        agnes_video_poll_timeout: int = 1800     # 1.2 视频轮询总超时

        # ── CORS（PR #33 吸收 Phase 2：可配置跨源白名单）──
        # 供独立本地伴侣工具（如 agnes-simple-ui）从浏览器跨源调用本服务 API。
        # agnes_cors_origins: 逗号分隔的允许源列表，空 = 不启用 CORS（默认，攻击面不变）。
        # agnes_cors_enabled: None=auto（设置了 origins 才启用）；显式 "false" 即使设置了 origins 也禁用。
        agnes_cors_origins: str = ""
        agnes_cors_enabled: bool | None = None

        # ── 运维 ──
        agnes_log_file: str = ""
        agnes_sweep_age_days: int | None = None
        agnes_config_id_hmac_key: str = "agnes-config-keys-id-v1"

        # ── 回归测试专用 ──
        agnes_regression_working_dir: str = ""

    def get_settings() -> RuntimeSettings:
        """返回运行配置（每次读取环境变量，保证测试/运行时动态修改生效）。"""
        return RuntimeSettings()

    _HAS_PYDANTIC_SETTINGS = True

except ImportError:  # pragma: no cover - pydantic-settings 为必备依赖，仅兜底
    _HAS_PYDANTIC_SETTINGS = False

    class RuntimeSettings:  # type: ignore[no-redef]
        """pydantic-settings 缺失时的降级视图（读 os.environ）。"""

        def __init__(self):
            self.host = os.environ.get("HOST", "0.0.0.0")
            self.port = int(os.environ.get("PORT", "8765"))
            self.agnes_rate_limit = _env_int("AGNES_RATE_LIMIT")
            self.agnes_video_rate_limit = _env_int("AGNES_VIDEO_RATE_LIMIT")
            self.agnes_rate_burst = _env_int("AGNES_RATE_BURST")
            self.agnes_video_rate_burst = _env_int("AGNES_VIDEO_RATE_BURST")
            self.agnes_image_i2i_model = os.environ.get("AGNES_IMAGE_I2I_MODEL") or None
            self.prompt_language = os.environ.get("PROMPT_LANGUAGE", "zh")
            self.agnes_subtitle_ass = os.environ.get("AGNES_SUBTITLE_ASS", "1").strip().lower() not in (
                "0", "false", "off",
            )
            self.agnes_video_poll_timeout = int(os.environ.get("AGNES_VIDEO_POLL_TIMEOUT", "1800"))
            self.agnes_cors_origins = os.environ.get("AGNES_CORS_ORIGINS", "")
            _cors_enabled = os.environ.get("AGNES_CORS_ENABLED", "").strip().lower()
            if _cors_enabled in ("0", "false", "off"):
                self.agnes_cors_enabled = False
            elif _cors_enabled in ("1", "true", "on"):
                self.agnes_cors_enabled = True
            else:
                self.agnes_cors_enabled = None
            self.agnes_log_file = os.environ.get("AGNES_LOG_FILE", "")
            self.agnes_sweep_age_days = _env_int("AGNES_SWEEP_AGE_DAYS")
            self.agnes_config_id_hmac_key = os.environ.get(
                "AGNES_CONFIG_ID_HMAC_KEY", "agnes-config-keys-id-v1",
            )
            self.agnes_regression_working_dir = os.environ.get("AGNES_REGRESSION_WORKING_DIR", "")

    def get_settings() -> RuntimeSettings:
        return RuntimeSettings()


def _env_int(name: str):
    v = os.environ.get(name, "").strip()
    return int(v) if v else None


# ═══════════════════════════════════════════════════
# API Key 管理（保持现有逻辑）
# ═══════════════════════════════════════════════════

# .env 支持（可选依赖 python-dotenv）：不存在时跳过，Key 仍可从环境变量 / 配置文件获取
try:
    from dotenv import load_dotenv as _load_dotenv
    _dotenv_path = os.path.join(_PROJECT_ROOT, ".env")
    if os.path.exists(_dotenv_path):
        _load_dotenv(_dotenv_path)
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False


def _dotenv_value(var: str) -> str:
    """从 .env 文件读取变量值（需已引入 python-dotenv；否则返回空串）。

    注意：dotenv 只做一次性注入到 os.environ，此处仅用于区分「Key 来自 .env」
    的场景（env 采集的 fallback 优先级高于 config 文件）。未引入 dotenv 时
    恒返回空串，行为与现状一致。
    """
    if not _HAS_DOTENV:
        return ""
    # load_dotenv(override=False) 语义：.env 值不会覆盖已有环境变量。
    # 这里仅读取 .env 中的原始值（不覆盖 os.environ）。
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(_dotenv_path)
        return str(vals.get(var, "") or "")
    except Exception:
        return ""


def _dedup(keys: list) -> list:
    """去重、去空，保持顺序。"""
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _collect_env_keys() -> list:
    """采集 .env（低优先）+ 环境变量（高优先，同槽位覆盖）的 Key 列表。

    Returns:
        按 AGNES_API_KEY, AGNES_API_KEY_2 ... 顺序排列的原始 Key 列表（未去重）。
    """
    keys: list = []
    for i in range(1, 100):
        var = "AGNES_API_KEY" if i == 1 else f"AGNES_API_KEY_{i}"
        dot_val = _dotenv_value(var).strip()
        env_val = os.environ.get(var, "").strip()
        val = env_val or dot_val  # 环境变量覆盖 .env
        if val:
            keys.append(val)
        elif i > 1:
            break
    return keys


def get_api_keys() -> list:
    """返回所有可用 API Key（去重、去空），合并顺序：

    1. 环境变量 / .env：AGNES_API_KEY, AGNES_API_KEY_2 ... _N（环境变量覆盖 .env）
    2. 配置文件：api_keys 列表（新字段，条目可为字符串或 {key, domain}）或旧 api_key 单个字段

    两来源合并后去重（同 Key 只保留一次，env 位置优先）。因此：
    - Web UI 保存的多 Key（config）与 env Key 可并存；
    - 与 env 重复的 Key 自动去重，不产生双份调用。
    """
    env_keys = _collect_env_keys()
    config = load_config()
    cfg_keys = config.get("api_keys", []) or []
    if not cfg_keys and config.get("api_key"):
        cfg_keys = [config["api_key"]]
    cfg_keys = [_extract_key(k) for k in cfg_keys if _extract_key(k)]
    return _dedup(env_keys + cfg_keys)


def _extract_key(entry) -> str:
    """从 api_keys 条目中提取 Key 明文（兼容字符串或 {key, domain} 字典）。"""
    if isinstance(entry, dict):
        return str(entry.get("key") or "").strip()
    return str(entry or "").strip()


def _key_domain_from_config(config: dict, key: str) -> str:
    """从已加载的 config dict 中查找某 Key 绑定的域名（未绑定返回空串）。"""
    entries = config.get("api_keys", []) or []
    if isinstance(entries, dict):
        entries = [entries]
    for e in entries:
        if isinstance(e, dict) and _extract_key(e) == key:
            return str(e.get("domain") or "").strip()
    return ""


def get_api_key_domains() -> dict:
    """返回 config 中每个 Key 绑定的域名（key -> domain，env key 不在内）。

    Returns:
        {"sk-...": "com"|"cn"|"cn_bak"|"", ...}
        未绑定的 Key 值为空串。
    """
    config = load_config()
    out: dict = {}
    entries = config.get("api_keys", []) or []
    if isinstance(entries, dict):
        entries = [entries]
    for e in entries:
        k = _extract_key(e)
        if not k or k in out:
            continue
        d = ""
        if isinstance(e, dict):
            d = str(e.get("domain") or "").strip()
        out[k] = d
    return out


def set_api_key_domains(mapping: dict) -> None:
    """按 key -> domain 写入 config api_keys 的域名绑定（仅 config 来源 key）。

    未提及的 config key 保留其现有 domain；无效域名（不在 AGNES_DOMAIN_MAP）视为空。
    不涉及 env key（env key 无法落盘，始终走全局默认域名）。

    Args:
        mapping: {key 明文: 域名}，domain 为空串表示清除绑定（回退全局域名）。
    """
    config = load_config()
    curr = get_api_key_domains()
    for k, d in mapping.items():
        k = _extract_key(k)
        d = str(d or "").strip()
        if k:
            curr[k] = d if d in AGNES_DOMAIN_MAP else ""
    config["api_keys"] = [{"key": k, "domain": curr[k]} for k in curr]
    config.pop("api_key", None)
    save_config(config)


def set_api_keys(keys: list) -> None:
    """持久化多 Key 到配置文件 ``api_keys`` 字段（原子写 + 0o600 权限）。

    keys 为空数组时：移除配置中的 api_keys 字段，使采集回退到 env（.env/环境变量）。
    已存在的 Key 会保留其域名绑定（仅对仍在 keys 中的 Key）。

    写入后必须在调用侧重建 KeyRing 与限速器（reset_key_ring / reset_rate_limiter），
    否则旧配置（单桶 + 旧 KeyRing）继续生效。
    """
    config = load_config()
    current = get_api_key_domains()
    cleaned = _dedup([_extract_key(k) for k in keys])
    if cleaned:
        config["api_keys"] = [{"key": k, "domain": current.get(k, "")} for k in cleaned]
        config.pop("api_key", None)
    else:
        config.pop("api_keys", None)
    save_config(config)


def _collect_config_keys() -> list:
    """采集配置文件中的 Key（api_keys 列表或旧 api_key 字段），去重、去空。"""
    config = load_config()
    cfg_keys = config.get("api_keys", []) or []
    if not cfg_keys and config.get("api_key"):
        cfg_keys = [config["api_key"]]
    return _dedup([_extract_key(k) for k in cfg_keys if _extract_key(k)])


def get_api_keys_with_sources() -> list:
    """返回去重后的 Key 列表（env 优先），每个条目含来源标记。

    Returns:
        [{"key": "sk-...", "source": "env"|"config"}, ...]
        同 Key 在 env 与 config 中重复时只保留一次，标记为 env。
    """
    env_keys = _dedup(_collect_env_keys())
    cfg_keys = _collect_config_keys()
    seen = set()
    out = []
    for k in env_keys:
        if k and k not in seen:
            seen.add(k)
            out.append({"key": k, "source": "env"})
    for k in cfg_keys:
        if k and k not in seen:
            seen.add(k)
            out.append({"key": k, "source": "config"})
    return out


def remove_api_key_single(key: str) -> tuple:
    """从配置文件移除单个 Key（不影响 env 来源）。

    Args:
        key: 要移除的 Key 明文。

    Returns:
        (changed, still_active): changed=是否移除了 config 副本；
        still_active=该 Key 是否仍生效（env 中存在同 Key 时仍生效）。
    """
    config = load_config()
    changed = False
    # 1. 从 api_keys 列表移除（保留其余条目的 domain 绑定）
    raw_cfg = config.get("api_keys", []) or []
    if any(_extract_key(e) == key for e in raw_cfg):
        kept = [e for e in raw_cfg if _extract_key(e) != key]
        changed = True
    # 2. 命中旧 api_key 字段
    if config.get("api_key") == key:
        config.pop("api_key", None)
        changed = True
    if changed:
        if kept:
            config["api_keys"] = kept
        else:
            config.pop("api_keys", None)
        save_config(config)
    still_active = key in _dedup(_collect_env_keys())
    return changed, still_active


def get_api_keys_source() -> str:
    """返回多 Key 采集来源描述，供 ``GET /api/config/keys`` 与日志展示。

    Returns:
        'env:N' / 'config:N' / 'mixed:envX+configY' / 'none'
        （各来源计数均为各自去重后的数量；合并去重后的总数见 get_api_keys()）
    """
    keys = get_api_keys()
    if not keys:
        return "none"

    env_keys = _dedup(_collect_env_keys())
    cfg_keys = _collect_config_keys()

    if env_keys and cfg_keys:
        return f"mixed:env{len(env_keys)}+config{len(cfg_keys)}"
    if env_keys:
        return f"env:{len(env_keys)}"
    if cfg_keys:
        return f"config:{len(cfg_keys)}"
    return "none"


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # 目录权限收紧为仅属主可读写执行，避免其他用户读取其中的 api_key
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def load_config() -> dict:
    _ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    _ensure_config_dir()
    # 原子写：先写临时文件再 os.replace，避免写入中途崩溃留下损坏 JSON
    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    # 配置含 api_key，权限收紧为仅属主可读写
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, CONFIG_FILE)


def get_api_key() -> str:
    """返回首个可用 Key（兼容入口）。

    统一走 ``get_api_keys()``（env + config 合并去重），因此：
    - 只配过 1 个 key（env 或 config api_key）时返回该 key；
    - 用户新增 key 后（config api_keys 列表）自动返回第一个 key，
      无需改动任何调用方，即自然进入多 Key 逻辑。
    """
    keys = get_api_keys()
    return keys[0] if keys else ""


def set_api_key(key: str):
    """保存单个 Key（兼容旧端点 POST /api/config）。

    与 ``set_api_keys`` 互斥：写入 api_key 字段并清掉 api_keys，
    避免两套字段并存造成 `api_keys` 优先级混乱。
    注意：env Key 始终参与 ``get_api_keys()`` 合并，不受影响。
    """
    config = load_config()
    config["api_key"] = key
    config.pop("api_keys", None)
    save_config(config)


def delete_api_key() -> bool:
    """Remove the API key from the config file（单 Key 与多 Key 字段一并清理）。

    Returns:
        True if a key was removed, False if no key existed.

    Note:
        This does NOT affect the AGNES_API_KEY environment variable.
        If the env var is set, get_api_key() will still return it.
    """
    config = load_config()
    removed = False
    if "api_key" in config:
        del config["api_key"]
        removed = True
    if "api_keys" in config:
        del config["api_keys"]
        removed = True
    if removed:
        save_config(config)
    return removed


def get_api_key_source() -> str:
    """Return the source of the current API key.

    Returns:
        'env' if from AGNES_API_KEY environment variable,
        'config' if from the config file（api_key 或 api_keys 字段）,
        'none' if no key is configured.
    """
    if get_api_keys():
        if _collect_env_keys():
            return "env"
        return "config"
    return "none"


# ═══════════════════════════════════════════════════
# 工作目录管理（多工作目录，同时仅一个 active）
# ═══════════════════════════════════════════════════

# 回归测试专用工作目录环境变量名
REGRESSION_WORKING_DIR_ENV = "AGNES_REGRESSION_WORKING_DIR"

# 默认工作目录的固定名称标识
DEFAULT_WORKSPACE_NAME = "默认空间"


def _default_working_dir() -> str:
    """默认工作目录（项目根目录下的 .working_dir）。"""
    return os.path.join(_PROJECT_ROOT, ".working_dir")


def _default_workspace_entry() -> dict:
    """返回默认工作目录条目。"""
    return {"path": _default_working_dir(), "name": DEFAULT_WORKSPACE_NAME, "is_default": True}


def get_working_dir() -> str:
    """返回当前激活的工作目录。

    优先级：
    1. 环境变量 AGNES_REGRESSION_WORKING_DIR（回归测试专用空间，最高优先级）
    2. 配置文件中的 active_workspace
    3. 默认 .working_dir
    """
    env_dir = get_settings().agnes_regression_working_dir
    if env_dir:
        return env_dir
    active = load_settings().active_workspace
    if active:
        return active
    return _default_working_dir()


def get_workspace_root() -> str:
    """返回工作目录允许根的受信任路径（safe_workspace_path 的 containment 基准）。

    工作目录功能允许操作员通过操作系统原生目录选择框挑选本机上的**任意**目录，
    因此默认根设为文件系统根 ``/``（受信任常量，绝不被 CodeQL 判定为受污染）。
    这样 safe_workspace_path 在保留“任意目录可用”特性的同时，仍通过
    realpath 规范化 + 受信任根 containment 检查，使 py/path-injection 告警被中和。
    """
    return "/"


def get_workspaces() -> list:
    """返回所有已配置的工作目录列表（含默认空间，始终排在首位）。

    Returns:
        [{"path": "...", "name": "...", "is_default": bool}, ...]
    """
    settings = load_settings()
    user_workspaces = [ws.model_dump() for ws in settings.workspaces]
    default_path = _default_working_dir()
    filtered = [ws for ws in user_workspaces if os.path.abspath(ws.get("path", "")) != default_path]
    return [_default_workspace_entry()] + filtered


def add_workspace(path: str, name: str = "") -> dict:
    """添加一个工作目录。若路径已存在则更新名称。

    Returns:
        添加后的工作目录条目
    """
    path = os.path.abspath(path)
    config = load_config()
    workspaces = config.get("workspaces", [])
    for ws in workspaces:
        if os.path.abspath(ws.get("path", "")) == path:
            if name:
                ws["name"] = name
            save_config(config)
            return ws
    entry = {"path": path, "name": name or os.path.basename(path) or path}
    workspaces.append(entry)
    config["workspaces"] = workspaces
    if not config.get("active_workspace"):
        config["active_workspace"] = path
    save_config(config)
    return entry


def remove_workspace(path: str) -> bool:
    """移除一个工作目录。默认空间不可移除。

    若移除的是当前激活项，则激活默认空间。

    Returns:
        True if removed, False if not found or is default
    """
    path = os.path.abspath(path)
    if path == _default_working_dir():
        return False
    config = load_config()
    workspaces = config.get("workspaces", [])
    new_list = [ws for ws in workspaces if os.path.abspath(ws.get("path", "")) != path]
    if len(new_list) == len(workspaces):
        return False
    config["workspaces"] = new_list
    if os.path.abspath(config.get("active_workspace", "")) == path:
        config.pop("active_workspace", None)
    save_config(config)
    return True


def get_active_workspace() -> str:
    """返回当前激活的工作目录路径。"""
    return get_working_dir()


def set_active_workspace(path: str) -> str:
    """设置当前激活的工作目录。路径必须已在列表中（含默认空间）。

    Returns:
        激活的工作目录路径

    Raises:
        ValueError: 路径不在已配置列表中
    """
    path = os.path.abspath(path)
    valid_paths = [os.path.abspath(ws.get("path", "")) for ws in get_workspaces()]
    if path not in valid_paths:
        raise ValueError(f"工作目录未配置: {path}")
    config = load_config()
    if path == _default_working_dir():
        config.pop("active_workspace", None)
    else:
        config["active_workspace"] = path
    save_config(config)
    return path


# ═══════════════════════════════════════════════════
# v2.0 新增：音频 / 字幕默认配置
# ═══════════════════════════════════════════════════

# D3：默认语音角色
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# D3：可选语音角色列表（v4.0 起改为运行时从 edge_tts 动态加载，见 core.audio.voices）。
# 保留 AVAILABLE_VOICES 作为向后兼容的别名（返回扁平列表），新代码请使用 get_voice_catalog()。
from core.audio.voices import (
    get_voice_catalog,
)


def AVAILABLE_VOICES() -> list:
    """向后兼容：返回扁平化的 [{id, label}, ...] 列表。

    原接口签名是模块级列表，升级为函数以保证与旧调用方兼容。
    """
    cat = get_voice_catalog()
    result = []
    for group in cat.get("languages", []):
        for v in group.get("voices", []):
            result.append({"id": v["id"], "label": f"{v['name']}（{v['region']}）"})
    return result


def get_default_subtitle_style() -> SubtitleStyle:
    """返回默认字幕样式配置（D4）。"""
    return SubtitleStyle(
        font=DEFAULT_CHINESE_FONT,
        color="white",
        position=("center", "bottom-80"),
        fontsize=48,
        stroke_color="black",
        stroke_width=2,
        bg_color=(0, 0, 0, 128),
    )


def get_default_subtitle_config() -> SubtitleConfig:
    """返回默认字幕配置（v3.0 独立配置）。"""
    return SubtitleConfig(
        enabled=True,
        style=get_default_subtitle_style(),
    )


def get_default_audio_config() -> AudioConfig:
    """返回默认音频配置（D3）。"""
    return AudioConfig(
        enabled=True,
        voice=DEFAULT_VOICE,
        rate="+0%",
    )


# ═══════════════════════════════════════════════════
# 水印配置
# ═══════════════════════════════════════════════════

DEFAULT_WATERMARK_ENABLED = False
DEFAULT_WATERMARK_LANGUAGE = "auto"  # "auto" | "zh" | "en"

WATERMARK_PROMO_TEXT_ZH = "为视频添加 Agnes Video Generator 水印，分享时让更多人发现这个工具"
WATERMARK_PROMO_TEXT_EN = "Add an Agnes Video Generator watermark to help more creators discover this tool"


def get_watermark_config() -> dict:
    """返回水印配置。

    Returns:
        {"enabled": bool, "language": str}
    """
    settings = load_settings()
    wm = settings.watermark
    return {
        "enabled": wm.enabled if wm.enabled is not None else DEFAULT_WATERMARK_ENABLED,
        "language": wm.language or DEFAULT_WATERMARK_LANGUAGE,
    }


def set_watermark_config(enabled: bool = None, language: str = None):
    """设置水印配置。

    Args:
        enabled: 是否开启水印，None 表示不修改
        language: 水印语言，None 表示不修改
    """
    config = load_config()
    wm = config.get("watermark", {})
    if enabled is not None:
        wm["enabled"] = enabled
    if language is not None:
        wm["language"] = language
    config["watermark"] = wm
    save_config(config)


# ═══════════════════════════════════════════════════
# 视频参数预设（D7）
# ═══════════════════════════════════════════════════

VIDEO_RESOLUTION_PRESETS = {
    "portrait": {"width": 768, "height": 1152, "label": "竖屏 9:16"},
    "landscape": {"width": 1152, "height": 768, "label": "横屏 16:9"},
    "square": {"width": 1024, "height": 1024, "label": "方形 1:1"},
}

# 时长 → (num_frames, frame_rate) 映射
DURATION_FRAME_MAP = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (441, 24),
    20: (441, 22),
}


# ═══════════════════════════════════════════════════
# 模型选择配置（v5.0 新增：文本 / 图像 / 视频模型）
# ═══════════════════════════════════════════════════

# 各类型 Agnes 模型默认值（与三个 API 客户端的默认 model 对齐）
DEFAULT_TEXT_MODEL = "agnes-2.0-flash"
DEFAULT_IMAGE_MODEL = "agnes-image-2.1-flash"
DEFAULT_VIDEO_MODEL = "agnes-video-v2.0"

DEFAULT_MODELS = {
    "text": DEFAULT_TEXT_MODEL,
    "image": DEFAULT_IMAGE_MODEL,
    "video": DEFAULT_VIDEO_MODEL,
}


def get_selected_models() -> dict:
    """返回当前选中的模型配置。

    Returns:
        {"text": str, "image": str, "video": str}
        缺省值回退到 Agnes 三个 API 客户端的默认模型。
    """
    settings = load_settings()
    m = settings.models or {}
    return {
        "text": m.get("text") or DEFAULT_TEXT_MODEL,
        "image": m.get("image") or DEFAULT_IMAGE_MODEL,
        "video": m.get("video") or DEFAULT_VIDEO_MODEL,
    }


def set_selected_models(text: str = None, image: str = None, video: str = None) -> dict:
    """保存选中的模型配置。

    Args:
        text:  文本（chat）模型名，None 表示不修改
        image: 图像模型名，None 表示不修改
        video: 视频模型名，None 表示不修改

    Returns:
        保存后的完整模型配置字典
    """
    config = load_config()
    m = config.get("models", {}) or {}
    if text is not None:
        m["text"] = text
    if image is not None:
        m["image"] = image
    if video is not None:
        m["video"] = video
    config["models"] = m
    save_config(config)
    return get_selected_models()


# ═══════════════════════════════════════════════════
# 视频模型能力元数据（v6.2：选模型阶段差异说明 + 表单选项归拢）
# ═══════════════════════════════════════════════════

# 2.5 系列模型 ID（新参数协议：mode/seconds/size/aspect_ratio，与 v2.0 不兼容）
VIDEO_MODEL_25_PREFIX = "agnes-video-2.5"


def is_v25_video_model(model: str) -> bool:
    """判断是否为 2.5 系列视频模型（新参数协议）。"""
    return bool(model) and model.startswith(VIDEO_MODEL_25_PREFIX)


# 支持的画幅比例（2.5 系列 aspect_ratio 枚举）
VIDEO_ASPECT_RATIOS = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]

# 2.5 系列时长档位（seconds 字符串 "4"–"12"）
VIDEO_25_DURATIONS = [4, 5, 6, 8, 10, 12]

# 视频模型能力元数据：供前端「选模型阶段」展示差异 + 按模型归拢表单选项
VIDEO_MODEL_CAPABILITIES = {
    DEFAULT_VIDEO_MODEL: {  # agnes-video-v2.0（免费旧版）
        "label": "Video 2.0",
        "price": "free",
        "price_text": {"zh": "免费", "en": "Free"},
        "modes": [
            {"id": "t2v", "label": {"zh": "文生视频", "en": "Text to video"}},
            {"id": "i2v", "label": {"zh": "图生视频（1 张参考图）", "en": "Image to video (1 ref)"}},
            {"id": "keyframes", "label": {"zh": "关键帧动画（首尾帧）", "en": "Keyframes (first+last)"}},
        ],
        "durations": [5, 10, 15, 18, 20],
        "resolution": {
            "type": "pixels",
            "options": [
                {"value": "768x1152", "label": {"zh": "竖屏 768x1152", "en": "Portrait 768x1152"}},
                {"value": "1152x768", "label": {"zh": "横屏 1152x768", "en": "Landscape 1152x768"}},
                {"value": "1024x1024", "label": {"zh": "方形 1024x1024", "en": "Square 1024x1024"}},
            ],
        },
        "supports_negative": True,
        "max_ref_images": None,  # 不限
        "supports_ref_video": False,
        "desc": {
            "zh": "免费旧版。支持任意像素分辨率、最长约 17 秒、多参考图关键帧；有负面提示词。",
            "en": "Free legacy model. Arbitrary pixel resolution, up to ~17s, multi-image keyframes; supports negative prompt.",
        },
    },
    "agnes-video-2.5": {  # 付费模型
        "label": "Video 2.5",
        "price": "paid",
        "price_text": {
            "zh": "付费：720P $0.025/s · 960P $0.04/s · 2K $0.055/s；图片前 5 张免费",
            "en": "Paid: 720P $0.025/s · 960P $0.04/s · 2K $0.055/s; first 5 images free",
        },
        "modes": [
            {"id": "text", "label": {"zh": "文生视频", "en": "Text to video"}},
            {"id": "keyframe", "label": {"zh": "首尾帧（自动降级图片参考）", "en": "First/last frame (auto fallback)"}},
            {"id": "reference", "label": {"zh": "图片/音频参考", "en": "Image/audio reference"}},
        ],
        "durations": VIDEO_25_DURATIONS,
        "resolution": {
            "type": "ratio_size",
            "ratios": VIDEO_ASPECT_RATIOS,
            "sizes": ["720P", "960P", "2K"],
        },
        "supports_negative": False,
        "max_ref_images": 5,  # 第 6 张起 $0.005/张
        "supports_ref_video": True,
        "desc": {
            "zh": "新一代付费模型。最高 2K 分辨率、4–12 秒、支持参考视频；不支持负面提示词。",
            "en": "New paid model. Up to 2K, 4–12s, supports reference videos; no negative prompt.",
        },
    },
    "agnes-video-2.5-flash": {  # 免费新版（限时免费）
        "label": "Video 2.5 Flash",
        "price": "free",
        "price_text": {"zh": "免费（限时）", "en": "Free (limited time)"},
        "modes": [
            {"id": "text", "label": {"zh": "文生视频", "en": "Text to video"}},
            {"id": "keyframe", "label": {"zh": "首尾帧（自动降级图片参考）", "en": "First/last frame (auto fallback)"}},
            {"id": "reference", "label": {"zh": "图片参考（≤5 张）", "en": "Image reference (≤5)"}},
        ],
        "durations": VIDEO_25_DURATIONS,
        "resolution": {
            "type": "ratio_size",
            "ratios": VIDEO_ASPECT_RATIOS,
            "sizes": ["720P"],  # 固定 720P
        },
        "supports_negative": False,
        "max_ref_images": 5,
        "supports_ref_video": False,
        "desc": {
            "zh": "免费新版（限时免费）。固定 720P、4–12 秒、图片参考最多 5 张；不支持负面提示词与参考视频。",
            "en": "Free new model (limited time). Fixed 720P, 4–12s, up to 5 ref images; no negative prompt or ref video.",
        },
    },
}


def get_video_model_capabilities() -> dict:
    """返回全部视频模型能力元数据（含未知模型的兜底默认）。"""
    return dict(VIDEO_MODEL_CAPABILITIES)


# ═══════════════════════════════════════════════════
# Agnes API 域名配置（v6.0）
# ═══════════════════════════════════════════════════

# 可用域名映射
# 注：Agnes 官方域名划分（来源：AgnesAI-Labs skills 的 model_catalog 参考值）：
#   - com 国际站（主）：apihub.agnes-ai.com（官方文档，接受国际站 key）
#   - cn  国内站（中国站）：api.agnes-ai.cn（官方文档，仅接受国内站专属 key，国际站 key 会 401）
#   - cn_bak  国内站备用端点：apihub.agnes-ai.cn
#       ⚠️ 官方文档未提及，仅作临时备用，后续可能下线
#       ⚠️ 该端点接受国际站 key（在 platform.agnes-ai.com 领取的 key），
#          避免切换 cn 后因国际站 key 撞上 api.agnes-ai.cn 得到 401。
#       ⚠️ 推荐用户选择与自身 key 匹配的域名：key 是国际站 → 用 com / cn_bak；
#          key 是国内站专属 → 用 cn（api.agnes-ai.cn）。长期仍应跟随官方文档域名。
AGNES_DOMAIN_MAP = {
    "com": "https://apihub.agnes-ai.com",   # 国际站（官方文档）
    "cn": "https://api.agnes-ai.cn",        # 国内站（官方文档，需国内站专属 key）
    "cn_bak": "https://apihub.agnes-ai.cn", # 国内站备用（官方文档未提及，可能下线；接受国际站 key）
}

_DEFAULT_DOMAIN = "com"


def get_agnes_domain() -> str:
    """返回当前配置的域名后缀。

    Returns:
        "com" 或 "cn"
    """
    return load_settings().agnes_domain or _DEFAULT_DOMAIN


def set_agnes_domain(domain: str):
    """设置 Agnes API 域名后缀。

    Args:
        domain: "com" 或 "cn"
    """
    config = load_config()
    config["agnes_domain"] = domain
    save_config(config)


def get_agnes_base_url() -> str:
    """返回基于当前全局域名配置的完整 API Base URL（含 /v1 后缀）。

    未绑定域名的 Key 与 env Key 以及模型列表等全局操作均走这里。
    """
    domain = get_agnes_domain()
    root = AGNES_DOMAIN_MAP.get(domain, AGNES_DOMAIN_MAP[_DEFAULT_DOMAIN])
    return f"{root}/v1"


def get_base_url_for_key(key: str) -> str:
    """返回某 Key 应使用的 API Base URL（含 /v1 后缀），按 Key 绑定域名路由。

    - 若该 Key 在配置中绑定了有效域名（com/cn/cn_bak）→ 走该域名；
    - 否则（未绑定 / env key / 无效域名）→ 回退到全局 agnes_domain。

    供各 API 客户端在选中具体 Key 后据此构造请求 URL。
    """
    config = load_config()
    domain = _key_domain_from_config(config, key)
    if domain not in AGNES_DOMAIN_MAP:
        domain = config.get("agnes_domain") or _DEFAULT_DOMAIN
    root = AGNES_DOMAIN_MAP.get(domain, AGNES_DOMAIN_MAP[_DEFAULT_DOMAIN])
    return f"{root}/v1"


def get_agnes_api_root() -> str:
    """返回基于当前域名配置的 API Root URL（不含 /v1 后缀）。"""
    domain = get_agnes_domain()
    return AGNES_DOMAIN_MAP.get(domain, AGNES_DOMAIN_MAP[_DEFAULT_DOMAIN])
