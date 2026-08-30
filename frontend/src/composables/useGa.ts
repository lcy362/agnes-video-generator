// GA4 埋点（固定 Measurement ID，统一收集用户操作数据）
const GA_MEASUREMENT_ID = 'G-RQW2189QSK'
const GA_OPT_OUT_KEY = 'ga_opt_out'
let gaEnabled = false

// 3.4：隐私开关——localStorage 'ga_opt_out' === '1' 时完全不加载 GA
function isGaOptedOut(): boolean {
  try {
    return localStorage.getItem(GA_OPT_OUT_KEY) === '1'
  } catch {
    return false
  }
}

function setGaOptOut(on: boolean) {
  try {
    if (on) localStorage.setItem(GA_OPT_OUT_KEY, '1')
    else localStorage.removeItem(GA_OPT_OUT_KEY)
  } catch {
    /* ignore */
  }
}

function initGA() {
  if (gaEnabled || isGaOptedOut()) return
  gaEnabled = true
  try {
    window.dataLayer = window.dataLayer || []
    window.gtag = function (...args: unknown[]) {
      window.dataLayer!.push(args)
    }
    const s = document.createElement('script')
    s.async = true
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(GA_MEASUREMENT_ID)
    document.head.appendChild(s)
    window.gtag('js', new Date())
    window.gtag('config', GA_MEASUREMENT_ID)
  } catch (e) {
    console.warn('GA init failed:', e)
    gaEnabled = false
  }
}

// 3.4：上报脱敏——内容类字段（prompt/idea/诗词等）不进入 GA，
// 避免用户创作内容与 API Key 外泄到第三方分析
const SENSITIVE_KEYS = new Set([
  'prompt', 'idea', 'poem', 'poem_text', 'manuscript_text', 'script_text',
  'text', 'api_key', 'reference_image', 'end_frame_images', 'negative', 'system',
])

function sanitizeParams(params?: Record<string, unknown>): Record<string, unknown> {
  if (!params) return {}
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(params)) {
    if (SENSITIVE_KEYS.has(k)) {
      out[k] = typeof v === 'string' && v.length > 0 ? '<redacted>' : v
      continue
    }
    // 任何字符串值 > 200 字符一律截断，防止意外外泄长文本
    out[k] = typeof v === 'string' && v.length > 200 ? v.slice(0, 200) + '…' : v
  }
  return out
}

// 统一事件上报
function trackEvent(name: string, params?: Record<string, unknown>) {
  if (!gaEnabled || typeof window.gtag !== 'function') return
  try {
    window.gtag('event', name, sanitizeParams(params))
  } catch {
    /* 静默 */
  }
}

// 任务结果去重上报
const trackedTaskResults: Record<string, string> = {}
function trackTaskResultOnce(name: string, taskId: string, params?: Record<string, unknown>) {
  if (trackedTaskResults[taskId] === name) return
  trackedTaskResults[taskId] = name
  trackEvent(name, params || {})
}

// 异常去重上报
let lastErrSig = ''
let lastErrTime = 0
function reportException(description: string, fatal?: boolean) {
  const now = Date.now()
  if (description === lastErrSig && now - lastErrTime < 10000) return
  lastErrSig = description
  lastErrTime = now
  trackEvent('exception', {
    description: (description || '').slice(0, 500),
    fatal: fatal ? '1' : '0',
  })
}

// 全局错误捕获
function initErrorListeners() {
  window.addEventListener('error', (e) => {
    reportException((e.message || 'Unknown error') + ' @ ' + (e.filename || 'inline') + ':' + (e.lineno || 0), true)
  })
  window.addEventListener('unhandledrejection', (e) => {
    let msg = ''
    const r = e.reason
    if (r instanceof Error) msg = r.message
    else if (r != null) msg = String(r)
    reportException('Unhandled promise rejection: ' + (msg || 'unknown'), false)
  })
}

export function useGa() {
  return { initGA, trackEvent, trackTaskResultOnce, reportException, initErrorListeners, isGaOptedOut, setGaOptOut }
}

declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}
