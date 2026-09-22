import { appState } from '@/store'

// 顶层视图导航 + URL hash 同步（无 vue-router，零后端改动）
// hash 规则：'#/progress/<taskId>' | '#/list' | '#/gallery' | '#/create'

export function useNavigation() {
  // 打开任务详情页：始终在新标签页打开，原页面（主页）保持不变
  function goProgress(taskId: string, origin: 'create' | 'list' | 'gallery' = 'create') {
    // 来源标记不跨标签页传递（新标签页内默认回主页），仅在当前页记录
    appState.progressOrigin = origin
    const url = location.pathname + location.search + '#/progress/' + encodeURIComponent(taskId)
    window.open(url, '_blank', 'noopener')
  }

  // 同页打开任务详情（自动恢复场景用，避免自动重连时无限开新标签页）
  function goProgressInPage(taskId: string) {
    appState.view = 'progress'
    appState.progressTaskId = taskId
    appState.currentTaskId = taskId
    location.hash = '#/progress/' + encodeURIComponent(taskId)
  }

  // 显式跳转主页（去掉 hash 回到根视图）
  function goHome() {
    location.href = location.pathname + location.search
  }

  function goBack() {
    const origin = appState.progressOrigin === 'list' ? 'list' : 'create'
    appState.view = origin
    appState.progressTaskId = null
    location.hash = origin === 'list' ? '#/list' : '#/create'
  }

  function parseHash(): { view: 'create' | 'list' | 'gallery' | 'progress'; taskId?: string } {
    const h = location.hash || ''
    const m = h.match(/^#\/progress\/(.+)$/)
    if (m) return { view: 'progress', taskId: decodeURIComponent(m[1]) }
    if (h.startsWith('#/list')) return { view: 'list' }
    if (h.startsWith('#/gallery')) return { view: 'gallery' }
    return { view: 'create' }
  }

  return { goProgress, goProgressInPage, goHome, goBack, parseHash }
}
