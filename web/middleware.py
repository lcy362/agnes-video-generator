"""web.middleware — HTTP 请求级中间件（v7.0）。

目前只承载一个中间件：``LangContextMiddleware``，把前端注入的
``X-Agnes-UI-Lang`` 头（或 ``Accept-Language`` 兜底）写入
``core.i18n_backend.current_lang`` ContextVar，供同请求生命周期内的
``HTTPException(detail=translate(...))`` 与短同步代码读取。

**异步 Pipeline 不走这里**：任务在后台协程里跑，请求上下文早已切走，
Pipeline 通过 ``BaseTaskState.ui_language``（任务创建时落盘）拿到语言。
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from core.i18n_backend import (
    UI_LANG_HEADER,
    current_lang,
    normalize_lang,
    parse_accept_language,
)

logger = logging.getLogger(__name__)

__all__ = ["LangContextMiddleware", "extract_request_lang"]


def extract_request_lang(request: Request) -> str:
    """按优先级从请求里提取 UI 语言：自定义头 > ``Accept-Language`` > ``zh``。

    Args:
        request: Starlette/FastAPI 请求对象。

    Returns:
        归一化后的 2 字母语言代码，永远落在 ``SUPPORTED_UI_LANGS`` 内。
    """
    header_lang = request.headers.get(UI_LANG_HEADER)
    if header_lang:
        return normalize_lang(header_lang)
    return parse_accept_language(request.headers.get("accept-language"))


class LangContextMiddleware(BaseHTTPMiddleware):
    """把请求级 UI 语言写入 ContextVar，供同请求内的 ``translate()`` 读取。

    实现要点：
    - 使用 ``BaseHTTPMiddleware`` 而非纯 ASGI 中间件：本仓库已经在
      ``server.py`` 里以 ``add_middleware`` 形式挂 CORS，风格一致，
      且我们只需要在 dispatch 前后各做一次 ContextVar 读写；
    - ``finally`` 里 ``current_lang.reset(token)``：避免同一个协程池复用
      时残留上一个请求的语言（ContextVar 在 asyncio Task 边界自动隔离，
      但 Starlette 的 BaseHTTPMiddleware 会为每个请求起独立 Task，
      保险起见仍显式 reset）；
    - 不抛异常：语言解析失败一律回退默认 ``zh``，绝不让 i18n 缺陷把
      正常业务请求打断。
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: D401
        lang = extract_request_lang(request)
        token = current_lang.set(lang)
        try:
            return await call_next(request)
        finally:
            current_lang.reset(token)
