"""utils 层覆盖率补测：image_normalizer / image / video

纯逻辑/文件级单测，不触网（网络调用均 mock requests）。仅依赖 PIL（已装）。

用法:
    .venv/bin/python -m pytest tests/test_utils_coverage.py -q
"""

import sys
import os
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from tenacity import RetryError

from utils import image, video
from utils import image_normalizer
from utils.image_normalizer import (
    PAD,
    COVER,
    normalize_image,
    normalize_image_async,
    normalize_reference_path,
)


# ═══════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════

def _make_png(path, width, height, color=(200, 30, 30)):
    from PIL import Image
    im = Image.new("RGBA", (width, height), color + (255,))
    # 加一个半透明角落，验证透明背景合成
    im.putpixel((width - 1, height - 1), (10, 200, 10, 0))
    im.save(path, "PNG")
    return path


def _make_palette_png(path, width, height):
    from PIL import Image
    im = Image.new("P", (width, height), 0)
    im.putpalette([200, 30, 30, 10, 200, 10] + [0, 0, 0] * 253)
    im.save(path, "PNG")
    return path


@pytest.fixture
def src_png(tmp_path):
    return _make_png(str(tmp_path / "src.png"), 120, 80)


# ═══════════════════════════════════════════════
# normalize_image
# ═══════════════════════════════════════════════

class TestNormalizeImage:
    def test_pad_strategy_same_size_reuse(self, src_png, tmp_path):
        """源图已是目标尺寸且格式匹配 → 直接复用源路径，不写新文件。"""
        out = normalize_image(src_png, 120, 80, strategy=PAD)
        assert out == src_png

    def test_pad_downscale(self, src_png, tmp_path):
        dst = str(tmp_path / "pad.jpg")
        out = normalize_image(src_png, 60, 40, dst=dst, strategy=PAD)
        assert out == dst
        from PIL import Image as PILImage
        with PILImage.open(dst) as im:
            assert im.size == (60, 40)

    def test_cover_up_crop(self, src_png, tmp_path):
        """COVER 策略等比放大后居中裁剪填满目标尺寸。"""
        dst = str(tmp_path / "cover.jpg")
        out = normalize_image(src_png, 60, 60, dst=dst, strategy=COVER)
        assert out == dst
        from PIL import Image as PILImage
        with PILImage.open(dst) as im:
            assert im.size == (60, 60)

    def test_png_format_no_alpha_issue(self, src_png, tmp_path):
        dst = str(tmp_path / "out.png")
        out = normalize_image(src_png, 50, 50, dst=dst, fmt="PNG")
        from PIL import Image as PILImage
        with PILImage.open(dst) as im:
            assert im.format == "PNG"
            assert im.size == (50, 50)

    def test_no_dst_auto_generate(self, src_png, tmp_path):
        """dst=None → 同目录生成 {stem}_norm.jpg。"""
        out = normalize_image(src_png, 30, 30, strategy=PAD)
        base = os.path.basename(out)
        assert base == "src_norm.jpg"
        assert out.startswith(os.path.dirname(src_png))

    def test_cache_hit_returns_dst(self, src_png, tmp_path):
        """目标文件已存在且非空 → 缓存复用直接返回。"""
        dst = str(tmp_path / "cached.jpg")
        with open(dst, "wb") as f:
            f.write(b"fake-cache")
        out = normalize_image(src_png, 60, 60, dst=dst)
        assert out == dst
        assert open(dst, "rb").read() == b"fake-cache"  # 未被覆盖

    def test_palette_image_normalized(self, tmp_path):
        """P 模式索引图也应能归一化（RGBA 转换）。"""
        src = _make_palette_png(str(tmp_path / "palette.png"), 100, 100)
        dst = str(tmp_path / "palette_out.jpg")
        out = normalize_image(src, 40, 40, dst=dst)
        from PIL import Image as PILImage
        with PILImage.open(out) as im:
            assert im.size == (40, 40)

    def test_pillow_missing_raises(self, src_png, tmp_path, monkeypatch):
        """Pillow 不可用 → 抛 OSError。"""
        monkeypatch.setattr(image_normalizer, "Image", None)
        with pytest.raises(OSError, match="Pillow"):
            normalize_image(src_png, 60, 60)

    def test_async_normalize(self, src_png, tmp_path):
        dst = str(tmp_path / "async.jpg")
        out = asyncio.run(normalize_image_async(src_png, 32, 32, dst=dst, strategy=PAD))
        assert out == dst


