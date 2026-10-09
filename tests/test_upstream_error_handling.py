"""上游视频接口可靠性加固回归（v7.0 U1/U2/U3/U5/U9）。

对应计划：``docs/plans/v7.0/upstream_error_handling_plan.md``
事实依据：``docs/dev/agnes_video_upstream_behavior.md``

覆盖：
- U1 ``video_queue_full`` 独立退避轨道（不计入普通 5xx 配额、预算到期报错、进度回调）
- U2 ``_upstream_error`` 统一提取（提交侧 body / 轮询侧 error 对象）+ 异常文案
- U3 ``_needs_portrait_rotation_fix`` 躺倒签名判定（默认开关关闭）
- U5 ``progress`` 恒为 0 时任务仍能正常完成
- U9 轮询侧 404 =「任务未就绪」中间态（不消耗连续失败配额，仅周期性 info 日志）
- U9 轮询侧 404 视为「任务未就绪」中间态（不消耗连续失败配额、不进 error_logs）

约定：测试在协议边界 mock ``requests``（HTTP 层），保留 API 类全部内部逻辑。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
import requests as _requests

import core.api.agnes_video as av


class FakeResponse:
    """最小化的 requests.Response 桩（仅含本模块使用的属性）。"""

    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text if text is not None else json.dumps(self._json, ensure_ascii=False)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _requests.HTTPError(f"HTTP {self.status_code}")


class FakeLimiter:
    """限速器桩：acquire / acquire_async 立即返回，避免真实令牌桶拖慢测试。"""

    def acquire(self):
        return True

    async def acquire_async(self, stop_event=None):
        return None


class FakeRing:
    """KeyRing 桩：与真实实现相同的语义（rotate 钉住下一个 next 的 Key）。"""

    def __init__(self, keys):
        self._keys = list(keys)
        self._i = -1
        self._force = None
        self.rotations = []           # 记录 rotate 调用（断言 401 不换 Key）
        self.auth_failures_log = []   # 记录 401 归因上报（v7.1）

    def next(self):
        if self._force is not None:
            i, self._force = self._force, None
            return self._keys[i]
        self._i = (self._i + 1) % len(self._keys)
        return self._keys[self._i]

    def rotate(self):
        self._i = (self._i + 1) % len(self._keys)
        self._force = self._i
        self.rotations.append(self._keys[self._i])
        return self._keys[self._i]

    def mark_auth_failed(self, key, *, status=401, domain="", message=""):
        """401 归因登记桩：只记录上报内容，与真实实现一样不参与选 Key。"""
        rec = {"key": key, "status": status, "domain": domain, "message": message}
        self.auth_failures_log.append(rec)
        return rec

    def has_multiple(self):
        return len(self._keys) > 1

    def __len__(self):
        return len(self._keys)


@pytest.fixture
def api(monkeypatch):
    """最小化外部依赖的 AgnesVideoAPI（零退避 + 限速器/报错收集打桩）。"""
    monkeypatch.setattr(av, "get_video_submit_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(av, "get_rate_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)
    monkeypatch.setattr(av, "collect_error_from_exception", lambda *a, **k: None)
    # 队列退避缩到 0，避免测试真的等 30–60s
    monkeypatch.setattr(av, "_QUEUE_RETRY_BASE_DELAY", 0.0)
    monkeypatch.setattr(av, "_QUEUE_RETRY_JITTER", 0.0)
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing(["k1"]))
    return av.AgnesVideoAPI(api_key="k1", max_retries=3, retry_base_delay=0.001)


def _queue_full_response():
    return FakeResponse(
        status_code=503,
        json_data={"code": "video_queue_full",
                   "message": "video queue is full, please retry later (request id: abc)"},
    )


# ── 401 归因登记（v7.1）：只上报，不换 Key / 不重试 ────────────────────


async def test_401_reports_auth_failure_and_keeps_failure_path(api, monkeypatch):
    """401：归因上报给 KeyRing 后仍按原逻辑失败——不换 Key、不重试、文案不变。

    依据：判定与归因收口在 ``core/api/key_manager.py``（KeyRing 只记录、不剔除），
    是否移除该 Key 由用户在前端配置页决定；用户不处理时保持原有报错行为。
    """
    ring = FakeRing(["k1", "k2"])
    calls = []
    monkeypatch.setattr(av, "get_key_ring", lambda: ring)
    monkeypatch.setattr(av, "get_api_key_domains", lambda: {"k1": "cn"})
    monkeypatch.setattr(
        av.requests, "post",
        lambda *a, **k: (calls.append(1), FakeResponse(
            status_code=401, json_data={"message": "Invalid token"}))[1],
    )

    with pytest.raises(RuntimeError) as exc_info:
        await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert len(calls) == 1                      # 未重试（保持 max_retries 无关）
    assert "HTTP 401" in str(exc_info.value)    # 错误文案与行为保持原样
    assert ring.rotations == []                 # 未换 Key
    # 归因已上报，域名取自该 Key 的绑定配置（供配置页提示「Key 与域名不匹配」）
    assert ring.auth_failures_log == [
        {"key": "k1", "status": 401, "domain": "cn", "message": "Invalid token"},
    ]


# ── U2：统一错误提取 ────────────────────────────────────────────────


def test_upstream_error_from_response_body():
    code, message = av._upstream_error(_queue_full_response())
    assert code == "video_queue_full"
    assert "queue is full" in message


def test_upstream_error_from_poll_error_object():
    code, message = av._upstream_error({
        "status": "failed",
        "error": {"code": "500",
                  "message": "ComfyUI internal error: inference not finished after 15 minutes"},
    })
    assert code == "500"
    assert "inference not finished after 15 minutes" in message


def test_upstream_error_tolerates_missing_and_broken_json():
    assert av._upstream_error(None) == ("", "")
    assert av._upstream_error({"status": "failed"}) == ("", "")

    class BadJson:
        status_code = 500
        text = "gateway exploded"

        def json(self):
            raise ValueError("no json")

    assert av._upstream_error(BadJson()) == ("", "gateway exploded")


# ── U1：队列满独立退避轨道 ──────────────────────────────────────────


async def test_queue_full_uses_separate_retry_track(api, monkeypatch):
    """队列满重试不计入普通 5xx 配额（调用次数可超过 max_retries）。"""
    calls = []
    progress = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) <= 5:
            return _queue_full_response()
        return FakeResponse(status_code=200, json_data={"video_id": "vid-ok"})

    monkeypatch.setattr(av.requests, "post", fake_post)

    vid = await api._submit_with_retry(
        {"prompt": "x"}, "t2v",
        progress_callback=lambda stage, data: progress.append((stage, data)),
    )

    assert vid == "vid-ok"
    assert len(calls) == 6  # 5 次队列退避 + 1 次成功，未被 max_retries=3 截断
    assert [s for s, _ in progress] == ["queue_full"] * 5
    # 载荷须带上原样报错（HTTP 码 + body code），供前端拼出「Agnes 队列已满」提示
    assert [d["attempt"] for _, d in progress] == [1, 2, 3, 4, 5]
    assert all(d["status"] == 503 and d["code"] == "video_queue_full" for _, d in progress)
    assert all("queue is full" in (d["message"] or "") for _, d in progress)


async def test_queue_full_budget_exhausted_raises(api, monkeypatch):
    """队列预算到期抛结构化异常：带 HTTP 码 / body code / 等待时长，供 UI 多语言渲染。

    异常消息本身只含技术事实（不写死语种），用户可见文案由
    前端 i18n key（``error.video.queue_full``）或后端兜底 translate 生成。
    """
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            agnes_video_queue_retry_seconds=0,
            agnes_video_poll_timeout=1800,
            agnes_fix_v25_portrait_rotation=False,
        ),
    )
    monkeypatch.setattr(av.requests, "post", lambda *a, **k: _queue_full_response())
    with pytest.raises(av.AgnesQueueFullError) as exc_info:
        await api._submit_with_retry({"prompt": "x"}, "t2v")

    err = exc_info.value
    assert err.queue_full_status == 503
    assert err.queue_full_code == "video_queue_full"
    # 提交阶段就被拒 → 未产生任务，不属于「服务端确认失败」，无需丢弃 video_id
    assert av.is_remote_video_failure(err) is False
    # 后端兜底：zh/en 双基线渲染（点名 Agnes + 原样报错 + 错峰建议）
    from utils.network import describe_queue_full_error, queue_full_message_params
    assert queue_full_message_params(err) == {
        "status": 503, "code": "video_queue_full", "waited": 1,
    }
    zh = describe_queue_full_error(err, lang="zh")
    assert "Agnes" in zh and "503" in zh and "video_queue_full" in zh
    assert "错峰" in zh
    en = describe_queue_full_error(err, lang="en")
    assert "Agnes" in en and "off-peak" in en
    # 非队列满异常不误判
    assert describe_queue_full_error(RuntimeError("boom"), lang="zh") == ""
    assert queue_full_message_params(RuntimeError("boom")) == {}


async def test_fail_to_fetch_task_goes_queue_track(api, monkeypatch):
    """``fail_to_fetch_task`` 与 video_queue_full 同轨（上游瞬时故障可重试）。"""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(
                status_code=503,
                json_data={"code": "fail_to_fetch_task", "message": "task not found"},
            )
        return FakeResponse(status_code=200, json_data={"video_id": "vid-2"})

    monkeypatch.setattr(av.requests, "post", fake_post)
    assert await api._submit_with_retry({"prompt": "x"}, "t2v") == "vid-2"
    assert len(calls) == 2


async def test_normal_5xx_still_capped_at_max_retries(api, monkeypatch):
    """非队列类 5xx 仍只尝试 max_retries 次（不因 U1 变成无限重试）。"""
    calls = []
    errors = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return FakeResponse(
            status_code=503,
            json_data={"code": "internal_error", "message": "boom"},
        )

    monkeypatch.setattr(av.requests, "post", fake_post)
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: errors.append(k))

    with pytest.raises(RuntimeError, match="max retries"):
        await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert len(calls) == api.max_retries
    # U2：error_message 透出 body 的 message + extra 带 upstream_code
    assert any(e.get("error_message") == "HTTP 503: boom" for e in errors)
    assert any(e.get("extra", {}).get("upstream_code") == "internal_error" for e in errors)


async def test_queue_full_error_message_not_dict_literal(api, monkeypatch):
    """U2：error_logs 的 error_message 不得是 dict 字面量。

    注：必须把队列预算压到 0——否则默认 900s 预算会按真实时钟空转
    （退避间隔虽被打桩为 0，但预算到期判定用的是 time.monotonic）。
    """
    errors = []
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: errors.append(k))
    monkeypatch.setattr(av.requests, "post", lambda *a, **k: _queue_full_response())
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            agnes_video_queue_retry_seconds=0,
            agnes_video_poll_timeout=1800,
            agnes_fix_v25_portrait_rotation=False,
        ),
    )

    with pytest.raises(RuntimeError):
        await api._submit_with_retry({"prompt": "x"}, "t2v")

    assert errors
    for e in errors:
        assert "{" not in str(e.get("error_message", ""))
    assert any("queue is full" in str(e.get("error_message", "")) for e in errors)


# ── U2/U5：轮询失败文案与进度容错 ───────────────────────────────────


async def test_poll_failed_surfaces_error_message(api, monkeypatch):
    """轮询 failed 时把 error.message 透出（含上游 15 分钟硬闸原文）。"""
    payload = {
        "status": "failed",
        "internal_status": "stuck_inference",
        "error": {"code": "500",
                  "message": "ComfyUI internal error: inference not finished after 15 minutes"},
        "progress": 0,
        "internal_progress": 100,
    }
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: FakeResponse(200, payload))

    with pytest.raises(RuntimeError) as exc_info:
        await api._poll_task("vid", interval=0.01, max_consecutive_failures=3,
                             max_poll_duration=600)

    msg = str(exc_info.value)
    assert "inference not finished after 15 minutes" in msg
    assert "code=500" in msg
    # 提交侧 0.2 的判定语义必须保持：服务端确认失败 → 可安全丢弃 video_id
    assert av.is_remote_video_failure(exc_info.value) is True


async def test_poll_progress_stuck_at_zero_still_completes(api, monkeypatch):
    """U5：progress 恒为 0（与 internal_progress 矛盾）不影响终态判定。"""
    seq = [
        {"status": "pending", "progress": 0, "internal_progress": 0},
        {"status": "in_progress", "progress": 0, "internal_progress": 100},
        {"status": "completed", "progress": 0, "internal_progress": 100,
         "video_url": "https://cdn.example/v.mp4"},
    ]
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(1)
        return FakeResponse(200, seq[min(len(calls) - 1, len(seq) - 1)])

    monkeypatch.setattr(av.requests, "get", fake_get)
    seen = []
    result = await api._poll_task(
        "vid", interval=0.01, max_consecutive_failures=3, max_poll_duration=600,
        progress_callback=lambda status, progress, curl: seen.append((status, progress)),
    )
    assert result["status"] == "completed"
    assert [p for _, p in seen] == [0, 0, 0]  # 进度值原样透传，不做真值假设


async def test_wait_for_video_returns_url_when_progress_zero(api, monkeypatch):
    """U5：wait_for_video 在 progress 恒 0 时仍产出可下载 URL。"""
    payload = {"status": "completed", "progress": 0,
               "video_url": "https://cdn.example/v.mp4"}
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    out = await api.wait_for_video("vid")
    assert out.data == "https://cdn.example/v.mp4"
    assert out.fix_rotation is False  # 非 2.5 模型 / 开关默认关闭


# ── U9：轮询侧 404 =「任务未就绪」中间态 ────────────────────────────


async def test_poll_404_does_not_burn_failure_budget(api, monkeypatch):
    """U9：连续 404 不计入 max_consecutive_failures，任务最终仍能完成。

    场景：上游高峰期任务记录入库可见性延迟（实测从 ~20s 劣化到 10min+），
    连续 404 次数超过普通网络错误的容忍上限（10）后任务才可见。
    """
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(1)
        if len(calls) <= 15:
            return FakeResponse(404, {"error": {"code": 404,
                                                "message": "task not found (request id: x)"}})
        return FakeResponse(200, {"status": "completed", "progress": 100,
                                  "video_url": "https://cdn.example/v.mp4"})

    monkeypatch.setattr(av.requests, "get", fake_get)
    result = await api._poll_task("vid", interval=0.01)
    assert result["status"] == "completed"
    assert len(calls) == 16  # 15 次 404 中间态 + 1 次可见即成功，未被 10 次上限截断


async def test_poll_404_forever_falls_back_to_poll_timeout(api, monkeypatch):
    """U9：任务记录始终不出现 → 仍受 max_poll_duration 兜底，不无限等。

    超时异常不属于「服务端确认失败」（``is_remote_video_failure`` 为 False），
    续传必须保留 video_id 以免重复提交浪费配额。
    """
    monkeypatch.setattr(
        av.requests, "get",
        lambda *a, **k: FakeResponse(404, {"error": {"code": 404,
                                                     "message": "task not found"}}),
    )
    with pytest.raises(RuntimeError, match="Polling timed out"):
        await api._poll_task("vid", interval=0.01, max_poll_duration=0.05)


# ── U3：竖屏躺倒探测签名（默认关闭） ────────────────────────────────


def test_needs_portrait_rotation_fix_signature():
    # 命中：推理内部横屏（1280x720）+ 容器竖屏（720x1280）
    assert av._needs_portrait_rotation_fix(1280, 720, 720, 1280) is True
    # 不命中：方向一致（v2.0 竖屏 768x1152 / perf 832x1088）
    assert av._needs_portrait_rotation_fix(832, 1088, 768, 1152) is False
    # 不命中：容器也是横屏
    assert av._needs_portrait_rotation_fix(1280, 720, 1280, 720) is False
    # 不命中：尺寸缺失 / 非法
    assert av._needs_portrait_rotation_fix(None, 720, 720, 1280) is False
    assert av._needs_portrait_rotation_fix("x", "y", "z", "w") is False


def test_video_output_default_no_rotation_probe(monkeypatch, tmp_path):
    """默认开关关闭：即使 perf_params 可疑也不会触发 ffprobe/ffmpeg。"""
    called = []
    monkeypatch.setattr(av, "_probe_video_size", lambda p: called.append(p) or (720, 1280))
    out = av.VideoOutput(fmt="bytes", ext="mp4", data=b"1234")
    target = tmp_path / "v.mp4"
    out._save_sync(str(target))  # 同步保存路径（含旋转判定分支）
    assert target.exists()
    assert called == []


def test_video_output_rotation_skipped_when_perf_missing(monkeypatch, tmp_path):
    """fix_rotation 开启但缺少 perf_params 尺寸 → 保守跳过，不误转。"""
    called = []
    monkeypatch.setattr(av, "_probe_video_size", lambda p: called.append(p) or (720, 1280))
    out = av.VideoOutput(fmt="bytes", ext="mp4", data=b"1234",
                         perf_params={}, fix_rotation=True)
    out._save_sync(str(tmp_path / "v.mp4"))
    assert called == []


def test_wait_for_video_enables_rotation_for_v25_when_switch_on(monkeypatch):
    """开关开启 + 2.5 系列 → VideoOutput.fix_rotation=True；v2.0 不受影响。"""
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            agnes_video_poll_timeout=1800,
            agnes_video_queue_retry_seconds=900,
            agnes_fix_v25_portrait_rotation=True,
        ),
    )
    payload = {
        "status": "completed", "progress": 100,
        "video_url": "https://cdn.example/v.mp4",
        "perf_params": {"width": 1280, "height": 720},
    }
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    monkeypatch.setattr(av, "get_rate_limiter", lambda: FakeLimiter())
    monkeypatch.setattr(av, "get_key_ring", lambda: FakeRing(["k1"]))
    monkeypatch.setattr(av, "collect_error", lambda *a, **k: None)

    out = asyncio.run(
        av.AgnesVideoAPI(api_key="k1", model="agnes-video-2.5-flash").wait_for_video("vid")
    )
    assert out.fix_rotation is True
    assert out.perf_params == {"width": 1280, "height": 720}

    out20 = asyncio.run(
        av.AgnesVideoAPI(api_key="k1", model="agnes-video-v2.0").wait_for_video("vid")
    )
    assert out20.fix_rotation is False  # 非 2.5 系列不校正
