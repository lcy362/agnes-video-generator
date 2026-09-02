"""异步文件读写辅助（Sonar ``python:S7493``）。

背景
----
在 ``async def`` 中直接使用内置 ``open()`` 会阻塞事件循环（文件 IO 虽短，
但在高并发/大文件场景下会拖慢整个服务）。Sonar 将此类调用判为 BUG。

方案
----
统一走 AnyIO 的 ``open_file``（FastAPI/Starlette 的既有依赖，无需新增包）：
它把文件读写下沉到线程池，对外暴露与内置 ``open()`` 对齐的异步上下文管理器。

用法
----
需要完整文件对象时（如逐块写入）::

    async with await async_open(path, "wb") as f:
        await f.write(chunk)

只是整体读写时用便捷函数更省事::

    content = await read_text(path)
    await write_text(path, json.dumps(data, ensure_ascii=False))
"""
from __future__ import annotations

from anyio import open_file

__all__ = [
    "async_open",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
]

# 语义等价于内置 open()，返回 AnyIO 异步文件对象（需 ``await`` 后再 ``async with``）
async_open = open_file


async def read_text(path: str, encoding: str = "utf-8") -> str:
    """异步读取整个文本文件。"""
    async with await async_open(path, "r", encoding=encoding) as f:
        return await f.read()


async def write_text(path: str, data: str, encoding: str = "utf-8") -> None:
    """异步写入整个文本文件（覆盖写）。"""
    async with await async_open(path, "w", encoding=encoding) as f:
        await f.write(data)


async def read_bytes(path: str) -> bytes:
    """异步读取整个二进制文件。"""
    async with await async_open(path, "rb") as f:
        return await f.read()


async def write_bytes(path: str, data: bytes) -> None:
    """异步写入整个二进制文件（覆盖写）。"""
    async with await async_open(path, "wb") as f:
        await f.write(data)
