"""core.audio.tts — TTS 统一接口：EdgeTTSEngine + SilentTTSEngine

基于 edge_tts（免费 Azure Edge TTS）和静音占位两种实现。
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import edge_tts

logger = logging.getLogger(__name__)


class TTSEngine(ABC):
    """TTS 抽象基类。"""

    @abstractmethod
    async def generate(
        self, text: str, output_path: str, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%"
    ) -> Tuple[str, object]:
        """生成音频文件，返回 (audio_path, sub_maker_or_cues)。"""
        ...


class EdgeTTSEngine(TTSEngine):
    """基于 edge_tts 的免费 TTS 引擎。

    generate() 返回 (audio_path, sub_maker)，其中 sub_maker 是 edge_tts.SubMaker 实例，
    包含逐词时间戳 cues，可用于生成 SRT 字幕。
    """

    async def generate(
        self, text: str, output_path: str, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%"
    ) -> Tuple[str, "edge_tts.SubMaker"]:
        """生成 TTS 音频 + SubMaker（含 cues 时间戳）。

        Args:
            text: 要朗读的文本
            output_path: 输出音频文件路径（.mp3）
            voice: edge_tts 语音角色
            rate: 语速调节（如 "+0%", "+20%", "-10%"）

        Returns:
            (audio_path, sub_maker) 元组

        Raises:
            RuntimeError: TTS 生成失败时抛出，调用方应降级到 SilentTTSEngine。
        """
        logger.info(f"[TTS] Generating audio: voice={voice}, rate={rate}, text={len(text)} chars...")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
                sub_maker = edge_tts.SubMaker()

                tmp_path = output_path + ".tmp"
                with open(tmp_path, "wb") as audio_file:
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio_file.write(chunk["data"])
                        elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                            sub_maker.feed(chunk)

                # 原子替换，避免半成品被误用
                os.replace(tmp_path, output_path)
                logger.info(f"[TTS] Audio saved: {output_path}")
                return output_path, sub_maker
            except Exception as e:
                # 清理半成品文件
                for p in (tmp_path, output_path):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                if attempt < max_attempts - 1:
                    logger.warning(f"[TTS] edge_tts attempt {attempt + 1}/{max_attempts} failed: {e}, retrying...")
                    await asyncio.sleep(3)
                    continue
                logger.error(f"[TTS] edge_tts failed after {max_attempts} attempts: {e}")
                raise RuntimeError(f"EdgeTTS generation failed: {e}") from e


class SilentTTSEngine(TTSEngine):
    """静音占位 TTS 引擎。

    生成指定时长的静音音频，返回空 cues。用于用户关闭旁白时仍需要字幕时间轴的场景。
    """

    async def generate(
        self,
        text: str,
        output_path: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str = "+0%",
        duration_sec: Optional[float] = None,
    ) -> Tuple[str, dict]:
        """生成静音音频。

        Args:
            text: 文本（用于估算时长，如果 duration_sec 未提供）
            output_path: 输出音频文件路径
            voice: 忽略（静音模式）
            rate: 忽略（静音模式）
            duration_sec: 指定静音时长（秒），如果不提供则按文本长度估算

        Returns:
            (audio_path, empty_cues_dict) 元组
        """
        if duration_sec is None:
            # 估算时长：中文 4 字/秒
            duration_sec = max(len(text) / 4.0, 1.0)

        logger.info(f"[TTS] Generating silent audio: {duration_sec:.1f}s → {output_path}")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # 使用 ffmpeg 生成静音音频
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono",
            "-t", str(duration_sec),
            "-c:a", "libmp3lame",
            "-q:a", "4",
            output_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        # P9: 检查 ffmpeg 返回码，失败时抛出异常而非静默返回
        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:500] if stderr else ""
            raise RuntimeError(
                f"[TTS] ffmpeg silent generation failed (code {proc.returncode}): {err_msg}"
            )

        # 返回空 cues
        return output_path, {}
