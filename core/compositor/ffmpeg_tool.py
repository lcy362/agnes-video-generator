"""core.compositor.ffmpeg_tool — ffmpeg / ffprobe 可执行文件统一解析。

背景：此前所有 ffmpeg/ffprobe 调用都用裸命令字符串经 ``subprocess.run`` 执行，
依赖系统 PATH 搜索可执行文件。Windows 未安装 ffmpeg 时 ``CreateProcess`` 抛
``[WinError 2] The system cannot find the file specified``，且发生在任务运行到
拼接步骤而非启动时（见 Issue #36 的完整 traceback）。

解析优先级（推荐，但不强制用户安装系统 ffmpeg）：
  1. 环境变量显式指定：``FFMPEG_BINARY`` / ``FFPROBE_BINARY`` —— 尊重用户意图
  2. 系统 PATH（``shutil.which``）—— 已安装则用之，绝不覆盖
  3. ``imageio-ffmpeg`` 内置静态二进制兜底 —— wheel 自带，无需用户操作

结果带进程级缓存；全部不可用时返回 None，由启动检测 / 调用方给出清晰指引
而非裸的 ``[WinError 2]``。
"""
import logging
import os
import shutil

logger = logging.getLogger(__name__)

# 二进制名 → 覆盖环境变量名
_EXE_OVERRIDE = {"ffmpeg": "FFMPEG_BINARY", "ffprobe": "FFPROBE_BINARY"}
_cache: "dict[str, str | None]" = {}


def resolve_binary(name: str) -> "str | None":
    """按优先级解析 ffmpeg/ffprobe 可执行文件绝对路径，进程内缓存。

    Args:
        name: ``"ffmpeg"`` 或 ``"ffprobe"``。

    Returns:
        可用可执行文件绝对路径；全部不可用时返回 None。
    """
    if name not in _EXE_OVERRIDE:
        raise ValueError(f"unknown binary: {name}")
    if name in _cache:
        return _cache[name]
    path = _resolve(name)
    _cache[name] = path
    return path


def resolve_ffmpeg() -> "str | None":
    """便捷：解析 ffmpeg。"""
    return resolve_binary("ffmpeg")


def resolve_ffprobe() -> "str | None":
    """便捷：解析 ffprobe（可能为 None，仅时长/尺寸探测用，调用方自带兜底）。"""
    return resolve_binary("ffprobe")


def _resolve(name: str) -> "str | None":
    # 1) 显式指定
    override = os.environ.get(_EXE_OVERRIDE[name])
    if override and os.path.exists(override):
        logger.info(f"[Compositor] {name}: explicit {override}")
        return override

    # 2) 系统 PATH
    found = shutil.which(name)
    if found:
        logger.info(f"[Compositor] {name}: system {found}")
        return found

    # 3) imageio-ffmpeg 内置（仅自带 ffmpeg；ffprobe 从同目录推导）
    base = _cache.get("ffmpeg") or _resolve_builtin_ffmpeg()
    if base:
        if name == "ffmpeg":
            return base
        probe = _sibling(base, "ffprobe")
        if probe:
            logger.info(f"[Compositor] {name}: builtin {probe}")
            return probe

    logger.warning(f"[Compositor] {name}: not found (no system PATH nor builtin)")
    return None


def _resolve_builtin_ffmpeg() -> "str | None":
    """取 imageio-ffmpeg 内置静态二进制；加载/失败时记录并返回 None。"""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # 加载失败 / 内置缺失 / 首次下载失败
        logger.warning(f"[Compositor] builtin ffmpeg unavailable: {e}")
        return None
    if exe and os.path.exists(exe):
        logger.info(f"[Compositor] ffmpeg: builtin {exe}")
        return exe
    return None


def _sibling(exe: str, stem: str) -> "str | None":
    """由可执行文件路径推导同目录兄弟程序（Windows 补 .exe）。"""
    candidate = os.path.join(
        os.path.dirname(exe), stem + (".exe" if os.name == "nt" else "")
    )
    return candidate if os.path.exists(candidate) else None