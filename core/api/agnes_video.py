"""core.api.agnes_video — Agnes Video API 封装（从 core/video_generator.py 迁移）"""

import asyncio
import base64
import json
import logging
import mimetypes
import os
import subprocess
import time
from typing import List, Optional

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.key_manager import get_key_ring, key_fingerprint
from core.api.rate_limiter import get_rate_limiter, get_video_submit_limiter
from core.api.retry_policy import (
    QUEUE_FULL_CODES,
    BusyTracker,
    busy_delay,
    fault_delay,
    is_busy_signal,
)
from core.config import (
    get_api_key_domains,
    get_api_root_for_key,
    get_base_url_for_key,
    get_max_ref_images,
    is_v25_video_model,
    normalize_video_size,
    width_height_to_aspect_ratio,
)
from utils.image_normalizer import normalize_reference_path
from utils.video import download_video

logger = logging.getLogger(__name__)

#: v8.1：keyframe 方形输出告警只打一次的进程内标记（见 ``_apply_v25_mode``）
_KEYFRAME_SQUARE_WARNED = False

_UPLOAD_RETRY_BASE_DELAY_SECONDS = 30  # 上传退避基数：忙轨取固定值，故障轨取 base×(n+1)
_UPLOAD_RETRY_MAX_ATTEMPTS = 10        # v7.2 上传忙轨次数封顶（等效旧的 300s 预算 ÷ 30s）


