import logging
import requests
from tenacity import retry, stop_after_attempt

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3))
def download_image(url: str, save_path: str) -> None:
    logger.info(f"Downloading image from {url} to {save_path}")
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Image saved to {save_path}")


def image_path_to_b64(image_path: str) -> str:
    import base64, mimetypes
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    return f"data:{mime};base64,{b64}"