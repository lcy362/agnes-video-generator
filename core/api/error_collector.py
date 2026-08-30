"""core.api.error_collector — 模型接口报错收集模块

    收集 Agnes 文本/图片/视频模型 API 调用失败时的报错信息，
    包含 prompt、错误类型、错误详情等，存储在工作目录下的 error_logs/ 中。

    使用方式：
        from core.api.error_collector import collect_error, collect_error_from_exception

        # 方式一：手动构造
        collect_error(model_type="image", api_method="generate_single_image",
                      prompt="一只猫", error_type="ConnectionError",
                      error_message="Connection timed out", retry_count=3)

        # 方式二：从异常对象收集（自动提取 HTTPError 响应体中的 API 错误详情）
        collect_error_from_exception("chat", "chat", exc, prompt="你好")
"""

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests as _requests_lib

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT: Optional[Path] = None

# v6.1 二期：当前任务 ID 上下文（BasePipeline 执行入口 set，record 时落盘 task_id）。
# 用 contextvar 而非逐层传参，将改动面收敛到 API 模块内部（PRD FR9）。
_TASK_ID_CTX: ContextVar[str] = ContextVar("error_collector_task_id", default="")


def set_workspace_root(path: str) -> None:
    """设置错误日志存储的根目录（通常为激活的工作空间路径）。

    应在服务启动时调用一次。如果不设置，则回退到 server.py 所在目录。
    """
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path).resolve()
    logger.info(f"[ErrorCollector] Workspace root set to {_WORKSPACE_ROOT}")


def _get_workspace_root() -> Path:
    """获取存储根目录。

    优先级：
    1. set_workspace_root() 显式设置
    2. 自动检测 server.py 所在目录
    """
    global _WORKSPACE_ROOT
    if _WORKSPACE_ROOT is not None:
        return _WORKSPACE_ROOT
    current = Path(os.getcwd()).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "server.py").exists():
            _WORKSPACE_ROOT = parent
            break
    if _WORKSPACE_ROOT is None:
        _WORKSPACE_ROOT = current
    return _WORKSPACE_ROOT


def _get_log_dir() -> Path:
    """获取 error_logs 目录路径，不存在则创建。"""
    log_dir = _get_workspace_root() / "error_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# 优化路线图 1.5b：error_logs 按数量轮转，超过上限后删除最旧文件，
# 防止长期运行的工作区无限膨胀（诊断端点 _iter_error_logs 全量读取也受影响）。
_MAX_ERROR_LOGS = 500


def _rotate_error_logs(log_dir: Path) -> None:
    """超过 _MAX_ERROR_LOGS 个文件时，按 mtime 删除最旧的超量文件。"""
    try:
        files = [p for p in log_dir.glob("*.json") if p.is_file()]
        if len(files) <= _MAX_ERROR_LOGS:
            return
        files.sort(key=lambda p: p.stat().st_mtime)  # 最旧在前
        for p in files[: len(files) - _MAX_ERROR_LOGS]:
            p.unlink(missing_ok=True)
            logger.info(f"[ErrorCollector] Rotated old error log → {p.name}")
    except OSError:
        pass


def set_error_task_id(task_id: str) -> None:
    """设置当前上下文的 task_id（v6.1 二期，诊断关联用）。

    由流水线执行入口（``web/deps.run_pipeline``）调用，使后续 ``collect_error``
    落盘时带上 task_id。通过 contextvar 传递，避免逐层向 API 模块传参。
    """
    _TASK_ID_CTX.set(task_id or "")


def _extract_from_http_error(exc: Exception) -> tuple[Optional[int], str, str]:
    """从 HTTPError 异常中提取状态码、响应体、以及 API 级错误详情。

    返回 (status_code, response_body, enhanced_message)。
    如果 exc 不是 HTTPError 或提取失败，返回 (None, "", str(exc))。
    """
    try:
        if isinstance(exc, _requests_lib.exceptions.HTTPError):
            resp = getattr(exc, "response", None)
            if resp is not None:
                sc = resp.status_code
                body = resp.text or ""
                enhanced = str(exc)

                # 尝试从 JSON 响应体中提取 API 级错误详情
                if body.strip():
                    try:
                        data = json.loads(body)
                        err = data.get("error", {})
                        api_msg = err.get("message", "") if isinstance(err, dict) else str(err)
                        api_type = err.get("type", "") if isinstance(err, dict) else ""
                        if api_msg:
                            # 优先使用 API 级错误消息，避免重复拼接 type
                            if api_type and api_msg.startswith(api_type):
                                # message 已含 type 前缀，不再重复
                                enhanced = f"{api_msg} (HTTP {sc})"
                            elif api_type:
                                enhanced = f"{api_type}: {api_msg} (HTTP {sc})"
                            else:
                                enhanced = f"{api_msg} (HTTP {sc})"
                        else:
                            enhanced = enhanced + " | body=" + body[:500]
                    except (json.JSONDecodeError, ValueError):
                        enhanced = enhanced + " | body=" + body[:500]

                return sc, body, enhanced
    except Exception:
        pass
    return None, "", str(exc)


