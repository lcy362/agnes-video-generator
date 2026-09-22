import { reactive } from 'vue'
import type { TaskType, VoiceCatalog, Workspace } from './types'

// 全局应用状态（模块级 reactive，跨组件共享）
export const appState = reactive({
  // 顶层视图：创建 / 任务列表 / 产物画廊 / 简易模式 / 任务进度页
  view: 'create' as 'create' | 'list' | 'simple' | 'gallery' | 'progress',
  // 进度页当前任务（首次执行与任务列表进入复用同一页面）
  progressTaskId: null as string | null,
  progressOrigin: 'create' as 'create' | 'list' | 'gallery',
  // 任务类型 tab
  currentTaskType: 'creative' as TaskType | string,
  // 运行中任务
  isTaskRunning: false,
  currentTaskId: null as string | null,
  currentDirName: null as string | null,
  // 当前产物任务
  currentArtifactsTaskId: null as string | null,
  // 配置
  apiKeySource: '' as string, // 'env' | 'config' | ''
  // v6.1 问题反馈：应用版本（诊断信息用，来自 /api/config.app_version）
  appVersion: '' as string,
  workspaces: [] as Workspace[],
  activeWorkspace: '' as string,
  workingDirSource: 'config' as string,
  watermarkEnabled: false,
  agnesDomain: 'com' as string,
  models: { text: '', image: '', video: '' },
  modelListCache: { text: [] as string[], image: [] as string[], video: [] as string[] },
  // v6.2：视频模型能力元数据（来自 /api/models video_capabilities）
  videoCapabilities: {} as Record<string, any>,
  // 音色目录
  voiceCatalog: null as VoiceCatalog | null,
  voiceIndex: {} as Record<string, any>,
  // v6.0 手动模式：创建时的执行模式与暂停点（写入表单提交）
  execMode: 'auto' as 'auto' | 'manual',
  pausePoints: [] as string[],
})

// 折叠偏好
export function getCollapsePrefs(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem('wb_config_collapsed') || '{}')
  } catch {
    return {}
  }
}

export function setCollapsePref(section: string, val: boolean) {
  const prefs = getCollapsePrefs()
  prefs[section] = val
  try {
    localStorage.setItem('wb_config_collapsed', JSON.stringify(prefs))
  } catch {
    /* ignore */
  }
}
