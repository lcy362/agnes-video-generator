import logging
import requests
from tenacity import retry, stop_after_attempt

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3))
def download_video(url: str, save_path: str) -> None:
    logger.info(f"Downloading video from {url} to {save_path}")
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Video saved to {save_path}")