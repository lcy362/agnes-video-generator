/**
 * v7.3：上游队列繁忙时的「错峰重试」建议时段。
 *
 * 数据来源：GA4 媒体资源 video_local（报告时区 Asia/Shanghai, GMT+08:00）
 * 2026-09-28 ~ 2026-10-08（11 天）的 api_error / create_task / task_failed 统计。
 * 综合两个口径挑选成功率最高的时段：
 *   · 任务失败率 = (task_failed + create_task_failed) / (create_task + create_task_failed)
 *   · 每任务上游报错数 = api_error / create_task
 *
 *   北京时间 22:00–01:00 → 失败率 21%–33%、每任务报错 0.68–0.75（全周最好一档）
 *   北京时间 06:00–09:00 → 失败率 32%–34%、每任务报错 0.51–0.91
 *   对照基线：全时段平均失败率 35.3%、每任务报错 0.89
 *
 * ── v8.2.3 复盘修订（本文件的现行数值）────────────────────────────────────
 * 触发：2026-11-24 用「近 7 天」重跑，发现旧第二窗口（06:00–09:00）实测是全天最差带之一。
 * 数据：GA4 探索报表「接口报错趋势(api_error)」逐时行（日期+时点），
 *       主样本 2026-11-17 ~ 11-23（7 天），并用 11-02 ~ 11-23（22 天）复核。
 * 口径：每任务上游报错数 = SUM(api_error.count) / create_task，越低越好。
 *       ⚠️ 必须用 SUM(count)：count 是该事件代表的真实报错次数。旧的「事件数」口径
 *       会漏掉进度页首次打开时被静默建基线的历史累计，实测低估约 40%
 *       （同一 7 天窗口：事件数 5.9/任务 vs SUM(count) 9.6/任务）。
 *
 *   北京时间 21:00–24:00 → 7.80 / 5.54 / 3.60（7 天）；8.05 / 6.96 / 4.89（22 天）
 *   北京时间 09:00–12:00 → 3.16 / 8.05 / 10.93（7 天）；5.80 / 7.59 / 9.68（22 天）
 *   对照基线：9.65（7 天）/ 10.93（22 天）
 *   最差时段：02:00 25.7、15:00 23.3、19:00 23.0、17:00 18.8（均为基线的 2 倍以上）
 *   说明：两个窗口的小时在两个样本里都稳定低于各自基线；窗口边界之外的相邻小时
 *       呈混合（如 00:00 7 天 8.97 低于基线、22 天 11.61 高于基线），故不并入。
 *
 * 存储刻意用 **UTC 小时**（而不是直接写北京时间）：展示时按浏览者所在时区换算，
 * 不同时区用户看到的是各自的本地时间 + 本地时区标签。
 *
 * 更新方式：重跑 GA 分时段分析后，只改 RETRY_WINDOWS_UTC 即可，无需动其他代码。
 * ⚠️ v8.2.3 起 api_error 走「首错 + 汇总」降噪（见 utils/apiErrorAggregator.ts），
 *   重算时段必须用 **SUM(count)/create_task**（或 GA4 里已注册的自定义指标 count），
 *   直接数 api_error 事件条数会低估最近的错误密度。
 */

import { t, tf, currentLang } from '@/i18n'

export interface RetryWindowUtc {
  /** UTC 起始小时（0–23） */
  startHour: number
  /** 持续小时数（允许跨午夜） */
  hours: number
}

export const RETRY_WINDOWS_UTC: RetryWindowUtc[] = [
  { startHour: 13, hours: 3 }, // UTC 13:00–16:00 → 北京 21:00–24:00（每任务报错 3.6–7.8）
  { startHour: 1, hours: 3 }, // UTC 01:00–04:00 → 北京 09:00–12:00（每任务报错 3.2–10.9）
]

/** 队列满提示里追加时段指引的 i18n key（形如 `{windows}` / `{tz}` 两个占位符） */
export const QUEUE_FULL_WINDOW_HINT_KEY = 'error.video.queue_full.window_hint'

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

/** 本地时区标签（如 GMT+8 / GMT+05:30）；Intl 不支持 shortOffset 时按当前偏移手算 */
export function localTimezoneLabel(now: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: 'shortOffset' }).formatToParts(now)
    const label = parts.find((p) => p.type === 'timeZoneName')?.value
    if (label) return label
  } catch {
    /* 老浏览器不支持 shortOffset，落入手算分支 */
  }
  const offsetMin = -now.getTimezoneOffset()
  const sign = offsetMin >= 0 ? '+' : '-'
  const abs = Math.abs(offsetMin)
  return `GMT${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`
}

/**
 * 把 UTC 时段换算成浏览者本地时间的展示文案。
 *
 * @param lang 当前 UI 语言（用于列表连接符，如中文「、」、英文「, 」）
 * @returns 本地时段串 + 时区标签；无建议时段时返回 null
 */
export function localRetryWindows(
  lang: string,
  now: Date = new Date(),
): { windows: string; tz: string } | null {
  if (!RETRY_WINDOWS_UTC.length) return null
  // getTimezoneOffset 返回「本地比 UTC 慢多少分钟」，取负即本地相对 UTC 的偏移
  const offsetMin = -now.getTimezoneOffset()
  const toLocal = (utcHour: number): string => {
    const total = (((utcHour * 60 + offsetMin) % 1440) + 1440) % 1440
    return `${pad2(Math.floor(total / 60))}:${pad2(total % 60)}`
  }
  const parts = RETRY_WINDOWS_UTC.map((w) => `${toLocal(w.startHour)}–${toLocal(w.startHour + w.hours)}`)
  // 时段列举连接符：中日韩用顿号，其余用逗号
  // （不用 Intl.ListFormat：中文 unit 样式下不插分隔符，会把两个时段粘成 "22:00–01:0006:00–09:00"）
  const sep = /^(zh|ja|ko)$/i.test(lang || '') ? '、' : ', '
  return { windows: parts.join(sep), tz: localTimezoneLabel(now) }
}

/**
 * 队列满 / 上游 503 场景下追加的「错峰重试」指引文案（已按本地时区渲染）。
 *
 * 未命中 i18n key（旧语言包）时返回空串，调用方据此跳过追加，不影响原提示。
 */
export function queueFullWindowHint(): string {
  const raw = t(QUEUE_FULL_WINDOW_HINT_KEY)
  if (!raw || raw === QUEUE_FULL_WINDOW_HINT_KEY) return ''
  const w = localRetryWindows(currentLang.value)
  if (!w) return ''
  return tf(QUEUE_FULL_WINDOW_HINT_KEY, { windows: w.windows, tz: w.tz })
}
