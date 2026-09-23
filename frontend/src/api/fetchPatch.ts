/**
 * frontend/src/api/fetchPatch.ts — 全局 fetch 拦截（v7.0，issue #64）。
 *
 * 在应用启动时安装一次，之后**所有** ``window.fetch`` 调用（包括第三方库、
 * 组件里的一次性 ``fetch('/api/xxx')``、以及 ``api/index.ts`` 里的 ``apiFetch``）
 * 都会自动带上 ``X-Agnes-UI-Lang`` 头，让后端把用户可见消息按当前 UI 语言返回。
 *
 * 为什么用 monkey-patch 而不是逐个 call site 改：
 * - ``api/index.ts`` 之外还有 8+ 个组件/composable 直接调 ``fetch``；
 * - 未来新增的调用点若忘记走 ``apiFetch``，语言头会静默丢失，回归很难发现；
 * - Patch 只在 ``Headers`` 里追加一个字段，不改变 body / method / 其他行为，
 *   风险可控；且已经尊重调用方显式设置的同名头（不覆盖）。
 *
 * 卸载：本模块不提供卸载入口。测试环境如需干净 fetch，请在装载本模块前
 * mock ``window.fetch``。
 */

import { UI_LANG_HEADER, getUiLang } from './langHeader'

let installed = false

/**
 * 安装全局 fetch 拦截；重复调用是幂等的（只安装一次）。
 */
export function installFetchLangHeader(): void {
  if (installed) return
  if (typeof window === 'undefined' || typeof window.fetch !== 'function') return

  const originalFetch = window.fetch.bind(window)

  const patched: typeof window.fetch = (input, init) => {
    try {
      const lang = getUiLang()
      // Request 对象形态：复制 headers 后追加
      if (input instanceof Request) {
        const headers = new Headers(input.headers)
        if (!headers.has(UI_LANG_HEADER)) headers.set(UI_LANG_HEADER, lang)
        // 保留原 Request 的其他属性（method/body/mode 等）
        const cloned = new Request(input, { headers })
        return originalFetch(cloned, init)
      }
      // 字符串 / URL 形态：走 init.headers
      const nextInit: RequestInit = { ...(init || {}) }
      const existing = nextInit.headers
      if (existing instanceof Headers) {
        if (!existing.has(UI_LANG_HEADER)) existing.set(UI_LANG_HEADER, lang)
        nextInit.headers = existing
      } else if (Array.isArray(existing)) {
        const hasLang = existing.some(
          ([k]) => k.toLowerCase() === UI_LANG_HEADER.toLowerCase(),
        )
        nextInit.headers = hasLang
          ? existing
          : [...existing, [UI_LANG_HEADER, lang]]
      } else if (existing && typeof existing === 'object') {
        const record = existing as Record<string, string>
        const hasLang = Object.keys(record).some(
          (k) => k.toLowerCase() === UI_LANG_HEADER.toLowerCase(),
        )
        nextInit.headers = hasLang ? record : { ...record, [UI_LANG_HEADER]: lang }
      } else {
        nextInit.headers = { [UI_LANG_HEADER]: lang }
      }
      return originalFetch(input as string | URL, nextInit)
    } catch {
      // 拦截失败时不阻断请求，退回原始 fetch（宁可丢语言头也不打断业务）
      return originalFetch(input as string | URL, init)
    }
  }

  window.fetch = patched
  installed = true
}
