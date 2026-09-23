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
