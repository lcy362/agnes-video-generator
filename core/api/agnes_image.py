"""core.api.agnes_image — Agnes Image API 封装（从 core/image_generator.py 迁移）"""

import asyncio
import base64
import logging
import mimetypes
import os
import time
from typing import List, Optional

import requests

from core.api.rate_limiter import get_rate_limiter
from utils.image import download_image

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"


class ImageOutput:
    def __init__(self, fmt: str, ext: str, data: str):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    def save(self, path: str) -> None:
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
        env_i2i = os.environ.get("AGNES_IMAGE_I2I_MODEL")
        self.i2i_model = i2i_model or env_i2i or model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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
        max_retries: int = 3,
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
            resolved = [await self._resolve_image_ref(p) for p in reference_image_paths]
            # 官方文档所有 i2i 示例均用 image 数组形式（extra_body.image=[url]），
            # 单图也统一传数组，保持与官方协议一致。
            payload["extra_body"] = {
                "response_format": "url",
                "image": resolved,
            }

        logger.info(f"[AgnesImage] Generating ({'i2i' if use_i2i else 't2i'}): {prompt[:80]}...")

        resp = None
        for attempt in range(max_retries):
            try:
                # 全局限速：在发起 HTTP 请求前获取令牌
                await asyncio.to_thread(get_rate_limiter().acquire)
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{BASE_URL}/images/generations",
                    headers=self.headers,
                    json=payload,
                    timeout=(30, 120),
                )

                # 429 限流：退避重试
                if resp.status_code == 429 and attempt < max_retries - 1:
                    delay = retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesImage] 429 rate limit, "
                        f"retry {attempt + 1}/{max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                # 5xx 服务端错误：退避重试
                if resp.status_code >= 500 and attempt < max_retries - 1:
                    delay = retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesImage] {resp.status_code} server error, "
                        f"retry {attempt + 1}/{max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code != 200:
                    logger.error(f"[AgnesImage] Non-retryable error: HTTP {resp.status_code}, body: {resp.text[:500]}")
                resp.raise_for_status()
                break

            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt < max_retries - 1:
                    delay = retry_base_delay * (attempt + 1)
                    logger.warning(
                        f"[AgnesImage] {type(e).__name__}, "
                        f"retry {attempt + 1}/{max_retries} in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        else:
            # 重试耗尽
            if resp is not None:
                logger.error(f"[AgnesImage] max retries exceeded, last response: {resp.status_code} {resp.text[:500]}")
                resp.raise_for_status()
            logger.error(f"[AgnesImage] max retries ({max_retries}) exceeded with no response")
            raise RuntimeError(
                f"[AgnesImage] max retries ({max_retries}) exceeded"
            )

        result = resp.json()

        if "error" in result:
            err = result["error"]
            raise RuntimeError(f"Agnes image error: {err.get('message', err)}")

        data_list = result.get("data", [])
        if not data_list:
            raise RuntimeError("Agnes image: no data returned")

        url = data_list[0].get("url", "")
        if not url:
            b64_data = data_list[0].get("b64_json", "")
            if b64_data:
                logger.info("[AgnesImage] Got base64 response, saving...")
                return ImageOutput(fmt="b64", ext="png", data=b64_data)
            raise RuntimeError("Agnes image: no URL or base64 in response")

        logger.info(f"[AgnesImage] Done: {url[:80]}...")
        return ImageOutput(fmt="url", ext="png", data=url)
