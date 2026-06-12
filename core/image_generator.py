import asyncio
import base64
import logging
import mimetypes
import os
from typing import List, Optional
import requests
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


class ImageGeneratorAgnesAPI:
    def __init__(self, api_key: str, model: str = "agnes-image-2.1-flash"):
        self.api_key = api_key
        self.model = model
        self.i2i_model = "agnes-image-2.0-flash"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _path_to_b64(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    def _resolve_image_ref(self, ref: str) -> str:
        if ref.startswith(("http://", "https://", "data:")):
            return ref
        if os.path.exists(ref):
            return self._path_to_b64(ref)
        return ref

    async def generate_single_image(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        size: Optional[str] = None,
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

        if reference_image_paths:
            resolved = [self._resolve_image_ref(p) for p in reference_image_paths]
            extra_body: dict = {"response_format": "url"}
            if len(resolved) == 1:
                extra_body["image"] = resolved[0]
            else:
                extra_body["image"] = resolved
            payload["extra_body"] = extra_body

        logger.info(f"[Agnes Image] Generating ({'i2i' if use_i2i else 't2i'}): {prompt[:80]}...")

        try:
            resp = await asyncio.to_thread(
                requests.post,
                f"{BASE_URL}/images/generations",
                headers=self.headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = resp.text[:500]
            except Exception:
                pass
            logger.error(f"[Agnes Image] HTTP {resp.status_code}: {error_detail}")
            raise

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
                logger.info("[Agnes Image] Got base64 response, saving...")
                return ImageOutput(fmt="b64", ext="png", data=b64_data)
            raise RuntimeError("Agnes image: no URL or base64 in response")

        logger.info(f"[Agnes Image] Done: {url[:80]}...")
        return ImageOutput(fmt="url", ext="png", data=url)