def _adaptive_poll_interval(interval: int, poll_count: int) -> int:
    """优化路线图 1.3：自适应轮询间隔。

    此前固定 ``interval``（默认 60s），每个视频平均多等 ~30s 检测延迟。
    现改为 20s 起步，每 5 次轮询 +5s，上限为调用方 ``interval``；
    调用方传小间隔（<20，如测试）时保持原样。
    """
    if interval < 20:
        return interval
    return min(interval, 20 + (poll_count // 5) * 5)


# ── v7.0/v7.1 上游可靠性加固（docs/plans/v7.0/upstream_error_handling_plan.md）──
#
# 所有上游调用的重试已收敛到「忙轨 / 故障轨」两轨模型（core/api/retry_policy.py）：
# - 忙轨（429 / 所有 503 / 队列类 code）：首跳 0s 贴着限流（交给令牌桶），
#   之后固定间隔 + 次数封顶；
# - 故障轨（非忙 5xx / 超时 / 连接错误）：base×(attempt+1) 逐级 + 次数上限。
#
# 队列类瞬时错误（U1）走忙轨的意义：实测 video_queue_full 可持续 12 分钟以上
# （连续 25 次被拒），而故障轨退避（5 次 × 30s 递增）约 5.5 分钟就会放弃。

# 视频提交忙轨间隔（秒）：第 1 次重试 0s（贴限流），之后为固定基数 + 随机抖动
# （模块级常量，便于测试缩小）
_QUEUE_RETRY_BASE_DELAY = 30.0
_QUEUE_RETRY_JITTER = 30.0
# 视频提交忙轨次数封顶（v7.2）：单 Key 下 15 次 × 60s(配额下限) ≈ 旧的 900s 窗口，
# 多 Key 下每次重试更快，跑完同样次数的总耗时随 Key 数缩短。
_QUEUE_RETRY_MAX_ATTEMPTS = 15


def _upstream_error(body) -> tuple:
    """U2：从上游响应体统一提取 ``(code, message)``。

    兼容两种输入：已解析的 dict（轮询结果）或 ``requests.Response``（提交响应）。

    - 提交侧 5xx：body 形如 ``{"code": "video_queue_full", "message": "..."}``
    - 轮询侧 ``status=failed``：``error`` 字段是对象 ``{"code", "message"}``

    提取失败返回 ``("", "")``，由调用方回退到通用文案。
    """
    data = body
    if body is not None and hasattr(body, "json"):
        try:
            data = body.json()
        except Exception:
            return "", (getattr(body, "text", "") or "").strip()[:200]
    if isinstance(data, dict):
        code = str(data.get("code") or "")
        message = str(data.get("message") or "")
        err = data.get("error")
        if isinstance(err, dict):
            code = code or str(err.get("code") or "")
            if not message:
                message = str(err.get("message") or "")
        return code, message
    if data is None:
        return "", ""
    return "", str(data)[:200]


def _register_auth_failure(ring, key: str, resp) -> None:
    """把一次 401（Invalid token）上报给 KeyRing 做归因登记（v7.1）。

    判定与归因收口在 ``core/api/key_manager.py``；此处只上报事实，**不换 Key、
    不重试、不改池**——该 Key 是否删除由用户在配置页自行决定。域名后缀取自
    Key 的绑定配置（''=未绑定，走全局域名），用于归因「Key 与域名不匹配」。
    """
    _, message = _upstream_error(resp)
    ring.mark_auth_failed(
        key,
        status=resp.status_code,
        domain=get_api_key_domains().get(key, ""),
        message=message,
    )


# ── v7.9：任务查询端点双轨 ────────────────────────────────────────────
#
# 实测（2026-11-07，任务 8363228b8a2d / task_i0340b4VzAELyzMf1dRPApPjaWZIrnLT）：
# 国内站 ``api.agnes-ai.cn`` 的 `GET /agnesapi?video_id=xxx` 对**任何**任务都
# 返回 404「任务不存在」，而同一把 Key 打 `GET /v1/videos/{id}` 返回 200
# （status=completed、progress=100、``metadata.url`` 即成品地址）；国际站
# ``apihub.agnes-ai.com`` 两个端点都认（老端点 404 才是真的查不到）。
# 此前只查老端点 → 国内站提交的任务从第一轮就 404，被 U9 当成「网关入库延迟」
# 白等到 AGNES_VIDEO_POLL_TIMEOUT（1800s）后超时，成品其实早就生成好了。
POLL_STYLE_LEGACY = "agnesapi"   # GET {root}/agnesapi?video_id=xxx（老网关端点）
POLL_STYLE_REST = "v1"           # GET {root}/v1/videos/{id}（RESTful 端点）
_POLL_STYLES = (POLL_STYLE_LEGACY, POLL_STYLE_REST)
# /v1/videos 用 HTTP 400 + code 表达「任务不存在」（老端点用 404）
_TASK_NOT_FOUND_CODES = {"task_not_exist", "task_not_found"}


def _poll_url_for_style(key: str, video_id: str, model_param: str, style: str) -> str:
    """按查询风格构造轮询 URL（域名严格取自该 Key 的绑定配置）。"""
    if style == POLL_STYLE_REST:
        return f"{get_base_url_for_key(key)}/videos/{video_id}"
    return f"{get_api_root_for_key(key)}/agnesapi?video_id={video_id}{model_param}"


def _is_task_not_found(resp) -> bool:
    """是否「上游查不到该任务」——两站点表达方式不同，语义一致（U9 中间态）。

    老端点：HTTP 404 ``{"error": {"code": 404, "message": "task not found"}}``；
    REST 端点：HTTP 400 ``{"code": "task_not_exist"}``。
    """
    if resp.status_code == 404:
        return True
    if resp.status_code != 400:
        return False
    try:
        body = resp.json()
    except Exception:
        return False
    code = str((body or {}).get("code") or "").lower() if isinstance(body, dict) else ""
    return code in _TASK_NOT_FOUND_CODES


def _needs_portrait_rotation_fix(perf_w, perf_h, cont_w, cont_h) -> bool:
    """U3：判定 2.5 系列「容器竖、像素横」的竖屏躺倒缺陷签名。

    低代价代理判定（docs/dev/agnes_video_upstream_behavior.md §5.2）：
    推理内部尺寸（``perf_params``）为横屏而产物容器为竖屏 → 命中。
    任一尺寸缺失 / 方向一致 → 不命中（保守：宁可漏判，不可误转）。
    """
    try:
        pw, ph, cw, ch = int(perf_w), int(perf_h), int(cont_w), int(cont_h)
    except (TypeError, ValueError):
        return False
    if pw <= 0 or ph <= 0 or cw <= 0 or ch <= 0:
        return False
    return pw > ph and ch > cw


def _probe_video_size(path: str) -> tuple:
    """ffprobe 读取视频容器宽高（U3 判定用；失败返回 ``(None, None)``）。"""
    try:
        from core.compositor.ffmpeg_tool import resolve_binary
        ffprobe = resolve_binary("ffprobe")
        if not ffprobe:
            return None, None
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", path],
            capture_output=True, text=True, timeout=60,
        )
        streams = json.loads(result.stdout).get("streams") or []
        if streams:
            return streams[0].get("width"), streams[0].get("height")
    except Exception as e:
        logger.debug(f"[UpstreamRotate] ffprobe failed: {e}")
    return None, None


class AgnesQueueFullError(RuntimeError):
    """U1（v7.0）：队列类 503 在预算内始终没排进队——**未产生任务、未消耗配额**。

    消息体只放技术事实（日志/traceback 用）；用户可见文案交给 UI 层：
    - 前端：按 ``i18n key = error.video.queue_full`` + 参数用 22 语言渲染；
    - 后端兜底：``core.i18n_backend`` 的 zh/en（``utils.network.describe_queue_full_error``）。

    注意：``is_remote_video_failure`` 对本类返回 False（提交阶段就被拒，
    video_id 都不存在，自然不需要「服务端确认失败才丢弃 video_id」的判定）。
    """

    def __init__(self, status: int, code: str, waited_s: int):
        super().__init__(
            f"Agnes video queue full (HTTP {status} · {code}) after {waited_s}s "
            f"of retrying; no job was created"
        )
        self.queue_full_status = status
        self.queue_full_code = code
        self.queue_full_waited_s = waited_s


class VideoTaskCancelled(RuntimeError):
    """用户停止任务导致的取消（优化路线图 0.2）。

    继承 RuntimeError 以保持向后兼容，但语义上区别于可重试的临时错误
    （超时 / 网络 / 5xx）：停止必须立即穿透上层重试循环，否则用户点停止后
    仍要经历 20s/40s 退避才真正停下。
    """


def is_remote_video_failure(exc: BaseException) -> bool:
    """判断是否为「服务端已确认失败」——只有这种情况才可安全丢弃 video_id。

    仅当服务端明确返回 ``status=failed``（异常信息含 "Video generation failed:"）
    时为 True。超时、用户取消、网络中断时服务端任务**可能仍在运行**，必须返回
    False 以保留 video_id 供续传，避免重复提交浪费视频配额（1 次/分钟/Key）。

    优化路线图 0.2：此前流水线在任何异常下都删除 task.json，导致超时/取消后
    续传只能重新提交。
    """
    return "Video generation failed:" in str(exc)


def _read_json_cache(path: str) -> dict:
    """读取 JSON 缓存文件（线程池执行，避免阻塞事件循环，S7493）。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def _write_json_cache(path: str, data: dict) -> None:
    """原子写入 JSON 缓存文件（先写临时文件再 replace，线程池执行）。"""
    tmp_file = path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, path)


class VideoOutput:
    def __init__(self, fmt: str, ext: str, data: str,
                 perf_params: Optional[dict] = None,
                 fix_rotation: bool = False):
        self.fmt = fmt
        self.ext = ext
        self.data = data
        # U3：perf_params 为上游推理内部尺寸（非产物尺寸，勿用于产物校验）；
        # fix_rotation 开启时保存后探测「容器竖、像素横」签名并做方向校正
        self.perf_params = perf_params or {}
        self.fix_rotation = fix_rotation

    async def save(self, path: str) -> None:
        """保存视频到 path（异步）。

        优化路线图 0.3：URL 下载为同步 requests 流式读取，耗时 5~30s+，
        此前在协程中直接调用会阻塞事件循环；整体下沉到线程池执行。
        """
        await asyncio.to_thread(self._save_sync, path)

    def _save_sync(self, path: str) -> None:
        """同步保存实现（供线程池调用；同步上下文可直接使用）。"""
        if self.fmt == "url":
            download_video(self.data, path)
        else:
            with open(path, "wb") as f:
                f.write(self.data if isinstance(self.data, bytes) else self.data.encode())
        if self.fix_rotation:
            self._maybe_fix_rotation(path)

    def _maybe_fix_rotation(self, path: str) -> None:
        """U3：2.5 系列竖屏（9:16）上游躺倒缺陷的探测式校正（默认关闭）。

        判定签名见 ``_needs_portrait_rotation_fix``（容器竖 + 推理内部横）；
        校正 = ffmpeg ``transpose=2``（逆时针 90°，实测可还原正确构图）。
        任何一步失败保留原片并告警，不影响主流程。
        开关：``AGNES_FIX_V25_PORTRAIT_ROTATION``（默认关闭，见计划 §三）。
        """
        perf = self.perf_params or {}
        perf_w, perf_h = perf.get("width"), perf.get("height")
        if perf_w is None or perf_h is None:
            return
        try:
            cont_w, cont_h = _probe_video_size(path)
            if not _needs_portrait_rotation_fix(perf_w, perf_h, cont_w, cont_h):
                return
            from core.compositor.ffmpeg_tool import resolve_binary
            ffmpeg = resolve_binary("ffmpeg")
            if not ffmpeg:
                logger.warning("[UpstreamRotate] ffmpeg unavailable, keep original video")
                return
            tmp_path = path + ".rotated.mp4"
            cmd = [
                ffmpeg, "-y", "-i", path,
                "-vf", "transpose=2",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "copy",
                tmp_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.warning(
                    f"[UpstreamRotate] ffmpeg failed (rc={result.returncode}): "
                    f"{result.stderr[:300]}"
                )
                _silent_remove(tmp_path)
                return
            os.replace(tmp_path, path)
            logger.info(
                f"[UpstreamRotate] Fixed portrait rotation: perf={perf_w}x{perf_h} "
                f"container={cont_w}x{cont_h} -> transposed {os.path.basename(path)}"
            )
        except Exception as e:
            logger.warning(f"[UpstreamRotate] rotation fix skipped: {e}")


def _silent_remove(path: str) -> None:
    """尽力删除临时文件（失败静默，供 U3 校正失败清理）。"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class AgnesVideoAPI:
    """Agnes Video 生成 API 封装（t2v / i2v / ti2vid / keyframes）。"""

    def __init__(
        self,
        api_key: str,
        model: str = "agnes-video-2.5-flash",
        default_duration: int = 5,
        max_retries: int = 5,
        retry_base_delay: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.default_duration = default_duration
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.shutdown_event = None
        # 基础 headers（不含 Authorization）：每次请求前经 _auth_headers() 注入当前 Key
        self._base_headers = {
            "Content-Type": "application/json",
        }
        # 向后兼容：旧调用方可能读取 self.headers
        self.headers = dict(self._base_headers)
        # 任务 → 提交时使用的 Key（v7.3）：同一任务的提交与轮询必须用同一把 Key。
        # 每个 Key 绑定自己的域名（com/cn），混用会打错站点 → 401 Invalid token；
        # 多 Key 池下换 Key 还可能看不到别人账号下的任务（404）。
        self._task_keys: dict = {}
        # v7.7 快速重试模式：由流水线注入的可选钩子（见 core/api/fast_retry.py）。
        # 默认 None = 完全走原有忙轨节奏，行为与引入本功能前一致（零回归）。
        self.fast_retry_hook = None
        # 快速模式下的探测计数（仅用于 collect_error 降采样）
        self._fast_retry_probes = 0
        # ── v7.8：轮询健壮性钩子（全部由流水线注入，默认 None = 零回归）──
        # on_task_key_bound(video_id, key)：提交成功时把 Key 指纹落到任务状态
        self.on_task_key_bound = None
        # key_hint_resolver(video_id) -> key | None：resume 时按指纹找回 Key
        self.key_hint_resolver = None
        # poll_progress_hook(video_id, status, progress, elapsed_s)：每轮透传进度
        self.poll_progress_hook = None

    # ── 任务与 Key 绑定（v7.3）──────────────────────────────────────

    def _remember_task_key(self, video_id: str, key: str) -> None:
        """记录提交该任务所用的 Key（供 ``wait_for_video`` 复用）。"""
        if len(self._task_keys) >= 256:
            # 长驻进程兜底：只保留最近的绑定，避免无界增长
            self._task_keys.pop(next(iter(self._task_keys)), None)
        self._task_keys[video_id] = key
        # v7.8：同步落盘指纹（进程重启 / resume 后仍可找回这把 Key）
        if self.on_task_key_bound is not None:
            try:
                self.on_task_key_bound(video_id, key)
            except Exception as e:  # 落盘失败不影响提交
                logger.debug(f"[KeyBind] persist hook failed: {e}")

    def key_for_task(self, video_id: str) -> Optional[str]:
        """返回提交该任务所用的 Key；未知（进程重启/旧任务/外部传入）返回 None。"""
        return self._task_keys.get(video_id)

    def api_root_for_task(self, video_id: str) -> Optional[str]:
        """返回该任务所在站点的 API Root（按提交 Key 的域名绑定）；未知返回 None。

        供调试产物（curl.sh 等）输出与真实请求一致的地址。
        """
        key = self.key_for_task(video_id)
        return get_api_root_for_key(key) if key else None

    def _auth_headers(self, key: str | None = None) -> dict:
        """每次请求前生成带当前 Key 的 headers 副本。

        Args:
            key: 显式指定 Key（供按 Key 绑定域名路由时与 URL 保持一致）。
                省略时从 KeyRing 轮转取当前 Key。
        """
        k = key or get_key_ring().next()
        h = dict(self._base_headers)
        h["Authorization"] = f"Bearer {k}"
        return h

    # ── v7.7 快速重试模式（用户显式开启的高频忙信号探测）──────────────

    @staticmethod
    def _fast_retry_payload_brief(payload: dict) -> str:
        """快速模式日志用：序列化提交 payload（prompt 截断，避免刷屏）。"""
        try:
            brief = dict(payload)
        except (TypeError, ValueError):
            return str(payload)[:300]
        prompt = brief.get("prompt")
        if isinstance(prompt, str) and len(prompt) > 80:
            brief["prompt"] = f"{prompt[:80]}...(len={len(prompt)})"
        try:
            return json.dumps(brief, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(brief)[:300]

    def _fast_retry_decide(self, busy_attempt: int, payload: dict) -> Optional[float]:
        """询问快速重试钩子：本跳是否改用快速节奏（默认否）。

        钩子由流水线注入（见 ``core/api/fast_retry.py`` 的协议说明），内部只读
        任务状态；未注入（``fast_retry_hook is None``）时恒返回 None，调用方
        走原有忙轨节奏，行为与引入本功能前完全一致。

        Args:
            busy_attempt: 常规忙轨已重试次数（快速模式期间不递增）。
            payload: 上游忙信号事实（status / code / attempt / waited_s）。

        Returns:
            None = 走常规忙轨；float = 快速模式间隔（秒），本跳起按该节奏连打。
        """
        hook = self.fast_retry_hook
        if hook is None:
            return None
        try:
            interval = hook.decide(busy_attempt, payload)
        except Exception as e:  # 钩子异常绝不打断提交流程
            logger.warning(f"[FastRetry] hook decide() failed, fallback to busy track: {e}")
            return None
        if interval is None:
            return None
        try:
            return max(0.05, float(interval))
        except (TypeError, ValueError):
            return None

    def _fast_retry_sync_probe(self) -> None:
        """v8.0：每发出一跳就同步「已打次数」（与响应类型无关）。

        快速模式的次数以前只在 ``_fast_retry_decide()`` 里同步，而 decide 只在
        收到**忙信号**时才被调用；连打期间一旦遇到非忙响应（非队列 5xx、多 Key
        轮换的 429、请求超时），那一跳就不会同步次数 → 面板上的「已发 N 次」
        冻结不动。这里在每次发包后无条件同步一次，钩子内部再做落盘节流。
        """
        hook = self.fast_retry_hook
        if hook is None:
            return
        sync = getattr(hook, "on_probe", None)
        if sync is None:      # 兼容只实现 decide/on_success 的旧钩子
            return
        try:
            sync(self._fast_retry_probes)
        except Exception as e:  # 计数同步失败绝不打断提交流程
            logger.debug(f"[FastRetry] hook on_probe() failed: {e}")

    def _fast_retry_notify_success(self, probe: int = 0) -> None:
        """提交通知钩子（用于把快速模式标记为 success 并关闭）。

        Args:
            probe: 快速模式下已发出的请求次数（含本次成功那一跳）。
        """
        hook = self.fast_retry_hook
        if hook is None:
            return
        try:
            hook.on_success(probe)
        except TypeError:
            # 兼容只实现 on_success() 的旧钩子
            try:
                hook.on_success()
            except Exception as e:
                logger.warning(f"[FastRetry] hook on_success() failed: {e}")
        except Exception as e:
            logger.warning(f"[FastRetry] hook on_success() failed: {e}")

    def _path_to_b64(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    async def _resolve_image_ref(self, ref: str) -> str:
        if ref.startswith(("http://", "https://")):
            return ref
        if ref.startswith("data:"):
            return ref
        if os.path.exists(ref):
            url_file = ref + ".url"
            # P12: 缓存过期检查（预签名 URL 有效期有限，超过 1 小时则重新上传）
            _URL_CACHE_MAX_AGE = 3600  # 1 小时
            if os.path.exists(url_file):
                try:
                    cache_data = await asyncio.to_thread(_read_json_cache, url_file)
                    cached_url = cache_data.get("url", "")
                    cached_ts = cache_data.get("ts", 0)
                    age = time.time() - cached_ts
                    if cached_url and age < _URL_CACHE_MAX_AGE:
                        logger.info(
                            f"[AgnesVideo] Using cached hosted URL (age={age:.0f}s): "
                            f"{cached_url[:80]}..."
                        )
                        return cached_url
                    if cached_url:
                        logger.info(
                            f"[AgnesVideo] Cached URL expired (age={age:.0f}s), re-uploading"
                        )
                except (json.JSONDecodeError, OSError) as e:
                    logger.debug(f"[AgnesVideo] Failed to read cached URL: {e}")
                # 兼容旧格式纯文本缓存文件
                except Exception as e:
                    logger.debug(f"[AgnesVideo] Failed to read legacy URL cache: {e}")
            url = await self._upload_image_to_url(ref)
            if url:
                try:
                    await asyncio.to_thread(_write_json_cache, url_file, {"url": url, "ts": time.time()})
                except Exception as e:
                    logger.debug(f"[AgnesVideo] Failed to cache URL: {e}")
                return url
            logger.warning("[AgnesVideo] Image upload failed, falling back to base64.")
            return self._path_to_b64(ref)
        return ref

    async def _upload_image_to_url(self, image_path: str, retries: int = 3) -> Optional[str]:
        attempt = 0
        rotations = 0
        ring = get_key_ring()
        max_rotations = len(ring) * retries
        # 忙轨（429 / 所有 503）：首跳贴限流 + 固定间隔 + 次数封顶（core.api.retry_policy）
        busy: BusyTracker | None = None
        while attempt < retries:
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("[AgnesVideo] Image upload cancelled by shutdown")
                return None
            try:
                b64_data = self._path_to_b64(image_path)
                payload = {
                    "model": "agnes-image-2.5-flash",
                    "prompt": "Keep the image exactly as it is",
                    "n": 1,
                    "size": "1024x1024",
                    "extra_body": {
                        "response_format": "url",
                        "image": b64_data,
                    },
                }
                logger.info(f"[AgnesVideo] Uploading image to hosted URL (attempt {attempt + 1}/{retries})...")
                await get_rate_limiter().acquire_async(self.shutdown_event)
                key = ring.next()
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{get_base_url_for_key(key)}/images/generations",
                    headers=self._auth_headers(key),
                    json=payload,
                    timeout=(30, 120),
                )
                if resp.status_code == 429 and ring.has_multiple() and rotations < max_rotations:
                    rotations += 1
                    ring.rotate()
                    logger.warning(
                        f"[KeyRotation] HTTP 429, 换 Key 立即重试 "
                        f"(upload, rotation {rotations})"
                    )
                    continue

                code, _message = _upstream_error(resp)

                # ── 忙轨（429 / 所有 503）：首跳贴限流 + 固定间隔 + 次数封顶 ──
                if is_busy_signal(resp.status_code, code):
                    if busy is None:
                        from core.config import get_settings
                        busy = BusyTracker(
                            get_settings().agnes_busy_retry_attempts
                            or _UPLOAD_RETRY_MAX_ATTEMPTS
                        )
                    if busy.exhausted():
                        logger.warning(
                            f"[AgnesVideo] Image upload busy retries exhausted "
                            f"(HTTP {resp.status_code}, {busy.retries} attempts, "
                            f"waited {busy.waited_s:.0f}s), falling back to base64"
                        )
                        return None
                    busy.retries += 1
                    # 第 1 次重试 0s（贴着限流，交给共享令牌桶），之后固定基数
                    delay = busy_delay(
                        _UPLOAD_RETRY_BASE_DELAY_SECONDS, 0.0, busy.retries - 1
                    )
                    logger.warning(
                        f"[AgnesVideo] Image upload busy (HTTP {resp.status_code}"
                        f"{f' · {code}' if code else ''}), retry "
                        f"#{busy.retries}/{busy.max_attempts} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                # ── 故障轨（非忙 5xx）：逐级加长 + retries 次数封顶 ──
                if resp.status_code >= 500:
                    if attempt < retries - 1:
                        delay = fault_delay(_UPLOAD_RETRY_BASE_DELAY_SECONDS, attempt)
                        logger.warning(
                            f"[AgnesVideo] Image upload {resp.status_code} server error, "
                            f"retry {attempt + 1}/{retries} in {delay:.0f}s..."
                        )
                        await asyncio.sleep(delay)
                    attempt += 1
                    continue

                # 401：上报归因（不换 Key、不改退避节奏，随后的 raise_for_status
                # 仍按原逻辑进入重试/降级路径）
                if resp.status_code == 401:
                    _register_auth_failure(ring, key, resp)
                resp.raise_for_status()
                result = resp.json()
                data_list = result.get("data", [])
                if data_list:
                    url = data_list[0].get("url", "")
                    if url:
                        logger.info(f"[AgnesVideo] Image uploaded to hosted URL: {url[:80]}...")
                        return url
                # 响应里没有可用 URL：计一次尝试，避免原地死循环
                attempt += 1
            except Exception as e:
                # ── 故障轨（连接/超时/4xx 等）：逐级加长（原为写死 15s）──
                logger.warning(f"[AgnesVideo] Image upload attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    delay = fault_delay(_UPLOAD_RETRY_BASE_DELAY_SECONDS, attempt)
                    await asyncio.sleep(delay)
                attempt += 1
        return None

    async def _probe_owner_key(self, video_id: str, ring, model_param: str) -> Optional[str]:
        """v7.8：绑定丢失时，探测哪把 Key 拥有该上游任务（只读查询，最多 N 次）。

        实测（2026-11-06）：同一个 ``video_id``，只有提交时那把 Key 查得到
        （HTTP 200），同站点的另一把 Key 与 cn 站 Key 都返回 404。因此当
        ``_task_keys`` 因进程重启/resume 丢失时，用一次性的只读探测找回
        「任务归属的 Key」，避免把错 Key 导致的 404 误判为「网关入库延迟」
        而无限轮询到 1800s 超时。

        v7.9：每把 Key 都同时探「老网关端点」与「REST 端点」——国内站只认后者，
        只探老端点会把真实存在的任务误判成「全部 Key 都查不到」。

        Returns:
            第一个能查到该任务的 Key；全部查不到返回 ``None``（交回 U9 语义）。
        """
        candidates = getattr(ring, "keys", None) or []
        if len(candidates) < 2:
            return None  # 单 Key 不存在「用错 Key」的可能
        for k in candidates:
            for style in _POLL_STYLES:
                url = _poll_url_for_style(k, video_id, model_param, style)
                try:
                    resp = await asyncio.wait_for(
                        asyncio.to_thread(
                            requests.get, url,
                            headers=self._auth_headers(k), timeout=10,
                        ),
                        timeout=20,
                    )
                    if resp.status_code == 200:
                        logger.info(
                            f"[KeyBind] Video {video_id[:16]}... 归属 Key 探测命中 "
                            f"(key_fp={key_fingerprint(k)}, "
                            f"domain={get_api_root_for_key(k)}, "
                            f"endpoint={style})"
                        )
                        return k
                except Exception as e:
                    logger.debug(
                        f"[KeyBind] owner probe failed for key_fp={key_fingerprint(k)} "
                        f"({style}): {e}"
                    )
        logger.warning(
            f"[KeyBind] Video {video_id[:16]}... 全部 {len(candidates)} 把 Key "
            f"（两种查询端点）均查不到，按 U9「网关入库延迟」继续等待"
        )
        return None

    async def _poll_task(self, video_id: str, interval: int = 60,
                          max_poll_duration: int = 1800,
                          max_consecutive_failures: int = 10,
                          progress_callback=None,
                          key: str | None = None) -> dict:
        last_status = ""
        poll_count = 0
        consecutive_failures = 0
        # U9（v7.0.4）：提交返回的是网关路由键，任务记录入库可见有延迟——
        # 轮询侧 404 "task not found" 是「任务还没准备好」的中间态而非错误
        # （实测上游高峰期可见性延迟可从历史 ~20s 劣化到 10min+），单独计数、
        # 只做周期性 info 日志，不进 error_logs、不消耗连续失败配额；
        # 最终兜底是循环顶部的 max_poll_duration 整体超时。
        not_found_count = 0
        start_time = asyncio.get_event_loop().time()
        ring = get_key_ring()
        # v7.3 任务与 Key 绑定：轮询复用提交该任务的 Key，且整个轮询周期只用这一把。
        # 原因：①Key 绑定自己的域名（com/cn），混用会打错站点 → 401 Invalid token；
        # ②上游任务归属该 Key 的账号，换 Key 可能查不到（404 task not found）。
        # 进程重启后内存绑定丢失（旧任务/外部传入 video_id）时，退化为「本次轮询
        # 固定一把 Key」，不再逐次轮转——轮转只会让同一任务在多把 Key 之间跳动。
        pinned_key = key or self._task_keys.get(video_id)
        pool_keys = getattr(ring, "keys", None)
        if pinned_key is not None and pool_keys is not None and pinned_key not in pool_keys:
            # 提交 Key 已被删除/关闭：继续用只会 401，改用当前池内 Key 并提示
            logger.warning(
                f"[AgnesVideo] Video {video_id[:16]}... 的提交 Key 已不在 Key 池内"
                f"（被删除/关闭），改用当前 Key 轮询"
            )
            pinned_key = None
        poll_key = pinned_key or ring.next()
        if pinned_key is None and ring.has_multiple():
            logger.warning(
                f"[AgnesVideo] Video {video_id[:16]}... 无提交 Key 记录"
                f"（进程重启或旧任务），本次轮询固定复用同一 Key；"
                f"若持续 401/404 请在配置页核对该 Key 的域名绑定"
            )
        # 2.5 系列查询需带 model_name（text 模式可省略，但带上更通用）
        model_param = f"&model_name={self.model}" if is_v25_video_model(self.model) else ""
        # URL 与 Key 严格配对：域名取自该 Key 的绑定配置（未绑定才回退全局域名）
        def _poll_url_for(k: str, style: str = POLL_STYLE_LEGACY) -> str:
            return _poll_url_for_style(k, video_id, model_param, style)

        def _curl_for(url: str) -> str:
            return f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" "{url}"'

        # v7.9：已确认可用的查询端点（拿到 200 后固定下来，此后每轮只查它）；
        # None = 尚未确认，本轮按「老网关 → REST」逐个试。国内站只认 REST。
        poll_style: Optional[str] = None
        poll_url = _poll_url_for(poll_key)
        curl_cmd = _curl_for(poll_url)
        # v7.8：绑定丢失时只在第一次 404 做一次「Key 归属探测」，避免每轮多发 N 个请求
        owner_probed = False
        while True:
            # M2: 每次轮询前检查停止信号
            if self.shutdown_event and self.shutdown_event.is_set():
                raise VideoTaskCancelled("Video generation cancelled by user")

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_poll_duration:
                error_msg = (
                    f"[AgnesVideo] Polling timed out after {max_poll_duration}s "
                    f"for video {video_id[:16]}"
                )
                collect_error(
                    "video", "poll_task",
                    prompt=curl_cmd,
                    error_type="PollingTimeout",
                    error_message=error_msg,
                    extra={"video_id": video_id[:16], "elapsed_s": int(elapsed)},
                )
                raise RuntimeError(error_msg)

            try:
                # v7.8：10 次才打一行太稀疏（20s 起步 ≈ 200s 静默），改为每 5 次
                if poll_count % 5 == 0:
                    logger.info(
                        f"[AgnesVideo] Polling video {video_id[:16]}... "
                        f"(poll #{poll_count + 1}, elapsed {elapsed:.0f}s, "
                        f"key_fp={key_fingerprint(poll_key)})"
                    )
                # v7.9：端点双轨——已确认可用的只查它；否则本轮按「老网关 → REST」
                # 逐个试（前者 404 立刻换后者，不 sleep），谁 200 就固定下来。
                styles = [poll_style] if poll_style else list(_POLL_STYLES)
                resp = None
                for idx, style in enumerate(styles):
                    style_url = _poll_url_for(poll_key, style)
                    # 全局限速：每次轮询都消耗一个令牌（2.3 异步原生，停止可打断）
                    await get_rate_limiter().acquire_async(self.shutdown_event)
                    # M2: 用 wait_for 包裹以支持取消
                    resp = await asyncio.wait_for(
                        asyncio.to_thread(
                            requests.get,
                            style_url,
                            headers=self._auth_headers(poll_key),
                            timeout=15,
                        ),
                        timeout=30,
                    )
                    poll_url = style_url
                    curl_cmd = _curl_for(style_url)
                    if resp.status_code == 429:
                        # 任务与 Key 绑定：不换 Key（换 Key 可能打错站点或看不到任务），
                        # 交给连续失败计数 + 自适应间隔退避后用同一把 Key 继续探
                        logger.warning(
                            f"[AgnesVideo] Poll 429 for {video_id[:16]}..., "
                            f"保持同一 Key 重试（任务与 Key 绑定）"
                        )
                    # 401：只做归因登记（不换 Key、不改池），失败路径仍由 raise_for_status 保持原样
                    if resp.status_code == 401:
                        _register_auth_failure(ring, poll_key, resp)
                    if resp.status_code == 200:
                        if poll_style != style:
                            logger.info(
                                f"[AgnesVideo] Video {video_id[:16]}... 查询端点确认 "
                                f"为 {style}（{style_url.split('?')[0]}）"
                            )
                        poll_style = style
                        break
                    if _is_task_not_found(resp) and idx < len(styles) - 1:
                        continue  # 换另一个端点再试（U9 中间态，本跳不 sleep）
                    break
                # U9：查不到任务（404 / 400 task_not_exist）既可能是「记录尚未在网关
                # 任务库可见」，也可能是 v7.8 实测的「用错 Key / 站点」（同 video_id
                # 换 Key 一律查不到）。
                if _is_task_not_found(resp):
                    # 已确认的端点又开始查不到 → 下一轮重新做双端点确认
                    poll_style = None
                    not_found_count += 1
                    poll_count += 1  # 计入自适应间隔与周期日志的推进
                    if not_found_count == 1 or not_found_count % 5 == 0:
                        logger.info(
                            f"[AgnesVideo] Video {video_id[:16]}... not yet visible "
                            f"(task not found: HTTP {resp.status_code}, 端点 "
                            f"{'/'.join(styles)}), poll #{not_found_count}, "
                            f"elapsed {elapsed:.0f}s"
                        )
                    # 绑定丢失时做一次只读探测：谁查得到就固定用谁；
                    # 全部查不到才按 U9「入库延迟」继续等（不误伤高峰期可见性延迟）。
                    if pinned_key is None and not owner_probed:
                        owner_probed = True
                        found_key = await self._probe_owner_key(
                            video_id, ring, model_param
                        )
                        if found_key and found_key != poll_key:
                            logger.warning(
                                f"[KeyBind] Video {video_id[:16]}... 的 404 系 Key 错配，"
                                f"已探测到所属账号并固定改用该 Key 轮询"
                            )
                            poll_key = found_key
                            pinned_key = found_key
                            # 换 Key 可能换了站点，端点能力需重新确认
                            poll_style = None
                            poll_url = _poll_url_for(poll_key)
                            curl_cmd = _curl_for(poll_url)
                            continue  # 立刻用正确 Key 重查，不额外 sleep
                    await asyncio.sleep(_adaptive_poll_interval(interval, poll_count))
                    continue
                resp.raise_for_status()
                result = resp.json()
                status = result.get("status", "")
                # U5：progress 与 internal_progress 实测互相矛盾（可 0 vs 100）、
                # started_at 可为 null——仅作日志展示，任何逻辑不得依赖其数值
                # （自适应间隔 _adaptive_poll_interval 也只按次数推进）。
                progress = result.get("progress", 0)
                poll_count += 1
                consecutive_failures = 0  # reset on success

                if status != last_status:
                    logger.info(f"[AgnesVideo] Video {video_id[:16]}... status={status} progress={progress}%")
                    last_status = status

                if progress_callback:
                    progress_callback(status, progress, curl_cmd)

                # v7.8：把上游状态/已等时长透传给流水线，前端不再「一直等待」无反馈
                if self.poll_progress_hook is not None:
                    try:
                        self.poll_progress_hook(video_id, status, progress, elapsed)
                    except Exception as e:
                        logger.debug(f"[PollProgress] hook failed: {e}")

                if status in ("completed", "COMPLETED"):
                    return result

                if status in ("failed", "FAILED"):
                    # U2：error 是对象 {code, message}，统一提取而非字面量化
                    code, message = _upstream_error(result)
                    if not message:
                        message = str(result.get("error") or "unknown error")
                    error_msg = f"Video generation failed: {message}"
                    if code:
                        error_msg += f" (code={code})"
                    collect_error(
                        "video", "poll_task",
                        prompt=curl_cmd,
                        error_type="VideoFailed",
                        error_message=message,
                        response_body=resp.text,
                        extra={
                            "video_id": video_id[:16], "status": status,
                            "upstream_code": code,
                        },
                    )
                    raise RuntimeError(error_msg)
            except (requests.exceptions.RequestException, asyncio.TimeoutError) as e:
                consecutive_failures += 1
                logger.warning(
                    f"[AgnesVideo] Poll error ({consecutive_failures}/{max_consecutive_failures}): {e}"
                )
                # 每次轮询失败都记录
                collect_error_from_exception(
                    "video", "poll_task",
                    exc=e, prompt=curl_cmd,
                    retry_count=consecutive_failures,
                    extra={"video_id": video_id[:16], "poll_count": poll_count},
                )
                if consecutive_failures >= max_consecutive_failures:
                    error_msg = (
                        f"[AgnesVideo] Polling failed after {max_consecutive_failures} "
                        f"consecutive errors for video {video_id[:16]}"
                    )
                    collect_error_from_exception(
                        "video", "poll_task",
                        exc=e, prompt=curl_cmd,
                        retry_count=max_consecutive_failures,
                        extra={"video_id": video_id[:16], "poll_count": poll_count},
                    )
                    raise RuntimeError(error_msg)

            # 优化路线图 1.3：自适应轮询间隔（20s 起步，每 5 次 +5s，上限 interval）
            await asyncio.sleep(_adaptive_poll_interval(interval, poll_count))

    async def _submit_with_retry(self, payload: dict, mode_desc: str,
                                 progress_callback=None) -> str:
        frame_reductions_left = 2  # allow up to 2 frame-count reductions on 400
        attempt = 0
        rotations = 0
        # v7.7：每次提交独立计数（快速模式降采样用）
        self._fast_retry_probes = 0
        ring = get_key_ring()
        max_rotations = len(ring) * self.max_retries
        # 忙轨（429 / 所有 503 / 队列类 code）：首跳贴限流 + 固定间隔 + 次数封顶，
        # 不计入 max_retries 配额；次数上限首次命中时惰性读取（便于测试覆盖）
        busy: BusyTracker | None = None
        # v7.7 快速重试：>0 表示本跳按该间隔连打，且**跳过**共享视频提交桶
        # （用户显式开启；实测 503 阶段不会 429，若仍取桶令牌则 x 次/分钟无法兑现）
        fast_gap = 0.0
        while attempt < self.max_retries:
            if self.shutdown_event and self.shutdown_event.is_set():
                raise VideoTaskCancelled("Video generation cancelled by user")
            try:
                logger.info(f"[AgnesVideo] Submitting {mode_desc} (attempt {attempt + 1}/{self.max_retries})...")
                fast_mode = fast_gap > 0
                if fast_mode:
                    # 快速模式自带节奏：不占用共享桶，避免抢占其他任务的提交配额
                    self._fast_retry_probes += 1
                    await asyncio.sleep(fast_gap)
                else:
                    # 视频提交独立限速桶（服务端 1/min 硬限制，不与 chat/image 共享配额；
                    # 2.3 异步原生，停止可打断）
                    await get_video_submit_limiter().acquire_async(self.shutdown_event)
                # M2: 缩短读超时从 180s 到 60s，使 stop() 更快生效
                key = ring.next()
                url = f"{get_base_url_for_key(key)}/videos"
                # v7.7：快速模式下逐跳打印「请求 / 响应」原文，便于用户与排查侧核对
                # 每一次探测到底发了什么、上游回了什么（常规忙轨保持原有日志量）。
                if fast_mode:
                    logger.info(
                        "[FastRetry] probe #%d → POST %s | key_fp=%s | payload=%s",
                        self._fast_retry_probes, url,
                        key_fingerprint(key),
                        self._fast_retry_payload_brief(payload),
                    )
                req_started = time.monotonic()
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        url,
                        headers=self._auth_headers(key),
                        json=payload,
                        timeout=(15, 60),
                    ),
                    timeout=90,
                )
                if fast_mode:
                    logger.info(
                        "[FastRetry] probe #%d ← HTTP %d in %.2fs | body=%s",
                        self._fast_retry_probes, resp.status_code,
                        time.monotonic() - req_started, (resp.text or "")[:400],
                    )

                # v8.0：无论上游回什么（忙 / 非忙 / 400 降帧），这一跳都已经发出，
                # 先同步「已打次数」，避免面板上的计数停在上一次忙信号的值。
                if fast_mode:
                    self._fast_retry_sync_probe()

                if resp.status_code == 200:
                    result = resp.json()
                    video_id = result.get("video_id") or result.get("task_id") or result.get("id")
                    if video_id:
                        # 记住提交 Key：此后轮询必须复用该 Key（见 _poll_task）
                        self._remember_task_key(video_id, key)
                        # v7.7：快速模式命中队列 → 通知钩子收尾（enabled=False/success）
                        self._fast_retry_notify_success(self._fast_retry_probes)
                        return video_id

                if resp.status_code == 429 and ring.has_multiple() and rotations < max_rotations:
                    # 多 Key：换 Key 立即重试（不 sleep、不计入退避）
                    rotations += 1
                    ring.rotate()
                    logger.warning(
                        f"[KeyRotation] HTTP 429 on submit, 换 Key 立即重试 "
                        f"(rotation {rotations})"
                    )
                    continue

                if resp.status_code == 429 or resp.status_code >= 500:
                    # U2：解析响应体的 code/message（此前统一丢成 "server error"）
                    code, message = _upstream_error(resp)

                    # ── 忙轨（429 / 所有 503 / 队列类 code）──────────────────
                    # 服务器忙：首跳 0s 贴着限流（节奏交给令牌桶，单 Key ≈60s、
                    # 多 Key 先用满各 Key 突发额度）+ 之后固定间隔 + 次数封顶。
                    if is_busy_signal(resp.status_code, code):
                        if busy is None:
                            from core.config import get_settings
                            attempts = (
                                get_settings().agnes_video_busy_retry_attempts
                                or _QUEUE_RETRY_MAX_ATTEMPTS
                            )
                            busy = BusyTracker(attempts)
                            logger.warning(
                                f"[AgnesVideo] {mode_desc}: entering busy retry "
                                f"track (HTTP {resp.status_code}"
                                f"{f' · {code}' if code else ''}, "
                                f"max {busy.max_attempts} attempts)"
                            )
                        waited = busy.waited_s
                        if resp.status_code == 429:
                            error_type = "RateLimit429"
                            error_message = "HTTP 429: rate limited"
                        elif code in QUEUE_FULL_CODES:
                            error_type = f"QueueFull_{code}"
                            error_message = message or f"HTTP {resp.status_code}: {code}"
                        else:
                            error_type = f"Busy{resp.status_code}"
                            error_message = message or f"HTTP {resp.status_code}: server busy"

                        # ── v7.7 快速重试模式（用户显式开启，优先级高于常规忙轨）──
                        # 期间**不消耗**常规忙轨次数（否则 15 次额度会在几分钟内烧光），
                        # 到期/关闭后 hook 返回 None，原样回到下面的常规忙轨继续。
                        fast_interval = self._fast_retry_decide(
                            busy.retries,
                            {
                                "status": resp.status_code,
                                "code": code,
                                "attempt": busy.retries,
                                "waited_s": waited,
                                # v7.7：快速模式已打次数（计数在请求发出前递增）
                                "probe": self._fast_retry_probes,
                            },
                        )
                        if fast_interval is not None:
                            fast_gap = fast_interval
                            # 请求/响应原文已在上面逐跳打印，这里只补充节奏信息
                            logger.warning(
                                f"[AgnesVideo] {mode_desc}: fast mode active "
                                f"(probe #{self._fast_retry_probes}, HTTP "
                                f"{resp.status_code}{f' · {code}' if code else ''}), "
                                f"next in {fast_interval:.1f}s "
                                f"(waited {waited:.0f}s, busy quota intact)"
                            )
                            # 降采样落盘：高频探测若逐跳写 error_logs 会在几分钟内
                            # 刷掉诊断目录（轮转上限 500 个），只保留首跳与每 20 跳。
                            if (self._fast_retry_probes == 1
                                    or self._fast_retry_probes % 20 == 0):
                                collect_error(
                                    "video", "submit_video",
                                    prompt=payload.get("prompt", ""),
                                    error_type=error_type,
                                    error_message=error_message,
                                    status_code=resp.status_code,
                                    response_body=resp.text,
                                    retry_count=busy.retries,
                                    extra={
                                        "mode": mode_desc, "upstream_code": code,
                                        "waited_s": int(waited),
                                        "fast_retry_probe": self._fast_retry_probes,
                                    },
                                )
                            # 仅队列类信号下发进度回调（与常规忙轨一致）；
                            # 高频下每秒一次的进度推送没有意义，只在第 1 跳推一次。
                            if (progress_callback and code in QUEUE_FULL_CODES
                                    and self._fast_retry_probes == 1):
                                try:
                                    progress_callback("queue_full", {
                                        "attempt": busy.retries,
                                        "waited_s": waited,
                                        "status": resp.status_code,
                                        "code": code,
                                        "message": message,
                                    })
                                except Exception:
                                    logger.debug(
                                        "[AgnesVideo] fast-retry progress callback failed",
                                        exc_info=True,
                                    )
                            continue

                        # 快速模式到期/被关闭：本跳起恢复常规忙轨（含令牌桶节奏）
                        fast_gap = 0.0
                        if busy.exhausted():
                            collect_error(
                                "video", "submit_video",
                                prompt=payload.get("prompt", ""),
                                error_type=error_type,
                                error_message=error_message,
                                status_code=resp.status_code,
                                response_body=resp.text,
                                retry_count=busy.retries,
                                extra={
                                    "mode": mode_desc, "upstream_code": code,
                                    "waited_s": int(waited),
                                },
                            )
                            if code in QUEUE_FULL_CODES:
                                # 结构化异常：用户可见文案由 UI 层按 22 语言渲染，
                                # 此处只保留技术事实（HTTP 码 / body code / 等待时长）
                                raise AgnesQueueFullError(
                                    status=resp.status_code, code=code,
                                    waited_s=int(waited),
                                )
                            # 429 / 裸 503 等无队列语义的「忙」：走通用技术报错
                            raise RuntimeError(
                                f"[AgnesVideo] {mode_desc}: upstream busy "
                                f"(HTTP {resp.status_code}"
                                f"{f' · {code}' if code else ''}) after "
                                f"{busy.retries} retries"
                                f"{f' / {int(waited)}s' if waited else ''}; "
                                f"no job was created"
                            )
                        busy.retries += 1
                        # 第 1 次重试 0s（贴着限流），之后固定基数 + 抖动
                        delay = busy_delay(
                            _QUEUE_RETRY_BASE_DELAY, _QUEUE_RETRY_JITTER,
                            busy.retries - 1,
                        )
                        logger.warning(
                            f"[AgnesVideo] {mode_desc}: upstream busy "
                            f"(HTTP {resp.status_code}"
                            f"{f' · {code}' if code else ''}), busy retry "
                            f"#{busy.retries}/{busy.max_attempts} "
                            f"(waited {waited:.0f}s) in {delay:.0f}s..."
                        )
                        collect_error(
                            "video", "submit_video",
                            prompt=payload.get("prompt", ""),
                            error_type=error_type,
                            error_message=error_message,
                            status_code=resp.status_code,
                            response_body=resp.text,
                            retry_count=busy.retries,
                            extra={
                                "mode": mode_desc, "upstream_code": code,
                                "waited_s": int(waited),
                            },
                        )
                        # 仅队列类信号下发进度回调：前端据此渲染「Agnes 队列已满」
                        # 文案，429 / 裸 503 无队列语义，不误用该 key。
                        if progress_callback and code in QUEUE_FULL_CODES:
                            try:
                                # (stage, payload)：payload 带原样报错（HTTP 码 + body code）
                                # 与等待信息，供前端拼出「Agnes 队列已满 + 原始报错 + 错峰建议」
                                progress_callback("queue_full", {
                                    "attempt": busy.retries,
                                    "waited_s": waited,
                                    "status": resp.status_code,
                                    "code": code,
                                    "message": message,
                                })
                            except Exception:
                                logger.debug(
                                    "[AgnesVideo] queue progress callback failed",
                                    exc_info=True,
                                )
                        await asyncio.sleep(delay)
                        continue

                    # ── 故障轨（非忙 5xx）──────────────────────────────────
                    # 服务侧故障：间隔 base×(attempt+1) 逐级加长 + max_retries 次数封顶
                    delay = fault_delay(self.retry_base_delay, attempt)
                    logger.warning(
                        f"[AgnesVideo] {resp.status_code} server error on {mode_desc}"
                        f"{f' (code={code})' if code else ''}, "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    error_message = (
                        f"HTTP {resp.status_code}: {message}"
                        if message else f"HTTP {resp.status_code}: server error"
                    )
                    collect_error(
                        "video", "submit_video",
                        prompt=payload.get("prompt", ""),
                        error_type=f"HTTP{resp.status_code}",
                        error_message=error_message,
                        status_code=resp.status_code,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                        extra={"mode": mode_desc, "upstream_code": code},
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                # HTTP 400 with num_frames exceeded → reduce frames and retry
                error_text = resp.text[:500]
                if (resp.status_code == 400
                        and "num_frames" in error_text
                        and frame_reductions_left > 0):
                    old_nf = payload.get("num_frames", 0)
                    new_nf = max(int(old_nf * 0.7), 49)
                    logger.warning(
                        f"[AgnesVideo] 400 num_frames error ({old_nf} frames), "
                        f"reducing to {new_nf} and retrying "
                        f"({frame_reductions_left} reductions left)..."
                    )
                    collect_error(
                        "video", "submit_video",
                        prompt=payload.get("prompt", ""),
                        error_type="NumFramesExceeded",
                        error_message=f"HTTP 400: num_frames {old_nf} exceeded, reducing to {new_nf}",
                        status_code=400,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                        extra={"mode": mode_desc, "old_nf": old_nf, "new_nf": new_nf},
                    )
                    payload["num_frames"] = new_nf
                    frame_reductions_left -= 1
                    continue

                # 401：认证失败只做归因登记（收口在 KeyRing），失败行为保持不变
                # —— 不换 Key、不重试，Key 是否删除由用户在配置页决定
                if resp.status_code == 401:
                    _register_auth_failure(ring, key, resp)

                logger.error(f"[AgnesVideo] HTTP {resp.status_code}: {error_text}")
                collect_error(
                    "video", "submit_video",
                    prompt=payload.get("prompt", ""),
                    error_type="HTTPError",
                    error_message=f"HTTP {resp.status_code}: {error_text}",
                    status_code=resp.status_code,
                    response_body=resp.text,
                    retry_count=attempt + 1,
                    extra={"mode": mode_desc},
                )
                raise RuntimeError(f"Agnes video submit failed (HTTP {resp.status_code}): {error_text}")

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                        asyncio.TimeoutError) as e:
                # v8.0：超时/连接失败这一跳也算「已发出」，同步计数后前端才会动
                # （用 fast_gap 判定：它在本轮循环外定义，不受 try 内异常影响）
                if fast_gap > 0:
                    self._fast_retry_sync_probe()
                # 每次失败都记录（包括中间重试）
                collect_error_from_exception(
                    "video", "submit_video",
                    exc=e, prompt=payload.get("prompt", ""),
                    retry_count=attempt + 1,
                    extra={"mode": mode_desc},
                )
                if attempt < self.max_retries - 1:
                    delay = fault_delay(self.retry_base_delay, attempt)
                    logger.warning(
                        f"[AgnesVideo] {type(e).__name__} on {mode_desc}, "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise

        collect_error(
            "video", "submit_video",
            prompt=payload.get("prompt", ""),
            error_type="RetriesExhausted",
            error_message=f"{mode_desc}: max retries ({self.max_retries}) exceeded",
            retry_count=self.max_retries,
            extra={"mode": mode_desc},
        )
        raise RuntimeError(
            f"[AgnesVideo] {mode_desc}: max retries ({self.max_retries}) exceeded"
        )

    async def generate_single_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        duration: Optional[int] = None,
        width: int = 1280,
        height: int = 720,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        progress_callback=None,
        **kwargs,
    ) -> VideoOutput:
        video_id = await self.submit_video(
            prompt=prompt,
            reference_image_paths=reference_image_paths,
            duration=duration,
            width=width,
            height=height,
            seed=seed,
            negative_prompt=negative_prompt,
            progress_callback=progress_callback,
            **kwargs,
        )
        return await self.wait_for_video(video_id, progress_callback)

    async def submit_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        duration: Optional[int] = None,
        width: int = 1280,
        height: int = 720,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        progress_callback=None,
        first_frame: Optional[str] = None,
        last_frame: Optional[str] = None,
        reference_audio_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        # 2.5 系列为标准协议（v6.2）：mode / seconds / size / aspect_ratio。
        # v2.0 渠道已于 2026-10-14 下线（docs/dev/agnes_video_upstream_behavior.md §4.0.2），
        # 不再保留 width/height/num_frames 旧协议分支，统一走 2.5 提交路径。
        return await self._submit_video_v25(
            prompt=prompt,
            reference_image_paths=reference_image_paths,
            duration=duration,
            width=width,
            height=height,
            seed=seed,
            progress_callback=progress_callback,
            first_frame=first_frame,
            last_frame=last_frame,
            reference_audio_urls=reference_audio_urls,
            **kwargs,
        )

    @staticmethod
    def _width_height_to_aspect_ratio(width: int, height: int) -> str:
        """将像素宽高映射到 2.5 系列 aspect_ratio 枚举（委托 ``core.config``）。

        映射规则已上提到 ``core.config.width_height_to_aspect_ratio``，供回归
        校验脚本共用（保证「提交」与「校验」同一套规则）；此方法保留为类内
        调用入口，行为与上提前完全一致。
        """
        return width_height_to_aspect_ratio(width, height)

    async def _submit_video_v25(
        self,
        prompt: str,
        reference_image_paths: List[str],
        duration: Optional[int] = None,
        width: int = 1280,
        height: int = 720,
        seed: Optional[int] = None,
        progress_callback=None,
        first_frame: Optional[str] = None,
        last_frame: Optional[str] = None,
        reference_audio_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        """2.5 / 2.5-flash 新协议提交：mode / seconds / size / aspect_ratio。

        与 v2.0 的关键差异：
        - size 走官方枚举（flash 强制 720P；2.5 支持 720P/1080P/1K/2K）
        - seconds 为字符串 "4"–"12"
        - 首/尾帧 → 原生 keyframe（first_frame/last_frame）
        - 参考图 → reference(images)；参考音频 → reference(audios)
        - 不支持 negative_prompt（忽略）

        模式互斥（官方规则）：``text`` 不允许任何媒体字段；``keyframe`` 只允许
        first_frame/last_frame；``reference`` 只允许 images/audios/videos。
        调用方若混传，本方法按「keyframe > reference > text」取舍，保证不触发
        上游 400（前端/路由层另有显式校验）。
        """
        payload = self._build_v25_payload(
            prompt, duration, width, height, seed, kwargs.get("video_size"),
        )
        resolved_refs, resolved_first, resolved_last, audios = await self._resolve_v25_media(
            reference_image_paths, first_frame, last_frame,
            reference_audio_urls, width, height,
        )
        mode_desc = self._apply_v25_mode(
            payload, resolved_refs, resolved_first, resolved_last, audios,
        )

        logger.info(f"[AgnesVideo] {mode_desc}: {prompt[:80]}...")
        video_id = await self._submit_with_retry(payload, mode_desc, progress_callback)
        logger.info(f"[AgnesVideo] Video submitted: {video_id[:20]}...")
        return video_id

    @staticmethod
    def _normalize_seconds(duration: Optional[int]) -> str:
        """秒数 → 官方 seconds 字符串（4–12，缺省 5，超界截断）。"""
        secs = int(duration) if duration else 5
        return str(max(4, min(secs, 12)))

    def _build_v25_payload(
        self,
        prompt: str,
        duration: Optional[int],
        width: int,
        height: int,
        seed: Optional[int],
        video_size: Optional[str],
    ) -> dict:
        """构造 2.5 协议的基础负载（mode 由 ``_apply_v25_mode`` 后续决定）。"""
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "mode": "text",
            "seconds": self._normalize_seconds(duration),
            # 分辨率：官方枚举归一（旧 960P → 1080P；flash 强制 720P）
            "size": normalize_video_size(video_size, self.model),
            "aspect_ratio": self._width_height_to_aspect_ratio(width, height),
        }
        if seed is not None:
            payload["seed"] = seed
        return payload

    async def _resolve_v25_media(
        self,
        reference_image_paths: List[str],
        first_frame: Optional[str],
        last_frame: Optional[str],
        reference_audio_urls: Optional[List[str]],
        width: int,
        height: int,
    ) -> tuple:
        """解析 2.5 协议素材：参考图 + 首尾帧 + 参考音频。

        Returns:
            ``(resolved_refs, resolved_first, resolved_last, audios)``。
        """

        async def _resolve(src: str) -> str:
            """本地图片 → 归一化 → 公开 URL（与既有参考图链路一致）。"""
            norm = await asyncio.to_thread(normalize_reference_path, src, width, height)
            return await self._resolve_image_ref(norm)

        resolved_refs: List[str] = [await _resolve(p) for p in reference_image_paths if p]
        resolved_first = await _resolve(first_frame) if first_frame else ""
        resolved_last = await _resolve(last_frame) if last_frame else ""
        # 参考音频（仅接受公开 http(s) URL；本地文件上传通道暂不支持音频）
        audios = [
            u.strip() for u in (reference_audio_urls or [])
            if isinstance(u, str) and u.strip().startswith(("http://", "https://"))
        ][:3]
        return resolved_refs, resolved_first, resolved_last, audios

    @staticmethod
    def _native_keyframe_enabled() -> bool:
        """原生 keyframe 开关（默认开）。

        关闭后回落 v6.2.1 的 reference 多图降级，便于上游若仍存在
        「keyframe 固定 704×704」问题时一键回退。
        """
        return os.environ.get("AGNES_KEYFRAME_NATIVE", "1").strip().lower() not in (
            "0", "false", "off", "no",
        )

    def _apply_v25_mode(
        self,
        payload: dict,
        resolved_refs: List[str],
        resolved_first: str,
        resolved_last: str,
        audios: List[str],
    ) -> str:
        """按「keyframe > reference > text」写入 mode 与素材，返回日志描述。"""
        native_keyframe = self._native_keyframe_enabled()
        if (resolved_first or resolved_last) and native_keyframe:
            # v8.1 实测（2026-11-11）：keyframe 模式忽略 aspect_ratio，固定返回方形视频
            # （720P → 720×720，竖图被拉伸）。这里一次性告警，避免用户以为参数生效。
            global _KEYFRAME_SQUARE_WARNED
            aspect = str(payload.get("aspect_ratio") or "")
            if aspect and aspect != "1:1" and not _KEYFRAME_SQUARE_WARNED:
                _KEYFRAME_SQUARE_WARNED = True
                logger.warning(
                    "[AgnesVideo] keyframe mode ignores aspect_ratio=%s: upstream returns "
                    "square video; set AGNES_KEYFRAME_NATIVE=0 to fall back to reference "
                    "multi-image if exact aspect ratio matters",
                    aspect,
                )
            return self._apply_keyframe_payload(payload, resolved_first, resolved_last)
        if not (resolved_first or resolved_last or resolved_refs or audios):
            return "text-to-video"
        return self._apply_reference_payload(
            payload, resolved_refs, resolved_first, resolved_last, audios, native_keyframe,
        )

    @staticmethod
    def _apply_keyframe_payload(payload: dict, first: str, last: str) -> str:
        """原生 keyframe 模式：只提交 first_frame / last_frame。"""
        payload["mode"] = "keyframe"
        if first:
            payload["first_frame"] = first
        if last:
            payload["last_frame"] = last
        if first and last:
            return "keyframe (first+last)"
        if first:
            return "keyframe (first)"
        return "keyframe (last)"

    def _apply_reference_payload(
        self,
        payload: dict,
        resolved_refs: List[str],
        resolved_first: str,
        resolved_last: str,
        audios: List[str],
        native_keyframe: bool,
    ) -> str:
        """reference 模式：images / audios（keyframe 关闭时首尾帧并入参考图）。"""
        payload["mode"] = "reference"
        # v8.1：上限唯一来源（core.config.get_max_ref_images），不再硬编码
        max_refs = get_max_ref_images(self.model)
        images = resolved_refs
        if not native_keyframe:
            # 降级路径：首尾帧并入参考图（旧行为），输出遵循 aspect_ratio
            images = [x for x in (resolved_first, resolved_last) if x] + images
        if len(images) > max_refs:
            # 兜底截断必须留痕：此前静默截断，误以为「传了 N 张都生效」
            logger.warning(
                "[AgnesVideo] reference images truncated: %d > %d (%s)",
                len(images), max_refs, self.model,
            )
        if images:
            payload["images"] = images[:max_refs]
        if audios:
            payload["audios"] = audios
        descs = []
        if images:
            descs.append(f"{len(images)} image(s)")
        if audios:
            descs.append(f"{len(audios)} audio(s)")
        return "reference (" + ", ".join(descs) + ")"

    def _resolve_pinned_key(self, video_id: str, key: Optional[str]) -> Optional[str]:
        """确定轮询使用的 Key：显式指定 → 内存绑定 → 状态文件指纹回查。"""
        pinned_key = key or self._task_keys.get(video_id)
        if pinned_key is None and self.key_hint_resolver is not None:
            try:
                pinned_key = self.key_hint_resolver(video_id)
            except Exception as e:
                logger.debug(f"[KeyBind] hint resolver failed: {e}")
        return pinned_key

    @staticmethod
    def _extract_video_url(final: dict) -> str:
        """从完成任务负载中取成品地址（兼容 2.0 / 2.5 / REST 端点结构）。

        v7.9：REST 端点（``/v1/videos/{id}``）把成品地址放在 ``metadata.url``。
        """
        video_url = (
            final.get("remixed_from_video_id")
            or final.get("video_url")
            or final.get("url")
        )
        if video_url:
            return video_url
        data = final.get("data", {})
        if isinstance(data, dict):
            video_url = data.get("video_url") or data.get("url")
        if video_url:
            return video_url
        meta = final.get("metadata")
        if isinstance(meta, dict):
            return meta.get("url") or meta.get("video_url") or ""
        return ""

    async def wait_for_video(self, video_id: str, progress_callback=None,
                             key: str | None = None) -> VideoOutput:
        """轮询视频直至完成。

        Args:
            video_id: 上游任务 id。
            progress_callback: 进度回调。
            key: 显式指定轮询使用的 Key（默认复用提交该任务的 Key）。
                同一任务的提交与轮询必须使用同一把 Key——每个 Key 绑定自己的
                域名（com/cn），混用会打错站点（401 Invalid token）；多 Key 池
                下换 Key 还可能看不到别人账号下的任务（404）。
        """
        # 1.2：轮询总超时可经 AGNES_VIDEO_POLL_TIMEOUT 配置（3.5 RuntimeSettings 收敛）
        from core.config import get_settings
        settings = get_settings()
        # v7.8：优先内存绑定 → 其次按任务状态里的 Key 指纹恢复（进程重启/resume）
        pinned_key = self._resolve_pinned_key(video_id, key)
        final = await self._poll_task(
            video_id, progress_callback=progress_callback,
            max_poll_duration=settings.agnes_video_poll_timeout,
            key=pinned_key,
        )

        video_url = self._extract_video_url(final)
        if not video_url:
            raise RuntimeError(f"Agnes video: no URL in completed task: {final}")

        logger.info(f"[AgnesVideo] Done: {video_url[:80]}...")
        # U3：携带推理内部尺寸 + 校正开关（默认关闭；仅 2.5 系列探测「容器竖、
        # 像素横」签名后 ffmpeg transpose=2 校正，详见计划 §三）
        fix_rotation = (
            settings.agnes_fix_v25_portrait_rotation
            and is_v25_video_model(self.model)
        )
        return VideoOutput(
            fmt="url", ext="mp4", data=video_url,
            perf_params=final.get("perf_params") or {},
            fix_rotation=fix_rotation,
        )
