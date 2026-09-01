"""配置类路由：API Key、模型、水印、域名。"""
from __future__ import annotations

import hashlib
import os
import re
import time

from fastapi import APIRouter, Form, HTTPException

from core.api.agnes_models import fetch_available_models
from core.api.key_manager import reset_key_ring
from core.api.rate_limiter import reset_rate_limiter
from core.config import (
    AGNES_DOMAIN_MAP,
    APP_VERSION,
    REGRESSION_WORKING_DIR_ENV,
    WATERMARK_PROMO_TEXT_EN,
    WATERMARK_PROMO_TEXT_ZH,
    delete_api_key,
    get_active_workspace,
    get_agnes_domain,
    get_api_key,
    get_api_key_source,
    get_api_keys,
    get_api_key_domains,
    get_api_keys_source,
    get_api_keys_with_sources,
    get_selected_models,
    get_video_model_capabilities,
    get_watermark_config,
    get_workspaces,
    load_config,
    remove_api_key_single,
    set_agnes_domain,
    set_api_key,
    set_api_key_domains,
    set_api_keys,
    set_selected_models,
    set_watermark_config,
)

router = APIRouter(tags=["config"])

# 模型列表服务端缓存，避免每次页面加载都打外部接口（apihub.agnes-ai.com）导致变慢。
# TTL 默认 5 分钟；?refresh=1 或缓存过期时重新拉取。
_MODEL_CACHE = {"models": None, "ts": 0.0, "ttl": 300}


@router.get("/api/config")
async def get_config():
    key = get_api_key()
    source = get_api_key_source()
    active_ws = get_active_workspace()
    wm = get_watermark_config()
    data = {
        "app_version": APP_VERSION,
        "api_key": key[:8] + "..." if key else "",
        "source": source,
        "can_clear": source == "config",
        "workspaces": get_workspaces(),
        "active_workspace": active_ws,
        "working_dir_source": "regression" if os.environ.get(REGRESSION_WORKING_DIR_ENV) else "config",
        "watermark": wm,
        "watermark_promo_zh": WATERMARK_PROMO_TEXT_ZH,
        "watermark_promo_en": WATERMARK_PROMO_TEXT_EN,
        "models": get_selected_models(),
        "agnes_domain": get_agnes_domain(),
        "agnes_domains": list(AGNES_DOMAIN_MAP.keys()),
    }
    return data


@router.post("/api/config")
async def save_config(api_key: str = Form(...)):
    set_api_key(api_key)
    return {"ok": True}


@router.delete("/api/config")
async def clear_config():
    """Delete the API key(s) from the config file（api_key 与 api_keys 一并清除）。"""
    source = get_api_key_source()
    if source == "env":
        raise HTTPException(
            status_code=400,
            detail="API Key 来自环境变量，无法从界面清除",
        )
    delete_api_key()
    # 清除后重建 KeyRing 与限速器（回退到 env 采集 / 空）
    reset_key_ring()
    reset_rate_limiter()
    return {"ok": True}


# ═══════════════════════════════════════════════════
# 多 API Key（优化 1：多 Key 轮询 + 限流整合）
# ═══════════════════════════════════════════════════

def _mask_key(key: str) -> str:
    """生成 Key 掩码：仅展示首 6 + 尾 4，中间省略。"""
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***"


# _key_id 用带迭代的 PBKDF2（慢哈希）生成 Key 标识。迭代次数为速度与强度的折中：
# 本机约 15ms/次，少量 Key 场景下 GET /api/config/keys 可接受；同时满足
# CodeQL 对「有限输入空间敏感数据」使用抗爆破哈希的推荐（HMAC-SHA256 会被标记）。
_KEY_ID_PBKDF2_ITERATIONS = 100_000


def _key_id(key: str) -> str:
    """生成 Key 的稳定标识（PBKDF2-HMAC-SHA256 前 24 位），供前端删除时定位，不回传明文。

    使用带迭代的 PBKDF2（keyed 慢哈希、不可离线爆破），避免对敏感
    Key 使用可直接哈希爆破的算法。ID 每次 GET 动态生成，算法更换无兼容性影响。
    """
    from core.config import get_settings
    secret = get_settings().agnes_config_id_hmac_key.encode("utf-8")
    # 注意：password 参数（第一个位置参数）必须传入 Key 明文本身。此前误写成仅传
    # key=secret 而漏掉 message，导致对空串做哈希——所有 Key 生成相同 id，
    # 多 Key 场景下按 id 删除会永远命中第一个（见优化路线图 0.7）。
    return hashlib.pbkdf2_hmac(
        "sha256", key.encode("utf-8"), secret, _KEY_ID_PBKDF2_ITERATIONS
    ).hex()[:24]


