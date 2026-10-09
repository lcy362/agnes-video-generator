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
 * 存储刻意用 **UTC 小时**（而不是直接写北京时间）：展示时按浏览者所在时区换算，
 * 不同时区用户看到的是各自的本地时间 + 本地时区标签。
 *
 * 更新方式：重跑 GA 分时段分析后，只改 RETRY_WINDOWS_UTC 即可，无需动其他代码。
 */

import { t, tf, currentLang } from '@/i18n'

export interface RetryWindowUtc {
  /** UTC 起始小时（0–23） */
  startHour: number
  /** 持续小时数（允许跨午夜） */
  hours: number
}

export const RETRY_WINDOWS_UTC: RetryWindowUtc[] = [
  { startHour: 14, hours: 3 }, // UTC 14:00–17:00 → 北京 22:00–01:00
  { startHour: 22, hours: 3 }, // UTC 22:00–01:00 → 北京 06:00–09:00
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
