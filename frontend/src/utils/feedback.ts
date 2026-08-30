/**
 * 问题反馈模块公共工具（v6.1）。
 *
 * 包含：
 * - 按任务持久化的重试计数（localStorage）
 * - 确定性故障预筛（保守关键词匹配）
 * - 诊断信息报告拼接（复制 / GitHub Issue 预填共用）
 * GitHub Issue 链接构造（含编码长度截断与降级）
 */

import { t } from '@/i18n'

// ── 常量 ──

/** 重试次数达到该阈值后反馈区自动展开（PRD FR2） */
export const RETRY_THRESHOLD = 2

/** 错误消息进入报告的最大字符数 */
const ERROR_MESSAGE_MAX = 2000

/** v6.2.2：完整 traceback 进入报告的最大字符数（诊断端点已截断 6000，此处再兜底） */
export const TRACEBACK_MAX = 8000

/**
 * Issue 预填 body 的原始字符数上限（PRD FR6.2：预填截断上限 4000 字符）。
 * 由于 body 会作为 URL query 传递，编码后可能翻倍以上（中文约 3×），
 * 4000 字符足以保证编码后仍处于浏览器/网关可接受范围内；超限走降级。
 */
const ISSUE_BODY_MAX_RAW = 4000

export const GITHUB_REPO = 'https://github.com/lcy362/agnes-video-generator'
export const FAQ_URL = 'https://video.lichuanyang.top/faq'

// ── 重试计数（localStorage 持久化） ──

const RETRY_COUNT_PREFIX = 'fb_retry_'

/**
 * 读取任务的重试次数（未记录或数据异常时返回 0）。
 */
export function getRetryCount(taskId: string): number {
  if (!taskId) return 0
  try {
    const raw = localStorage.getItem(RETRY_COUNT_PREFIX + taskId)
    const n = raw ? parseInt(raw, 10) : 0
    return Number.isFinite(n) && n > 0 ? n : 0
  } catch {
    return 0
  }
}

/**
 * 重试次数 +1 并返回新值。
 */
export function bumpRetryCount(taskId: string): number {
  if (!taskId) return 0
  const next = getRetryCount(taskId) + 1
  try {
    localStorage.setItem(RETRY_COUNT_PREFIX + taskId, String(next))
  } catch {
    /* 存储不可用时静默降级（计数不持久，不影响功能） */
  }
  return next
}

/**
 * 清理任务的重试计数（任务成功后调用）。
 */
export function clearRetryCount(taskId: string): void {
  if (!taskId) return
  try {
    localStorage.removeItem(RETRY_COUNT_PREFIX + taskId)
  } catch {
    /* ignore */
  }
}

// ── 反馈区展开状态（用户手动覆盖时持久化） ──

const FEEDBACK_OPEN_PREFIX = 'fb_open_'

/**
 * 读取用户对反馈区展开/收起的手动覆盖；未操作过返回 null（走自动策略）。
 */
export function getFeedbackOpenOverride(taskId: string): boolean | null {
  if (!taskId) return null
  try {
    const v = localStorage.getItem(FEEDBACK_OPEN_PREFIX + taskId)
    if (v === '1') return true
    if (v === '0') return false
  } catch {
    /* ignore */
  }
  return null
}

/**
 * 记录用户手动展开/收起的覆盖状态。
 */
export function setFeedbackOpenOverride(taskId: string, open: boolean): void {
  if (!taskId) return
  try {
    localStorage.setItem(FEEDBACK_OPEN_PREFIX + taskId, open ? '1' : '0')
  } catch {
    /* ignore */
  }
}

// ── 确定性故障预筛 ──

/**
 * 确定性故障的保守匹配模式。
 * 注意：绝不能命中 429 / 5xx / timeout 等偶发故障（这类必须走重试引导）。
 */
