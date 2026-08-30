"""工作目录管理路由（多工作目录，同时仅一个 active）。"""
from __future__ import annotations

import os

from fastapi import APIRouter, Form, HTTPException

from core.config import (
    add_workspace,
    get_active_workspace,
    get_workspaces,
    remove_workspace,
    set_active_workspace,
)
from core.path_security import UnsafePathError, safe_workspace_path
from web import helpers

router = APIRouter(tags=["workspaces"])


@router.get("/api/workspaces")
async def list_workspaces():
    """列出所有已配置的工作目录及当前激活项。"""
    return {
        "workspaces": get_workspaces(),
        "active_workspace": get_active_workspace(),
    }


@router.post("/api/workspaces")
async def create_workspace(path: str = Form(...), name: str = Form("")):
    """添加一个工作目录。"""
    if not path.strip():
        raise HTTPException(status_code=422, detail="path 不能为空")
    try:
        safe_path = safe_workspace_path(path.strip())
    except UnsafePathError:
        raise HTTPException(
            status_code=422,
            detail="工作目录路径不合法或超出允许范围（可由 AGNES_WORKSPACE_ROOT 环境变量放宽）",
        )
    entry = add_workspace(safe_path, name.strip())
    # safe_path 已是 safe_workspace_path 净化后的受信任值（受信任根 containment 检查），
    # 直接用于落盘即可中和路径穿越。
    os.makedirs(safe_path, exist_ok=True)
    os.makedirs(os.path.join(safe_path, "uploads"), exist_ok=True)
    return {"ok": True, "workspace": entry, "active_workspace": get_active_workspace()}


@router.delete("/api/workspaces")
async def delete_workspace(path: str = Form(...)):
    """移除一个工作目录（仅从配置中移除，不删除磁盘文件）。"""
    if not path.strip():
        raise HTTPException(status_code=422, detail="path 不能为空")
    removed = remove_workspace(path.strip())
    if not removed:
        raise HTTPException(status_code=404, detail="工作目录不存在")
    return {"ok": True, "active_workspace": get_active_workspace()}


@router.post("/api/workspaces/active")
async def activate_workspace(path: str = Form(...)):
    """设置当前激活的工作目录。"""
    if not path.strip():
        raise HTTPException(status_code=422, detail="path 不能为空")
    try:
        safe_path = safe_workspace_path(path.strip())
        active = set_active_workspace(safe_path)
    except UnsafePathError:
        raise HTTPException(
            status_code=422,
            detail="工作目录路径不合法或超出允许范围（可由 AGNES_WORKSPACE_ROOT 环境变量放宽）",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # safe_path 已是 safe_workspace_path 净化后的受信任值，直接用于落盘。
    os.makedirs(safe_path, exist_ok=True)
    os.makedirs(os.path.join(safe_path, "uploads"), exist_ok=True)
    return {"ok": True, "active_workspace": active}


@router.get("/api/workspaces/pick-directory")
async def pick_directory():
    """弹出操作系统原生目录选择框，返回所选目录路径。"""
    return await helpers.pick_directory()
