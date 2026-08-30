"""core.api.agnes_image — Agnes Image API 封装（从 core/image_generator.py 迁移）"""

import asyncio
import base64
import logging
import mimetypes
import os
from typing import List, Optional

import requests

from core.api.error_collector import collect_error, collect_error_from_exception
from core.api.key_manager import get_key_ring
from core.api.rate_limiter import get_rate_limiter
from core.config import get_agnes_base_url
from utils.image import download_image
from utils.image_normalizer import normalize_reference_path

logger = logging.getLogger(__name__)

# 图像生成读超时基数（秒）：timeout = 基数 * (attempt + 1)，首次 120s 逐步放宽
_READ_TIMEOUT_BASE_SECONDS = 120


class ImageOutput:
    def __init__(self, fmt: str, ext: str, data: str):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    async def save(self, path: str) -> None:
        """保存图片到 path（异步）。

        优化路线图 0.3：URL 下载为同步 requests 流式读取，协程中直接调用会
        阻塞事件循环；整体下沉到线程池执行。
        """
        await asyncio.to_thread(self._save_sync, path)

    def _save_sync(self, path: str) -> None:
        """同步保存实现（供线程池调用；同步上下文可直接使用）。"""
        if self.fmt == "url":
            download_image(self.data, path)
        else:
            raw = self.data.split(",")[1] if "," in self.data else self.data
            with open(path, "wb") as f:
                f.write(base64.b64decode(raw))


