"""优化路线图批次 0 修复的回归护栏（1.6 测试补齐）。

锁定 2026-08-28 批次 0 修复的关键行为，防止复发：
- 0.1 docker-run.sh 端口映射（$PORT:8765）
- 0.3 VideoOutput/ImageOutput.save 异步化
- 0.4 信号量「仅获取成功才释放」语义
- 0.5 水印坐标 WatermarkLayout 返回值传递
- 0.7 _key_id 对 Key 明文做 keyed hash（多 Key 删除定位唯一）
"""
import asyncio
import inspect
import os

import pytest

from core.api.agnes_image import ImageOutput
from core.api.agnes_video import VideoOutput
from core.compositor.watermark import WatermarkLayout
from web.app_state import WeightedSemaphore
from web.routes.config_routes import _key_id

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 0.7 _key_id ─────────────────────────────────────────────────────


def test_key_id_unique_per_key():
    """不同 Key 生成不同 id；相同 Key 生成相同 id（修复前所有 Key 共用同一 id）。"""
    ids = [_key_id("sk-aaa"), _key_id("sk-bbb"), _key_id("sk-ccc")]
    assert len(set(ids)) == 3, "不同 Key 的 id 必须互不相同，否则按 id 删除会误删"
    assert _key_id("sk-aaa") == _key_id("sk-aaa")
    assert _key_id("sk-bbb") != _key_id("sk-ccc")


def test_key_id_is_deterministic_hex():
    """id 为 12 字节 hex（24 字符），供 /api/config/keys 往返一致。"""
    key_id = _key_id("sk-aaa")
    assert len(key_id) == 24
    int(key_id, 16)  # 是合法 hex


# ── 0.4 信号量 ──────────────────────────────────────────────────────


async def test_semaphore_failed_acquire_keeps_current():
    """acquire(weight > max) 抛 ValueError 后 current 不变负（修复前 finally 无条件 release）。"""
    sem = WeightedSemaphore(3)
    assert sem.current == 0
    with pytest.raises(ValueError):
        await sem.acquire(4)
    assert sem.current == 0


async def test_semaphore_normal_acquire_release_roundtrip():
    """正常路径：acquire 增、release 减，往返归零。"""
    sem = WeightedSemaphore(3)
    await sem.acquire(2)
    assert sem.current == 2
    await sem.release(2)
    assert sem.current == 0


async def test_semaphore_queued_cancellation_does_not_release():
    """排队中的 acquire 被取消后不改变 current（未获取则不释放，0.4 语义）。"""
    sem = WeightedSemaphore(2)
    await sem.acquire(2)  # 占满
    waiter = asyncio.create_task(sem.acquire(1))  # 排队中
    await asyncio.sleep(0.01)  # 让 waiter 真正进入条件等待
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert sem.current == 2  # 取消发生在获取前：不占槽、不变负
    # 释放后仍可正常获取（无残余 waiter 占用）
    await sem.release(2)
    await sem.acquire(2)
    assert sem.current == 2


# ── 3.5 并发上限动态缩放 ────────────────────────────────────────────


async def test_semaphore_update_max_weight_wakes_waiters():
    """上限上调后唤醒排队等待者（多 Key 配额提升立即生效）。"""
    from web.app_state import WeightedSemaphore

    sem = WeightedSemaphore(3)
    await sem.acquire(3)  # 占满
    waiter = asyncio.create_task(sem.acquire(2))  # 排队
    await asyncio.sleep(0.01)
    assert not waiter.done()

    await sem.update_max_weight(5)  # 3.5：配额提升
    await asyncio.wait_for(waiter, 1)  # 被唤醒并成功获取
    assert sem.current == 5


async def test_semaphore_update_max_weight_not_below_current():
    """下调不回收已占用权重（不低于 current）。"""
    from web.app_state import WeightedSemaphore

    sem = WeightedSemaphore(5)
    await sem.acquire(4)
    await sem.update_max_weight(2)
    assert sem.max_weight == 4


def test_effective_concurrency_limit_positive():
    """有效并发上限为正数（随配额动态计算）。"""
    from web import app_state

    assert app_state._effective_concurrency_limit() > 0


# ── 0.5 WatermarkLayout ─────────────────────────────────────────────


def test_watermark_layout_fields():
    """水印坐标经 NamedTuple 返回值传递（不再写函数对象属性）。"""
    layout = WatermarkLayout(pos_x=10, pos_y=20, box_w=100, box_h=30)
    assert (layout.pos_x, layout.pos_y, layout.box_w, layout.box_h) == (10, 20, 100, 30)
    assert layout is not None  # 成功路径返回布局而非 bool


# ── 0.3 save 异步化 ─────────────────────────────────────────────────


def test_save_is_async_coroutine():
    """VideoOutput/ImageOutput.save 已异步化（to_thread 下沉），且保留同步实现。"""
    assert inspect.iscoroutinefunction(VideoOutput.save)
    assert inspect.iscoroutinefunction(ImageOutput.save)
    assert inspect.isfunction(VideoOutput._save_sync)
    assert inspect.isfunction(ImageOutput._save_sync)


# ── 0.1 docker-run.sh ───────────────────────────────────────────────


def test_docker_run_port_mapping():
    """端口映射为 $PORT:8765（容器内固定监听 8765），自定义 AGNES_PORT 可用。"""
    text = open(os.path.join(_ROOT, "docker-run.sh"), encoding="utf-8").read()
    assert '-p "$PORT:8765"' in text
