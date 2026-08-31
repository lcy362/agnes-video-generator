"""预览路由：脚本/分段的同步「干跑」预览，不创建 TaskManager/后台任务。

供独立本地伴侣工具（如 agnes-simple-ui）在提交正式生成任务前，
先展示 LLM 将要写出的故事/脚本/旁白（创意模式），或稿件的自动分段结果
（稿件模式），供用户确认后再点击生成。

⚠️ 成本说明（PRD 1.1）：``preview-script`` 每次调用 = **3 次真实 LLM Chat
调用**（develop_story + write_script + generate_narration_for_video），
与正式创意任务走完全相同的 Screenwriter 调用序列、消耗共享限速桶配额，
**并非零成本接口**。调用方（尤其是第三方工具）不应将其当作免费接口高频轮询。

防滥用（PRD 1.1a）：preview 不经 ``WeightedSemaphore`` 流水线并发门控，
此处增加进程内并发上限（``_PreviewGate``，默认 2），超限直接返回
429 + Retry-After；LLM 调用本身走共享限速桶（与 Chat 一致）。

Port: PR #33 by @Khaled97Sho（content_lang 白名单校验、语速估算/变音符号
剥离收敛为公共函数，移除对 manuscript_video 私有函数的导入）。
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Form, HTTPException

from core.audio.voices import duration_len, estimate_chars_per_sec
from core.config import API_KEY_MISSING_MSG, get_api_key, get_selected_models
from core.pipelines.manuscript_video import split_manuscript_text
from core.screenwriter import Screenwriter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])

# content_lang 白名单（v0.2 修订 #5）：不再有"未知语言静默默认阿拉伯语"。
# 语言指令只对已知可可靠跟随的语言生效；越界直接 422。
_CONTENT_LANG_LABELS = {"ar": "Arabic", "en": "English"}

# ── 进程内并发上限（PRD 1.1a）──
# preview 不经 WeightedSemaphore 流水线门控，若不加防护，一个循环脚本可以在
# 正式任务之外无限制地刷 LLM 调用。超限返回 429 + Retry-After。
#
# 注意：不用 asyncio.Semaphore + wait_for(timeout=0) 做 try-acquire——
# 事件循环单线程下「检查 _value 后立即 await acquire」虽无竞态，但依赖私有
# 属性；wait_for(0) 则会因 timeout=0 立即超时导致已获取的槽位泄漏（永久 429）。
# 因此用显式计数器 + 锁实现非阻塞闸门。
_PREVIEW_CONCURRENCY_LIMIT = 2


class _PreviewGate:
    """预览并发闸：非阻塞获取槽位，超限立即失败（不排队等待）。

    Args:
        limit: 同时允许的最大预览请求数。
    """

    def __init__(self, limit: int):
        self._limit = limit
        self._count = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        """尝试占用一个槽位；已满返回 False（不阻塞）。"""
        async with self._lock:
            if self._count >= self._limit:
                return False
            self._count += 1
            return True

    async def release(self) -> None:
        """释放一个槽位。"""
        async with self._lock:
            self._count = max(0, self._count - 1)


_PREVIEW_GATE = _PreviewGate(_PREVIEW_CONCURRENCY_LIMIT)


async def _acquire_preview_slot() -> None:
    """获取预览并发槽位；已满时抛 429 + Retry-After。"""
    if not await _PREVIEW_GATE.try_acquire():
        raise HTTPException(
            status_code=429,
            detail=(
                f"预览请求过于频繁，请稍后重试"
                f"（同时最多 {_PREVIEW_CONCURRENCY_LIMIT} 个预览）"
            ),
            headers={"Retry-After": "5"},
        )


async def _release_preview_slot() -> None:
    """释放预览并发槽位（配合 _acquire_preview_slot 使用）。"""
    try:
        await _PREVIEW_GATE.release()
    except Exception as e:  # pragma: no cover - 防御：释放失败不影响主流程
        logger.warning("[Preview] failed to release slot: %s", e)


def _language_directive(content_lang: str) -> str:
    """构建一条显式语言指令，前置到 style 字段。

    仅让模型"跟随输入语言"（develop_story/write_script/generate_narration_for_video
    自带的系统提示词已包含该指令）在实测中不够可靠——同一个英文 idea 有时仍会被
    写成中文故事/旁白。显式声明目标语言（同时保留"场景视觉提示词用英文"的既有
    约定，因为视频生成模型对英文提示词响应更精确）能稳定复现预期语言。
    """
    label = _CONTENT_LANG_LABELS[content_lang]  # 调用前已白名单校验
    return (
        f"IMPORTANT: Write the story and the narration text in {label} only — "
        f"do not use any other language. For scene visual prompts specifically, "
        f"still write in English instead (video generation models respond more "
        f"precisely to English prompts).\n\n"
    )


def _split_narration_by_scene(narration: str, scene_durations: list) -> list:
    """按每个场景时长占比，把单段连续旁白近似切成逐场景片段，仅用于预览展示。

    实际生成仍使用完整的单段连续旁白（一次性 TTS，音画对齐由 concatenator 处理），
    这里只是把同一段文本按比例、在词边界处切开，让用户预览"大致哪段话对应哪个
    场景"，而不是展示对视频生成更关键、但对用户预览意义不大的英文视觉提示词。
    """
    total_duration = sum(scene_durations) or 1
    total_chars = len(narration)
    boundaries = [0]
    acc = 0.0
    for d in scene_durations[:-1]:
        acc += d
        target = int(total_chars * acc / total_duration)
        # 就近找一个空格/标点断点，避免把单词切断。
        window = 15
        best = target
        for offset in range(window + 1):
            for candidate in (target + offset, target - offset):
                if 0 < candidate < total_chars and narration[candidate - 1] in " ，.!؟,.!?":
                    best = candidate
                    break
            else:
                continue
            break
        boundaries.append(min(max(best, boundaries[-1]), total_chars))
    boundaries.append(total_chars)

    segments = []
    for i in range(len(scene_durations)):
        segments.append(narration[boundaries[i]:boundaries[i + 1]].strip())
    return segments


def _parse_scene_durations(scene_durations_json: str) -> list:
    try:
        durations = json.loads(scene_durations_json)
        if not isinstance(durations, list):
            raise ValueError("not a list")
    except Exception:
        raise HTTPException(status_code=422, detail="scene_durations_json 必须为 JSON 数组")
    for i, d in enumerate(durations):
        if not isinstance(d, (int, float)) or d < 2 or d > 30:
            raise HTTPException(status_code=422, detail=f"场景 {i + 1} 时长范围 2-30 秒")
    return durations


@router.post("/api/creative/preview-script")
async def preview_creative_script(
    idea: str = Form(...),
    style: str = Form(""),
    scene_count: int = Form(5),
    scene_durations_json: str = Form("[8,8,8,8,8]"),
    content_lang: str = Form("ar"),
    add_tashkeel: bool = Form(False),
):
    """同步生成故事 + 分场景脚本 + 旁白文案，供确认后再提交正式创意任务。

    与 create_creative_task（web/routes/task_creation_routes.py）使用完全相同的
    Screenwriter 调用序列（develop_story -> write_script -> generate_narration_for_video），
    只是不创建 TaskManager/后台任务，直接返回 JSON。

    ⚠️ 每次调用消耗 3 次真实 LLM 调用（共享限速桶配额），并非零成本。
    """
    await _acquire_preview_slot()
    try:
        api_key = get_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail=API_KEY_MISSING_MSG)

        if not idea.strip():
            raise HTTPException(status_code=422, detail="idea 不能为空")
        if len(idea) > 10000:
            raise HTTPException(status_code=422, detail="idea 最多 10000 字符")
        if scene_count < 1 or scene_count > 30:
            raise HTTPException(status_code=422, detail="scene_count 范围 1-30")
        # v0.2 修订 #5：content_lang 白名单校验，越界 422，不再静默默认阿拉伯语
        if content_lang not in _CONTENT_LANG_LABELS:
            raise HTTPException(
                status_code=422,
                detail=f"content_lang 必须为 {sorted(_CONTENT_LANG_LABELS)} 之一",
            )
        scene_durations = _parse_scene_durations(scene_durations_json)
        style = _language_directive(content_lang) + style

        text_model = get_selected_models()["text"]
        # 显式指定 language="en"：Screenwriter 的系统提示词默认使用 PROMPT_LANGUAGE
        # 环境变量（默认 "zh"），而非固定跟随输入语言。中文系统提示词会让模型倾向于
        # 输出中文，即使提示词本身写明"使用与输入相同的语言"——实测英文 idea 在中文
        # 系统提示词下会被错误地写成中文故事/旁白。英文系统提示词经验证对阿拉伯语和
        # 英语输入都能正确遵循"与输入语言一致"的规则，因此固定使用 "en"。
        screenwriter = Screenwriter(api_key=api_key, model=text_model, language="en")

        story = await asyncio.to_thread(
            screenwriter.develop_story, idea, "", style, "", scene_count, scene_durations,
        )
        scenes = await asyncio.to_thread(
            screenwriter.write_script, story, "", style, scene_count, scene_durations,
        )
        total_duration = sum(float(d) for d in scene_durations) if scene_durations else float(scene_count * 5)
        narration = await asyncio.to_thread(
            screenwriter.generate_narration_for_video, story, scenes, total_duration, style,
        )

        if add_tashkeel:
            from core.audio.tashkeel import add_tashkeel_safe

            narration = add_tashkeel_safe(narration)

        narration_by_scene = _split_narration_by_scene(narration, scene_durations)

        return {
            "ok": True,
            "story": story,
            "scenes": scenes,
            "narration": narration,
            "narration_by_scene": narration_by_scene,
        }
    finally:
        await _release_preview_slot()


@router.post("/api/manuscript/preview-split")
async def preview_manuscript_split(
    manuscript_text: str = Form(...),
    add_tashkeel: bool = Form(False),
):
    """按稿件模式的真实分段算法预览段落划分，不创建任务。

    与正式稿件任务共用 ``split_manuscript_text``（PRD 1.6）与公共语速估算
    （``estimate_chars_per_sec`` / ``duration_len``，PRD 1.3a）；本端点不调用 LLM。
    """
    await _acquire_preview_slot()
    try:
        if not manuscript_text.strip():
            raise HTTPException(status_code=400, detail="稿件内容不能为空")
        if len(manuscript_text) > 50000:
            raise HTTPException(status_code=422, detail="稿件文本最多 50000 字符")

        texts = split_manuscript_text(manuscript_text)
        chars_per_sec = estimate_chars_per_sec(manuscript_text)

        if add_tashkeel:
            from core.audio.tashkeel import add_tashkeel_safe

            texts = [add_tashkeel_safe(t) for t in texts]

        paragraphs = [
            {
                "index": i,
                "text": t,
                "est_duration_sec": round(duration_len(t) / chars_per_sec, 1),
            }
            for i, t in enumerate(texts)
        ]
        total_duration = round(sum(p["est_duration_sec"] for p in paragraphs), 1)
        return {"ok": True, "paragraphs": paragraphs, "total_duration_sec": total_duration}
    finally:
        await _release_preview_slot()
