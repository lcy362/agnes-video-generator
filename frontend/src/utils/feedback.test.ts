/**
 * 3.3 前端纯函数单测（vitest）：确定性故障预筛。
 *
 * `isDeterministicError` 为纯函数（不依赖 i18n / localStorage），
 * 适合作为前端单测的起步覆盖；后续可扩展 i18n、steps 等纯函数。
 */
import { describe, expect, it } from 'vitest'

import { isDeterministicError } from './feedback'

describe('isDeterministicError（确定性故障预筛）', () => {
  it('识别 HTTP 400~404', () => {
    expect(isDeterministicError('status=failed: 400 Bad Request')).toBe(true)
    expect(isDeterministicError('HTTP 404 Not Found')).toBe(true)
    expect(isDeterministicError('401 Unauthorized')).toBe(true)
  })

  it('识别 invalid api key / unauthorized', () => {
    expect(isDeterministicError('Invalid API Key provided')).toBe(true)
    expect(isDeterministicError('unauthorized')).toBe(true)
  })

  it('识别内容审核 / 敏感词', () => {
    expect(isDeterministicError('content policy violation')).toBe(true)
    expect(isDeterministicError('内容涉及敏感信息')).toBe(true)
  })

  it('非确定性错误返回 false（可重试类错误）', () => {
    expect(isDeterministicError('Connection reset by peer')).toBe(false)
    expect(isDeterministicError('Video generation failed: 500 internal error')).toBe(false)
    expect(isDeterministicError('')).toBe(false)
  })
})
