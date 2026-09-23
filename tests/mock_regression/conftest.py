"""tests.mock_regression.conftest — pytest 全局 fixtures

自动注入 mock API 替换，确保所有测试无外部网络调用。

Mock 策略：替换类定义（不是实例），使所有地方的 `ClassName()` 都创建 mock 对象。
"""

import os
import sys
import pytest
import logging

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from .mock_apis import (
    MockAgnesVideoAPI,
    MockAgnesImageAPI,
    MockAgnesChatAPI,
    MockEdgeTTSEngine,
    MockRateLimiter,
)

from core.config import DEFAULT_TEXT_MODEL, REGRESSION_WORKING_DIR_ENV

logging.basicConfig(level=logging.WARNING)


# ══════════════════════════════════════════════════════════════════════
# 文本供应商路由的 mock 替换
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def mock_text_provider_route(monkeypatch):
    """强制文本调用走内置 agnes 分支，使回归只依赖 mock。

    v7.0 起文本客户端由 ``core.api.chat_providers.get_or_build_text_chat_client()``
    按 ``models.text_provider`` 分派：若开发机 config.json 里选中了第三方供应商
    （如 AMD Radeon Cloud / DeepSeek），回归会**真的**去请求该外部端点而失败，
    违背本 conftest「无外部网络调用」的约定。把 ``resolve_text_chat`` 固定为
    agnes 后，工厂取 ``core.api.agnes_chat.AgnesChatAPI``（已被 mock）兜底。
    """
    from core.api import chat_providers

    monkeypatch.setattr(
        chat_providers, "resolve_text_chat",
        lambda: {"kind": "agnes", "model": DEFAULT_TEXT_MODEL},
    )


# ══════════════════════════════════════════════════════════════════════
# Core API 类的 mock 替换
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def mock_video_api(monkeypatch):
    """替换 AgnesVideoAPI 为 mock 版本（覆盖所有导入位置）。"""
    paths = [
        "core.api.agnes_video.AgnesVideoAPI",
        "core.pipelines.simple_video.AgnesVideoAPI",
        "core.pipelines.creative.pipeline.AgnesVideoAPI",
        "core.pipelines.manuscript_video.AgnesVideoAPI",
        "core.pipelines.anchor_video.AgnesVideoAPI",
        "core.pipelines.poetry_video.AgnesVideoAPI",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockAgnesVideoAPI)


@pytest.fixture(autouse=True)
def mock_image_api(monkeypatch):
    """替换 AgnesImageAPI 为 mock 版本。"""
    paths = [
        "core.api.agnes_image.AgnesImageAPI",
        "core.pipelines.creative.pipeline.AgnesImageAPI",
        "core.pipelines.anchor_video.AgnesImageAPI",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockAgnesImageAPI)


@pytest.fixture(autouse=True)
def mock_chat_api(monkeypatch):
    """替换 AgnesChatAPI 为 mock 版本。"""
    paths = [
        "core.api.agnes_chat.AgnesChatAPI",
        "core.screenwriter.AgnesChatAPI",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockAgnesChatAPI)


@pytest.fixture(autouse=True)
def mock_edge_tts(monkeypatch):
    """替换 EdgeTTSEngine 为 mock 版本（内部用 SilentTTSEngine）。

    需要 patch 所有 pipeline 中直接 import EdgeTTSEngine 的位置。
    """
    # Batch 2（S2）：全部 pipeline 已收敛到共享方法（函数级 import core.audio.tts），
    # 仅 patch 引擎源头即可覆盖所有调用点
    paths = [
        "core.audio.tts.EdgeTTSEngine",
    ]
    for p in paths:
        monkeypatch.setattr(p, MockEdgeTTSEngine)


@pytest.fixture(autouse=True)
def mock_rate_limiter(monkeypatch):
    """禁用全局限速器。"""
    paths = [
        "core.api.rate_limiter.get_rate_limiter",
        "core.api.agnes_video.get_rate_limiter",
        "core.api.agnes_chat.get_rate_limiter",
        "core.api.agnes_image.get_rate_limiter",
    ]
    for p in paths:
        monkeypatch.setattr(p, lambda: MockRateLimiter())


# ══════════════════════════════════════════════════════════════════════
# 测试 fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_workdir(tmp_path):
    """临时工作目录，测试结束后自动清理。"""
    workdir = tmp_path / "agnes_test"
    workdir.mkdir()
    return str(workdir)


@pytest.fixture(autouse=True)
def _regression_working_dir(temp_workdir, monkeypatch):
    """将 get_working_dir() 指向测试临时目录。

    TaskManager 现在用 safe_join() 做路径穿越防护：task_dir = safe_join(working目录, dir_name)。
    测试以绝对路径 temp_workdir 作为 dir_name 传入，等价于“任务目录就是这个绝对路径”。
    把 AGNES_REGRESSION_WORKING_DIR 设为 realpath(temp_workdir)，使 safe_join 的
    root 与 dir_name 同源（os.path.join 对绝对第二部分会采用 dir_name 本身，再通过
    realpath 与 root 一致性检查），从而既通过防护又不改变测试期望的任务目录。
    """
    monkeypatch.setenv(REGRESSION_WORKING_DIR_ENV, os.path.realpath(temp_workdir))


@pytest.fixture
def mock_api_key():
    """Mock API Key。"""
    return "mock_api_key_12345"
