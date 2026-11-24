/**
 * api_error 上报降噪（v8.2.3）。
 *
 * 背景：后端 `error_collector` 把上游报错按 `status_code|model_type|api_method`
 * 内存聚合成 `upstream_errors`，前端进度页每次轮询看到的只是**累计计数**。
 * 旧实现把「本轮相对上轮的增量」直接发一条 `api_error`，在快重试（每秒轮询、
 * 忙轨连打）下会把一次队列饱和刷成上百条事件——GA4 里 `api_error` 一度占全部
 * 事件的 26%（2026-11 复盘：每任务 5.9 条），真实故障率被淹没。
 *
 * 新语义（每个签名各自独立）：
 *   1. 首次出现 → 立刻发一条 `api_error`（aggregated=false，即「首错」），保住
 *      故障发生的时间点，趋势图不会因为降噪而整体右移；
 *   2. 之后的增量攒进 pending，在下列任一时刻折成**一条**汇总事件
 *      （aggregated=true，count=累计增量）：
 *        · 距上次汇总满 `flushIntervalMs`（默认 5 分钟）
 *        · 任务进入终态（completed / failed / stopped）
 *        · 页面隐藏 / 卸载（由调用方挂 visibilitychange / pagehide）
 *   3. 切换任务时先把上一个任务的 pending 冲掉，不丢数据。
 *
 * 「每任务上游报错数」不再是事件条数，而是 SUM(count) / create_task；
 * `count` 需在 GA4 注册为**自定义指标**（scripts/setup_ga4.py 的 CUSTOM_METRICS）。
 */

/** 后端 `upstream_errors` 的单条形状（与 models/task.py 对齐，字段可缺省） */
export interface UpstreamErrorLike {
  status_code?: number | string
  model_type?: string
  api_method?: string
  count?: number
}

/** 交给 trackEvent 的 api_error 参数 */
export interface ApiErrorPayload {
  task_type: string
  status_code: string
  model_type: string
  api_method: string
  /** 本条事件代表的报错次数（首错=本次增量，汇总=窗口内累计增量） */
  count: number
  /** false=首错（实时），true=汇总（合并后） */
  aggregated: boolean
}

/** 进度页观察到的最小状态切片，便于纯函数单测 */
export interface ApiErrorStateLike {
  task_id?: string
  task_type?: string
  status?: string
  upstream_errors?: UpstreamErrorLike[]
}

/** 汇总节流窗口：快重试期间同一签名最多每 5 分钟产生一条汇总事件 */
export const API_ERROR_FLUSH_INTERVAL_MS = 5 * 60 * 1000

/** 任务终态：进入这些状态时立即冲掉 pending，保证一次任务闭环不被丢掉 */
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'stopped'])

/** 签名口径与后端 error_collector 一致：status_code|model_type|api_method */
export function apiErrorSignature(e: UpstreamErrorLike): string {
  return `${e.status_code || 0}|${e.model_type || ''}|${e.api_method || ''}`
}

export interface ApiErrorAggregatorOptions {
  /** 汇总节流窗口（毫秒），默认 5 分钟 */
  flushIntervalMs?: number
  /** 时钟注入，便于单测推进时间 */
  now?: () => number
}

export interface ApiErrorAggregator {
  /** 每轮轮询调用；返回本轮应当上报的事件（0 条表示攒着） */
  observe(state: ApiErrorStateLike): ApiErrorPayload[]
  /** 立即冲掉 pending（页面隐藏 / 卸载时调用） */
  flush(): ApiErrorPayload[]
  /** 当前跟踪的任务 id（空串表示尚未建基线） */
  currentTaskId(): string
}

interface PendingEntry {
  task_type: string
  status_code: string
  model_type: string
  api_method: string
  count: number
}

/**
 * 创建聚合器。
 *
 * 设计约束：纯内存、无副作用（不发事件），所有可观测行为都通过返回值表达，
 * 调用方负责真正调用 trackEvent——这样单测无需 mock GA。
 */
export function createApiErrorAggregator(options: ApiErrorAggregatorOptions = {}): ApiErrorAggregator {
  const flushIntervalMs = options.flushIntervalMs ?? API_ERROR_FLUSH_INTERVAL_MS
  const now = options.now ?? (() => Date.now())

  let trackedTaskId = ''
  /** 每个签名已「看到」的累计计数（含尚未上报的部分） */
  const seen: Record<string, number> = {}
  /** 每个签名是否已发过首错 */
  const emittedFirst: Record<string, true> = {}
  /** 待汇总的增量，按签名分桶 */
  const pending: Record<string, PendingEntry> = {}
  let lastFlushAt = 0

  function clearAll() {
    for (const k of Object.keys(seen)) delete seen[k]
    for (const k of Object.keys(emittedFirst)) delete emittedFirst[k]
    for (const k of Object.keys(pending)) delete pending[k]
  }

  function flush(): ApiErrorPayload[] {
    const out: ApiErrorPayload[] = []
    for (const key of Object.keys(pending)) {
      const p = pending[key]
      if (p.count > 0) {
        out.push({
          task_type: p.task_type,
          status_code: p.status_code,
          model_type: p.model_type,
          api_method: p.api_method,
          count: p.count,
          aggregated: true,
        })
      }
      delete pending[key]
    }
    lastFlushAt = now()
    return out
  }

  function observe(state: ApiErrorStateLike): ApiErrorPayload[] {
    const taskId = state.task_id || ''
    const taskType = state.task_type || ''
    const errs = Array.isArray(state.upstream_errors) ? state.upstream_errors : []
    const out: ApiErrorPayload[] = []

    // 换任务：先冲掉上一个任务的 pending（不能因为切换而丢汇总），再静默建基线。
    // 建基线是刻意的：进度页刷新 / 重开时，历史累计不该被当成「新发生的错误」重报。
    if (taskId && taskId !== trackedTaskId) {
      out.push(...flush())
      clearAll()
      trackedTaskId = taskId
      for (const e of errs) {
        seen[apiErrorSignature(e)] = Math.max(0, Number(e.count) || 0)
      }
      lastFlushAt = now()
      return out
    }

    for (const e of errs) {
      const key = apiErrorSignature(e)
      const total = Math.max(0, Number(e.count) || 0)
      const prev = seen[key] || 0
      if (total <= prev) continue
      const delta = total - prev
      seen[key] = total

      if (!emittedFirst[key]) {
        emittedFirst[key] = true
        out.push({
          task_type: taskType,
          status_code: String(e.status_code || 0),
          model_type: e.model_type || '',
          api_method: e.api_method || '',
          count: delta,
          aggregated: false,
        })
        continue
      }

      const entry = pending[key] || (pending[key] = {
        task_type: taskType,
        status_code: String(e.status_code || 0),
        model_type: e.model_type || '',
        api_method: e.api_method || '',
        count: 0,
      })
      if (taskType) entry.task_type = taskType
      entry.count += delta
    }

    const terminal = TERMINAL_STATUSES.has(state.status || '')
    if (terminal || (Object.keys(pending).length > 0 && now() - lastFlushAt >= flushIntervalMs)) {
      out.push(...flush())
    }
    return out
  }

  return {
    observe,
    flush,
    currentTaskId: () => trackedTaskId,
  }
}