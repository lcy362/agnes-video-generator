"""音色路由：目录列表、试听（带缓存）、兼容性查询。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.audio.voices import (
    LANG_COMPAT,
    get_voice_catalog,
    get_voice_lang,
    is_voice_compatible,
)
from web import helpers

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voices"])


@router.get("/api/voices")
async def get_voices():
    """返回按语言分组的可选 TTS 语音角色列表（含兼容性提示）。

    响应结构：
    {
      "languages": [
        {"code": "zh", "label": "中文", "count": N, "voices": [ {id,name,region,gender,style_tags,preview_text,lang}, ... ]},
        ...
      ],
      "compat_hint": { "zh": ["zh","en"], ... }
    }
    """
    return get_voice_catalog()


@router.get("/api/voices/preview")
async def preview_voice(voice: str, text: str = ""):
    """返回音色试听音频（audio/mpeg），带服务端缓存。

    - voice: 必填，音色 id
    - text: 选填，试听文本；缺省时使用该音色语言的预设试听句
    - 跨语言不兼容时 edge_tts 抛异常，返回 400 + 明确错误信息
    """
    if not voice:
        raise HTTPException(status_code=400, detail="缺少 voice 参数")
    preview_text = helpers._resolve_preview_text(voice, text)
    try:
        cache_path = await helpers._get_or_generate_preview(voice, preview_text)
    except Exception as e:
        logger.warning(f"[Preview] voice={voice} failed: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"该音色不支持此语言的试听文本（跨文字体系无法朗读）：{e}",
        )
    return FileResponse(
        cache_path,
        media_type="audio/mpeg",
        filename=f"{voice}.mp3",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/voices/compat")
async def voice_compat(voice: str, target_lang: str):
    """查询 voice 与目标语言 target_lang 的兼容性。

    响应：{"compatible": bool, "voice_lang": str, "target_lang": str, "supported_langs": [...]}
    """
    vlang = get_voice_lang(voice)
    compatible = is_voice_compatible(voice, target_lang)
    supported = LANG_COMPAT.get(vlang, [vlang]) if vlang else []
    return {
        "compatible": compatible,
        "voice_lang": vlang,
        "target_lang": target_lang,
        "supported_langs": supported,
    }