@router.get("/api/config/keys")
async def get_config_keys():
    """返回 Key 掩码列表（去重后，含来源标记）与数量。

    **不回传 Key 明文**：keys 数组仅含掩码（mask）与稳定标识（id）。
    env 与 config 中重复的 Key 只返回一次（标记 env，env 优先）。

    Returns:
        {
          "ok": true,
          "key_count": int,            # 去重后总数
          "source": "env:N|config:N|mixed:...|none",
          "keys": [{"id": "sha256[:12]", "mask": "sk-xxx...xxxx", "source": "env"|"config"}, ...],
        }
    """
    items = get_api_keys_with_sources()
    domains = get_api_key_domains()
    return {
        "ok": True,
        "key_count": len(items),
        "source": get_api_keys_source(),
        "keys": [
            {
                "id": _key_id(it["key"]),
                "mask": _mask_key(it["key"]),
                "source": it["source"],
                # 每个 Key 绑定的域名；config 来源可持久化，env 来源无法落盘（回退全局域名）
                "domain": domains.get(it["key"], ""),
                "persistable": it["source"] == "config",
            }
            for it in items
        ],
    }


@router.delete("/api/config/keys")
async def remove_config_key(id: str = Form(""), key: str = Form("")):
    """移除单个 Key（仅针对 config 中保存的 Key；env 来源不可在此移除）。

    Args:
        id: Key 的稳定标识（GET /api/config/keys 返回的 id，掩码接口的定位方式）。
        key: Key 明文（向后兼容的旧参数；新前端请用 id，避免明文回传）。

    Returns:
        {"ok": true, "key_count": ..., "source": ..., "removed": 掩码, "still_active": bool}

    Raises:
        400: Key 来自环境变量，无法从界面移除；或 Key 参数缺失。
        404: Key 不存在。
    """
    id = (id or "").strip()
    key = (key or "").strip()
    if not key and not id:
        raise HTTPException(status_code=400, detail="Key 参数缺失")

    items = get_api_keys_with_sources()
    if key:
        # 兼容旧调用：明文直接匹配
        env_has = any(it["source"] == "env" and it["key"] == key for it in items)
        config_has = any(it["source"] == "config" and it["key"] == key for it in items)
        if not env_has and not config_has:
            raise HTTPException(status_code=404, detail="Key 不存在")
    else:
        # 掩码接口：按稳定 id 定位明文 Key
        matched = [it for it in items if _key_id(it["key"]) == id]
        if not matched:
            raise HTTPException(status_code=404, detail="Key 不存在")
        key = matched[0]["key"]
        env_has = matched[0]["source"] == "env"
        config_has = not env_has

    changed, still_active = remove_api_key_single(key)
    if not changed and env_has and not config_has:
        # 该 Key 只来自 env（含与 config 重复但 env 优先去重的情况）
        raise HTTPException(
            status_code=400,
            detail="该 Key 来自环境变量（含 .env），请在启动环境 / .env 中移除",
        )
    # 重建 KeyRing 与限速器，使移除即时生效
    reset_key_ring()
    reset_rate_limiter()
    # 移除后 key_count 可能不变：Key 同时存在于 env 与 config 时，移除的是 config 副本
    masked = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***"
    return {
        "ok": True,
        "key_count": len(get_api_keys()),
        "source": get_api_keys_source(),
        "removed": masked,
        "still_active": still_active,
    }


