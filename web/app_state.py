"""应用级全局状态（Batch 1 从 server.py 拆出）。

集中管理并发控制、活动任务注册表、生命周期事件等所有路由模块共享的可变状态，
避免各路由模块在模块级各自持有副本导致状态不一致。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Dict, Set

from core.api.error_collector import set_workspace_root
from core.config import get_settings, get_working_dir
from models.task import TaskType
from web.log_safe import safe_log

logger = logging.getLogger(__name__)


def _settings_rate_limit() -> int:
    """AGNES_RATE_LIMIT（3.5 RuntimeSettings 收敛），未配置时默认 20。"""
    v = get_settings().agnes_rate_limit
    return v if v and v > 0 else 20

# ═══════════════════════════════════════════════════
# 并发控制（复用回归流程的加权信号量逻辑）
# ═══════════════════════════════════════════════════

# Agnes API 每分钟调用上限（与 rate_limiter.py / regression_runner.py 一致）
# 3.5：经 RuntimeSettings 收敛读取，未显式配置时由 rate_limiter 按 Key 数动态计算
_AGNES_RATE_LIMIT = _settings_rate_limit()

# 各任务类型权重 = 该类型预估的每分钟 Agnes API 调用数
# 留 50% 余量 => 总权重上限 = _AGNES_RATE_LIMIT / 2
TASK_TYPE_WEIGHTS = {
    TaskType.SIMPLE: 1,       # 1 submit + 轻量轮询
    TaskType.CREATIVE: 3,     # Chat + N*Image + N*Video + 轮询
    TaskType.MANUSCRIPT: 4,   # 段落*Chat + 段落*Image + 轮询
    TaskType.ANCHOR: 2,       # 1 i2v submit + 轻量轮询
    TaskType.POETRY: 3,       # 1 Chat(拆分) + N*Video + N*合成
    TaskType.IMAGE: 1,        # 1 image submit
}
MAX_CONCURRENT_WEIGHT = _AGNES_RATE_LIMIT // 2  # 默认 10


class WeightedSemaphore:
    """加权信号量：控制并发任务的总权重不超过上限。

    每个任务类型的权重 = 该类型预估的每分钟 Agnes API 调用数。
    控制并发任务数，确保总 API 调用 ≤ AGNES_RATE_LIMIT/分钟。
    逻辑与 regression_runner.py 的 WeightedSemaphore 完全一致。
    """
    def __init__(self, max_weight: int):
        self.max_weight = max_weight
        self.current = 0
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)

    async def acquire(self, weight: int):
        if weight > self.max_weight:
            raise ValueError(f"task weight {weight} > max {self.max_weight}")
        async with self._lock:
            while self.current + weight > self.max_weight:
                await self._cond.wait()
            self.current += weight

    async def release(self, weight: int):
        async with self._lock:
            self.current -= weight
            self._cond.notify_all()

    async def update_max_weight(self, new_max: int):
        """优化路线图 3.5：动态调整并发上限（随 Key 数/配额缩放）。

        - 不低于当前已占用权重（避免已获取的槽位失效）
        - 上调时唤醒排队等待者（新任务可继续获取）
        - 下调不回收已占槽位（等其自然释放）
        """
        if new_max <= 0:
            return
        async with self._lock:
            self.max_weight = max(new_max, self.current)
            self._cond.notify_all()

    @property
    def utilization(self) -> float:
        return self.current / self.max_weight if self.max_weight else 0


# 全局加权信号量（服务端所有任务共享）
_pipeline_semaphore = WeightedSemaphore(MAX_CONCURRENT_WEIGHT)
# 排队中的任务: task_id -> weight
_queued_tasks: Dict[str, int] = {}
# 运行中的 pipeline: task_id -> BasePipeline
active_pipelines: Dict[str, object] = {}
# task_id -> asyncio.Lock, 串行化 create/resume/stop，避免并发操作同一任务导致
# 旧 pipeline 的 finally 误删新 pipeline、或同任务双重运行。
_pipeline_locks: Dict[str, asyncio.Lock] = {}
# 后台任务强引用集合，防止 GC 回收运行中的协程
background_tasks: Set[asyncio.Task] = set()
# 优雅退出事件（Ctrl+C 两次强制退出）
shutdown_event = asyncio.Event()


def get_rate_limit() -> int:
    """Agnes API 每分钟调用上限。"""
    return _AGNES_RATE_LIMIT


def _effective_concurrency_limit() -> int:
    """并发权重上限 = 有效配额 // 2（对齐 rate_limiter._effective_rate()）。

    优化路线图 3.5：此前固定为 ``env 值 // 2``，不随 Key 数缩放——多 Key 部署
    下并发上限过严（8 Key 时配额 128 却仍按 10），而低 ``AGNES_RATE_LIMIT``
    配置（如 6）下稿件(权重 4) 反被硬拒绝。动态化后 0.4 的硬拒绝场景消失。
    """
    try:
        from core.api.rate_limiter import get_rate_limiter
        rate = get_rate_limiter().stats.get("effective_rate_per_min", 0) or 0
        if rate > 0:
            return max(1, int(rate) // 2)
    except Exception:
        pass
    return _AGNES_RATE_LIMIT // 2


def get_semaphore() -> WeightedSemaphore:
    """全局加权信号量（3.5：max_weight 随 Key 数/配额动态缩放）。"""
    target = _effective_concurrency_limit()
    if target > 0 and target != _pipeline_semaphore.max_weight:
        try:
            asyncio.get_running_loop().create_task(
                _pipeline_semaphore.update_max_weight(target)
            )
        except RuntimeError:
            # 无运行中事件循环（如回归脚本同步上下文）：直接跳过动态更新
            pass
    return _pipeline_semaphore


def get_pipeline_lock(task_id: str) -> asyncio.Lock:
    """获取（必要时创建）task_id 级别的并发锁。

    create/resume/stop 端点对 ``active_pipelines`` 的检查与插入之间存在
    ``await`` 让出点，快速重复操作（如 resume→stop）会让旧 pipeline 的
    ``finally`` 误删新 pipeline，甚至产生同任务双重运行。用 per-task 锁将
    这三类操作的「检查+插入/删除」关键段串行化。
    """
    lock = _pipeline_locks.get(task_id)
    if lock is None:
        lock = asyncio.Lock()
        _pipeline_locks[task_id] = lock
    return lock


def release_pipeline_lock(task_id: str) -> None:
    """删除任务后释放 per-task 锁（防字典无限膨胀）。"""
    _pipeline_locks.pop(task_id, None)


def launch_background_task(coro):
    """Launch a background task with a strong reference to prevent GC."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


