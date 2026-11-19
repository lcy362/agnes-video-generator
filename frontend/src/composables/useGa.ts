// GA4 埋点（固定 Measurement ID，统一收集用户操作数据）
//
// ── 埋点契约（v8.2，改埋点前必读）──────────────────────────────────────────
// 1. 事件名只有 5 类业务事件 + 2 类通用事件，全部英文蛇形、与 UI 语言无关：
//      page_view            页面级 PV（SPA 自己发，page_key 为稳定键）
//      ui_click             任意按钮/可点控件的点击（action 为稳定键）
//      create_task(_failed) 任务提交成功 / 失败（转化终点）
//      task_completed/failed/stopped/deleted  任务结果与操作
//      api_error / exception 上游错误与前端异常
// 2. 多语言：事件名与 action **绝不**取 t('xxx') 的翻译结果，否则 22 种语言
//    会被拆成 22 个按钮。按钮的 i18n key（如 submit_simple_video）就是 action；
//    语言只作为 `lang` 维度上报，可用于「同一按钮在各语言下的转化对比」。
// 3. 转化口径：某按钮点击量 = ui_click{action} ；其转化 = 同一会话后续
//    create_task / task_completed。因此提交类按钮必须同时有 ui_click 与
//    create_task（click 是分母，create_task 是分子）。
// 4. 脱敏：用户创作内容（prompt/剧本/诗词/API Key 等）一律不入 GA，
//    见 SENSITIVE_KEYS；data-track-params 只允许枚举值、数字、布尔与稳定 id。
import { currentLang } from '@/i18n'

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

// 加载 gtag 脚本（PV 由 trackPageView 统一发送，见下）
function loadGtag() {
  window.dataLayer = window.dataLayer || []
  // 必须 push `arguments`（Arguments 对象）而非剩余参数数组：
  // Google Tag 只消费 arguments 形态的 dataLayer 条目，普通 Array 会被静默忽略，
  // 导致 config/event 全部丢失、collect 信标一次都不发（曾因此埋点完全不上报）。
  window.gtag = function () {
    window.dataLayer!.push(arguments as unknown as unknown[])
  } as (...args: unknown[]) => void
  const s = document.createElement('script')
  s.async = true
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(GA_MEASUREMENT_ID)
  document.head.appendChild(s)
  window.gtag('js', new Date())
  // 关闭自动 page_view：本应用是 hash 路由的单页，自动 PV 只在文档加载时触发一次，
  // 切 Tab 不产生 PV，且进度页 URL 含 taskId 会让 page_location 基数爆炸。
  // 改由 trackPageView 以稳定 page_key 上报（每个视图恰好一次）。
  window.gtag('config', GA_MEASUREMENT_ID, { send_page_view: false })
}

