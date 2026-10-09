"""core.api.key_manager — 多 API Key 统一轮换（KeyRing 单例）

职责：
1. 基于 get_api_keys() 惰性初始化；Key 变更后 reset_key_ring() 重建
2. next(): 普通请求轮转（round-robin，原子计数，均匀分摊配额）
3. rotate(): 429 时强制切到下一个 Key（供换 Key 重试）
4. has_multiple() / __len__: 供限速器配额与重试策略判断
5. mark_auth_failed() / auth_failures(): 401 认证失败的**归因登记**（只记录）

关于 401 归因登记（v7.1）：
    上游 401（Invalid token）的**判定与归因收口在本模块**，流水线只负责上报事实。
    登记表是纯粹的观测数据：``next()`` / ``rotate()`` / ``_keys`` 一律不读它，
    因此**不剔除 Key、不降权、不改变轮转顺序**——Key 池的唯一写入口仍是
    ``set_api_keys`` / ``delete_api_key``（用户在前端配置页自行决定删除）。
    记录随 ``reset_key_ring()``（保存/删除 Key 后）与进程重启清零，与
    ``core/api/error_collector.py`` 的内存聚合语义一致。

用法::

    from core.api.key_manager import get_key_ring, reset_key_ring

    key = get_key_ring().next()
    get_key_ring().rotate()   # 429 换 Key
"""
import itertools
import logging
import threading
import time
from typing import Optional

from core.config import get_api_keys

logger = logging.getLogger(__name__)


class KeyRing:
    def __init__(self, keys: list):
        if not keys:
            raise ValueError("KeyRing requires at least one key")
        self._keys = list(keys)
        self._count = itertools.count()
        self._lock = threading.Lock()
        # rotate() 钉住的下一个 Key 索引：rotate 后紧接的 next() 必须返回该 Key
        # （此前 rotate 与 next 共享递增计数，rotate 消费一个序号后 next 取模
        #  又回到原 Key，导致 429 换 Key 重试实际仍用旧 Key）
        self._force_next: Optional[int] = None
        # 401 归因登记：{Key 明文: {"count", "status", "domain", "first_at", "last_at", "message"}}
        # 仅供观测/前端展示，不参与任何选 Key 决策
        self._auth_failures: dict = {}

    def next(self) -> str:
        """轮转取下一个 Key（普通请求调用，均匀分摊）。"""
        with self._lock:
            if self._force_next is not None:
                idx = self._force_next
                self._force_next = None
                return self._keys[idx]
            return self._keys[next(self._count) % len(self._keys)]

    def rotate(self) -> str:
        """强制切换到下一个 Key（429 换 Key 重试调用）。

        递增计数返回下一个 Key，并记录为 ``_force_next``，确保紧随其后的
        ``next()``（即重试请求的 ``_auth_headers()``）真的使用新 Key，
        之后恢复正常 round-robin。
        """
        with self._lock:
            idx = next(self._count) % len(self._keys)
            self._force_next = idx
            return self._keys[idx]

    @property
    def keys(self) -> list:
        return list(self._keys)

    def has_multiple(self) -> bool:
        return len(self._keys) > 1

    def __len__(self) -> int:
        return len(self._keys)

    def describe(self) -> str:
        """日志用：key#2/3 等。"""
        return f"key#{next(self._count) % len(self._keys) + 1}/{len(self._keys)}"

    # ── 401 归因登记（v7.1）：只记录事实，不影响选 Key ──────────────

    def mark_auth_failed(self, key: str, *, status: int = 401,
                         domain: str = "", message: str = "") -> dict:
        """登记一次上游认证失败（401）。**不改变 Key 池与轮转。**

        Args:
            key: 触发失败的 Key（调用方从 ``next()`` / ``rotate()`` 取得）。
            status: 上游 HTTP 状态码（当前仅 401）。
            domain: 该次请求实际使用的域名后缀（''=全局域名），用于归因
                「Key 与域名不匹配」。
            message: 上游返回的可读描述（来自 ``_upstream_error``）。

        Returns:
            该 Key 的累计登记记录（含 count / first_at / last_at）。
        """
        now = time.time()
        with self._lock:
            rec = self._auth_failures.get(key)
            if rec is None:
                rec = {
                    "count": 0, "status": status, "domain": domain,
                    "first_at": now, "last_at": now, "message": message,
                }
                self._auth_failures[key] = rec
            rec["count"] += 1
            rec["status"] = status
            rec["domain"] = domain or rec.get("domain", "")
            rec["last_at"] = now
            if message:
                rec["message"] = message
            snapshot = dict(rec)
            # 日志标签按位置只读计算：不能用 describe()——它会推进轮转计数，
            # 那样 401 上报就间接改变了后续选 Key，违背「执行中不调整」
            label = (
                f"key#{self._keys.index(key) + 1}/{len(self._keys)}"
                if key in self._keys else "key#(不在池内)"
            )
        # 只打日志，不触发任何池调整；用户据配置页提示自行决定是否删除该 Key
        logger.warning(
            f"[KeyAuth] {label} 认证失败 (HTTP {status}"
            f"{f' · {domain}' if domain else ''}): {message or 'invalid token'} "
            f"— 已登记第 {snapshot['count']} 次，请在配置页确认是否移除该 Key"
        )
        return snapshot

    def auth_failures(self) -> dict:
        """返回全部 401 归因登记（Key 明文 → 记录副本）。

        调用方（配置路由）负责按 ``_key_id`` 映射到掩码列表；本方法不泄露
        Key 明文给前端。
        """
        with self._lock:
            return {k: dict(v) for k, v in self._auth_failures.items()}

    def clear_auth_failures(self, key: Optional[str] = None) -> None:
        """清空归因登记（``key=None`` 时清全部）。供 Key 变更/单测复位调用。"""
        with self._lock:
            if key is None:
                self._auth_failures.clear()
            else:
                self._auth_failures.pop(key, None)


_instance: KeyRing | None = None
_lock = threading.Lock()


def get_key_ring() -> KeyRing:
    """获取全局 KeyRing（线程安全单例，惰性初始化）。"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                keys = get_api_keys()
                if not keys:
                    raise RuntimeError(
                        "No Agnes API Key configured (AGNES_API_KEY or config api_key)"
                    )
                _instance = KeyRing(keys)
                logger.info(f"[KeyManager] KeyRing 初始化: {len(keys)} 个 Key")
    return _instance


def reset_key_ring() -> None:
    """Key 变更后重建 KeyRing（配合 set_api_keys / delete_api_key）。"""
    global _instance
    with _lock:
        _instance = None


def _reset_and_reload() -> KeyRing:
    """重建 KeyRing 并返回新实例（供 set_api_keys 后调用）。"""
    reset_key_ring()
    return get_key_ring()
