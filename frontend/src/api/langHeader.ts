/**
 * frontend/src/api/langHeader.ts — 统一的 UI 语言请求头（v7.0，issue #64）。
 *
 * 背景：后端生成的用户可见消息（网络诊断、任务排队中、AI 修改失败等）此前
 * 硬编码中文，英文/日文/阿拉伯语界面用户看到的仍然是中文，无法理解又误以为
 * 服务侧故障。修复方案是：
 *
 *   1. 前端在每次 fetch 上注入 ``X-Agnes-UI-Lang: <currentLang>`` 头；
 *   2. 后端 ``web.middleware.LangContextMiddleware`` 把它写入 ContextVar；
 *   3. 请求同步路径（HTTPException）通过 ``translate(key)`` 自动读上下文；
 *   4. 任务创建端点额外把语言快照落盘到 ``BaseTaskState.ui_language``，
 *      供异步 Pipeline 在整个任务生命周期里保持一致的语种。
 *
 * 为什么不用浏览器自动发的 ``Accept-Language``：那是**浏览器**语言偏好，
 * 用户在应用内切到别的语言（localStorage ``lang``）时两者会不一致，
 * 以应用内选择为准更符合直觉。
 */

import { currentLang } from '@/i18n'

/** 后端识别的请求头名称，与 ``core.i18n_backend.UI_LANG_HEADER`` 保持一致。 */
export const UI_LANG_HEADER = 'X-Agnes-UI-Lang'

/**
 * 读取当前 UI 语言（与 ``useI18n().lang`` 同源），非法/空值回退 ``zh``。
 */
export function getUiLang(): string {
  const raw = (currentLang.value || '').trim()
  return raw || 'zh'
}

/**
 * 合并调用方传入的 headers 与 UI 语言头，返回新的 ``HeadersInit``。
 *
 * - 调用方已经显式设置了 ``X-Agnes-UI-Lang`` → 尊重调用方（便于测试注入）；
 * - 调用方传入 ``Headers`` 实例 → 复制后追加；
 * - 调用方传入普通对象 / 数组 → 归一化为对象后追加；
 * - 未传 headers → 返回只含 UI 语言头的对象。
 */
export function withUiLangHeader(init?: HeadersInit): HeadersInit {
  const lang = getUiLang()
  if (!init) return { [UI_LANG_HEADER]: lang }

  if (init instanceof Headers) {
    const next = new Headers(init)
    if (!next.has(UI_LANG_HEADER)) next.set(UI_LANG_HEADER, lang)
    return next
  }

  if (Array.isArray(init)) {
    const next = new Headers(init)
    if (!next.has(UI_LANG_HEADER)) next.set(UI_LANG_HEADER, lang)
    return next
  }

  // 普通对象（Record<string, string>）
  const record = init as Record<string, string>
  // 大小写不敏感检测：调用方可能已经写了 'x-agnes-ui-lang'
  const alreadySet = Object.keys(record).some(
    (k) => k.toLowerCase() === UI_LANG_HEADER.toLowerCase(),
  )
  return alreadySet ? record : { ...record, [UI_LANG_HEADER]: lang }
}
