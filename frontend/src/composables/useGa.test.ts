/**
 * 埋点契约单测（v8.2 按钮级埋点）：
 * 1. `data-track-params` 解析容错——模板里由 JSON.stringify 生成，异常值不得中断交互。
 * 2. 脱敏——用户创作内容与 API Key 不得进入 GA；超长字符串必须截断。
 *
 * 多语言无关性是结构性的：action 来自模板写死的英文键，不经过 t()，
 * 因此这里只需保证解析/脱敏不会把语言相关内容带进参数。
 */
import { beforeEach, describe, expect, it } from 'vitest'

import {
  __resetCompletedCacheForTest,
  parseTrackParams,
  sanitizeParams,
  seedCompletedTasks,
  shouldReportCompleted,
} from './useGa'

describe('parseTrackParams（data-track-params 解析）', () => {
  it('解析普通对象', () => {
    expect(parseTrackParams('{"mode":"manual","n":3}')).toEqual({ mode: 'manual', n: 3 })
  })

  it('空值 / undefined 返回空对象', () => {
    expect(parseTrackParams('')).toEqual({})
    expect(parseTrackParams(null)).toEqual({})
    expect(parseTrackParams(undefined)).toEqual({})
  })

  it('非法 JSON 返回空对象（不抛异常）', () => {
    expect(parseTrackParams('{bad json')).toEqual({})
  })

  it('非对象（数组 / 标量）一律丢弃', () => {
    expect(parseTrackParams('[1,2]')).toEqual({})
    expect(parseTrackParams('42')).toEqual({})
    expect(parseTrackParams('"str"')).toEqual({})
  })
})

describe('sanitizeParams（上报脱敏）', () => {
  it('敏感内容字段替换为 <redacted>', () => {
    const out = sanitizeParams({ prompt: '一只猫', api_key: 'sk-xxx', mode: 't2v' })
    expect(out.prompt).toBe('<redacted>')
    expect(out.api_key).toBe('<redacted>')
    expect(out.mode).toBe('t2v')
  })

  it('空字符串敏感字段保持原样（不上报 <redacted> 噪音）', () => {
    expect(sanitizeParams({ prompt: '' }).prompt).toBe('')
  })

  it('超长字符串截断到 100 字符加省略号', () => {
    const long = 'a'.repeat(300)
    const out = sanitizeParams({ error: long }) as { error: string }
    expect(out.error.length).toBe(101)
    expect(out.error.endsWith('…')).toBe(true)
  })

  it('数字 / 布尔 / 枚举原样保留（用于按维度聚合）', () => {
    const out = sanitizeParams({ count: 3, paid_model: true, action: 'submit_simple_video' })
    expect(out).toEqual({ count: 3, paid_model: true, action: 'submit_simple_video' })
  })
})

describe('生成成功去重（taskId 级持久化）', () => {
  beforeEach(() => {
    __resetCompletedCacheForTest()
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
        clear: () => store.clear(),
      },
    })
  })

  it('同一 taskId 只应上报一次（模拟刷新后仍去重）', () => {
    expect(shouldReportCompleted('task-a')).toBe(true)
    expect(shouldReportCompleted('task-a')).toBe(false)
    expect(shouldReportCompleted('task-b')).toBe(true)
  })

  it('空 taskId 不上报', () => {
    expect(shouldReportCompleted('')).toBe(false)
  })

  it('首次播种只登记历史任务、不上报；播种后新任务仍可上报', () => {
    expect(seedCompletedTasks(['old-1', 'old-2'])).toBe(true)
    expect(shouldReportCompleted('old-1')).toBe(false)
    expect(shouldReportCompleted('old-2')).toBe(false)
    expect(shouldReportCompleted('new-1')).toBe(true)
  })

  it('第二次调用不再播种（历史任务不会被重复登记为已上报）', () => {
    expect(seedCompletedTasks(['old-1'])).toBe(true)
    expect(seedCompletedTasks(['another-old'])).toBe(false)
    expect(shouldReportCompleted('another-old')).toBe(true)
  })
})
