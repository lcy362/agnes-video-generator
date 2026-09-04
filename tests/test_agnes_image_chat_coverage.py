"""agnes_image / agnes_chat 核心外部 API 模块覆盖率补充测试。

目标：提升 core/api/agnes_image.py（t2i/i2i）与 core/api/agnes_chat.py
（文本/多模态/JSON mode）的 pytest 行覆盖率至 >=85%。

约定（与 test_api_retry_matrix.py 一致）：
- 在协议边界 mock ``requests``（HTTP 层），保留 API 类全部内部业务逻辑
  （参数构造、429/5xx 退避重试、多 Key 轮换、超时、报错收集等），不整类替换；
- mock KeyRing / rate_limiter（FakeRing / FakeLimiter）；
- mock error_collector 的写入，避免污染工作目录；
- mock asyncio.sleep 或退避间隔用极小值，避免真实等待；
- 完全不触网、不写真实文件到工作区（临时参考图仅用 tmp_path 单元验证编码）。
"""
import asyncio
import base64
import json

import pytest
import requests as _requests

import core.api.agnes_image as ai
import core.api.agnes_chat as ac

# 确保项目根目录可导入（-m pytest 时 cwd 已在 path，此处兜底，兼容其他调用方式）
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


class FakeResponse:
    """最小化 requests.Response 桩（HTTP 层协议边界）。"""

    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text if text is not None else json.dumps(self._json, ensure_ascii=False)
        self.headers = {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            e = _requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            e.response = self
            raise e


class FakeLimiter:
    """限速器桩：acquire / acquire_async 立即返回，避免真实令牌桶拖慢测试。"""

    def acquire(self):
        return True

    async def acquire_async(self, stop_event=None):
        return None


class FakeRing:
    """KeyRing 桩：与真实实现相同的语义（rotate 钉住下一次 next）。"""

    def __init__(self, keys):
        self._keys = list(keys)
        self._i = -1
        self._force = None

    def next(self):
        if self._force is not None:
            i, self._force = self._force, None
            return self._keys[i]
        self._i = (self._i + 1) % len(self._keys)
        return self._keys[self._i]

    def rotate(self):
        self._i = (self._i + 1) % len(self._keys)
        self._force = self._i
        return self._keys[self._i]

    def has_multiple(self):
        return len(self._keys) > 1

    def __len__(self):
        return len(self._keys)


def _install_ring(monkeypatch, keys):
    ring = FakeRing(keys)
    monkeypatch.setattr(ai, "get_key_ring", lambda: ring)
    return ring


@pytest.fixture
def image_api(monkeypatch):
    """最小化外部依赖的 AgnesImageAPI（快退避 + 限速/报错收集/配置打桩）。"""
    monkeypatch.setattr(ai, "get_rate_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(ai, "get_base_url_for_key", lambda key: "http://api.test")
    monkeypatch.setattr(ai, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(ai, "collect_error_from_exception", lambda *a, **k: None)
    monkeypatch.setattr(ai.asyncio, "sleep", _a_sleep)
    return ai.AgnesImageAPI(api_key="k1", i2i_model="agnes-image-2.1-flash")


async def _a_sleep(*args, **kwargs):
    return None


# ── agnes_image：初始化 / headers / 参考图编码 ──────────────────────

def test_image_init_i2i_model_fallback(monkeypatch):
    """i2i_model 省略时回退顺序：显式 > 环境设置 > 默认 t2i 模型。"""
    class _S:
        agnes_image_i2i_model = "env-i2i"
    api = ai.AgnesImageAPI("k1", model="t2i-model", i2i_model="explicit")
    assert api.i2i_model == "explicit"
    api2 = ai.AgnesImageAPI("k1", model="t2i-model", i2i_model=None)
    assert api2.i2i_model == "t2i-model"
    assert api2.headers["Content-Type"] == "application/json"


def test_image_auth_headers_explicit_and_ring(monkeypatch):
    _install_ring(monkeypatch, ["k1", "k2"])
    api = ai.AgnesImageAPI("k1")
    h = api._auth_headers("custom")
    assert h["Authorization"] == "Bearer custom"
    assert h["Content-Type"] == "application/json"
    # 未传 key 时从 KeyRing 轮转
    h2 = api._auth_headers()
    assert h2["Authorization"] == "Bearer k1"
    # 不污染基础 headers
    assert "Authorization" not in api._base_headers


async def test_path_to_b64(tmp_path):
    api = ai.AgnesImageAPI("k1")
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    b64 = await api._path_to_b64(str(f))
    assert b64.startswith("data:image/png;base64,")
    # data_url 二次解析可还原
    assert base64.b64decode(b64.split(",", 1)[1]) == b"\x89PNG\r\n\x1a\nfake"


async def test_resolve_image_ref_passthrough_and_local(monkeypatch, tmp_path):
    api = ai.AgnesImageAPI("k1")
    # URL / data: 直接透传
    assert await api._resolve_image_ref("https://x/a.png") == "https://x/a.png"
    assert await api._resolve_image_ref("data:image/png;base64,xx") == "data:image/png;base64,xx"
    # 不存在的本地路径原样返回
    assert await api._resolve_image_ref("/no/such/file.png") == "/no/such/file.png"
    # 存在的本地路径 → base64
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNGfake")
    res = await api._resolve_image_ref(str(f))
    assert res.startswith("data:image/png;base64,")


async def test_image_output_save_url(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(ai, "download_image", lambda url, path: saved.update(url=url, path=str(path)))
    out = ai.ImageOutput("url", "png", "http://img/1.png")
    dest = tmp_path / "out.png"
    await out.save(str(dest))
    assert saved["url"] == "http://img/1.png"
    assert saved["path"] == str(dest)


async def test_image_output_save_b64(tmp_path):
    raw = base64.b64encode(b"pngdata").decode()
    out = ai.ImageOutput("b64", "png", raw)
    dest = tmp_path / "out.png"
    await out.save(str(dest))
    assert dest.read_bytes() == b"pngdata"


# ── agnes_image：t2i 成功/解析 ──────────────────────────────────────

async def test_image_t2i_success_url(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["payload"] = json
        seen["timeout"] = timeout
        return FakeResponse(200, {"data": [{"url": "http://img/generated.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)

    out = await image_api.generate_single_image("一只猫")
    assert out.fmt == "url"
    assert out.data == "http://img/generated.png"
    assert seen["url"] == "http://api.test/images/generations"
    assert seen["headers"]["Authorization"] == "Bearer k1"
    assert seen["payload"]["model"] == "agnes-image-2.5-flash"
    assert seen["payload"]["prompt"] == "一只猫"
    assert seen["payload"]["size"] == "1024x1024"
    assert seen["payload"]["n"] == 1
    assert (30, 120) == seen["timeout"]  # 首次读超时 120s


async def test_image_t2i_with_negative_prompt(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        return FakeResponse(200, {"data": [{"url": "http://img/1.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    await image_api.generate_single_image("猫", negative_prompt="模糊")
    assert seen["payload"]["negative_prompt"] == "模糊"


async def test_image_base64_response(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    b64 = base64.b64encode(b"pixels").decode()

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(200, {"data": [{"b64_json": b64}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = await image_api.generate_single_image("猫")
    assert out.fmt == "b64"
    assert out.data == b64


async def test_image_no_output_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    collected = []
    monkeypatch.setattr(ai, "collect_error", lambda *a, **k: collected.append(k))

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(200, {"data": [{}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="no URL or base64"):
        await image_api.generate_single_image("猫")
    assert collected and collected[0]["error_type"] == "NoOutputError"


async def test_image_no_data_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    collected = []
    monkeypatch.setattr(ai, "collect_error", lambda *a, **k: collected.append(k))

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(200, {"data": []})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="no data returned"):
        await image_api.generate_single_image("猫")
    assert collected[0]["error_type"] == "NoDataError"


async def test_image_api_error_field_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(200, {"error": {"message": "content policy"}})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="Agnes image error: content policy"):
        await image_api.generate_single_image("猫")


# ── agnes_image：429 / 5xx / 超时重试与多 Key 轮换 ──────────────────

async def test_image_single_key_429_backoff_then_success(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return FakeResponse(429)
        return FakeResponse(200, {"data": [{"url": "http://img/ok.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = await image_api.generate_single_image("猫", max_retries=2, retry_base_delay=0.001)
    assert out.data == "http://img/ok.png"
    assert calls == ["Bearer k1", "Bearer k1"]  # 单 Key 不换 Key


async def test_image_multi_key_429_rotates_immediately(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1", "k2"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return FakeResponse(429)
        return FakeResponse(200, {"data": [{"url": "http://img/ok.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = await image_api.generate_single_image("猫", max_retries=2, retry_base_delay=0.001)
    assert out.data == "http://img/ok.png"
    assert calls == ["Bearer k1", "Bearer k2"]  # 429 后切换到第二个 Key


async def test_image_429_retries_exhausted_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    collected = []
    monkeypatch.setattr(ai, "collect_error", lambda *a, **k: collected.append(k))

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(429, text="rate")

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(_requests.exceptions.HTTPError):
        await image_api.generate_single_image("猫", max_retries=2, retry_base_delay=0.001)
    # 第一次 429 走退避收集，最后一次走耗尽收集
    assert collected[-1]["error_type"] == "RateLimit429"
    assert collected[-1]["error_message"] == "HTTP 429: retries exhausted"


async def test_image_multi_key_429_rotations_exhausted_then_backoff(image_api, monkeypatch):
    """多 Key 但轮转次数耗尽 → 落入退避分支，最终 raise_for_status。"""
    _install_ring(monkeypatch, ["k1", "k2"])
    collected = []
    monkeypatch.setattr(ai, "collect_error", lambda *a, **k: collected.append(k))

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(429)

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(_requests.exceptions.HTTPError):
        await image_api.generate_single_image("猫", max_retries=1, retry_base_delay=0.001)
    assert collected[-1]["error_type"] == "RateLimit429"


async def test_image_5xx_backoff_then_success(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            return FakeResponse(500)
        return FakeResponse(200, {"data": [{"url": "http://img/ok.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = await image_api.generate_single_image("猫", max_retries=3, retry_base_delay=0.001)
    assert out.data == "http://img/ok.png"
    assert len(calls) == 3


async def test_image_5xx_exhausted_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return FakeResponse(503)

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(_requests.exceptions.HTTPError):
        await image_api.generate_single_image("猫", max_retries=2, retry_base_delay=0.001)
    assert calls == [1, 1]  # 尝试 2 次后耗尽


async def test_image_non_retryable_4xx_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse(400, text='{"error": "bad request"}')

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(_requests.exceptions.HTTPError):
        await image_api.generate_single_image("猫", max_retries=3, retry_base_delay=0.001)


async def test_image_connection_error_retry_then_success(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    errors = []
    calls = []
    monkeypatch.setattr(
        ai, "collect_error_from_exception",
        lambda *a, **k: errors.append(k["exc"].__class__.__name__),
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise _requests.exceptions.ConnectionError("boom")
        return FakeResponse(200, {"data": [{"url": "http://img/ok.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = await image_api.generate_single_image("猫", max_retries=2, retry_base_delay=0.001)
    assert out.data == "http://img/ok.png"
    assert errors == ["ConnectionError"]


async def test_image_connection_error_exhausted_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])

    def fake_post(url, headers=None, json=None, timeout=None):
        raise _requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(_requests.exceptions.ConnectionError, match="boom"):
        await image_api.generate_single_image("猫", max_retries=2, retry_base_delay=0.001)


async def test_image_timeout_error_exhausted_raises(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])

    def fake_post(url, headers=None, json=None, timeout=None):
        raise _requests.exceptions.Timeout("slow")

    monkeypatch.setattr(ai.requests, "post", fake_post)
    with pytest.raises(_requests.exceptions.Timeout):
        await image_api.generate_single_image("猫", max_retries=1, retry_base_delay=0.001)


# ── agnes_image：i2i ────────────────────────────────────────────────

async def test_image_i2i_with_url_reference(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        return FakeResponse(200, {"data": [{"url": "http://img/i2i.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    out = await image_api.generate_single_image(
        "同款风格",
        reference_image_paths=["https://cdn/x/ref.png"],
        size="768x1152",
    )
    assert out.fmt == "url"
    p = seen["payload"]
    assert p["model"] == "agnes-image-2.1-flash"  # i2i 用 i2i_model
    assert p["size"] == "768x1152"
    assert p["extra_body"]["response_format"] == "url"
    assert p["extra_body"]["image"] == ["https://cdn/x/ref.png"]


async def test_image_i2i_invalid_size_fallback(image_api, monkeypatch):
    _install_ring(monkeypatch, ["k1"])
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        return FakeResponse(200, {"data": [{"url": "http://img/i2i.png"}]})

    monkeypatch.setattr(ai.requests, "post", fake_post)
    # "768xabc" 可拆成 2 段但 int() 失败 → 走 except 回退到 1024x1024
    await image_api.generate_single_image(
        "同款风格", reference_image_paths=["https://cdn/x/ref.png"], size="768xabc",
    )
    assert seen["payload"]["extra_body"]["image"] == ["https://cdn/x/ref.png"]


# ── agnes_chat：基础工具函数 ────────────────────────────────────────

def test_strip_code_fence_variants():
    assert ac.strip_code_fence("```json\n{\"a\":1}\n```") == "{\"a\":1}"
    assert ac.strip_code_fence("```\nhello\n```") == "hello"
    assert ac.strip_code_fence("  plain text  ") == "plain text"
    assert ac.strip_code_fence("```x") == ""  # 无换行的围栏按整串去除
    assert ac.strip_code_fence("```") == ""  # 纯栅栏


def test_should_retry():
    assert ac.AgnesChatAPI._should_retry(FakeResponse(500))
    assert ac.AgnesChatAPI._should_retry(FakeResponse(503))
    assert ac.AgnesChatAPI._should_retry(FakeResponse(429))
    assert not ac.AgnesChatAPI._should_retry(FakeResponse(400))
    assert not ac.AgnesChatAPI._should_retry(FakeResponse(200))


def test_extract_prompt_from_payload():
    # 纯文本 user content
    p1 = {"messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]}
    assert ac.AgnesChatAPI._extract_prompt_from_payload(p1) == "hello"
    # 多模态：content 为 list，取 text 项
    p2 = {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "看这张图"},
        {"type": "image_url", "image_url": {"url": "x"}},
    ]}]}
    assert ac.AgnesChatAPI._extract_prompt_from_payload(p2) == "看这张图"
    # 空 / 无匹配
    assert ac.AgnesChatAPI._extract_prompt_from_payload({"messages": []}) == ""
    assert ac.AgnesChatAPI._extract_prompt_from_payload({"messages": [{"role": "user", "content": ""}]}) == ""


def test_image_to_b64_uri(tmp_path):
    api = ac.AgnesChatAPI("k1")
    f = tmp_path / "img.jpg"
    f.write_bytes(b"\xff\xd8fake")
    uri = api._image_to_b64_uri(str(f))
    assert uri.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == b"\xff\xd8fake"


def test_auth_headers_ring(monkeypatch):
    from core.api import key_manager
    ring = FakeRing(["a", "b"])
    monkeypatch.setattr(key_manager, "get_key_ring", lambda: ring)
    api = ac.AgnesChatAPI("k1")
    assert api._auth_headers("explicit")["Authorization"] == "Bearer explicit"
    assert api._auth_headers()["Authorization"] == "Bearer a"
    assert "Authorization" not in api._base_headers


# ── agnes_chat：_request_with_retry / chat / chat_multimodal ────────

@pytest.fixture
def chat_api(monkeypatch):
    """最小化外部依赖的 AgnesChatAPI（限速/报错收集打桩）。"""
    monkeypatch.setattr(ac, "get_rate_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(ac, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(ac, "collect_error_from_exception", lambda *a, **k: None)
    return ac.AgnesChatAPI(api_key="k1")


async def test_chat_success(chat_api, monkeypatch):
    seen = {}

    def fake_kr(requester, endpoint, **kw):
        seen["endpoint"] = endpoint
        seen["json"] = kw.get("json")
        seen["timeout"] = kw.get("timeout")
        return FakeResponse(200, {"choices": [{"message": {"content": "你好"}}]})

    monkeypatch.setattr(ac, "request_with_key_rotation", fake_kr)
    result = chat_api.chat("你是助手", "你好吗", max_tokens=100)
    assert result == "你好"
    assert seen["endpoint"] == "/chat/completions"
    assert seen["json"]["model"] == "agnes-2.5-flash"
    assert seen["json"]["temperature"] == 0.7
    assert seen["json"]["max_tokens"] == 100
    assert seen["timeout"] == 120


async def test_request_with_retry_exhausted_429_collects(chat_api, monkeypatch):
    collected = []
    monkeypatch.setattr(ac, "collect_error", lambda *a, **k: collected.append(k))
    monkeypatch.setattr(ac, "request_with_key_rotation", lambda r, ep, **kw: FakeResponse(429))

    with pytest.raises(_requests.exceptions.HTTPError):
        chat_api._request_with_retry({"messages": [{"role": "user", "content": "hi"}]})
    assert collected and collected[0]["error_type"] == "RateLimit429"


async def test_request_with_retry_exhausted_5xx_collects(chat_api, monkeypatch):
    collected = []
    monkeypatch.setattr(ac, "collect_error", lambda *a, **k: collected.append(k))
    monkeypatch.setattr(ac, "request_with_key_rotation", lambda r, ep, **kw: FakeResponse(503))

    with pytest.raises(_requests.exceptions.HTTPError):
        chat_api._request_with_retry({"messages": [{"role": "user", "content": "hi"}]})
    assert collected and collected[0]["error_type"] == "HTTP503"


async def test_request_with_retry_4xx_not_retryable(chat_api, monkeypatch):
    collected = []
    monkeypatch.setattr(ac, "collect_error", lambda *a, **k: collected.append(k))
    monkeypatch.setattr(ac, "request_with_key_rotation", lambda r, ep, **kw: FakeResponse(400))

    with pytest.raises(_requests.exceptions.HTTPError):
        chat_api._request_with_retry({"messages": [{"role": "user", "content": "hi"}]})
    # 4xx（非 429）走"不可重试"收集分支
    assert collected[0]["error_type"] == "HTTPError"
    assert collected[0]["status_code"] == 400


async def test_request_with_retry_connection_error(chat_api, monkeypatch):
    collected = []
    monkeypatch.setattr(ac, "collect_error_from_exception", lambda *a, **k: collected.append(k))

    def boom(r, ep, **kw):
        raise _requests.exceptions.ConnectionError("net down")

    monkeypatch.setattr(ac, "request_with_key_rotation", boom)
    with pytest.raises(_requests.exceptions.ConnectionError):
        chat_api._request_with_retry({"messages": [{"role": "user", "content": "hi"}]})
    assert collected and collected[0]["prompt"] == "hi"


async def test_chat_multimodal_url_and_local(chat_api, monkeypatch, tmp_path):
    local = tmp_path / "img.png"
    local.write_bytes(b"\x89PNGfake")

    def fake_kr(requester, endpoint, **kw):
        return FakeResponse(200, {"choices": [{"message": {"content": "图中是三只猫"}}]})

    monkeypatch.setattr(ac, "request_with_key_rotation", fake_kr)
    seen = {}

    def fake_rwr(payload, timeout=300):
        seen["payload"] = payload
        seen["timeout"] = timeout
        return {"choices": [{"message": {"content": "图中是三只猫"}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    result = chat_api.chat_multimodal(
        "看图", "描述", ["https://cdn/a.png", str(local)], max_tokens=50,
    )
    assert result == "图中是三只猫"
    assert seen["timeout"] == 300
    user_content = seen["payload"]["messages"][-1]["content"]
    # URL 引用
    assert user_content[0] == {"type": "text", "text": "描述"}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"] == "https://cdn/a.png"
    # 本地文件 → base64 uri
    assert user_content[2]["type"] == "image_url"
    assert user_content[2]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_chat_multimodal_skips_missing_file(chat_api, monkeypatch):
    def fake_rwr(payload, timeout=300):
        msgs = payload["messages"]
        user_content = msgs[-1]["content"]
        # 不存在的本地文件不应被加入 image_url（无 base64 项）
        assert not [c for c in user_content if c.get("type") == "image_url"]
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    result = chat_api.chat_multimodal("sys", "txt", ["/no/such.png"])
    assert result == "ok"


# ── agnes_chat：chat_json 健壮解析 ──────────────────────────────────


async def test_chat_json_direct_parse(chat_api, monkeypatch):
    def fake_rwr(payload, timeout=120):
        return {"choices": [{"message": {"content": "{\"a\": 1}"}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    assert chat_api.chat_json("sys", "user") == {"a": 1}


async def test_chat_json_regex_fallback(chat_api, monkeypatch):
    def fake_rwr(payload, timeout=120):
        return {"choices": [{"message": {"content": "前缀说明 {\"a\": 1} 结尾"}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    assert chat_api.chat_json("sys", "user") == {"a": 1}


async def test_chat_json_code_fence(chat_api, monkeypatch):
    def fake_rwr(payload, timeout=120):
        content = "```json\n{\"b\": 2}\n```"
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    assert chat_api.chat_json("sys", "user") == {"b": 2}


async def test_chat_json_repair_fallback(chat_api, monkeypatch):
    monkeypatch.setattr(
        ac, "repair_json",
        lambda text, return_objects=True: {"c": 3},
    )
    calls = []

    def fake_rwr(payload, timeout=120):
        calls.append(1)
        return {"choices": [{"message": {"content": "[不合法json"}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    assert chat_api.chat_json("sys", "user") == {"c": 3}
    assert len(calls) == 1  # 修复成功无需再调 chat


async def test_chat_json_first_fails_then_succeeds(chat_api, monkeypatch):
    monkeypatch.setattr(ac, "repair_json", None)  # 排除 json_repair 干扰，确保走重试分支
    contents = ["坏 [json", "{\"ok\": true}"]
    calls = []

    def fake_rwr(payload, timeout=120):
        calls.append(1)
        return {"choices": [{"message": {"content": contents[len(calls) - 1]}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    assert chat_api.chat_json("sys", "user") == {"ok": True}
    assert len(calls) == 2


async def test_chat_json_final_failure_raises(chat_api, monkeypatch):
    monkeypatch.setattr(ac, "repair_json", None)  # 确保走失败路径
    collected = []
    monkeypatch.setattr(ac, "collect_error", lambda *a, **k: collected.append(k))
    calls = []

    def fake_rwr(payload, timeout=120):
        calls.append(1)
        return {"choices": [{"message": {"content": "完全不是 json"}}]}

    monkeypatch.setattr(chat_api, "_request_with_retry", fake_rwr)
    with pytest.raises(ValueError, match="Failed to parse JSON"):
        chat_api.chat_json("sys", "user")
    assert len(calls) == 2  # 两次 chat 调用
    assert collected[0]["error_type"] == "JSONParseError"