class AgnesImageAPI:
    """Agnes Image 生成 API 封装（t2i / i2i）。"""

    def __init__(
        self,
        api_key: str,
        model: str = "agnes-image-2.1-flash",
        i2i_model: Optional[str] = None,
    ):
        """初始化图片 API。

        Args:
            api_key: Agnes API Key。
            model: t2i 默认模型。
            i2i_model: i2i 默认模型。默认与 ``model`` 相同（官方 agnes-image-2.1-flash
                同时支持 t2i 与 i2i）。如需回退到 2.0，可通过环境变量
                ``AGNES_IMAGE_I2I_MODEL`` 或显式传参覆盖。
        """
        self.api_key = api_key
        self.model = model
        # i2i 默认与 t2i 同模型（官方 2.1 同时支持 t2i/i2i）；环境变量可回退到 2.0。
        from core.config import get_settings
        env_i2i = get_settings().agnes_image_i2i_model
        self.i2i_model = i2i_model or env_i2i or model
        # 基础 headers（不含 Authorization）：每次请求前经 _auth_headers() 注入当前 Key
        self._base_headers = {
            "Content-Type": "application/json",
        }
        # 向后兼容：旧调用方可能读取 self.headers
        self.headers = dict(self._base_headers)

    def _auth_headers(self) -> dict:
        """每次请求前生成带当前 Key 的 headers 副本（从 KeyRing 轮转取 Key）。"""
        key = get_key_ring().next()
        h = dict(self._base_headers)
        h["Authorization"] = f"Bearer {key}"
        return h

    async def _path_to_b64(self, path: str) -> str:
        def _read():
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")

        b64 = await asyncio.to_thread(_read)
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    async def _resolve_image_ref(self, ref: str) -> str:
        if ref.startswith(("http://", "https://", "data:")):
            return ref
        if os.path.exists(ref):
            return await self._path_to_b64(ref)
        return ref

    async def generate_single_image(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        size: Optional[str] = None,
        max_retries: int = 4,
        retry_base_delay: float = 20.0,
        **kwargs,
    ) -> ImageOutput:
        use_i2i = len(reference_image_paths) > 0
        model = self.i2i_model if use_i2i else self.model
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "size": size or "1024x1024",
            "n": 1,
        }

        if kwargs.get("negative_prompt"):
            payload["negative_prompt"] = kwargs["negative_prompt"]

        if reference_image_paths:
            # 优化 2：入参处先归一化参考图（尺寸统一 + 体积压缩），再 resolve。
            # 目标尺寸从 size（"768x1152"）解析，失败回退 1024x1024。
            sw, sh = 1024, 1024
            try:
                parts = (size or "").lower().split("x")
                if len(parts) == 2:
                    sw, sh = int(parts[0]), int(parts[1])
            except (ValueError, TypeError):
                sw, sh = 1024, 1024
            normalized_paths = []
            for p in reference_image_paths:
                norm = await asyncio.to_thread(normalize_reference_path, p, sw, sh)
                normalized_paths.append(norm)
            resolved = [await self._resolve_image_ref(p) for p in normalized_paths]
            # 官方文档所有 i2i 示例均用 image 数组形式（extra_body.image=[url]），
            # 单图也统一传数组，保持与官方协议一致。
            payload["extra_body"] = {
                "response_format": "url",
                "image": resolved,
            }

        logger.info(f"[AgnesImage] Generating ({'i2i' if use_i2i else 't2i'}): {prompt[:80]}...")

        resp = None
        attempt = 0
        rotations = 0
        ring = get_key_ring()
        max_rotations = len(ring) * max_retries
        while attempt < max_retries:
            try:
                # 全局限速：在发起 HTTP 请求前获取令牌（2.3 异步原生）
                await get_rate_limiter().acquire_async()
                # 动态超时：第一次 120s，后续逐步增加（图像生成较慢，放宽读超时）
                read_timeout = _READ_TIMEOUT_BASE_SECONDS * (attempt + 1)
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{get_agnes_base_url()}/images/generations",
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=(30, read_timeout),
                )

                # 429 限流：多 Key 换 Key 立即重试；否则指数退避
                if resp.status_code == 429:
                    if ring.has_multiple() and rotations < max_rotations:
                        rotations += 1
                        ring.rotate()
                        logger.warning(
                            f"[KeyRotation] HTTP 429, 换 Key 立即重试 "
                            f"(image, rotation {rotations})"
                        )
                        continue
                    if attempt < max_retries - 1:
                        delay = retry_base_delay * (attempt + 1)
                        logger.warning(
                            f"[AgnesImage] 429 rate limit, "
                            f"retry {attempt + 1}/{max_retries} in {delay:.0f}s..."
                        )
                        collect_error(
                            "image", "generate_single_image",
                            prompt=prompt,
                            error_type="RateLimit429",
                            error_message="HTTP 429: rate limited",
                            status_code=429,
                            response_body=resp.text,
                            retry_count=attempt + 1,
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                        continue
                    # 退避耗尽：记录最终失败并抛出
                    collect_error(
                        "image", "generate_single_image",
                        prompt=prompt,
                        error_type="RateLimit429",
                        error_message="HTTP 429: retries exhausted",
                        status_code=429,
                        response_body=resp.text,
                        retry_count=max_retries,
                    )
                    resp.raise_for_status()
                    break

                # 5xx 服务端错误：退避重试
                if resp.status_code >= 500 and attempt < max_retries - 1:
                    delay = retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesImage] {resp.status_code} server error, "
                        f"retry {attempt + 1}/{max_retries} in {delay:.0f}s..."
                    )
                    collect_error(
                        "image", "generate_single_image",
                        prompt=prompt,
                        error_type=f"HTTP{resp.status_code}",
                        error_message=f"HTTP {resp.status_code}: server error",
                        status_code=resp.status_code,
                        response_body=resp.text,
                        retry_count=attempt + 1,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                if resp.status_code != 200:
                    logger.error(f"[AgnesImage] Non-retryable error: HTTP {resp.status_code}, body: {resp.text[:500]}")
                resp.raise_for_status()
                break

            except (requests.ConnectionError, requests.Timeout) as e:
                # 每次失败都记录（包括中间重试）
                collect_error_from_exception(
                    "image", "generate_single_image",
                    exc=e, prompt=prompt, retry_count=attempt + 1,
                )
                if attempt < max_retries - 1:
                    delay = retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesImage] {type(e).__name__}, "
                        f"retry {attempt + 1}/{max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise
        else:
            # 重试耗尽
            if resp is not None:
                logger.error(f"[AgnesImage] max retries exceeded, last response: {resp.status_code} {resp.text[:500]}")
                collect_error(
                    "image", "generate_single_image",
                    prompt=prompt,
                    error_type="HTTPError",
                    error_message=f"Max retries exceeded, last status: {resp.status_code}",
                    status_code=resp.status_code,
                    response_body=resp.text,
                    retry_count=max_retries,
                )
                resp.raise_for_status()
            logger.error(f"[AgnesImage] max retries ({max_retries}) exceeded with no response")
            collect_error(
                "image", "generate_single_image",
                prompt=prompt,
                error_type="RetriesExhausted",
                error_message=f"Max retries ({max_retries}) exceeded with no response",
                retry_count=max_retries,
            )
            raise RuntimeError(
                f"[AgnesImage] max retries ({max_retries}) exceeded"
            )

        result = resp.json()

        if "error" in result:
            err = result["error"]
            error_msg = f"Agnes image error: {err.get('message', err)}"
            collect_error(
                "image", "generate_single_image",
                prompt=prompt,
                error_type="APIError",
                error_message=error_msg,
                response_body=resp.text,
                retry_count=attempt + 1 if resp else max_retries,
            )
            raise RuntimeError(error_msg)

        data_list = result.get("data", [])
        if not data_list:
            collect_error(
                "image", "generate_single_image",
                prompt=prompt,
                error_type="NoDataError",
                error_message="Agnes image: no data returned",
                response_body=resp.text,
                retry_count=attempt + 1 if resp else max_retries,
            )
            raise RuntimeError("Agnes image: no data returned")

        url = data_list[0].get("url", "")
        if not url:
            b64_data = data_list[0].get("b64_json", "")
            if b64_data:
                logger.info("[AgnesImage] Got base64 response, saving...")
                return ImageOutput(fmt="b64", ext="png", data=b64_data)
            collect_error(
                "image", "generate_single_image",
                prompt=prompt,
                error_type="NoOutputError",
                error_message="Agnes image: no URL or base64 in response",
                response_body=resp.text,
                retry_count=attempt + 1 if resp else max_retries,
            )
            raise RuntimeError("Agnes image: no URL or base64 in response")

        logger.info(f"[AgnesImage] Done: {url[:80]}...")
        return ImageOutput(fmt="url", ext="png", data=url)
