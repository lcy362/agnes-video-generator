import logging

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


# B6: 下载安全限制（防写满磁盘）
_MAX_IMAGE_SIZE = 50 * 1024 * 1024  # 50 MB

# 下载重试退避间隔（秒）：此前无 wait，3 次重试会瞬间连续发起，加剧服务端压力
_DOWNLOAD_RETRY_WAIT_SECONDS = 3


@retry(stop=stop_after_attempt(3), wait=wait_fixed(_DOWNLOAD_RETRY_WAIT_SECONDS))
def download_image(url: str, save_path: str, max_size: int = _MAX_IMAGE_SIZE) -> None:
    logger.info(f"Downloading image from {url} to {save_path}")
    resp = requests.get(url, timeout=(30, 120), stream=True)
    resp.raise_for_status()
    # 优先检查 Content-Length
    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > max_size:
        raise ValueError(f"Image too large: {content_length} bytes > max {max_size} bytes")
    downloaded = 0
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            if downloaded > max_size:
                raise ValueError(f"Image exceeded max_size {max_size} bytes during download")
            f.write(chunk)
    logger.info(f"Image saved to {save_path} ({downloaded} bytes)")


def image_path_to_b64(image_path: str) -> str:
    import base64
    import mimetypes
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    return f"data:{mime};base64,{b64}"