# ═══════════════════════════════════════════════
# normalize_reference_path
# ═══════════════════════════════════════════════

class TestNormalizeReferencePath:
    def test_non_local_passthrough(self):
        for ref in ("http://a.com/1.png", "https://a.com/1.png", "data:image/png;base64,xx"):
            assert normalize_reference_path(ref, 60, 60) == ref

    def test_nonexistent_passthrough(self):
        assert normalize_reference_path("/no/such/file.png", 60, 60) == "/no/such/file.png"

    def test_success_normalizes(self, src_png, tmp_path):
        out = normalize_reference_path(src_png, 40, 40, strategy=PAD, dst=str(tmp_path / "r.jpg"))
        assert out == str(tmp_path / "r.jpg")

    def test_failure_falls_back(self, tmp_path, monkeypatch):
        """归一化抛异常 → 返回原路径，不抛。"""
        src = str(tmp_path / "bad.png")
        with open(src, "wb") as f:
            f.write(b"not an image")
        monkeypatch.setattr(image_normalizer, "normalize_image", lambda **kw: (_ for _ in ()).throw(OSError("bad")))
        assert normalize_reference_path(src, 40, 40) == src


# ═══════════════════════════════════════════════
# download_image / download_video / image_path_to_b64
# ═══════════════════════════════════════════════

class _FakeResp:
    def __init__(self, chunks=b"0123456789", headers=None, status=200):
        self._chunks = chunks
        self.headers = headers or {}
        self._raise = None
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._chunks), chunk_size):
            yield self._chunks[i:i + chunk_size]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """屏蔽真实 sleep：避免 download_* 的 tenacity 重试退避（3s×3）拖慢测试。"""
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


class TestDownloadImage:
    def test_download_success(self, tmp_path, monkeypatch):
        resp = _FakeResp(chunks=b"abcde", headers={"Content-Length": "5"})
        monkeypatch.setattr(image.requests, "get", lambda *a, **k: resp)
        dest = str(tmp_path / "img.bin")
        image.download_image("http://x/1.png", dest)
        assert open(dest, "rb").read() == b"abcde"

    def test_download_content_length_too_large(self, tmp_path, monkeypatch):
        resp = _FakeResp(chunks=b"", headers={"Content-Length": "999999999"})
        monkeypatch.setattr(image.requests, "get", lambda *a, **k: resp)
        with pytest.raises(RetryError) as e:
            image.download_image("http://x/1.png", str(tmp_path / "x.png"), max_size=10)
        exc = e.value.last_attempt.exception()
        assert isinstance(exc, ValueError) and "too large" in str(exc)

    def test_download_exceeds_during_stream(self, tmp_path, monkeypatch):
        resp = _FakeResp(chunks=b"0123456789" * 10, headers={})
        monkeypatch.setattr(image.requests, "get", lambda *a, **k: resp)
        with pytest.raises(RetryError) as e:
            image.download_image("http://x/1.png", str(tmp_path / "x.png"), max_size=50)
        exc = e.value.last_attempt.exception()
        assert isinstance(exc, ValueError) and "exceeded max_size" in str(exc)


class TestDownloadVideo:
    def test_download_success(self, tmp_path, monkeypatch):
        resp = _FakeResp(chunks=b"123456", headers={"Content-Length": "6"})
        monkeypatch.setattr(video.requests, "get", lambda *a, **k: resp)
        dest = str(tmp_path / "v.bin")
        video.download_video("http://x/v.mp4", dest)
        assert open(dest, "rb").read() == b"123456"

    def test_download_content_length_too_large(self, tmp_path, monkeypatch):
        resp = _FakeResp(chunks=b"", headers={"Content-Length": "999999999"})
        monkeypatch.setattr(video.requests, "get", lambda *a, **k: resp)
        with pytest.raises(RetryError) as e:
            video.download_video("http://x/v.mp4", str(tmp_path / "v.mp4"), max_size=100)
        exc = e.value.last_attempt.exception()
        assert isinstance(exc, ValueError) and "too large" in str(exc)


class TestImagePathToB64:
    def test_png(self, tmp_path):
        p = _make_png(str(tmp_path / "a.png"), 10, 10)
        out = image.image_path_to_b64(p)
        assert out.startswith("data:image/png;base64,")
        import base64
        raw = base64.b64decode(out.split(",", 1)[1])
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"

    def test_unknown_mime_defaults_png(self, tmp_path):
        p = tmp_path / "noext"
        p.write_bytes(b"data")
        out = image.image_path_to_b64(str(p))
        assert out.startswith("data:image/png;base64,")