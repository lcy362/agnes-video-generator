import asyncio
import base64
import logging
import mimetypes
import os
from typing import List, Optional
import requests
from utils.video import download_video

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"
API_ROOT = "https://apihub.agnes-ai.com"

DURATION_PRESETS = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (441, 24),
    20: (441, 22),
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


class VideoGeneratorAgnesAPI:
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
            if os.path.exists(url_file):
                try:
                    with open(url_file, "r") as f:
                        cached_url = f.read().strip()
                    if cached_url:
                        logger.info(f"[Agnes Video] Using cached hosted URL: {cached_url[:80]}...")
                        return cached_url
                except Exception:
                    pass
            url = await self._upload_image_to_url(ref)
            if url:
                try:
                    tmp_file = url_file + ".tmp"
                    with open(tmp_file, "w") as f:
                        f.write(url)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_file, url_file)
                except Exception:
                    pass
                return url
            logger.warning("[Agnes Video] Image upload failed, falling back to base64.")
            return self._path_to_b64(ref)
        return ref

    async def _upload_image_to_url(self, image_path: str, retries: int = 3) -> Optional[str]:
        for attempt in range(retries):
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.info("[Agnes Video] Image upload cancelled by shutdown")
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
                logger.info(f"[Agnes Video] Uploading image to hosted URL (attempt {attempt+1}/{retries})...")
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{BASE_URL}/images/generations",
                    headers=self.headers,
                    json=payload,
                    timeout=(30, 120),
                )
                if resp.status_code == 429:
                    delay = 30 * (attempt + 1)
                    logger.warning(f"[Agnes Video] Image upload 429, retry in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                result = resp.json()
                data_list = result.get("data", [])
                if data_list:
                    url = data_list[0].get("url", "")
                    if url:
                        logger.info(f"[Agnes Video] Image uploaded to hosted URL: {url[:80]}...")
                        return url
            except Exception as e:
                logger.warning(f"[Agnes Video] Image upload attempt {attempt+1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(15)
        return None

    def _get_frame_config(self, duration: Optional[int] = None) -> tuple:
        d = duration or self.default_duration
        if d in DURATION_PRESETS:
            return DURATION_PRESETS[d]
        best = None
        for nf in range(9, 442, 8):
            fr = round(nf / d)
            if 1 <= fr <= 60:
                best = (nf, fr)
        return best or DURATION_PRESETS[5]

    async def _poll_task(self, video_id: str, interval: int = 15, progress_callback=None) -> dict:
        last_status = ""
        poll_count = 0
        curl_cmd = (
            f'curl -s -H "Authorization: Bearer $AGNES_API_KEY" '
            f'"{API_ROOT}/agnesapi?video_id={video_id}"'
        )
        while True:
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")
            try:
                if poll_count % 10 == 0:
                    logger.info(f"[Agnes Video] Polling video {video_id[:16]}... (poll #{poll_count+1})")
                resp = await asyncio.to_thread(
                    requests.get,
                    f"{API_ROOT}/agnesapi?video_id={video_id}",
                    headers=self.headers,
                    timeout=15,
                )
                resp.raise_for_status()
                result = resp.json()
                status = result.get("status", "")
                progress = result.get("progress", 0)
                poll_count += 1

                if status != last_status:
                    logger.info(f"[Agnes Video] Video {video_id[:16]}... status={status} progress={progress}%")
                    last_status = status

                if progress_callback:
                    progress_callback(status, progress, curl_cmd)

                if status in ("completed", "COMPLETED"):
                    return result

                if status in ("failed", "FAILED"):
                    err = result.get("error") or "unknown error"
                    raise RuntimeError(f"Video generation failed: {err}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"[Agnes Video] Poll error: {e}")

            await asyncio.sleep(interval)

    async def _submit_with_retry(self, payload: dict, mode_desc: str) -> str:
        for attempt in range(self.max_retries):
            if self.shutdown_event and self.shutdown_event.is_set():
                raise RuntimeError("Video generation cancelled by user")
            try:
                logger.info(f"[Agnes Video] Submitting {mode_desc} (attempt {attempt+1}/{self.max_retries})...")
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{BASE_URL}/videos",
                    headers=self.headers,
                    json=payload,
                    timeout=(30, 120),
                )

                if resp.status_code == 200:
                    result = resp.json()
                    video_id = result.get("video_id") or result.get("task_id") or result.get("id")
                    if video_id:
                        return video_id

                if resp.status_code == 429:
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[Agnes Video] 429 rate limit on {mode_desc}, "
                        f"retry {attempt+1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 500:
                    delay = self.retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[Agnes Video] {resp.status_code} server error on {mode_desc}, "
                        f"retry {attempt+1}/{self.max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                error_detail = resp.text[:500]
                logger.error(f"[Agnes Video] HTTP {resp.status_code}: {error_detail}")
                raise RuntimeError(f"Agnes video submit failed (HTTP {resp.status_code}): {error_detail}")

            except requests.exceptions.Timeout:
                delay = self.retry_base_delay * (attempt + 1)
                logger.warning(
                    f"[Agnes Video] Timeout on {mode_desc}, "
                    f"retry {attempt+1}/{self.max_retries} in {delay:.0f}s..."
                )
                await asyncio.sleep(delay)
                continue

        raise RuntimeError(
            f"[Agnes Video] {mode_desc}: max retries ({self.max_retries}) exceeded"
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
        num_frames, frame_rate = self._get_frame_config(duration)

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

        logger.info(f"[Agnes Video] {mode_desc}: {prompt[:80]}...")

        video_id = await self._submit_with_retry(payload, mode_desc)
        logger.info(f"[Agnes Video] Video submitted: {video_id[:20]}...")
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

        logger.info(f"[Agnes Video] Done: {video_url[:80]}...")
        return VideoOutput(fmt="url", ext="mp4", data=video_url)