@router.post("/api/config/keys")
async def save_config_keys(keys_json: str = Form(""), append: bool = Form(False)):
    """设置多 API Key（JSON 数组或逗号/换行分隔文本）。

    ``append=True`` 时：新 Key 追加到 config 现有 Key（api_keys / api_key）之后
    合并去重保存——用于「已有 1 个 Key，再加 1 个自然变多 Key」的交互，
    用户无需重输旧 Key。env 来源的 Key 不落盘，仍与 config Key 并存（get_api_keys 合并）。

    保存后立即重建 KeyRing 与限速器，使新 Key 数与配额即时生效（无需重启）。
    空输入不改动现有配置。

    Args:
        keys_json: JSON 数组字符串（如 '["k1","k2"]'）或普通逗号/换行分隔文本。
        append: True 追加到现有 config Key；False 覆盖（旧行为）。
    """
    import json as _json

    raw = (keys_json or "").strip()
    keys = []
    if raw:
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                keys = [str(k).strip() for k in parsed]
            else:
                keys = [str(parsed).strip()]
        except _json.JSONDecodeError:
            # 非 JSON：按逗号/换行/空白分隔拆分
            keys = [k.strip() for k in re.split(r"[\s,，;；]+", raw)]
    keys = [k for k in keys if k]

    if not keys:
        if append:
            # 追加模式空输入：不改动现有配置（避免误清空）
            return {
                "ok": True,
                "key_count": len(get_api_keys()),
                "source": get_api_keys_source(),
            }
        # 覆盖模式空输入 = 清空 config Key（回退 env / 无 Key）
        set_api_keys([])
        reset_key_ring()
        reset_rate_limiter()
        return {
            "ok": True,
            "key_count": len(get_api_keys()),
            "source": get_api_keys_source(),
        }

    if append:
        # 追加：config 现有 Key（api_keys / 旧 api_key）+ 新 Key → 合并去重
        config = load_config()
        existing = config.get("api_keys", []) or []
        if not existing and config.get("api_key"):
            existing = [config["api_key"]]
        set_api_keys(existing + keys)
    else:
        set_api_keys(keys)
    # Key 数变化 → 重建 KeyRing 与限速器（共享桶 + 视频提交桶）
    reset_key_ring()
    reset_rate_limiter()
    return {
        "ok": True,
        "key_count": len(get_api_keys()),
        "source": get_api_keys_source(),
    }


@router.post("/api/config/keys/domain")
async def save_config_key_domain(id: str = Form(""), domain: str = Form("")):
    """设置单个 Key 绑定的域名（config 来源 Key）。

    通过 GET /api/config/keys 返回的 stable id 定位 Key，避免重复回传明文。
    env 来源的 Key 不可落盘 (400)。domain 为空表示清除绑定（回退全局域名）。

    Args:
        id: Key 的稳定标识（GET /api/config/keys 返回的 id）。
        domain: 期望域名（com/cn/cn_bak），空串清除绑定。

    Raises:
        400: Key 来自环境变量，无法持久化域名。
        404: id 未匹配到任何 Key。
        422: domain 不在 AGNES_DOMAIN_MAP 内。
    """
    id = (id or "").strip()
    domain = (domain or "").strip().lower()
    if domain and domain not in AGNES_DOMAIN_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"域名后缀必须为 {list(AGNES_DOMAIN_MAP.keys())} 之一（或空以清除）",
        )
    items = get_api_keys_with_sources()
    matched = [it for it in items if _key_id(it["key"]) == id]
    if not matched:
        raise HTTPException(status_code=404, detail="Key 不存在")
    entry = matched[0]
    if entry["source"] == "env":
        raise HTTPException(status_code=400, detail="该 Key 来自环境变量，无法为它保存域名")
    set_api_key_domains({entry["key"]: domain})
    return {"ok": True, "mask": _mask_key(entry["key"]), "domain": domain}


# 探测候选域名顺序：官方国际站优先，其次国内站备用，最后严格国内站专属端点
_DETECT_CANDIDATES = ["com", "cn_bak", "cn"]
# 探测 /v1/models 的超时与并发上限
_DETECT_TIMEOUT = 10
_DETECT_CONCURRENCY = 4


def _probe_domain(key: str, domain: str) -> bool:
    """同步探测单个 Key 在某个域名下是否鉴权通过（/v1/models 返回 200）。"""
    import requests

    root = AGNES_DOMAIN_MAP[domain]
    try:
        resp = requests.get(
            f"{root}/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=_DETECT_TIMEOUT,
        )
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 — 连接/超时均视为该域名不可用
        return False


