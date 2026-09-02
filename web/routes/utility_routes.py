"""杂项路由：首页、回归测试清理。"""
from __future__ import annotations

import json
import logging
import os
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.async_io import read_text
from core.config import get_working_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["utility"])


@router.get("/")
async def root():
    index_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "index.html")
    index_path = os.path.abspath(index_path)
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Agnes Video Generator API"}


@router.post("/api/cleanup-regression")
async def cleanup_regression():
    """安全清理回归测试产物（报告、日志、任务目录）。

    只删除产物清单中记录的内容，不影响用户原有任务数据。
    """
    working_dir = get_working_dir()
    manifest_path = os.path.join(working_dir, ".regression_manifest.json")

    if not os.path.exists(manifest_path):
        raise HTTPException(
            status_code=404,
            detail="未找到回归测试产物清单，可能没有执行过回归测试")

    try:
        manifest = json.loads(await read_text(manifest_path))
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"读取清单失败: {e}")

    removed_dirs = 0
    removed_files = 0
    errors: list = []
    project_root = os.path.dirname(os.path.abspath(__file__)) + os.sep + ".." + os.sep + ".."
    project_root = os.path.abspath(project_root)
    upload_dir = os.path.join(working_dir, "uploads")

    # 1. 清理任务目录
    for dir_name in manifest.get("task_dirs", []):
        dir_path = os.path.join(working_dir, dir_name)
        if os.path.isdir(dir_path):
            try:
                shutil.rmtree(dir_path)
                removed_dirs += 1
            except OSError as e:
                logger.warning(f"[Cleanup] 删除目录失败 {dir_name}: {e}")
                errors.append(f"删除目录失败: {dir_name}")

    # 2. 清理上传文件
    for fname in manifest.get("uploads", []):
        fpath = os.path.join(upload_dir, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                removed_files += 1
            except OSError as e:
                logger.warning(f"[Cleanup] 删除上传文件失败 {fname}: {e}")
                errors.append(f"删除上传文件失败: {fname}")

    # 3. 清理报告文件
    for rel_path in manifest.get("reports", []):
        abs_path = os.path.join(project_root, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                removed_files += 1
            except OSError as e:
                logger.warning(f"[Cleanup] 删除报告失败 {rel_path}: {e}")
                errors.append(f"删除报告失败: {rel_path}")

    # 4. 清理服务器日志
    log_rel = manifest.get("server_log", "")
    if log_rel:
        log_path = os.path.join(project_root, log_rel)
        if os.path.isfile(log_path):
            try:
                os.remove(log_path)
                removed_files += 1
            except OSError as e:
                logger.warning(f"[Cleanup] 删除日志失败: {e}")
                errors.append("删除日志失败")

    # 5. 清理清单本身
    try:
        os.remove(manifest_path)
        removed_files += 1
    except OSError as e:
        logger.warning(f"[Cleanup] 删除清单失败: {e}")
        errors.append("删除清单失败")

    scenarios_cleaned = len(manifest.get("scenarios", {}))
    logger.info(
        f"[Cleanup] 回归清理完成: {removed_dirs} 目录, "
        f"{removed_files} 文件, {scenarios_cleaned} 场景")

    return {
        "ok": len(errors) == 0,
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "scenarios_cleaned": scenarios_cleaned,
        "errors": errors,
    }
