/**
 * api_error 降噪单测（v8.2.3）：
 * 「首错实时 + 增量按窗口汇总」的核心契约——避免快重试把一次队列饱和刷成上百条事件。
 */
import { describe, expect, it } from 'vitest'

import {
  API_ERROR_FLUSH_INTERVAL_MS,
  apiErrorSignature,
  createApiErrorAggregator,
} from './apiErrorAggregator'

/** 可控时钟 */
function clock(start = 1_000_000) {
  let t = start
  return {
    now: () => t,
    advance(ms: number) {
      t += ms
    },
  }
}

const VIDEO_503 = { status_code: 503, model_type: 'video', api_method: 'generate_video', count: 0 }

function err(over: Partial<typeof VIDEO_503> = {}) {
  return { ...VIDEO_503, ...over }
}

describe('apiErrorSignature', () => {
  it('与后端 error_collector 同口径（status_code|model_type|api_method）', () => {
    expect(apiErrorSignature(err())).toBe('503|video|generate_video')
    expect(apiErrorSignature({})).toBe('0||')
  })
})

describe('createApiErrorAggregator', () => {
  it('首次观察只建基线，不发事件（刷新进度页不重报历史错误）', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    const out = agg.observe({ task_id: 't1', task_type: 'simple', upstream_errors: [err({ count: 7 })] })
    expect(out).toEqual([])
  })

  it('首次增长发一条实时事件（aggregated=false，count=本次增量）', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 2 })] })
    const out = agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 5 })] })
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({
      status_code: '503',
      model_type: 'video',
      api_method: 'generate_video',
      count: 3,
      aggregated: false,
      task_type: 'simple',
    })
  })

  it('之后同一签名的增量攒到窗口满，只发一条汇总（count=累计增量）', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    agg.observe({ task_id: 't1', task_type: 'creative', status: 'running', upstream_errors: [err({ count: 0 })] })
    // 首错
    expect(agg.observe({ task_id: 't1', task_type: 'creative', status: 'running', upstream_errors: [err({ count: 1 })] })).toHaveLength(1)
    // 窗口内继续涨：静默攒着
    expect(agg.observe({ task_id: 't1', task_type: 'creative', status: 'running', upstream_errors: [err({ count: 9 })] })).toEqual([])
    expect(agg.observe({ task_id: 't1', task_type: 'creative', status: 'running', upstream_errors: [err({ count: 30 })] })).toEqual([])
    // 窗口到点：一条汇总，count = 8 + 21
    c.advance(API_ERROR_FLUSH_INTERVAL_MS)
    const out = agg.observe({ task_id: 't1', task_type: 'creative', status: 'running', upstream_errors: [err({ count: 30 })] })
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ count: 29, aggregated: true, task_type: 'creative' })
  })

  it('任务进入终态立即汇总，不等窗口', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 0 })] })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 1 })] })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 4 })] })
    const out = agg.observe({ task_id: 't1', task_type: 'simple', status: 'failed', upstream_errors: [err({ count: 4 })] })
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ count: 3, aggregated: true })
  })

  it('切换任务时先冲掉上一任务的 pending，再为新区建基线', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 0 })] })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 1 })] })
    agg.observe({ task_id: 't1', task_type: 'simple', status: 'running', upstream_errors: [err({ count: 2 })] })
    const out = agg.observe({ task_id: 't2', task_type: 'image', status: 'running', upstream_errors: [err({ count: 99 })] })
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ count: 1, aggregated: true, task_type: 'simple' })
    // t2 的历史累计被当作基线，不重报
    expect(agg.observe({ task_id: 't2', task_type: 'image', status: 'running', upstream_errors: [err({ count: 99 })] })).toEqual([])
  })

  it('无 upstream_errors 时完全静默（零回归）', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    expect(agg.observe({ task_id: 't1', status: 'running' })).toEqual([])
    expect(agg.observe({ task_id: 't1', status: 'completed', upstream_errors: [] })).toEqual([])
  })

  it('计数回退（重启清零）不产生负增量', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    agg.observe({ task_id: 't1', status: 'running', upstream_errors: [err({ count: 10 })] })
    expect(agg.observe({ task_id: 't1', status: 'running', upstream_errors: [err({ count: 3 })] })).toEqual([])
  })

  it('flush() 手动冲量（页面隐藏时用）后 pending 清空', () => {
    const c = clock()
    const agg = createApiErrorAggregator({ now: c.now })
    agg.observe({ task_id: 't1', task_type: 'anchor', status: 'running', upstream_errors: [err({ count: 0 })] })
    agg.observe({ task_id: 't1', task_type: 'anchor', status: 'running', upstream_errors: [err({ count: 1 })] })
    agg.observe({ task_id: 't1', task_type: 'anchor', status: 'running', upstream_errors: [err({ count: 5 })] })
    const out = agg.flush()
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ count: 4, aggregated: true })
    expect(agg.flush()).toEqual([])
  })
})