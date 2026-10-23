/**
 * 一次性公告弹窗的「已读」标记（localStorage）。
 *
 * 产品口径：公告类弹窗每个浏览器**只弹一次**，用户点「我知道了」/点遮罩关闭后
 * 写入标记，之后不再打扰；换浏览器或无痕模式会重新弹一次，属预期行为。
 *
 * 每期公告用独立的 id（如 `realname-cn-20261026`），下期公告换 id 即可再次弹出。
 */

const STORAGE_PREFIX = 'agnes.notice.'

/** 中国站实名认证公告（2026-10-26 12:00 截止）的公告 id */
export const REAL_NAME_NOTICE_ID = 'realname-cn-20261026'

/** 公告 id → localStorage key */
export function noticeStorageKey(id: string): string {
  return STORAGE_PREFIX + id
}

/**
 * 该公告是否已被用户关闭（localStorage 不可用时一律视为未关闭——宁可按「一次」处理，
 * 也不要因为隐私模式抛异常导致弹窗永远不出现）。
 */
export function isNoticeDismissed(id: string): boolean {
  try {
    return localStorage.getItem(noticeStorageKey(id)) === '1'
  } catch {
    return false
  }
}

/** 记录公告已读（写入失败静默忽略：最多下次再弹一次） */
export function dismissNotice(id: string): void {
  try {
    localStorage.setItem(noticeStorageKey(id), '1')
  } catch {
    /* ignore */
  }
}