const DETERMINISTIC_PATTERNS: RegExp[] = [
  /\bHTTP\s*40[0-4]\b/i, // HTTP 400~404：参数 / 鉴权 / 资源错误
  /\b40[0-4]\s*(Client Error|Bad Request|Unauthorized|Forbidden|Not Found)\b/i, // requests HTTPError 文案
  /invalid\s*(api\s*)?key/i,
  /unauthorized/i,
  /content\s*(policy|moderation)/i,
  /审核|敏感|违规|不合规|内容安全/,
]

/**
 * 判断错误消息是否为确定性故障（重试大概率无效）。
 * 误判只影响引导顺序，用户始终可手动重试与反馈。
 */
export function isDeterministicError(message: string): boolean {
  if (!message) return false
  return DETERMINISTIC_PATTERNS.some((p) => p.test(message))
}

// ── 诊断信息报告 ──

export interface DiagnosticInput {
  appVersion: string
  taskId: string
  taskType: string
  mode?: string
  failedStep: string
  errorMessage: string
  retryCount: number
  /** 关键配置，已格式化为「名称: 值」字符串列表 */
  configs: string[]
}

/**
 * 拼接 Markdown 诊断报告（复制与 Issue 预填共用同一份内容）。
 * 隐私约定：不含用户提示词原文，错误消息截断 2000 字符。
 */
export function buildDiagnosticReport(d: DiagnosticInput): string {
  const unk = t('fbRepUnknown')
  const lines: string[] = []
  lines.push(t('fbRepTitle'))
  lines.push(`- ${t('fbRepAppVersion')}: ${d.appVersion || unk}`)
  lines.push(`- ${t('fbRepTaskId')}: ${d.taskId}`)
  lines.push(`- ${t('fbRepTaskType')}: ${d.taskType}`)
  if (d.mode) lines.push(`- ${t('fbRepMode')}: ${d.mode}`)
  lines.push(`- ${t('fbRepFailedStep')}: ${d.failedStep || unk}`)
  lines.push(`- ${t('fbRepRetryCount')}: ${d.retryCount}`)
  if (d.configs.length) lines.push(`- ${t('fbRepConfigs')}: ${d.configs.join(' / ')}`)
  lines.push(`- ${t('fbRepEnv')}: ${navigator.userAgent}`)
  lines.push('')
  lines.push(t('fbRepErrorTitle'))
  lines.push('```')
  lines.push((d.errorMessage || '').slice(0, ERROR_MESSAGE_MAX))
  lines.push('```')
  lines.push('')
  lines.push(t('fbRepReproSteps'))
  lines.push(t('fbRepReproHint'))
  lines.push('')
  lines.push(t('fbRepExpected'))
  lines.push(t('fbRepExpectedHint'))
  return lines.join('\n')
}

// ── GitHub Issue 链接构造 ──

/**
 * 生成 Issue 标题。
 */
export function buildIssueTitle(taskType: string, failedStep: string): string {
  const tpl = failedStep ? t('fbRepIssueTitleStep') : t('fbRepIssueTitleNoStep')
  return tpl.replace('{taskType}', taskType).replace('{failedStep}', failedStep)
}

/**
 * 构造预填 title/body 的 issues/new 链接。
 *
 * body 编码后超过上限时逐步截断（并标注省略）；返回 truncated 供调用方提示
 * 用户粘贴已复制的完整诊断信息。
 */
export function buildIssueUrl(title: string, body: string): { url: string; truncated: boolean } {
  let b = body
  let truncated = false
  // 原始字符数超上限 → 逐步截断并标注省略（PRD FR6.2：4000 字符上限 + FR6.3 降级）
  if (b.length > ISSUE_BODY_MAX_RAW) {
    b = b.slice(0, ISSUE_BODY_MAX_RAW) + '\n\n' + t('fbRepTruncated')
    truncated = true
  }
  const url = `${GITHUB_REPO}/issues/new?labels=bug&title=${encodeURIComponent(title)}&body=${encodeURIComponent(b)}`
  return { url, truncated }
}
