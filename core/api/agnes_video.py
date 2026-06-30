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

from core.api.rate_limiter import get_rate_limiter
from utils.video import download_video

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"
API_ROOT = "https://apihub.agnes-ai.com"

DURATION_PRESETS = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (409, 24),   # capped at 409 (API max for 720p); actual ~17s
    20: (409, 24),   # capped at 409 (API max for 720p); actual ~17s
}


class VideoOutput:
    def __init__(self, fmt: str, ext: str, data: str):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    def save(self, path: str) -> None:
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
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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
                    with open(url_file, "r") as f:
                        cache_data = json.loads(f.read())
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
                    cache_data = {"url": url, "ts": time.time()}
                    tmp_file = url_file + ".tmp"
                    with open(tmp_file, "w") as f:
                        json.dump(cache_data, f)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_file, url_file)
                except Exception as e:
                    logger.debug(f"[AgnesVideo] Failed to cache URL: {e}")
                return url
            logger.warning("[AgnesVideo] Image upload failed, falling back to base64.")
            return self._path_to_b64(ref)
        return ref

    async def _upload_image_to_url(self, image_path: str, retries: int = 3) -> Optional[str]:
        for attempt in range(retries):
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("[AgnesVideo] Image upload cancelled by shutdown")
                return None
            try:
                b64_data = self._path_to_b64(image_path)
                payload = {
                    "model": "agnes-image-2.1-flash",
                    "prompt": "Keep the image exactly as it is",
                    "n": 1,
                    "size": "1024x1024",
                    "extra_body": {
                        "response_format": "url",
                        "image": b64_data,
                    },
                }
                logger.info(f"[AgnesVideo] Uploading image to hosted URL (attempt {attempt + 1}/{retries})...")
                await asyncio.to_thread(get_rate_limiter().acquire)
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{BASE_URL}/images/generations",
                    headers=self.headers,
                    json=payload,
                    timeout=(30, 120),
                )
                if resp.status_code == 429:
                    delay = 30 * (attempt + 1)
                    logger.warning(f"[AgnesVideo] Image upload 429, retry in {delay}s...")
                    await asyncio.sleep(delay)
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
        curl_cmd = (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"{API_ROOT}/agnesapi?video_id={video_id}"'
        )
        while True:
            # M2: 每次轮询前检查停止信号
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_poll_duration:
                raise RuntimeError(
                    f"[AgnesVideo] Polling timed out after {max_poll_duration}s for video {video_id[:16]}"
                )

            try:
                if poll_count % 10 == 0:
                    logger.info(f"[AgnesVideo] Polling video {video_id[:16]}... (poll #{poll_count + 1}, elapsed {elapsed:.0f}s)")
                # 全局限速：每次轮询都消耗一个令牌
                await asyncio.to_thread(get_rate_limiter().acquire)
                # M2: 用 wait_for 包裹以支持取消
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.get,
                        f"{API_ROOT}/agnesapi?video_id={video_id}",
                        headers=self.headers,
                        timeout=15,
                    ),
                    timeout=30,
                )
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
                    raise RuntimeError(f"Video generation failed: {err}")
            except (requests.exceptions.RequestException, asyncio.TimeoutError) as e:
                consecutive_failures += 1
                logger.warning(
                    f"[AgnesVideo] Poll error ({consecutive_failures}/{max_consecutive_failures}): {e}"
                )
                if consecutive_failures >= max_consecutive_failures:
                    raise RuntimeError(
                        f"[AgnesVideo] Polling failed after {max_consecutive_failures} consecutive errors for video {video_id[:16]}"
                    )

            await asyncio.sleep(interval)

    async def _submit_with_retry(self, payload: dict, mode_desc: str) -> str:
        frame_reductions_left = 2  # allow up to 2 frame-count reductions on 400
        for attempt in range(self.max_retries):
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")
            try:
                logger.info(f"[AgnesVideo] Submitting {mode_desc} (attempt {attempt + 1}/{self.max_retries})...")
                # 全局限速：在发起提交请求前获取令牌
                await asyncio.to_thread(get_rate_limiter().acquire)
                # M2: 缩短读超时从 180s 到 60s，使 stop() 更快生效
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        f"{BASE_URL}/videos",
                        headers=self.headers,
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
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesVideo] 429 rate limit on {mode_desc}, "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 500:
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesVideo] {resp.status_code} server error on {mode_desc}, "
                        f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
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
                    payload["num_frames"] = new_nf
                    frame_reductions_left -= 1
                    continue

                logger.error(f"[AgnesVideo] HTTP {resp.status_code}: {error_text}")
                raise RuntimeError(f"Agnes video submit failed (HTTP {resp.status_code}): {error_text}")

            except (requests.exceptions.Timeout, asyncio.TimeoutError):
                delay = self.retry_base_delay * (attempt + 1)
                logger.warning(
                    f"[AgnesVideo] Timeout on {mode_desc}, "
                    f"retry {attempt + 1}/{self.max_retries} in {delay:.0f}s..."
                )
                await asyncio.sleep(delay)
                continue

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
            resolved_refs.append(await self._resolve_image_ref(p))
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

    async def wait_for_video(self, video_id: str, progress_callback=None) -> VideoOutput:
        final = await self._poll_task(video_id, progress_callback=progress_callback)

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