# ═══════════════════════════════════════════════════
# 启动初始化（由 server.py lifespan 调用）
# ═══════════════════════════════════════════════════

def init_runtime_state() -> None:
    """初始化工作目录、错误收集根路径，并重置上次异常退出遗留的 running/queued 任务。"""
    os.makedirs(get_working_dir(), exist_ok=True)
    upload_dir = os.path.join(get_working_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    working_dir = get_working_dir()
    set_workspace_root(working_dir)  # 错误收集模块使用激活的工作空间
    if os.path.exists(working_dir):
        for name in os.listdir(working_dir):
            task_file = os.path.join(working_dir, name, "task_state.json")
            if os.path.exists(task_file):
                try:
                    with open(task_file, "r") as f:
                        data = json.load(f)
                    if data.get("status") in ("running", "queued"):
                        old_status = data["status"]
                        data["status"] = "pending"
                        # H5: 原子写（临时文件 + os.replace），避免写入中途崩溃损坏 JSON
                        tmp_fd, tmp_path = tempfile.mkstemp(
                            dir=os.path.join(working_dir, name), suffix=".tmp"
                        )
                        try:
                            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                            os.replace(tmp_path, task_file)
                        except Exception:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                            raise
                        logger.info("[Startup] Reset stale %s task %s -> pending",
                                    safe_log(old_status), safe_log(name))
                except Exception as e:
                    logger.debug(f"[Startup] Failed to reset stale task {name}: {e}")