def collect_error(
    model_type: str,
    api_method: str,
    prompt: str = "",
    system_prompt: str = "",
    error_type: str = "",
    error_message: str = "",
    status_code: Optional[int] = None,
    response_body: str = "",
    retry_count: int = 0,
    extra: Optional[dict] = None,
) -> Optional[str]:
    """收集一次 API 调用错误并写入 error_logs/ 目录。

    返回保存的文件路径，如果收集过程自身出错则返回 None（不影响主流程）。

    Args:
        model_type: 模型类型，如 "chat", "image", "video"。
        api_method: 调用的方法名，如 "chat", "generate_single_image", "submit_video"。
        prompt: 发送给模型的 prompt（超长自动截断至 5000 字符）。
        system_prompt: system 提示词（仅 chat 类，截断至 2000 字符）。
        error_type: 错误类型名称，如 "ConnectionError", "HTTPError", "RuntimeError"。
        error_message: 错误消息原文。
        status_code: HTTP 状态码（如有）。
        response_body: 响应体原文（截断至 5000 字符）。
        retry_count: 失败前已尝试的重试次数。
        extra: 额外结构化信息（如 video_id, mode 等）。
    """
    try:
        log_dir = _get_log_dir()
        now = datetime.now()
        filename = (
            now.strftime("%Y-%m-%d_%H-%M-%S-%f")
            + f"_{model_type}_{api_method}.json"
        )
        filepath = log_dir / filename

        # 限制字段长度，避免日志文件过大
        error_data = {
            "timestamp": now.isoformat(),
            # v6.1 二期：任务关联（诊断端点精确匹配用；无则留空串）
            "task_id": _TASK_ID_CTX.get(),
            "model_type": model_type,
            "api_method": api_method,
            "prompt": prompt[:5000] if prompt else "",
            "system_prompt": system_prompt[:2000] if system_prompt else "",
            "error_type": error_type,
            "error_message": error_message[:3000] if error_message else "",
            "status_code": status_code,
            "response_body": response_body[:5000] if response_body else "",
            "retry_count": retry_count,
        }
        if extra:
            error_data["extra"] = extra

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)

        # 优化路线图 1.5b：按数量轮转，防止 error_logs 无限膨胀
        _rotate_error_logs(log_dir)

        logger.info(f"[ErrorCollector] Error saved → {filepath}")
        return str(filepath)

    except Exception as e:
        logger.error(f"[ErrorCollector] Failed to collect error: {e}")
        return None


def collect_error_from_exception(
    model_type: str,
    api_method: str,
    exc: Exception,
    prompt: str = "",
    system_prompt: str = "",
    status_code: Optional[int] = None,
    response_body: str = "",
    retry_count: int = 0,
    extra: Optional[dict] = None,
) -> Optional[str]:
    """便捷包装：从异常对象自动提取 error_type 和 error_message。

    对于 requests.HTTPError，会自动从 exc.response 中提取状态码和响应体，
    并尝试解析 JSON 获取 API 级错误详情（如 content_policy_violation）。
    如果调用方已传入 status_code / response_body，则优先使用传入值。
    """
    error_type = type(exc).__name__
    error_msg = str(exc)

    # 自动提取 HTTPError 的响应信息（仅在未显式传入时填充）
    extracted_sc, extracted_body, extracted_msg = _extract_from_http_error(exc)
    if status_code is None:
        status_code = extracted_sc
    if not response_body:
        response_body = extracted_body
    # 如果有 API 级错误详情，优先使用
    if extracted_msg != str(exc):
        error_msg = extracted_msg

    return collect_error(
        model_type=model_type,
        api_method=api_method,
        prompt=prompt,
        system_prompt=system_prompt,
        error_type=error_type,
        error_message=error_msg,
        status_code=status_code,
        response_body=response_body,
        retry_count=retry_count,
        extra=extra,
    )
