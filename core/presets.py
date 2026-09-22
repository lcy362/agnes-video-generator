"""core/presets.py — 风格/提示词预设库（P0-1）。

数据来源分两层：
- **系统预设**（只读）：`resource/presets/styles.json`，只存 id + category + prompt；
  名称/分类文案走前端 i18n（避免 JSON 内联 22 语言）。
- **用户预设**（可读写）：持久化到 `.agnes_config/presets.json`，name 用户自填，
  不参与翻译，category 固定为 ``custom``。

纯函数、无后端依赖；复用 ``core.config.CONFIG_DIR`` 与原子写约定，不引入数据库，
不新增任务内实体文件。
"""

import json
import logging
import os
import uuid
from datetime import datetime

from core.config import _PROJECT_ROOT, CONFIG_DIR

logger = logging.getLogger(__name__)

# 系统预设源文件（随项目分发，只读）
_SYSTEM_PRESETS_PATH = os.path.join(_PROJECT_ROOT, "resource", "presets", "styles.json")
# 用户预设持久化文件（与 config.json 同级）
_USER_PRESETS_PATH = os.path.join(CONFIG_DIR, "presets.json")

# 用户自定义预设的固定分类
USER_CATEGORY = "custom"


def load_system_presets() -> list[dict]:
    """读取系统预设，失败（缺失/损坏）时返回空列表。

    Returns:
        ``[{"id": str, "category": str, "prompt": str}, ...]``
    """
    try:
        with open(_SYSTEM_PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            preset = {
                "id": str(item.get("id", "")),
                "category": str(item.get("category", "")),
                "prompt": str(item.get("prompt", "")),
            }
            if preset["id"]:
                out.append(preset)
        return out
    except Exception as e:
        logger.warning("[Presets] Failed to load system presets: %s", e)
        return []


def _load_user_raw() -> list[dict]:
    """读取用户预设列表（未校验），损坏/缺失时返回 []。"""
    if not os.path.exists(_USER_PRESETS_PATH):
        return []
    try:
        with open(_USER_PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("[Presets] Failed to load user presets: %s", e)
        return []


def load_user_presets() -> list[dict]:
    """读取用户预设（结构化过滤）。

    Returns:
        ``[{"id", "name", "category": "custom", "prompt", "created_at"}, ...]``
    """
    return [
        {
            "id": str(p.get("id", "")),
            "name": str(p.get("name", "未命名")),
            "category": USER_CATEGORY,
            "prompt": str(p.get("prompt", "")),
            "created_at": str(p.get("created_at", "")),
        }
        for p in _load_user_raw()
        if isinstance(p, dict) and p.get("id")
    ]


def _save_user_raw(items: list[dict]):
    """原子写用户预设到 .agnes_config/presets.json。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp_path = _USER_PRESETS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, _USER_PRESETS_PATH)


def create_user_preset(name: str, prompt: str) -> dict:
    """新增一条用户预设。

    Args:
        name: 用户自填名称（可重复，原样保存）。
        prompt: 预设 prompt 本体。

    Returns:
        新建的预设 dict（含 id / created_at）。
    """
    preset = {
        "id": "u_" + uuid.uuid4().hex[:10],
        "name": name.strip() or "未命名",
        "category": USER_CATEGORY,
        "prompt": prompt.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items = _load_user_raw()
    items.append(preset)
    _save_user_raw(items)
    return preset


def delete_user_preset(preset_id: str) -> bool:
    """删除一条用户预设。

    Args:
        preset_id: 用户预设 id。

    Returns:
        True 删除成功；False 未找到该用户预设。
    """
    items = _load_user_raw()
    kept = [p for p in items if str(p.get("id", "")) != preset_id]
    if len(kept) == len(items):
        return False
    _save_user_raw(kept)
    return True


def is_system_preset(preset_id: str) -> bool:
    """判断 preset_id 是否为系统预设（系统预设只读，不可删）。"""
    return any(p["id"] == preset_id for p in load_system_presets())


def get_system_preset_ids() -> set[str]:
    """返回系统预设 id 集合（供删除校验用）。"""
    return {p["id"] for p in load_system_presets()}


def grouped_presets() -> tuple[list[dict], list[dict]]:
    """返回 (系统预设按分类分组, 用户预设平面列表)。

    系统分组用于前端「按分类下拉」；用户预设作为独立 ``custom`` 分组追加。
    此组合避免在本模块内重复实现分类聚合逻辑。
    """
    system = load_system_presets()
    user = load_user_presets()
    return system, user