"""产物画廊（P1）单测 — tests/test_gallery_routes.py

覆盖（对应 SonarCloud Quality Gate 新代码覆盖率缺口 + 两条安全修复回归）：
- ``web/routes/gallery_routes.py``
  - GET /api/gallery：只收录「有成片文件」的任务、status/kind 过滤、描述字段优先级与截断
  - GET /api/gallery/thumbnail/{task_id}：404（任务不存在 / 成片不存在 / 抽帧失败）、200 送缓存
- ``core/gallery_cache.py``
  - ``_thumb_path`` 白名单形态校验 + safe_join containment（穿越输入一律拒绝）
  - ``ensure_thumb``：缓存命中 / 成片缺失 / 不安全源路径 / ffmpeg 成功 / ffmpeg 失败

安全回归点：缩略图端点的 ``task_id`` 只用于与工作区扫描结果做相等比较，
路径与缓存文件名一律取自扫描结果，URL 上传入的穿越型 id 不会被拼进路径。

用法:
    .venv/bin/python -m pytest tests/test_gallery_routes.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import gallery_cache
from core.path_security import UnsafePathError
from web.routes import gallery_routes

# ═══════════════════════════════════════════════════
# 公共夹具 / 工具
# ═══════════════════════════════════════════════════


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """挂载 gallery 路由并把工作区定向到 tmp_path（不触碰真实工作区）。"""
    app = FastAPI()
    app.include_router(gallery_routes.router)
    monkeypatch.setattr("core.task_manager.get_working_dir", lambda: str(tmp_path))
    return TestClient(app), tmp_path


def _make_task(
    working_dir: str,
    task_id: str,
    *,
    task_type: str = "simple",
    status: str = "completed",
    final_video: str = "",
    dir_name: str | None = None,
    **extra,
) -> str:
    """在 tmp 工作区造一个任务目录（写最小 task_state.json）。"""
    dir_name = dir_name or f"d_{task_id}"
    task_dir = os.path.join(working_dir, dir_name)
    os.makedirs(task_dir, exist_ok=True)
    data = {"task_id": task_id, "task_type": task_type, "status": status}
    if final_video:
        data["final_video_file"] = final_video
    data.update(extra)
    with open(os.path.join(task_dir, "task_state.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return task_dir


def _make_file(path: str, content: bytes = b"data") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


# ═══════════════════════════════════════════════════
# _derive_media：媒体类型/URL 纯逻辑
# ═══════════════════════════════════════════════════


def test_derive_media_image_uses_image_endpoint():
    derived = gallery_routes._derive_media({"task_id": "i1", "task_type": "image"})
    assert derived["is_image"] is True
    assert derived["image"] == "i1"


def test_derive_media_video_uses_artifact_id():
    derived = gallery_routes._derive_media({"task_id": "v1", "task_type": "creative"})
    assert derived["is_image"] is False
    assert derived["kind"] == "video"
    assert derived["artifact_id"] == "creative:final_video"


# ═══════════════════════════════════════════════════
# GET /api/gallery
# ═══════════════════════════════════════════════════


def test_gallery_only_includes_tasks_with_existing_final_file(client):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "a.mp4"))
    _make_task(wd, "t_ok", final_video=final, prompt="一只猫")
    _make_task(wd, "t_no_final", prompt="还没有成片")
    _make_task(wd, "t_ghost", final_video=os.path.join(wd, "missing.mp4"))

    data = app_client.get("/api/gallery").json()
    assert data["ok"] is True
    assert data["total"] == 1
    item = data["items"][0]
    assert item["task_id"] == "t_ok"
    assert item["kind"] == "video"
    assert item["description"] == "一只猫"
    assert item["media_url"] == "/api/tasks/t_ok/artifacts/simple:final_video/file"
    assert item["thumb_url"] == "/api/gallery/thumbnail/t_ok"


def test_gallery_image_item_has_no_thumbnail(client):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "img.png"))
    _make_task(wd, "i_ok", task_type="image", final_video=final)

    item = app_client.get("/api/gallery").json()["items"][0]
    assert item["kind"] == "image"
    assert item["media_url"] == "/api/image/i_ok"
    assert item["thumb_url"] is None


def test_gallery_status_and_kind_filters(client):
    app_client, wd = client
    video = _make_file(os.path.join(wd, "out", "v.mp4"))
    image = _make_file(os.path.join(wd, "out", "i.png"))
    _make_task(wd, "v_done", final_video=video)
    _make_task(wd, "v_failed", status="failed", final_video=video)
    _make_task(wd, "i_done", task_type="image", final_video=image)

    assert app_client.get("/api/gallery", params={"status": "failed"}).json()["total"] == 1
    video_only = app_client.get("/api/gallery", params={"filter": "video"}).json()
    assert {i["task_id"] for i in video_only["items"]} == {"v_done", "v_failed"}
    image_only = app_client.get("/api/gallery", params={"filter": "image"}).json()
    assert {i["task_id"] for i in image_only["items"]} == {"i_done"}


def test_gallery_description_field_priority_and_truncation(client):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "c.mp4"))
    # idea 优先于 prompt；超长描述截断到 120 字符
    _make_task(wd, "c1", task_type="creative", final_video=final,
               idea="I" * 200, prompt="P" * 10)
    _make_task(wd, "c2", task_type="simple", final_video=final, prompt="  空格裁剪  ")

    items = {i["task_id"]: i for i in app_client.get("/api/gallery").json()["items"]}
    assert items["c1"]["description"] == "I" * 120
    assert items["c2"]["description"] == "空格裁剪"


def test_gallery_legacy_task_without_type_falls_back(client):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "legacy.mp4"))
    task_dir = os.path.join(wd, "d_legacy")
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "task_state.json"), "w", encoding="utf-8") as f:
        json.dump({"task_id": "legacy", "final_video_file": final}, f)

    item = app_client.get("/api/gallery").json()["items"][0]
    # 旧数据无 task_type → 视为创意；无 status → pending
    assert item["task_type"] == "creative"
    assert item["status"] == "pending"
    assert item["title"] == "legacy"


def test_gallery_uses_creative_name_as_title(client):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "n.mp4"))
    _make_task(wd, "named", final_video=final, creative_name="我的片子")

    assert app_client.get("/api/gallery").json()["items"][0]["title"] == "我的片子"


# ═══════════════════════════════════════════════════
# GET /api/gallery/thumbnail/{task_id}
# ═══════════════════════════════════════════════════


def test_thumbnail_unknown_task_404(client):
    app_client, _wd = client
    resp = app_client.get("/api/gallery/thumbnail/not_exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "任务不存在"


def test_thumbnail_malicious_ids_not_served(client):
    app_client, wd = client
    # 造一个真实任务（其成片存在），确保下述 404 来自 id 未被扫描结果命中
    final = _make_file(os.path.join(wd, "out", "t.mp4"))
    _make_task(wd, "real", final_video=final)

    for bad in ["..%2F..%2Fetc%2Fpasswd", "%2Fetc%2Fpasswd", "..%2e", "a%2Fb"]:
        assert app_client.get(f"/api/gallery/thumbnail/{bad}").status_code == 404


def test_thumbnail_missing_final_file_404(client):
    app_client, wd = client
    _make_task(wd, "no_final")

    resp = app_client.get("/api/gallery/thumbnail/no_final")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "成片不存在"


def test_thumbnail_generation_failure_404(client, monkeypatch):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "f.mp4"))
    _make_task(wd, "gen_fail", final_video=final)
    monkeypatch.setattr(gallery_routes, "ensure_thumb", lambda *_a, **_kw: None)

    resp = app_client.get("/api/gallery/thumbnail/gen_fail")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "缩略图生成失败"


def test_thumbnail_serves_cached_file(client, monkeypatch, tmp_path):
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "ok.mp4"))
    _make_task(wd, "ok_task", final_video=final)
    thumb = _make_file(str(tmp_path / "thumb.jpg"), b"\xff\xd8\xff\xe0jpeg")
    monkeypatch.setattr(gallery_routes, "ensure_thumb", lambda *_a, **_kw: thumb)

    resp = app_client.get("/api/gallery/thumbnail/ok_task")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert "immutable" in resp.headers["cache-control"]
    assert resp.content == b"\xff\xd8\xff\xe0jpeg"


def test_thumbnail_uses_scanned_identity_not_url_value(client, monkeypatch):
    """URL 上的 id 只用于比较：传给缓存的必须是扫描得到的可信标识。"""
    app_client, wd = client
    final = _make_file(os.path.join(wd, "out", "scan.mp4"))
    # dir_name 与 task_id 不同，验证走的是扫描结果的 task_id
    _make_task(wd, "scan_id", final_video=final, dir_name="20260101_000000_scan")
    calls = []
    monkeypatch.setattr(
        gallery_routes, "ensure_thumb",
        lambda task_id, path: calls.append((task_id, path)) or None,
    )

    resp = app_client.get("/api/gallery/thumbnail/scan_id")
    assert resp.status_code == 404  # 缓存返回 None → 抽帧失败
    assert calls == [("scan_id", final)]


# ═══════════════════════════════════════════════════
# core/gallery_cache：路径收敛
# ═══════════════════════════════════════════════════


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "a\\b", "", "x" * 65, "/etc/passwd"])
def test_thumb_path_rejects_unsafe_ids(bad_id):
    assert gallery_cache._thumb_path(bad_id) is None


def test_thumb_path_accepts_plain_id(tmp_path, monkeypatch):
    cache_dir = str(tmp_path / "cache")
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", cache_dir)
    path = gallery_cache._thumb_path("20260101_000000_abcdef123456")
    assert path == os.path.realpath(os.path.join(cache_dir, "20260101_000000_abcdef123456.jpg"))


def test_has_thumb_reflects_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(cache_dir))

    assert gallery_cache.has_thumb("t1") is False
    assert gallery_cache.has_thumb("../t1") is False  # 非法 id 直接 False
    _make_file(str(cache_dir / "t1.jpg"))
    assert gallery_cache.has_thumb("t1") is True


def test_ensure_thumb_rejects_unsafe_id(tmp_path, monkeypatch):
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(tmp_path / "cache"))
    assert gallery_cache.ensure_thumb("../evil", "whatever.mp4") is None


def test_ensure_thumb_returns_cached_file(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(cache_dir))
    cached = _make_file(str(cache_dir / "t2.jpg"))

    assert gallery_cache.ensure_thumb("t2", "") == os.path.realpath(cached)


def test_ensure_thumb_without_source_video(tmp_path, monkeypatch):
    wd = tmp_path / "wd"
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(tmp_path / "cache"))
    # 源路径为空 / 不存在 → 均返回 None（前端回退原生首帧）
    assert gallery_cache.ensure_thumb("t3", "") is None
    assert gallery_cache.ensure_thumb("t3", str(wd / "none.mp4")) is None


def test_ensure_thumb_rejects_unsafe_source_path(tmp_path, monkeypatch):
    source = _make_file(str(tmp_path / "wd" / "src.mp4"))
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(tmp_path / "cache"))

    def _raise(_path):
        raise UnsafePathError("escape")

    monkeypatch.setattr(gallery_cache, "safe_workspace_path", _raise)
    assert gallery_cache.ensure_thumb("t4", source) is None


def test_ensure_thumb_runs_ffmpeg_and_caches(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    source = _make_file(str(tmp_path / "wd" / "src.mp4"))
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(cache_dir))
    monkeypatch.setattr(gallery_cache, "resolve_binary", lambda _name: "/fake/ffmpeg")
    seen = {}

    def _fake_run(cmd, **_kwargs):
        seen["cmd"] = cmd
        # 模拟 ffmpeg 落盘：最后一个参数是输出缩略图路径
        with open(cmd[-1], "wb") as f:
            f.write(b"\xff\xd8thumb")
        return None

    monkeypatch.setattr(gallery_cache.subprocess, "run", _fake_run)

    out = gallery_cache.ensure_thumb("t5", source)
    assert out == os.path.realpath(os.path.join(str(cache_dir), "t5.jpg"))
    assert os.path.isfile(out)
    assert seen["cmd"][0] == "/fake/ffmpeg"
    # 送入 ffmpeg 的成片路径已 realpath 规范化
    assert seen["cmd"][seen["cmd"].index("-i") + 1] == os.path.realpath(source)


def test_ensure_thumb_ffmpeg_failure_returns_none(tmp_path, monkeypatch):
    source = _make_file(str(tmp_path / "wd" / "src.mp4"))
    monkeypatch.setattr(gallery_cache, "_THUMB_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gallery_cache, "resolve_binary", lambda _name: "/fake/ffmpeg")

    def _boom(_cmd, **_kwargs):
        raise OSError("ffmpeg blew up")

    monkeypatch.setattr(gallery_cache.subprocess, "run", _boom)
    assert gallery_cache.ensure_thumb("t6", source) is None
