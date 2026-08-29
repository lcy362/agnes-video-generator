import logging

import requests
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


# B6: 下载安全限制（防写满磁盘）
_MAX_VIDEO_SIZE = 500 * 1024 * 1024  # 500 MB

# 下载重试退避间隔（秒）：此前无 wait，3 次重试会瞬间连续发起，加剧服务端压力
_DOWNLOAD_RETRY_WAIT_SECONDS = 3


@retry(stop=stop_after_attempt(3), wait=wait_fixed(_DOWNLOAD_RETRY_WAIT_SECONDS))
def download_video(url: str, save_path: str, max_size: int = _MAX_VIDEO_SIZE) -> None:
    logger.info(f"Downloading video from {url} to {save_path}")
    resp = requests.get(url, timeout=(30, 300), stream=True)
    resp.raise_for_status()
    # 优先检查 Content-Length
    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > max_size:
        raise ValueError(f"Video too large: {content_length} bytes > max {max_size} bytes")
    downloaded = 0
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            if downloaded > max_size:
                raise ValueError(f"Video exceeded max_size {max_size} bytes during download")
            f.write(chunk)
    logger.info(f"Video saved to {save_path} ({downloaded} bytes)")