@router.post("/api/config/keys/detect")
async def detect_config_key_domains(force: bool = Form(False)):
    """自动探测每个 config Key 应绑定的域名，并补写 key -> domain 映射。

    逐个 Key 按候选域名顺序（com / cn_bak / cn）探测 GET /v1/models：
    首个返回 200 的域名即判定为该 Key 的有效域名并落盘。探测并行执行，
    并限量并发（网络超时 10s，最多 4 个并发），避免阻塞 & 打爆外部接口。

    ``force=True`` 时对所有 config Key 重新探测并覆盖已有绑定；
    默认仅补写尚未绑定域名的 Key（已绑定的跳过）。

    env 来源的 Key 不参与探测（无法持久化域名）。

    Returns:
        {
          "ok": true,
          "applied": int,      # 本次新增/覆盖的绑定数
          "results": [{"id","mask","domain","ok","skipped"}],  # 每个 config Key 的探测结果
        }
    """
    import asyncio

    items = get_api_keys_with_sources()
    cfg_items = [it for it in items if it["source"] == "config"]
    current = get_api_key_domains()
    results = []
    mapping = {}
    sem = asyncio.Semaphore(_DETECT_CONCURRENCY)

    async def probe(entry: dict) -> None:
        key = entry["key"]
        if not force and current.get(key) in AGNES_DOMAIN_MAP:
            results.append(
                {"id": _key_id(key), "mask": _mask_key(key), "domain": current[key], "ok": True, "skipped": True}
            )
            return
        for d in _DETECT_CANDIDATES:
            ok = await asyncio.to_thread(_probe_domain, key, d)
            if ok:
                mapping[key] = d
                results.append(
                    {"id": _key_id(key), "mask": _mask_key(key), "domain": d, "ok": True, "skipped": False}
                )
                return
        results.append(
            {"id": _key_id(key), "mask": _mask_key(key), "domain": "", "ok": False, "skipped": False}
        )

    async def bounded(entry: dict) -> None:
        async with sem:
            await probe(entry)

    await asyncio.gather(*[bounded(it) for it in cfg_items])
    if mapping:
        set_api_key_domains(mapping)
    return {"ok": True, "applied": len(mapping), "results": results}


@router.get("/api/models")
async def list_models(refresh: bool = False):
    """拉取 Agnes 可用模型列表，按 text/image/video 分组。

    需已配置 API Key。列表来自 GET /v1/models?all=true（含内测模型）。
    失败时回退到硬编码默认列表。

    结果在服务端缓存 TTL 秒；普通页面加载走缓存瞬时返回，
    仅“刷新列表”按钮（?refresh=1）或缓存过期时才重新请求外部接口。
    """
    key = get_api_key()
    if not key:
        raise HTTPException(status_code=400, detail="未配置 API Key")
    now = time.time()
    if (
        not refresh
        and _MODEL_CACHE["models"] is not None
        and (now - _MODEL_CACHE["ts"]) < _MODEL_CACHE["ttl"]
    ):
        return {
            "ok": True,
            "models": _MODEL_CACHE["models"],
            "cached": True,
            "video_capabilities": get_video_model_capabilities(),
        }
    grouped = fetch_available_models(key)
    _MODEL_CACHE["models"] = grouped
    _MODEL_CACHE["ts"] = now
    return {
        "ok": True,
        "models": grouped,
        "cached": False,
        "video_capabilities": get_video_model_capabilities(),
    }


@router.post("/api/config/models")
async def save_models(
    text: str = Form(None),
    image: str = Form(None),
    video: str = Form(None),
):
    """保存选中的模型配置。

    text 为必填（目前仅文本模型开放选择）；image/video 接受但不强制，
    置灰时前端仍会随配置保存其值（缺省回退到当前默认值）。
    """
    if text is None or text.strip() == "":
        raise HTTPException(status_code=400, detail="文本模型不能为空")
    result = set_selected_models(
        text=text or None,
        image=image,
        video=video,
    )
    return {"ok": True, "models": result}


@router.post("/api/config/watermark")
async def save_watermark_config(enabled: bool = Form(False)):
    """Save watermark toggle."""
    set_watermark_config(enabled=enabled)
    return {"ok": True, "enabled": enabled}


@router.post("/api/config/domain")
async def save_agnes_domain(domain: str = Form(...)):
    """设置 Agnes API 域名后缀。

    Args:
        domain: "com" 或 "cn"
    """
    domain = domain.strip().lower()
    if domain not in AGNES_DOMAIN_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"域名后缀必须为 {list(AGNES_DOMAIN_MAP.keys())} 之一",
        )
    set_agnes_domain(domain)
    return {"ok": True, "agnes_domain": domain}
