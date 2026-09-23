/**
 * 3.3 前端纯函数单测（vitest）：确定性故障预筛 + 本机网络故障识别。
 *
 * `isDeterministicError` / `isLocalNetworkError` 为纯函数（不依赖 i18n / localStorage），
 * 适合作为前端单测的起步覆盖；后续可扩展 i18n、steps 等纯函数。
 */
import { describe, expect, it } from 'vitest'

import { isDeterministicError, isLocalNetworkError } from './feedback'

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

describe('isLocalNetworkError（本机网络 / DNS 故障识别，v6.4.8）', () => {
  it('识别 issue #56/#57 的 DNS 解析失败形态', () => {
    expect(
      isLocalNetworkError(
        "HTTPSConnectionPool(host='cos-platform-outputs.agnes-ai.cn', port=443): " +
          "Max retries exceeded (Caused by NameResolutionError(\"Failed to resolve " +
          "'cos-platform-outputs.agnes-ai.cn' ([Errno 11004] getaddrinfo failed)\"))",
      ),
    ).toBe(true)
    expect(isLocalNetworkError('socket.gaierror: [Errno 8] nodename nor servname provided')).toBe(true)
  })

  it('识别后端「网络诊断」提示（中文消息同样命中）', () => {
    expect(isLocalNetworkError('网络诊断：本机无法解析域名 `cos-platform-outputs.agnes-ai.cn`（DNS 解析失败）')).toBe(true)
  })

  it('识别后端英文 "Network diagnosis" 提示（v7.0 issue #64 双语化）', () => {
    expect(
      isLocalNetworkError(
        'Network diagnosis: this machine cannot resolve `cos-platform-outputs.agnes-ai.cn` (DNS failure).',
      ),
    ).toBe(true)
    expect(
      isLocalNetworkError(
        'Network diagnosis: this machine cannot reach `api.agnes-ai.cn` (connection refused, reset, or intercepted).',
      ),
    ).toBe(true)
  })

  it('识别代理 / 连接被拒', () => {
    expect(isLocalNetworkError('Cannot connect to proxy 10.16.2.80:80')).toBe(true)
    expect(isLocalNetworkError('Failed to establish a new connection: [Errno 111] Connection refused')).toBe(true)
  })

  it('限流、超时、服务端失败不误判为本地网络问题', () => {
    expect(isLocalNetworkError('HTTP 429: Too Many Requests')).toBe(false)
    expect(isLocalNetworkError('Read timed out. (read timeout=30)')).toBe(false)
    expect(isLocalNetworkError('Video generation failed: 500 internal error')).toBe(false)
    expect(isLocalNetworkError('Connection reset by peer')).toBe(false)
    expect(isLocalNetworkError('')).toBe(false)
  })
})