let initialized = false
function initGA() {
  if (initialized) return
  initialized = true
  try {
    // 3.4：隐私开关关闭（opt-out）时也上报一次匿名 page_view，保证 GA 的
    // PV/UV 统计准确；但 gaEnabled 保持 false，拦截后续事件/异常上报，
    // 不分享用户内容、API Key 等任何其他信息。
    loadGtag()
    gaEnabled = !isGaOptedOut()
    // 多标签页共享去重表：其他标签写入后同步失效缓存，避免同一任务被重复计数
    window.addEventListener('storage', (e) => {
      if (e.key === COMPLETED_KEY) completedCache = null
    })
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
    // 任何字符串值 > 100 字符一律截断，防止意外外泄长文本（按钮维度不需要长值）
    out[k] = typeof v === 'string' && v.length > 100 ? v.slice(0, 100) + '…' : v
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

// ── 页面级 PV ──────────────────────────────────────────────────────────────
// page_key 是稳定键（create / simple / list / gallery / progress），与语言、
// taskId 无关：22 种语言看到的「任务列表」在 GA 里始终是同一个页面。
let currentPageKey = 'create'

/** 上报一次页面浏览（App 切换视图时调用；opt-out 时仍保留匿名 PV，与旧行为一致） */
function trackPageView(pageKey: string, params?: Record<string, unknown>) {
  currentPageKey = pageKey
  if (typeof window.gtag !== 'function') return
  const payload = sanitizeParams({
    page_key: pageKey,
    page_path: '/' + pageKey,
    page_title: pageKey,
    lang: currentLang.value,
    ...params,
  })
  try {
    window.gtag('event', 'page_view', payload)
  } catch {
    /* 静默 */
  }
}

// ── 按钮级点击 ────────────────────────────────────────────────────────────
/**
 * 上报一次按钮点击。
 *
 * action 必须是稳定英文键（见模板里的 `data-track`），例如
 * `submit_simple_video` / `switch_task_type` / `checkpoint_continue`。
 * 禁止把翻译文案、taskId、用户输入塞进 action。
 */
function trackClick(action: string, params?: Record<string, unknown>) {
  if (!action) return
  trackEvent('ui_click', {
    action,
    page: currentPageKey,
    lang: currentLang.value,
    ...(params || {}),
  })
}

/**
 * 解析 `data-track-params`（JSON 字符串）。模板里用
 * `:data-track-params="JSON.stringify({ mode: 'manual' })"` 传枚举维度；
 * 解析失败按空对象处理，不能因此中断界面交互。
 */
function parseTrackParams(raw?: string | null): Record<string, unknown> {
  if (!raw) return {}
  try {
    const v = JSON.parse(raw)
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

let clickTrackingReady = false
// 去重窗口：<label data-track> 包裹 <input type="file"> 时，浏览器会先派发 label 的
// click、再派发 input 的 click，两次都会冒泡到代理 → 同一次操作会双计。
// 同 action + 同参数在 350ms 内只记一次；真实连点通常会带不同参数或间隔更久。
let lastClickSig = ''
let lastClickTime = 0
const CLICK_DEDUPE_MS = 350

function emitClickOnce(action: string, params: Record<string, unknown>) {
  const sig = action + '|' + JSON.stringify(params)
  const now = Date.now()
  if (sig === lastClickSig && now - lastClickTime < CLICK_DEDUPE_MS) return
  lastClickSig = sig
  lastClickTime = now
  trackClick(action, params)
}
/**
 * 全局点击代理：任何带 `data-track="<action>"` 的元素（含其内部文本/图标）
 * 被点击时上报 `ui_click`。用捕获阶段监听，避免组件内部 stopPropagation 漏报。
 *
 * 这样埋点与 UI 文案完全解耦：切换语言只改变渲染文本，`data-track` 不变，
 * 因此同一按钮在 22 种语言下始终落在同一个 action 上。
 */
function initClickTracking() {
  if (clickTrackingReady) return
  clickTrackingReady = true
  document.addEventListener(
    'click',
    (e) => {
      const target = e.target as Element | null
      const el = (target?.closest?.('[data-track]') || null) as HTMLElement | null
      if (!el) return
      const action = el.getAttribute('data-track') || ''
      if (!action) return
      emitClickOnce(action, parseTrackParams(el.getAttribute('data-track-params')))
    },
    // 捕获阶段：即使控件内部调用了 stopPropagation 也不会漏报
    true,
  )
}

// 任务结果去重上报
const trackedTaskResults: Record<string, string> = {}
function trackTaskResultOnce(name: string, taskId: string, params?: Record<string, unknown>) {
  if (trackedTaskResults[taskId] === name) return
  trackedTaskResults[taskId] = name
  trackEvent(name, params || {})
}

// ── 生成成功（task_completed）补齐 ─────────────────────────────────────────
// 只在进度页观察状态流转会上报，会漏掉三类成功：一键创作（提交后回列表）、
// 图片任务（结果留在表单里）、用户中途离开/刷新页面。
// 因此成功事件用「taskId + 持久化」去重，进度页与任务列表轮询都调用它：
// 同一任务在任意入口被观察到 completed 时补报一次，且跨刷新不重复。
const COMPLETED_KEY = 'ga_completed_tasks'
const COMPLETED_SEEDED_KEY = 'ga_completed_seeded'
const COMPLETED_LIMIT = 800 // 只保留最近 800 个 id，避免 localStorage 无限增长

// 内存缓存：任务列表每 5s 轮询、每次可能有几十个已完成任务，
// 逐个 parse localStorage 会做成 O(n²) 的重复 JSON 解析
let completedCache: Set<string> | null = null

function getCompletedSet(): Set<string> {
  if (completedCache) return completedCache
  const ids: string[] = []
  try {
    const raw = localStorage.getItem(COMPLETED_KEY)
    const arr = raw ? JSON.parse(raw) : []
    if (Array.isArray(arr)) {
      for (const x of arr) if (typeof x === 'string') ids.push(x)
    }
  } catch {
    /* 隐私模式 / 脏数据：按空表处理 */
  }
  completedCache = new Set(ids)
  return completedCache
}

function persistCompleted(): void {
  try {
    const ids = Array.from(getCompletedSet())
    localStorage.setItem(COMPLETED_KEY, JSON.stringify(ids.slice(-COMPLETED_LIMIT)))
  } catch {
    /* 隐私模式 / 配额满：忽略 */
  }
}

/**
 * 判断某个任务是否「首次被观察到成功」，并把 id 记入持久化注册表。
 * 返回 true 表示应上报；false 表示已报过（或 id 为空）。
 */
function shouldReportCompleted(taskId: string): boolean {
  if (!taskId) return false
  const set = getCompletedSet()
  if (set.has(taskId)) return false
  // 先落盘再上报：极端情况下写盘失败宁可多报一次，也不要漏报成功
  set.add(taskId)
  persistCompleted()
  return true
}

/**
 * 历史上已完成的任务在接入埋点后会一次性被列表扫到，全量上报会让「生成成功」
 * 突增。首次轮询时只把这些 id 播种进去重表（不上报），此后新完成的才计数。
 * 返回 true 表示本次是播种调用，调用方应跳过上报。
 */
function seedCompletedTasks(taskIds: string[]): boolean {
  try {
    if (localStorage.getItem(COMPLETED_SEEDED_KEY) === '1') return false
    const set = getCompletedSet()
    for (const id of taskIds) if (id) set.add(id)
    persistCompleted()
    localStorage.setItem(COMPLETED_SEEDED_KEY, '1')
    return true
  } catch {
    return false
  }
}

/**
 * 上报一次「生成成功」，同一 taskId 全局只记一次（跨页面、跨刷新）。
 * 参数应带 task_type，simple 任务再带 mode（t2v/i2v/ti2vid/keyframes）。
 */
function trackTaskCompletedOnce(taskId: string, params?: Record<string, unknown>) {
  if (!shouldReportCompleted(taskId)) return
  trackEvent('task_completed', params || {})
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
  return {
    initGA,
    initClickTracking,
    trackEvent,
    trackClick,
    trackPageView,
    trackTaskResultOnce,
    trackTaskCompletedOnce,
    seedCompletedTasks,
    reportException,
    initErrorListeners,
    isGaOptedOut,
    setGaOptOut,
  }
}

// 供单测使用（模板不直接调用）
export { parseTrackParams, sanitizeParams, shouldReportCompleted, seedCompletedTasks }

/** 仅供单测：清空成功去重的内存缓存（生产代码不要调用） */
export function __resetCompletedCacheForTest() {
  completedCache = null
}

declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}
