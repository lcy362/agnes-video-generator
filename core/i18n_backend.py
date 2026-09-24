"""core.i18n_backend — 后端用户可见消息的多语言运行时（v7.0）。

背景（GitHub issue #64）：此前 ``utils/network.py::describe_network_error`` 与
``core/config.py::API_KEY_MISSING_MSG`` 等**后端生成的用户可见文案**是硬编码中文，
无论前端切到英文/日文/阿拉伯语都会照原样展示，用户看不懂又误以为是「服务侧故障」。
本模块提供最小可运行的后端 i18n 基础设施：

- ``SUPPORTED_UI_LANGS``：与前端 ``frontend/src/i18n/index.ts::LANGS`` 对齐的 22 语言集合；
- ``normalize_lang(raw)``：把 ``X-Agnes-UI-Lang`` / ``Accept-Language`` / 用户表单里
  的语言标识归一到我们支持的 2 字母代码，未知一律回退 ``zh``（与前端 ``t()`` 的
  回退策略一致）；
- ``translate(key, lang, **params)``：从 ``CATALOG`` 里取模板，``str.format(**params)``
  渲染；缺 key 或缺语言时**先回退 zh，再回退 key 名**（不抛异常，避免把 i18n 缺陷
  放大成任务失败）；
- ``current_lang`` / ``set_current_lang`` / ``get_current_lang``：基于 ``ContextVar``
  的请求级语言上下文，由 ``web.middleware.LangContextMiddleware`` 在 HTTP 请求进入
  时写入，供 ``HTTPException`` 抛出路径与短生命周期同步代码读取；
- ``resolve_lang(explicit, request)``：统一优先级 —— 显式参数 > 请求上下文 > ``zh``。

**语言范围**：本轮 PR 只补齐 zh / en 两种（issue_handling_process.md 里也约定
zh/en 是 i18n 的双基线，缺一不可）。其余 20 语言的翻译留给后续批次
（``docs/plans/v7.0/backend_i18n_plan.md``），运行时会自动回退 zh，
行为与前端 ``t()`` 一致。

**不做什么**：
- 不翻译 ``logger.*`` 输出（那是给开发者的，语言固定即可）；
- 不翻译 LLM prompt（发给模型的内容，与用户 UI 语言解耦）；
- 不改变任何已存在的 API 响应字段名或状态码。
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from typing import Any, Dict, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "SUPPORTED_UI_LANGS",
    "DEFAULT_UI_LANG",
    "UI_LANG_HEADER",
    "normalize_lang",
    "parse_accept_language",
    "translate",
    "current_lang",
    "set_current_lang",
    "get_current_lang",
    "resolve_lang",
    "CATALOG",
]

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

#: 与前端 ``frontend/src/i18n/index.ts::LANGS`` 严格对齐的 22 语言代码。
#: 新增语言时必须同步更新前端 LANGS + ``frontend/src/i18n/langs/*.json``，
#: 否则前端 ``t()`` 会回退 zh 而用户切不到该语言。
SUPPORTED_UI_LANGS: frozenset[str] = frozenset({
    "zh", "en", "ru", "ja", "ko", "ms", "id", "de", "fr", "nl",
    "es", "pt", "it", "tr", "vi", "th", "hi", "bn", "tl", "ar",
    "fa", "ur",
})

#: 未知/缺失语言的统一回退，与前端 ``t()`` 一致。
DEFAULT_UI_LANG: str = "zh"

#: 前端在每次 ``fetch`` 上注入的请求头名称。选自定义头而非直接读
#: ``Accept-Language``，因为浏览器发出的 ``Accept-Language`` 反映的是**浏览器**
#: 语言偏好，而用户在应用内可能已经手动切到别的语言（localStorage 里存的
#: ``lang``），两者不一致时以应用内选择为准。
UI_LANG_HEADER: str = "X-Agnes-UI-Lang"

# ─────────────────────────────────────────────────────────────────────────────
# 语言归一化
# ─────────────────────────────────────────────────────────────────────────────

_LANG_TAG_RE = re.compile(r"([A-Za-z]{2,3})(?:[-_][A-Za-z0-9]+)*")


def normalize_lang(raw: Optional[str]) -> str:
    """把任意语言标识归一到 ``SUPPORTED_UI_LANGS`` 里的 2 字母代码。

    Args:
        raw: 原始语言字符串，例如 ``"en-US"``、``"zh_CN"``、``"ja"``、``None``、``""``。

    Returns:
        命中支持集合的 2 字母代码；未知/空一律回退 ``DEFAULT_UI_LANG``。

    Examples:
        >>> normalize_lang("en-US")
        'en'
        >>> normalize_lang("zh_Hans_CN")
        'zh'
        >>> normalize_lang("klingon")
        'zh'
        >>> normalize_lang(None)
        'zh'
    """
    if not raw:
        return DEFAULT_UI_LANG
    match = _LANG_TAG_RE.search(raw.strip())
    if not match:
        return DEFAULT_UI_LANG
    code = match.group(1).lower()
    return code if code in SUPPORTED_UI_LANGS else DEFAULT_UI_LANG


def parse_accept_language(header_value: Optional[str]) -> str:
    """解析 ``Accept-Language`` 头，返回首个我们支持的语言代码。

    遵循 RFC 7231 的 ``q`` 权重语法：``en-US,en;q=0.9,zh-CN;q=0.8``。
    权重相同时按出现顺序取首个命中支持集合的；全部不命中则回退
    ``DEFAULT_UI_LANG``。

    Args:
        header_value: 原始 ``Accept-Language`` 头字符串。

    Returns:
        归一化后的 2 字母语言代码。
    """
    if not header_value:
        return DEFAULT_UI_LANG
    entries: list[tuple[float, int, str]] = []
    for idx, part in enumerate(header_value.split(",")):
        chunk = part.strip()
        if not chunk:
            continue
        weight = 1.0
        if ";" in chunk:
            tag, _, params = chunk.partition(";")
            tag = tag.strip()
            for param in params.split(";"):
                param = param.strip()
                if param.lower().startswith("q="):
                    try:
                        weight = float(param[2:].strip())
                    except ValueError:
                        weight = 0.0
                    break
        else:
            tag = chunk
        entries.append((weight, idx, tag))
    # 权重降序 + 原序稳定
    entries.sort(key=lambda item: (-item[0], item[1]))
    for _, _, tag in entries:
        code = normalize_lang(tag)
        if code != DEFAULT_UI_LANG or normalize_lang(tag) == "zh":
            # 只有真正命中支持集合（且不是被 fallback 到 zh 的）才返回
            match = _LANG_TAG_RE.search(tag)
            if match and match.group(1).lower() in SUPPORTED_UI_LANGS:
                return code
    return DEFAULT_UI_LANG


# ─────────────────────────────────────────────────────────────────────────────
# 请求级语言上下文
# ─────────────────────────────────────────────────────────────────────────────

#: 请求级 UI 语言上下文。由 ``web.middleware.LangContextMiddleware`` 在 HTTP
#: 请求进入时 ``set_current_lang``，同步/异步代码均可通过 ``get_current_lang``
#: 读取；未设置时返回 ``DEFAULT_UI_LANG``。
current_lang: ContextVar[str] = ContextVar("agnes_ui_lang", default=DEFAULT_UI_LANG)


def set_current_lang(lang: Optional[str]) -> Any:
    """把归一化后的语言写入当前上下文，返回 ``Token`` 供 ``reset`` 使用。

    Args:
        lang: 原始语言字符串（会经 ``normalize_lang`` 归一化）。

    Returns:
        ``ContextVar.set`` 返回的 Token，调用方负责在 finally 里 ``reset``。
    """
    return current_lang.set(normalize_lang(lang))


def get_current_lang() -> str:
    """读取当前上下文的 UI 语言；未设置则返回默认 ``zh``。"""
    return current_lang.get()


def resolve_lang(explicit: Optional[str] = None) -> str:
    """按优先级确定当前应使用的 UI 语言。

    优先级：``explicit`` 参数 > 请求上下文 ``current_lang`` > ``DEFAULT_UI_LANG``。
    Pipeline 里通常把 ``state.ui_language`` 作为 ``explicit`` 传入，避免异步执行时
    请求上下文已切走。
    """
    if explicit:
        return normalize_lang(explicit)
    return get_current_lang()


# ─────────────────────────────────────────────────────────────────────────────
# 消息目录
# ─────────────────────────────────────────────────────────────────────────────

#: 后端用户可见消息目录：``{key: {lang: template}}``。
#:
#: 模板使用 ``str.format(**params)`` 渲染，占位符必须以关键字形式命名
#: （``{host}`` 而非 ``{0}``），便于翻译时调整语序。
#:
#: **约束**：新增/修改 key 时 zh 与 en 缺一不可，其余 20 语言允许暂时缺失
#: （``translate()`` 会回退 zh）。
CATALOG: Dict[str, Dict[str, str]] = {
    # ── 网络诊断（utils/network.py::describe_network_error）──
    "network.dns_failed": {
        "zh": (
            "网络诊断：本机无法解析域名 {target}（DNS 解析失败）。"
            "服务端任务通常已经完成，只是本机取不回结果文件。"
            "请依次检查：1) 换用能解析该域名的 DNS（国内推荐 223.5.5.5 或 119.29.29.29）；"
            "2) 关闭代理/VPN 的 DNS 劫持，检查安全软件与 hosts 是否拦截了该域名；"
            "3) Windows 执行 ipconfig /flushdns 后重新打开本页；"
            "4) 恢复后点「重试任务」从失败环节续传，已生成的视频不会重复提交。"
        ),
        "en": (
            "Network diagnosis: this machine cannot resolve {target} (DNS failure). "
            "The server-side job is usually already done — only the result file cannot "
            "be fetched back. Please check in order: "
            "1) switch to a DNS that can resolve the host (e.g. 223.5.5.5 / 119.29.29.29 "
            "in mainland China, or 1.1.1.1 / 8.8.8.8 elsewhere); "
            "2) disable proxy/VPN DNS hijacking, and check whether security software or "
            "the hosts file is blocking this domain; "
            "3) on Windows run `ipconfig /flushdns` and reload this page; "
            "4) once fixed, click \"Retry task\" to resume from the failed step — already "
            "generated videos will not be re-submitted."
        ),
    },
    "network.connect_blocked": {
        "zh": (
            "网络诊断：本机无法连接到 {target}（连接被拒绝或被拦截）。"
            "请检查代理、VPN、防火墙或安全软件是否拦截了该地址，"
            "放行后点「重试任务」从失败环节续传，已生成的视频不会重复提交。"
        ),
        "en": (
            "Network diagnosis: this machine cannot reach {target} "
            "(connection refused, reset, or intercepted). "
            "Please check whether a proxy, VPN, firewall, or security tool is blocking "
            "this address. Once unblocked, click \"Retry task\" to resume from the failed "
            "step — already generated videos will not be re-submitted."
        ),
    },
    "network.default_target": {
        "zh": "Agnes 服务域名",
        "en": "the Agnes service domain",
    },

    # ── API Key 缺失（core/config.py::API_KEY_MISSING_MSG 的替代）──
    "config.api_key_missing": {
        "zh": (
            "请先配置 API Key。免费获取：https://platform.agnes-ai.com ｜ "
            "不想配置？在线体验：https://video.lichuanyang.top/demo"
        ),
        "en": (
            "Please configure an API Key first. Get one for free at "
            "https://platform.agnes-ai.com — or try the hosted demo without setup at "
            "https://video.lichuanyang.top/demo"
        ),
    },

    # ── 任务生命周期（web/deps.py、core/pipelines/*）──
    "task.queued": {
        "zh": "任务排队中...",
        "en": "Task queued...",
    },
    "task.interrupted_resumable": {
        "zh": "任务已被中断，可从任务列表续传",
        "en": "Task interrupted. You can resume it from the task list.",
    },
    "task.start_failed": {
        "zh": "任务启动失败：{reason}",
        "en": "Failed to start task: {reason}",
    },
    "task.weight_exceeds_limit": {
        "zh": (
            "任务权重 {weight} 超过并发上限 {max_weight}"
            "（AGNES_RATE_LIMIT={rate_limit}，请调高该值或配置多个 API Key）"
        ),
        "en": (
            "Task weight {weight} exceeds the concurrency cap {max_weight} "
            "(AGNES_RATE_LIMIT={rate_limit}). Raise the limit or configure more API keys."
        ),
    },
    "task.awaiting_checkpoint": {
        "zh": "等待你在检查点 '{checkpoint}' 确认或修改产物",
        "en": "Waiting for you to review or edit artifacts at checkpoint '{checkpoint}'",
    },

    # ── 模式切换（web/routes/task_routes.py::switch_task_mode）──
    "mode.switched_to_manual": {
        "zh": "已切换为手动模式",
        "en": "Switched to manual mode",
    },
    "mode.switched_to_manual_at": {
        "zh": "已切换为手动模式，等待你在检查点 '{checkpoint}' 确认或修改产物",
        "en": (
            "Switched to manual mode. Waiting for you to review or edit artifacts "
            "at checkpoint '{checkpoint}'."
        ),
    },
    "mode.switched_to_auto": {
        "zh": "已切换为自动模式",
        "en": "Switched to auto mode",
    },
    "mode.manual_unsupported_task_type": {
        "zh": "该任务类型不支持手动模式",
        "en": "This task type does not support manual mode",
    },
    "mode.invalid": {
        "zh": "mode 必须为 auto 或 manual",
        "en": "mode must be either auto or manual",
    },

    # ── 图片保存失败（web/routes/image_routes.py）──
    "image.save_failed": {
        "zh": "图片保存失败: {reason}",
        "en": "Failed to save image: {reason}",
    },

    # ── AI 修改（web/routes/video_routes.py）──
    "ai_modify.failed": {
        "zh": "AI 修改失败：{reason}",
        "en": "AI modify failed: {reason}",
    },
    "ai_modify.image_regenerated": {
        "zh": "AI 已基于原图生成新版：{prompt}",
        "en": "AI regenerated the image based on the original: {prompt}",
    },
    "ai_modify.unsupported_category": {
        "zh": "该产物类型（{category}）暂不支持 AI 修改，请使用「在线编辑」或「自行处理」通道",
        "en": (
            "Artifact category ({category}) does not support AI modify yet. "
            "Please use \"Edit inline\" or \"Handle manually\" instead."
        ),
    },
    "ai_modify.diff_char_only": {
        "zh": "内容有变化（字符数 {old_len} → {new_len}）",
        "en": "Content changed (chars {old_len} → {new_len})",
    },
    "ai_modify.diff_no_change": {
        "zh": "未检测到内容变化",
        "en": "No content change detected",
    },
    "ai_modify.diff_summary": {
        "zh": "改动摘要：新增 {added} 行，删除 {removed} 行（字符数 {old_len} → {new_len}）",
        "en": (
            "Diff summary: +{added} / -{removed} lines "
            "(chars {old_len} → {new_len})"
        ),
    },

    # ── 文本供应商探测失败（web/routes/config_routes.py）──
    # 不携带异常原文：异常信息可能含服务端 URL / 内部细节，外泄属信息暴露
    # （CodeQL py/stack-trace-exposure）；详情只写服务端日志。
    "provider.probe_failed": {
        "zh": "模型探测失败：请检查 Base URL / API Key 与网络后重试",
        "en": "Model probe failed. Check the Base URL, API Key, and your network, then retry.",
    },

    # ── P1 流水线进度消息（core/pipelines/* + core/screenwriter，v7.0 backend i18n 收尾批次）──
    "progress.simple.start": {
        "zh": "开始简单视频生成...",
        "en": "Starting simple video generation...",
    },
    "progress.simple.done": {
        "zh": "视频生成完成!",
        "en": "Video generation complete!",
    },
    "progress.simple.resume_polling": {
        "zh": "恢复轮询视频任务 {vid}...",
        "en": "Resuming polling for video task {vid}...",
    },
    "progress.simple.submitting": {
        "zh": "提交视频任务 (mode={mode})...",
        "en": "Submitting video task (mode={mode})...",
    },
    "progress.simple.waiting": {
        "zh": "等待视频生成 {vid}...",
        "en": "Waiting for video generation {vid}...",
    },
    "progress.simple.completed": {
        "zh": "视频生成完成",
        "en": "Video generation complete",
    },
    "progress.multi_scene.init": {
        "zh": "开始视频生成...",
        "en": "Starting video generation...",
    },
    "progress.multi_scene.done": {
        "zh": "视频生成完成!",
        "en": "Video generation complete!",
    },
    "progress.multi_scene.scenes_running": {
        "zh": "构建分镜",
        "en": "Building scenes",
    },
    "progress.multi_scene.scenes_done": {
        "zh": "分镜构建完成",
        "en": "Scenes built",
    },
    "progress.multi_scene.reference_running": {
        "zh": "生成参考图",
        "en": "Generating reference images",
    },
    "progress.multi_scene.reference_done": {
        "zh": "参考图生成完成",
        "en": "Reference images generated",
    },
    "progress.multi_scene.videos_running": {
        "zh": "生成视频",
        "en": "Generating videos",
    },
    "progress.multi_scene.videos_done": {
        "zh": "视频生成完成",
        "en": "Videos generated",
    },
    "progress.multi_scene.audio_running": {
        "zh": "生成配音",
        "en": "Generating narration",
    },
    "progress.multi_scene.audio_done": {
        "zh": "配音完成",
        "en": "Narration done",
    },
    "progress.multi_scene.subtitles_running": {
        "zh": "生成字幕",
        "en": "Generating subtitles",
    },
    "progress.multi_scene.subtitles_done": {
        "zh": "字幕完成",
        "en": "Subtitles done",
    },
    "progress.multi_scene.composite_running": {
        "zh": "合成视频",
        "en": "Compositing final video",
    },
    "progress.multi_scene.composite_done": {
        "zh": "合成完成",
        "en": "Compositing done",
    },
    "progress.multi_scene.wait_videos": {
        "zh": "等待 {n} 个视频生成...",
        "en": "Waiting for {n} videos to generate...",
    },
    "progress.multi_scene.save_video": {
        "zh": "保存视频 {cur}/{total}...",
        "en": "Saving video {cur}/{total}...",
    },
    "progress.multi_scene.gen_audio": {
        "zh": "生成配音 ({chars} 字)...",
        "en": "Generating narration ({chars} chars)...",
    },
    "screenwriter.image_analyze_failed": {
        "zh": "图片分析失败（{label}）: {reason}",
        "en": "Image analysis failed ({label}): {reason}",
    },
    "progress.creative_script.analyzing_images": {
        "zh": "分析 {n} 张图片...",
        "en": "Analyzing {n} image(s)...",
    },
    "progress.creative_script.image_analysis_done": {
        "zh": "图片分析完成 ({chars} 字符)",
        "en": "Image analysis done ({chars} chars)",
    },
    "progress.creative_script.extracting_scene_info": {
        "zh": "正在从创意描述中提取场景信息...",
        "en": "Extracting scene info from your idea...",
    },
    "progress.creative_script.scene_info_extracted": {
        "zh": "从 prompt 提取: {n} 个场景, 时长 {durations}",
        "en": "Extracted from prompt: {n} scene(s), durations {durations}",
    },
    "progress.creative_script.scene_extract_failed": {
        "zh": "无法从创意描述中提取场景信息: {reason}",
        "en": "Could not extract scene info from your idea: {reason}",
    },
    "progress.creative_script.scene_extract_failed_retry_hint": {
        "zh": "场景信息提取失败: {reason}. 请手动设置场景数和每场景时长后重试。",
        "en": "Failed to extract scene info: {reason}. Set the scene count and per-scene durations manually, then retry.",
    },
    "progress.creative_script.scene_config_done": {
        "zh": "场景配置: {n} 个场景, 时长 {durations}",
        "en": "Scene config: {n} scene(s), durations {durations}",
    },
    "progress.creative_script.story_running": {
        "zh": "正在生成故事...",
        "en": "Generating the story...",
    },
    "progress.creative_script.story_done": {
        "zh": "故事生成完成 ({chars} 字符)",
        "en": "Story generated ({chars} chars)",
    },
    "progress.creative_script.character_ref_user_image": {
        "zh": "使用用户提供的参考图",
        "en": "Using your provided reference image",
    },
    "progress.creative_script.character_ref_cached": {
        "zh": "角色参考图已缓存",
        "en": "Character reference image found in cache",
    },
    "progress.creative_script.character_ref_extracting": {
        "zh": "正在提取角色描述并生成参考图...",
        "en": "Extracting character description and generating reference image...",
    },
    "progress.creative_script.character_ref_generating": {
        "zh": "正在生成角色参考图 (t2i)...",
        "en": "Generating character reference image (t2i)...",
    },
    "progress.creative_script.character_ref_done": {
        "zh": "角色参考图生成完成",
        "en": "Character reference image generated",
    },
    "progress.creative_script.script_running": {
        "zh": "正在编写脚本...",
        "en": "Writing the script...",
    },
    "progress.creative_script.script_done": {
        "zh": "脚本完成，共 {n} 个场景",
        "en": "Script complete, {n} scene(s) total",
    },
    "progress.creative_script.end_frame_prompts_running": {
        "zh": "正在生成尾帧提示词...",
        "en": "Generating end-frame prompts...",
    },
    "progress.creative_script.end_frame_prompts_done": {
        "zh": "尾帧提示词完成，共 {n} 个",
        "en": "End-frame prompts complete, {n} total",
    },
    "progress.creative_frames.using_user_end_frame": {
        "zh": "场景 {i}/{total}: 使用自定义尾帧",
        "en": "Scene {i}/{total}: using your custom end frame",
    },
    "progress.creative_frames.end_frame_from_ref": {
        "zh": "场景 {i}/{total}: 基于参考图生成尾帧 (i2i)",
        "en": "Scene {i}/{total}: generating end frame from reference image (i2i)",
    },
    "progress.creative_frames.end_frame_auto": {
        "zh": "场景 {i}/{total}: 自动生成尾帧 (t2i)",
        "en": "Scene {i}/{total}: auto-generating end frame (t2i)",
    },
    "progress.creative_frames.end_frame_pregen_done": {
        "zh": "尾帧预生成全部完成 ({done}/{total})",
        "en": "All end frames pre-generated ({done}/{total})",
    },
    "progress.creative_video.scene_submit_ti2vid": {
        "zh": "场景 {i}/{total}: 提交任务 (ti2vid)...",
        "en": "Scene {i}/{total}: submitting task (ti2vid)...",
    },
    "progress.creative_video.wait_independent": {
        "zh": "等待 {n} 个视频生成完成 (independent)...",
        "en": "Waiting for {n} videos to finish generating (independent)...",
    },
    "progress.creative_video.scene_waiting": {
        "zh": "场景 {i}/{total}: 等待生成中...",
        "en": "Scene {i}/{total}: waiting for generation...",
    },
    "progress.creative_video.scene_done": {
        "zh": "场景 {i}/{total}: 完成",
        "en": "Scene {i}/{total}: done",
    },
    "progress.creative_video.scene_cached": {
        "zh": "场景 {i}/{total}: 已缓存",
        "en": "Scene {i}/{total}: cached",
    },
    "progress.creative_video.scene_resume_ti2vid": {
        "zh": "场景 {i}/{total}: 续传视频 (ti2vid)...",
        "en": "Scene {i}/{total}: resuming video (ti2vid)...",
    },
    "progress.creative_video.submit_batch_keyframes": {
        "zh": "提交 {n} 个视频任务 (keyframes)...",
        "en": "Submitting {n} video tasks (keyframes)...",
    },
    "progress.creative_video.scene_submit": {
        "zh": "场景 {i}/{total}: 提交任务...",
        "en": "Scene {i}/{total}: submitting task...",
    },
    "progress.creative_video.wait_batch": {
        "zh": "等待 {n} 个视频生成完成...",
        "en": "Waiting for {n} videos to finish generating...",
    },
    "progress.creative_audio.narration_generating": {
        "zh": "正在生成旁白文案...",
        "en": "Generating narration script...",
    },
    "progress.creative_audio.tts_generating": {
        "zh": "生成旁白音频...",
        "en": "Generating narration audio...",
    },
    "progress.creative_audio.silent_timeline": {
        "zh": "生成静音时间轴...",
        "en": "Generating silent timeline...",
    },
    "progress.creative_audio.audio_done": {
        "zh": "音频生成完成",
        "en": "Audio generation complete",
    },
    "progress.creative_audio.subtitle_generating": {
        "zh": "生成字幕...",
        "en": "Generating subtitles...",
    },
    "progress.creative_audio.subtitle_skipped": {
        "zh": "跳过字幕生成",
        "en": "Skipping subtitle generation",
    },
    "progress.creative_audio.subtitle_done": {
        "zh": "字幕生成完成",
        "en": "Subtitles generated",
    },
    "progress.creative_audio.concat_running": {
        "zh": "正在拼接视频...",
        "en": "Stitching videos...",
    },
    "progress.creative_audio.concat_done": {
        "zh": "视频拼接完成",
        "en": "Video stitching complete",
    },
    "progress.manuscript.build_scenes": {
        "zh": "生成 {n} 个场景描述...",
        "en": "Generating {n} scene descriptions...",
    },
    "progress.manuscript.scenes_all_failed": {
        "zh": "稿件场景描述生成全部失败 {n} 段，首个失败段落 index={index}，原因: {reason}",
        "en": "All {n} manuscript scene descriptions failed to generate. First failed paragraph index={index}, reason: {reason}",
    },
    "progress.manuscript.scene_prompts_done_partial": {
        "zh": "场景描述生成完成 ({ok}/{total} 段)，{failed} 段失败可 resume 重试",
        "en": "Scene descriptions done ({ok}/{total} paragraphs); {failed} failed and can be retried by resuming the task",
    },
    "progress.manuscript.scene_prompts_done": {
        "zh": "场景描述生成完成 ({n} 段)",
        "en": "Scene descriptions done ({n} paragraphs)",
    },
    "progress.manuscript.submit_video": {
        "zh": "提交视频 {i}/{total}",
        "en": "Submitting video {i}/{total}",
    },
    "progress.manuscript.wait_video": {
        "zh": "等待视频 {i}/{total} ({vid}...)",
        "en": "Waiting for video {i}/{total} ({vid}...)",
    },
    "progress.manuscript.generate_audio": {
        "zh": "生成整段旁白 ({n} 字)...",
        "en": "Generating full narration ({n} chars)...",
    },
    "progress.manuscript.generate_subtitles": {
        "zh": "生成整段字幕 ({n} 字, {m} 段)...",
        "en": "Generating full subtitles ({n} chars, {m} segments)...",
    },
    "progress.manuscript.concat_av": {
        "zh": "拼接 {n} 段视频+音频+字幕...",
        "en": "Concatenating {n} video segments with audio and subtitles...",
    },
    "progress.manuscript.concat_no_av": {
        "zh": "拼接 {n} 段视频（无音频字幕）...",
        "en": "Concatenating {n} video segments (no audio or subtitles)...",
    },
    "progress.poetry.no_valid_scenes": {
        "zh": "[Poetry] LLM 未返回有效场景，请重试",
        "en": "[Poetry] The LLM returned no valid scenes. Please retry.",
    },
    "progress.poetry.generate_audio": {
        "zh": "生成朗诵配音 {i}/{total}...",
        "en": "Generating narration {i}/{total}...",
    },
    "progress.poetry.generate_subtitle": {
        "zh": "生成字幕 {i}/{total}...",
        "en": "Generating subtitles {i}/{total}...",
    },
    "progress.poetry.composite_single_pass": {
        "zh": "合并合成 {n} 个场景（单链）...",
        "en": "Compositing {n} scenes in a single pass...",
    },
    "progress.poetry.composite_scene": {
        "zh": "合成场景 {i}/{total}...",
        "en": "Compositing scene {i}/{total}...",
    },
    "progress.anchor.image_running": {
        "zh": "生成主播形象图...",
        "en": "Generating anchor image...",
    },
    "progress.anchor.image_running_ref": {
        "zh": "基于参考图生成主播形象...",
        "en": "Generating anchor image from the reference...",
    },
    "progress.anchor.image_failed": {
        "zh": "主播形象生成失败: {reason}",
        "en": "Failed to generate anchor image: {reason}",
    },
    "progress.anchor.image_done": {
        "zh": "主播形象生成完成",
        "en": "Anchor image generated",
    },
    "progress.anchor.prompts_running_loop": {
        "zh": "生成循环优化动态描述...",
        "en": "Generating loop-optimized motion description...",
    },
    "progress.anchor.prompts_running_model_audio": {
        "zh": "生成含口播的视频描述...",
        "en": "Generating video description with speech...",
    },
    "progress.anchor.prompts_done": {
        "zh": "动态描述生成完成",
        "en": "Motion description generated",
    },
    "progress.anchor.clip_running": {
        "zh": "生成单段循环视频...",
        "en": "Generating the loop clip...",
    },
    "progress.anchor.clip_done": {
        "zh": "单段循环视频生成完成",
        "en": "Loop clip generated",
    },
    "progress.anchor.audio_running": {
        "zh": "生成整段读稿 ({n} 字)...",
        "en": "Generating full narration ({n} chars)...",
    },
    "progress.anchor.audio_done": {
        "zh": "读稿音频生成完成",
        "en": "Narration audio generated",
    },
    "progress.anchor.subtitle_running": {
        "zh": "生成整段字幕 ({n} 字)...",
        "en": "Generating full-script subtitles ({n} chars)...",
    },
    "progress.anchor.subtitle_done": {
        "zh": "字幕生成完成",
        "en": "Subtitles generated",
    },
    "progress.anchor.concat_running": {
        "zh": "循环拼接视频+音频+字幕...",
        "en": "Looping clip and combining video + audio + subtitles...",
    },

    # ── P2 路由参数校验消息（web/routes/*）──
    "validation.scene_durations_not_list": {
        "zh": "scene_durations_json 必须为 JSON 数组",
        "en": "scene_durations_json must be a JSON array",
    },
    "validation.scene_duration_range": {
        "zh": "场景 {scene_index} 时长范围 2-30 秒",
        "en": "Scene {scene_index} duration must be within 2-30 seconds",
    },
    "validation.execution_mode_invalid": {
        "zh": "execution_mode 必须为 auto 或 manual",
        "en": "execution_mode must be either auto or manual",
    },
    "validation.pause_points_not_list": {
        "zh": "pause_points 必须为 JSON 数组",
        "en": "pause_points must be a JSON array",
    },
    "validation.pause_point_invalid": {
        "zh": "非法暂停点: {invalid}，可选: {options}",
        "en": "Invalid pause points: {invalid}. Available: {options}",
    },
    "validation.mode_invalid": {
        "zh": "mode 必须为 {options} 之一，当前: {current}",
        "en": "mode must be one of {options}, got: {current}",
    },
    "validation.duration_invalid": {
        "zh": "duration 必须为 {options} 之一，当前: {current}",
        "en": "duration must be one of {options}, got: {current}",
    },
    "validation.prompt_too_long": {
        "zh": "prompt 最多 5000 字符",
        "en": "prompt must be at most 5000 characters",
    },
    "validation.idea_empty": {
        "zh": "idea 不能为空",
        "en": "idea must not be empty",
    },
    "validation.idea_too_long": {
        "zh": "idea 最多 10000 字符",
        "en": "idea must be at most 10000 characters",
    },
    "validation.duration_source_invalid": {
        "zh": "duration_source 必须为 manual 或 prompt",
        "en": "duration_source must be either manual or prompt",
    },
    "validation.scene_count_range": {
        "zh": "scene_count 范围 {min}-{max}",
        "en": "scene_count must be between {min} and {max}",
    },
    "validation.manuscript_empty": {
        "zh": "稿件内容不能为空",
        "en": "Manuscript content must not be empty",
    },
    "validation.manuscript_too_long": {
        "zh": "稿件文本最多 50000 字符",
        "en": "Manuscript text must be at most 50000 characters",
    },
    "validation.reference_images_map_not_list": {
        "zh": "reference_images_map 必须为 JSON 数组，元素为段落 index 的整数数组",
        "en": "reference_images_map must be a JSON array whose elements are integer arrays of paragraph indices",
    },
    "validation.poem_empty": {
        "zh": "古诗原文不能为空",
        "en": "Poem text must not be empty",
    },
    "validation.poem_too_long": {
        "zh": "古诗原文最多 2000 字符",
        "en": "Poem text must be at most 2000 characters",
    },
    "validation.video_duration_range": {
        "zh": "video_duration 范围 {min}-{max} 秒",
        "en": "video_duration must be between {min} and {max} seconds",
    },
    "validation.user_scene_prompts_not_list": {
        "zh": "user_scene_prompts_json 必须为 JSON 数组",
        "en": "user_scene_prompts_json must be a JSON array",
    },
    "validation.anchor_script_empty": {
        "zh": "口播稿件不能为空",
        "en": "Anchor script must not be empty",
    },
    "validation.anchor_script_too_long": {
        "zh": "口播稿件最多 50000 字符",
        "en": "Anchor script must be at most 50000 characters",
    },
    "preview.rate_limited": {
        "zh": "预览请求过于频繁，请稍后重试（同时最多 {limit} 个预览）",
        "en": "Too many preview requests, please retry shortly (at most {limit} previews at a time)",
    },
    "preview.content_lang_invalid": {
        "zh": "content_lang 必须为 {options} 之一",
        "en": "content_lang must be one of {options}",
    },
    "config.key_from_env_no_clear": {
        "zh": "API Key 来自环境变量，无法从界面清除",
        "en": "The API key comes from an environment variable and cannot be cleared from the UI",
    },
    "config.missing_key_param": {
        "zh": "Key 参数缺失",
        "en": "Missing key parameter",
    },
    "config.env_key_remove_elsewhere": {
        "zh": "该 Key 来自环境变量（含 .env），请在启动环境 / .env 中移除",
        "en": "This key comes from an environment variable (including .env). Remove it in the launch environment / .env instead",
    },
    "config.domain_suffix_invalid_clear": {
        "zh": "域名后缀必须为 {opts} 之一（或空以清除）",
        "en": "The domain suffix must be one of {opts} (or empty to clear)",
    },
    "config.env_key_no_domain": {
        "zh": "该 Key 来自环境变量，无法为它保存域名",
        "en": "This key comes from an environment variable, so its domain can't be saved",
    },
    "config.api_key_not_configured": {
        "zh": "未配置 API Key",
        "en": "No API key configured",
    },
    "config.text_model_empty": {
        "zh": "文本模型不能为空",
        "en": "The text model can't be empty",
    },
    "config.domain_suffix_invalid": {
        "zh": "域名后缀必须为 {opts} 之一",
        "en": "The domain suffix must be one of {opts}",
    },
    "config.api_scheme_invalid": {
        "zh": "协议(api)必须为 {opts} 之一",
        "en": "The protocol (api) must be one of {opts}",
    },
    "config.base_url_empty": {
        "zh": "base_url 不能为空",
        "en": "base_url can't be empty",
    },
    "config.provider_empty": {
        "zh": "provider 不能为空",
        "en": "provider can't be empty",
    },
    "config.models_json_invalid": {
        "zh": "models_json 必须为合法 JSON 数组",
        "en": "models_json must be a valid JSON array",
    },
    "config.builtin_provider_no_delete": {
        "zh": "内置 Agnes 供应商不可删除",
        "en": "The built-in Agnes provider can't be deleted",
    },
    "config.provider_not_found": {
        "zh": "供应商不存在: {name}",
        "en": "Provider not found: {name}",
    },
    "config.builtin_provider_no_sync": {
        "zh": "内置 Agnes 供应商无需同步模型",
        "en": "The built-in Agnes provider doesn't need model sync",
    },
    "config.models_json_empty": {
        "zh": "models_json 不能为空",
        "en": "models_json can't be empty",
    },
    "config.key_not_found": {
        "zh": "Key 不存在",
        "en": "Key not found",
    },
    "ai_modify.user_request_empty": {
        "zh": "user_request 不能为空",
        "en": "user_request cannot be empty",
    },
    "checkpoint.artifact_ids_not_array": {
        "zh": "modified_artifact_ids 必须为 JSON 数组",
        "en": "modified_artifact_ids must be a JSON array",
    },
    "checkpoint.json_required": {
        "zh": "modified_artifact_ids / param_updates 必须为 JSON",
        "en": "modified_artifact_ids / param_updates must be valid JSON",
    },
    "gallery.task_not_found": {
        "zh": "任务不存在",
        "en": "Task not found",
    },
    "gallery.thumbnail_failed": {
        "zh": "缩略图生成失败",
        "en": "Failed to generate thumbnail",
    },
    "gallery.video_not_found": {
        "zh": "成片不存在",
        "en": "Final video not found",
    },
    "image.size_invalid": {
        "zh": "size 必须为 {opts} 之一",
        "en": "size must be one of {opts}",
    },
    "preset.not_found": {
        "zh": "预设不存在",
        "en": "Preset not found",
    },
    "preset.system_readonly": {
        "zh": "系统预设为只读，不可删除",
        "en": "System presets are read-only and cannot be deleted",
    },
    "utility.cleanup_dir_failed": {
        "zh": "删除目录失败: {name}",
        "en": "Failed to delete directory: {name}",
    },
    "utility.cleanup_log_failed": {
        "zh": "删除日志失败",
        "en": "Failed to delete server log",
    },
    "utility.cleanup_manifest_failed": {
        "zh": "删除清单失败",
        "en": "Failed to delete manifest file",
    },
    "utility.cleanup_report_failed": {
        "zh": "删除报告失败: {name}",
        "en": "Failed to delete report: {name}",
    },
    "utility.cleanup_upload_failed": {
        "zh": "删除上传文件失败: {name}",
        "en": "Failed to delete uploaded file: {name}",
    },
    "utility.manifest_read_failed": {
        "zh": "读取清单失败: {reason}",
        "en": "Failed to read manifest: {reason}",
    },
    "utility.regression_manifest_missing": {
        "zh": "未找到回归测试产物清单，可能没有执行过回归测试",
        "en": "No regression test manifest found; the regression suite may not have been run",
    },
    "validation.prompt_empty": {
        "zh": "prompt 不能为空",
        "en": "prompt cannot be empty",
    },
    "voice.param_missing": {
        "zh": "缺少 voice 参数",
        "en": "Missing voice parameter",
    },
    "voice.preview_unsupported": {
        "zh": "该音色不支持此语言的试听文本（跨文字体系无法朗读）：{reason}",
        "en": "This voice cannot read the preview text of this language (crossing writing systems): {reason}",
    },
    "workspace.dir_not_found": {
        "zh": "工作目录不存在",
        "en": "Workspace not found",
    },
    "workspace.path_empty": {
        "zh": "path 不能为空",
        "en": "path cannot be empty",
    },
    "workspace.path_invalid": {
        "zh": "工作目录路径不合法或超出允许范围（可由 AGNES_WORKSPACE_ROOT 环境变量放宽）",
        "en": "Workspace path is invalid or outside the allowed range (set the AGNES_WORKSPACE_ROOT environment variable to widen it)",
    },

    # ── P3 音色兼容性校验（web/helpers.py::_validate_voice_compat）──
    "voice_compat.cross_script": {
        "zh": "所选音色 {voice} 不支持当前稿件语言的朗读（跨文字体系无法朗读，任务将失败）。请更换为匹配语言的音色。",
        "en": "Voice {voice} cannot read text in the manuscript's language (crossing writing systems; the task would fail). Please pick a voice that matches the language.",
    },
    "voice_compat.lang_unsupported": {
        "zh": "所选音色 {voice} 不支持「{lang_name}」语言的视频生成（仅支持：{supported}）。请更换音色或语言。",
        "en": "Voice {voice} does not support video generation in {lang_name} (supported: {supported} only). Please change the voice or the language.",
    },

}


def translate(key: str, lang: Optional[str] = None, **params: Any) -> str:
    """按语言渲染 ``CATALOG`` 里的模板。

    回退策略：目标语言缺失 → ``zh`` → ``en`` → ``key`` 本身。**永不抛异常**，
    避免翻译缺失把业务失败放大成 500。

    Args:
        key: ``CATALOG`` 中的键，如 ``"network.dns_failed"``。
        lang: 目标语言；``None`` 时走 ``resolve_lang()`` 读上下文。
        **params: 传给 ``str.format`` 的关键字参数。

    Returns:
        渲染后的字符串；找不到 key 时返回 ``key`` 本身（便于日志排查）。
    """
    entry = CATALOG.get(key)
    if not entry:
        logger.warning("[I18n] Missing catalog key: %s", key)
        return key
    target = resolve_lang(lang)
    template = entry.get(target) or entry.get(DEFAULT_UI_LANG) or entry.get("en")
    if template is None:
        # 目录里连 zh/en 都没有 —— 属于开发错误，返回 key 兜底
        logger.warning("[I18n] No zh/en fallback for key: %s", key)
        return key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError) as e:
        # 占位符缺失/多余：降级为原模板 + 参数附录，避免把用户可见消息整段吞掉
        logger.warning("[I18n] Format failed for key=%s lang=%s: %s", key, target, e)
        suffix = " ".join(f"{k}={v}" for k, v in params.items())
        return f"{template} [{suffix}]" if suffix else template


def available_langs_for(key: str) -> Iterable[str]:
    """返回某个 key 已翻译的语言集合（供 i18n 完整性检查工具调用）。"""
    return tuple(CATALOG.get(key, {}).keys())


def catalog_snapshot() -> Mapping[str, Mapping[str, str]]:
    """返回 ``CATALOG`` 的只读快照（供诊断端点/测试断言）。"""
    return {k: dict(v) for k, v in CATALOG.items()}
