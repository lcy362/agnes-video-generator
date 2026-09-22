"""风格/提示词预设库路由（P0-1）。

只暴露三类操作：
- GET    /api/presets         — 系统预设（只读）+ 用户预设（可管理）
- POST   /api/presets          — 保存一条用户自定义预设
- DELETE /api/presets/{id}     — 删除用户自定义预设（系统预设只读，拒绝删除）

纯数据接口，不触发生成链路；数据源见 ``core/presets``。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException

from core.presets import (
    create_user_preset,
    delete_user_preset,
    get_system_preset_ids,
    load_system_presets,
    load_user_presets,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["presets"])


@router.get("/api/presets")
async def list_presets():
    """返回系统预设 + 用户预设。

    Returns:
        ``{"system": [{id, category, prompt}],
            "user": [{id, name, category, prompt, created_at}]}``
    """
    return {
        "ok": True,
        "system": load_system_presets(),
        "user": load_user_presets(),
    }


@router.post("/api/presets")
async def save_preset(name: str = Form(...), prompt: str = Form(...)):
    """保存一条用户自定义预设。

    Args:
        name: 用户自填名称。
        prompt: 预设 prompt 本体。
    """
    if not prompt.strip():
        raise HTTPException(status_code=422, detail="prompt 不能为空")
    preset = create_user_preset(name, prompt)
    return {"ok": True, **preset}


@router.delete("/api/presets/{preset_id}")
async def delete_preset(preset_id: str):
    """删除用户自定义预设（系统预设只读，拒绝删除）。"""
    if preset_id in get_system_preset_ids():
        raise HTTPException(status_code=400, detail="系统预设为只读，不可删除")
    if not delete_user_preset(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
    return {"ok": True, "preset_id": preset_id}