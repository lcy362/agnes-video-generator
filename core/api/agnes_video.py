"""core.api.agnes_video — Agnes Video API 封装（从 core/video_generator.py 迁移）"""

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
from typing import List, Optional

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.key_manager import get_key_ring
from core.api.rate_limiter import get_rate_limiter, get_video_submit_limiter
from core.config import (
    VIDEO_ASPECT_RATIOS,
    get_agnes_api_root,
    get_base_url_for_key,
    is_v25_video_model,
)
from utils.image_normalizer import normalize_reference_path
from utils.video import download_video

logger = logging.getLogger(__name__)

DURATION_PRESETS = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (409, 24),   # capped at 409 (API max for 720p); actual ~17s
    20: (409, 24),   # capped at 409 (API max for 720p); actual ~17s
}

# 图片上传 429 退避间隔基数（秒）：delay = 基数 * (attempt + 1)
_UPLOAD_RETRY_BASE_DELAY_SECONDS = 30


def _adaptive_poll_interval(interval: int, poll_count: int) -> int:
    """优化路线图 1.3：自适应轮询间隔。

    此前固定 ``interval``（默认 60s），每个视频平均多等 ~30s 检测延迟。
    现改为 20s 起步，每 5 次轮询 +5s，上限为调用方 ``interval``；
    调用方传小间隔（<20，如测试）时保持原样。
    """
    if interval < 20:
        return interval
    return min(interval, 20 + (poll_count // 5) * 5)


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
    def __init__(self, fmt: str, ext: str, data: str):
        self.fmt = fmt
        self.ext = ext
        self.data = data

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


class AgnesVideoAPI:
    """Agnes Video 生成 API 封装（t2v / i2v / ti2vid / keyframes）。"""

    def __init__(
        self,
        api_key: str,
        model: str = "agnes-video-v2.0",
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
                if resp.status_code == 429:
                    if ring.has_multiple() and rotations < max_rotations:
                        rotations += 1
                        ring.rotate()
                        logger.warning(
                            f"[KeyRotation] HTTP 429, 换 Key 立即重试 "
                            f"(upload, rotation {rotations})"
                        )
                        continue
                    delay = _UPLOAD_RETRY_BASE_DELAY_SECONDS * (attempt + 1)
                    logger.warning(f"[AgnesVideo] Image upload 429, retry in {delay}s...")
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                resp.raise_for_status()
                result = resp.json()
                data_list = result.get("data", [])
                if data_list:
                    url = data_list[0].get("url", "")
                    if url:
                        logger.info(f"[AgnesVideo] Image uploaded to hosted URL: {url[:80]}...")
                        return url
            except Exception as e:
                logger.warning(f"[AgnesVideo] Image upload attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(15)
        return None

    # API frame limits by resolution tier (from Agnes API error messages)
    _FRAME_LIMITS = {
        "1080p": 169,
        "720p": 409,
        "480p": 961,
    }

    @staticmethod
    def _get_max_frames(width: int, height: int) -> int:
        """Get the maximum allowed num_frames for the given resolution."""
        pixels = width * height
        if pixels > 1280 * 720:
            return 169   # 1080p tier
        elif pixels > 854 * 480:
            return 409   # 720p tier
        else:
            return 961   # 480p tier

    def _get_frame_config(self, duration: Optional[int] = None,
                          width: int = 1152, height: int = 768) -> tuple:
        d = duration or self.default_duration
        max_nf = self._get_max_frames(width, height)
        if d in DURATION_PRESETS:
            nf, fr = DURATION_PRESETS[d]
            if nf <= max_nf:
                return nf, fr
            # preset exceeds limit for this resolution, cap it
            logger.warning(
                f"[AgnesVideo] Duration preset {d}s has {nf} frames, "
                f"exceeds {max_nf} for {width}x{height}. Capping."
            )
            return max_nf, fr
        best = None
        for nf in range(9, min(410, max_nf + 1), 8):
            fr = round(nf / d)
            if 1 <= fr <= 60:
                best = (nf, fr)
        return best or DURATION_PRESETS[5]

    async def _poll_task(self, video_id: str, interval: int = 60,
                          max_poll_duration: int = 1800,
                          max_consecutive_failures: int = 10,
                          progress_callback=None) -> dict:
        last_status = ""
        poll_count = 0
        consecutive_failures = 0
        start_time = asyncio.get_event_loop().time()
        # 2.5 系列查询需带 model_name（text 模式可省略，但带上更通用）
        model_param = f"&model_name={self.model}" if is_v25_video_model(self.model) else ""
        curl_cmd = (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"{get_agnes_api_root()}/agnesapi?video_id={video_id}{model_param}"'
        )
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
                if poll_count % 10 == 0:
                    logger.info(f"[AgnesVideo] Polling video {video_id[:16]}... (poll #{poll_count + 1}, elapsed {elapsed:.0f}s)")
                # 全局限速：每次轮询都消耗一个令牌（2.3 异步原生，停止可打断）
                await get_rate_limiter().acquire_async(self.shutdown_event)
                # M2: 用 wait_for 包裹以支持取消；429 换 Key 立即重试（轮询也轮转 Key 分摊配额）
                poll_attempts = 0
                while True:
                    resp = await asyncio.wait_for(
                        asyncio.to_thread(
                            requests.get,
                            f"{get_agnes_api_root()}/agnesapi?video_id={video_id}{model_param}",
                            headers=self._auth_headers(),
                            timeout=15,
                        ),
                        timeout=30,
                    )
                    if resp.status_code == 429 and get_key_ring().has_multiple() and poll_attempts < 5:
                        get_key_ring().rotate()
                        poll_attempts += 1
                        logger.warning("[KeyRotation] HTTP 429 on poll, 换 Key 立即重试")
                        continue
                    break
                resp.raise_for_status()
                result = resp.json()
                status = result.get("status", "")
                progress = result.get("progress", 0)
                poll_count += 1
                consecutive_failures = 0  # reset on success

                if status != last_status:
                    logger.info(f"[AgnesVideo] Video {video_id[:16]}... status={status} progress={progress}%")
                    last_status = status

                if progress_callback:
                    progress_callback(status, progress, curl_cmd)

                if status in ("completed", "COMPLETED"):
                    return result

                if status in ("failed", "FAILED"):
                    err = result.get("error") or "unknown error"
                    error_msg = f"Video generation failed: {err}"
                    collect_error(
                        "video", "poll_task",
                        prompt=curl_cmd,
                        error_type="VideoFailed",
                        error_message=error_msg,
                        response_body=resp.text,
                        extra={"video_id": video_id[:16], "status": status},
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

    async def _submit_with_retry(self, payload: dict, mode_desc: str) -> str:
        frame_reductions_left = 2  # allow up to 2 frame-count reductions on 400
        attempt = 0
        rotations = 0
        ring = get_key_ring()
        max_rotations = len(ring) * self.max_retries
        while attempt < self.max_retries:
            if self.shutdown_event and self.shutdown_event.is_set():
                raise VideoTaskCancelled("Video generation cancelled by user")
            try:
                logger.info(f"[AgnesVideo] Submitting {mode_desc} (attempt {attempt + 1}/{self.max_retries})...")
                # 视频提交独立限速桶（服务端 1/min 硬限制，不与 chat/image 共享配额；
                # 2.3 异步原生，停止可打断）
                await get_video_submit_limiter().acquire_async(self.shutdown_event)
                # M2: 缩短读超时从 180s 到 60s，使 stop() 更快生效
                key = ring.next()
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        f"{get_base_url_for_key(key)}/videos",
                        headers=self._auth_headers(key),
                        json=payload,
                        timeout=(15, 60),
                    ),
                    timeout=90,
                )

                if resp.status_code == 200:
                    result = resp.json()
                    video_id = result.get("video_id") or result.get("task_id") or result.get("id")
                    if video_id:
                        return video_id

                if resp.status_code == 429:
                    # 多 Key：换 Key 立即重试（不 sleep、不计入退避）
                    if ring.has_multiple() and rotations < max_rotations:
                        rotations += 1
                        ring.rotate()
                        logger.warning(
                            f"[KeyRotation] HTTP 429 on submit, 换 Key 立即重试 "
                            f"(rotation {rotations})"
                        )
                        continue
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesVideo] 429 rate limit on {mode_desc}, "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    collect_error(
                        "video", "submit_video",
                        prompt=payload.get("prompt", ""),
                        error_type="RateLimit429",
                        error_message="HTTP 429: rate limited",
                        status_code=429,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                        extra={"mode": mode_desc},
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                if resp.status_code >= 500:
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesVideo] {resp.status_code} server error on {mode_desc}, "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    collect_error(
                        "video", "submit_video",
                        prompt=payload.get("prompt", ""),
                        error_type=f"HTTP{resp.status_code}",
                        error_message=f"HTTP {resp.status_code}: server error",
                        status_code=resp.status_code,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                        extra={"mode": mode_desc},
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
                # 每次失败都记录（包括中间重试）
                collect_error_from_exception(
                    "video", "submit_video",
                    exc=e, prompt=payload.get("prompt", ""),
                    retry_count=attempt + 1,
                    extra={"mode": mode_desc},
                )
                if attempt < self.max_retries - 1:
                    delay = self.retry_base_delay * (attempt + 1)
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
        width: int = 1152,
        height: int = 768,
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
            **kwargs,
        )
        return await self.wait_for_video(video_id, progress_callback)

    async def submit_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        duration: Optional[int] = None,
        width: int = 1152,
        height: int = 768,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        **kwargs,
    ) -> str:
        # 2.5 系列模型（v6.2）：新参数协议（mode/seconds/size/aspect_ratio）
        if is_v25_video_model(self.model):
            return await self._submit_video_v25(
                prompt=prompt,
                reference_image_paths=reference_image_paths,
                duration=duration,
                width=width,
                height=height,
                seed=seed,
                **kwargs,
            )
        num_frames, frame_rate = self._get_frame_config(duration, width, height)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }

        if seed is not None:
            payload["seed"] = seed
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        resolved_refs = []
        for p in reference_image_paths:
            # 优化 2：入参处先归一化参考图（尺寸统一 + 体积压缩），再 resolve。
            # URL/data: 透传、失败回退原图，安全无回归。
            norm = await asyncio.to_thread(normalize_reference_path, p, width, height)
            resolved_refs.append(await self._resolve_image_ref(norm))
        n_refs = len(resolved_refs)

        if n_refs == 0:
            mode_desc = "text-to-video"
        elif n_refs == 1:
            payload["image"] = resolved_refs[0]
            payload["mode"] = "ti2vid"
            mode_desc = "image-to-video"
        else:
            payload["extra_body"] = {
                "image": resolved_refs,
                "mode": "keyframes",
            }
            mode_desc = f"keyframes ({n_refs} frames)"

        logger.info(f"[AgnesVideo] {mode_desc}: {prompt[:80]}...")

        video_id = await self._submit_with_retry(payload, mode_desc)
        logger.info(f"[AgnesVideo] Video submitted: {video_id[:20]}...")
        return video_id

    @staticmethod
    def _width_height_to_aspect_ratio(width: int, height: int) -> str:
        """将像素宽高映射到最接近的 2.5 系列 aspect_ratio 枚举。

        找不到精确比例时取误差最小的档位（默认 16:9）。
        """
        if not width or not height:
            return "16:9"
        ratio = width / height
        best = "16:9"
        best_dist = float("inf")
        for ar in VIDEO_ASPECT_RATIOS:
            w, h = ar.split(":")
            target = int(w) / int(h)
            dist = abs(ratio - target)
            if dist < best_dist:
                best_dist = dist
                best = ar
        return best

    async def _submit_video_v25(
        self,
        prompt: str,
        reference_image_paths: List[str],
        duration: Optional[int] = None,
        width: int = 1152,
        height: int = 768,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        """2.5 / 2.5-flash 新协议提交：mode / seconds / size / aspect_ratio。

        与 v2.0 的关键差异：
        - size 固定 720P（flash）或 720P/960P/2K（2.5）；不传 width/height/num_frames
        - seconds 为字符串 "4"–"12"
        - 单参考图 → reference(images)；多图 → keyframe(first_frame + last_frame)
        - 不支持 negative_prompt（忽略）
        """
        # 时长：duration(秒) → seconds 字符串（4–12，超界截断）
        secs = int(duration) if duration else 5
        seconds = str(max(4, min(secs, 12)))
        # 分辨率：flash 固定 720P；2.5 用 video_size 参数（缺省 720P）
        size = kwargs.get("video_size") or "720P"
        if self.model == "agnes-video-2.5-flash":
            size = "720P"
        aspect_ratio = self._width_height_to_aspect_ratio(width, height)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "mode": "text",
            "seconds": seconds,
            "size": size,
            "aspect_ratio": aspect_ratio,
        }
        if seed is not None:
            payload["seed"] = seed

        # 参考图解析（与 v2.0 一致：归一化 + 上传为公开 URL）
        resolved_refs = []
        for p in reference_image_paths:
            norm = await asyncio.to_thread(normalize_reference_path, p, width, height)
            resolved_refs.append(await self._resolve_image_ref(norm))
        n_refs = len(resolved_refs)

        if n_refs == 1:
            payload["mode"] = "reference"
            payload["images"] = resolved_refs
            mode_desc = "reference (1 image)"
        elif n_refs >= 2:
            # v6.2.1: Agnes 2.5 系列 keyframe 模式固定输出 704x704 正方形
            # （忽略 aspect_ratio，竖屏/横屏画面会被拉伸，人物显宽）。
            # 降级为 reference 模式（多图参考，≤5 张），输出遵循 aspect_ratio。
            payload["mode"] = "reference"
            payload["images"] = resolved_refs[:5]
            mode_desc = f"reference ({n_refs} images, keyframe fallback)"
        else:
            mode_desc = "text-to-video"

        logger.info(f"[AgnesVideo] {mode_desc}: {prompt[:80]}...")
        video_id = await self._submit_with_retry(payload, mode_desc)
        logger.info(f"[AgnesVideo] Video submitted: {video_id[:20]}...")
        return video_id

    async def wait_for_video(self, video_id: str, progress_callback=None) -> VideoOutput:
        # 1.2：轮询总超时可经 AGNES_VIDEO_POLL_TIMEOUT 配置（3.5 RuntimeSettings 收敛）
        from core.config import get_settings
        poll_timeout = get_settings().agnes_video_poll_timeout
        final = await self._poll_task(
            video_id, progress_callback=progress_callback,
            max_poll_duration=poll_timeout,
        )

        video_url = (
            final.get("remixed_from_video_id")
            or final.get("video_url")
            or final.get("url")
        )
        if not video_url:
            data = final.get("data", {})
            if isinstance(data, dict):
                video_url = data.get("video_url") or data.get("url")
            if not video_url:
                raise RuntimeError(f"Agnes video: no URL in completed task: {final}")

        logger.info(f"[AgnesVideo] Done: {video_url[:80]}...")
        return VideoOutput(fmt="url", ext="mp4", data=video_url)
