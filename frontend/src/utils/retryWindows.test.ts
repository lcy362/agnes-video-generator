/**
 * v7.3 / v8.2.3：错峰重试时段单测——验证「UTC 存储 → 按浏览者时区渲染」的换算，
 * 覆盖整点时区、跨午夜回绕、半小时时区（如 UTC+5:30）三种情况。
 * v8.2.3 依据 GA4 近 7 天复盘改写了两个窗口（北京 21:00–24:00 / 09:00–13:00）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RETRY_WINDOWS_UTC, localRetryWindows, localTimezoneLabel, queueFullWindowHint } from './retryWindows'

/** 东 n 分钟时区（东八区传 480）。getTimezoneOffset 返回「本地 = UTC - offset」 */
function mockOffsetMinutesEast(minutesEast: number) {
  return vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-minutesEast)
}

describe('RETRY_WINDOWS_UTC（UTC 存储的推荐时段）', () => {
  it('等价于北京 21:00–24:00 与 09:00–12:00（v8.2.3 SUM(count) 口径复盘）', () => {
    expect(RETRY_WINDOWS_UTC).toEqual([
      { startHour: 13, hours: 3 },
      { startHour: 1, hours: 3 },
    ])
  })
})

describe('localRetryWindows（按时区渲染）', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('UTC+8 用户看到北京时间', () => {
    mockOffsetMinutesEast(480)
    const w = localRetryWindows('zh')
    expect(w).not.toBeNull()
    for (const t of ['21:00', '00:00', '09:00', '12:00']) expect(w!.windows).toContain(t)
    // 中文用顿号分隔，避免两个时段被粘连
    expect(w!.windows).toBe('21:00–00:00、09:00–12:00')
  })

  it('UTC 用户看到 UTC 时段', () => {
    mockOffsetMinutesEast(0)
    const w = localRetryWindows('en')
    for (const t of ['13:00', '16:00', '01:00', '04:00']) expect(w!.windows).toContain(t)
    // 非中日韩语言用逗号分隔
    expect(w!.windows).toBe('13:00–16:00, 01:00–04:00')
  })

  it('UTC-4 用户跨午夜正确回绕', () => {
    mockOffsetMinutesEast(-240)
    const w = localRetryWindows('en')
    for (const t of ['09:00', '12:00', '21:00', '00:00']) expect(w!.windows).toContain(t)
  })

  it('半小时时区 UTC+5:30 保留 30 分钟精度', () => {
    mockOffsetMinutesEast(330)
    const w = localRetryWindows('en')
    for (const t of ['18:30', '21:30', '06:30', '09:30']) expect(w!.windows).toContain(t)
  })
})

describe('localTimezoneLabel', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('返回 GMT 形式的可读标签', () => {
    mockOffsetMinutesEast(480)
    expect(localTimezoneLabel()).toMatch(/GMT[+-]?\d/)
  })
})

describe('queueFullWindowHint', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('中文环境渲染出时段与中文提示', () => {
    mockOffsetMinutesEast(480)
    const text = queueFullWindowHint()
    expect(text).toContain('21:00')
    expect(text).toContain('GMT')
    expect(text).not.toBe('error.video.queue_full.window_hint')
  })
})
