"""core.api.agnes_models — 拉取 Agnes 可用模型列表（v5.0）

封装 GET /v1/models?all=true，按模型 ID 前缀分组为 text/image/video 三类。
接口失败（网络/鉴权/非 200）时回退到硬编码默认列表，保证 UI 始终可用。
"""

import logging

import requests

from core.config import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    DEFAULT_VIDEO_MODEL,
    get_base_url_for_key,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20

# 分组失败时的兜底列表
_FALLBACK = {
    "text": [DEFAULT_TEXT_MODEL],
    "image": [DEFAULT_IMAGE_MODEL, "agnes-image-2.1-flash", "agnes-image-2.0-flash"],
    "video": [DEFAULT_VIDEO_MODEL],
}

# 已废弃、应从可选列表中剔除的模型 ID（如 agnes-2.0-flash，官方已迁移至 agnes-2.5-flash）
_DEPRECATED_MODELS = {"agnes-2.0-flash"}


def _classify(model_id: str) -> str:
    """根据模型 ID 前缀判断分组。

    - ``agnes-image*`` → image
    - ``agnes-video*`` → video
    - 其余（如 ``agnes-2.5-flash``）→ text
    """
    if model_id.startswith("agnes-image"):
        return "image"
    if model_id.startswith("agnes-video"):
        return "video"
    return "text"


def fetch_available_models(api_key: str) -> dict:
    """拉取并按类型分组 Agnes 可用模型。

    Args:
        api_key: Agnes API Key（Bearer Token）。

    Returns:
        {"text": [model_id, ...], "image": [...], "video": [...]}
        接口失败（网络/鉴权/非 200）时返回硬编码兜底列表。
    """
    try:
        endpoint = f"{get_base_url_for_key(api_key)}/models?all=true"
        resp = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(
                "[AgnesModels] /v1/models returned HTTP %s, using fallback",
                resp.status_code,
            )
            return dict(_FALLBACK)
        data = resp.json()
        grouped = {"text": [], "image": [], "video": []}
        for item in data.get("data", []):
            mid = item.get("id")
            if not mid or mid in _DEPRECATED_MODELS:
                continue
            grouped[_classify(mid)].append(mid)
        # 任一分类为空则补回默认，避免 UI 空下拉
        for k, default in _FALLBACK.items():
            if not grouped[k]:
                grouped[k] = list(default)
        # 确保各分类的默认模型始终在可选列表内（如服务端未返回时也能选择）
        _defaults = {
            "text": DEFAULT_TEXT_MODEL,
            "image": DEFAULT_IMAGE_MODEL,
            "video": DEFAULT_VIDEO_MODEL,
        }
        for k, d in _defaults.items():
            if d not in grouped[k]:
                grouped[k].append(d)
        return grouped
    except Exception as e:  # noqa: BLE001
        logger.warning("[AgnesModels] fetch failed (%s), using fallback", e)
        return dict(_FALLBACK)
