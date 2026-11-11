import { reactive } from 'vue'
import type { FastRetrySettings, TaskType, VoiceCatalog, Workspace } from './types'

// ── v8.0：记住上次选择的任务类型（默认 simple，让文生视频真正「打开即用」）──
const TASK_TYPE_STORAGE_KEY = 'wb_task_type'
const KNOWN_TASK_TYPES = ['simple', 'creative', 'manuscript', 'anchor', 'poetry']

function loadTaskType(): string {
  try {
    const saved = localStorage.getItem(TASK_TYPE_STORAGE_KEY) || ''
    if (KNOWN_TASK_TYPES.includes(saved)) return saved
  } catch {
    /* 隐私模式/禁用 localStorage 时回退默认 */
  }
  return 'simple'
}

/** 记录用户主动切换的任务类型（非法值忽略，避免脏数据污染下次启动）。 */
export function rememberTaskType(type: string) {
  if (!KNOWN_TASK_TYPES.includes(type)) return
  try {
    localStorage.setItem(TASK_TYPE_STORAGE_KEY, type)
  } catch {
    /* ignore */
  }
}

// 全局应用状态（模块级 reactive，跨组件共享）
export const appState = reactive({
  // 顶层视图：创建 / 任务列表 / 产物画廊 / 简易模式 / 任务进度页
  view: 'create' as 'create' | 'list' | 'simple' | 'gallery' | 'progress',
  // 进度页当前任务（首次执行与任务列表进入复用同一页面）
  progressTaskId: null as string | null,
  progressOrigin: 'create' as 'create' | 'list' | 'gallery',
  // 任务类型 tab（v8.0：默认 simple + 记住上次选择）
  currentTaskType: loadTaskType() as TaskType | string,
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
  // v8.0：快速重试全局设置（设置页控制「到条件自动开启」+ 频率）
  fastRetrySettings: { auto: false, per_minute: 30, minutes: 3 } as FastRetrySettings,
  agnesDomain: 'com' as string,
  models: { text: '', image: '', video: '', text_provider: '' },
  modelListCache: { text: [] as string[], image: [] as string[], video: [] as string[] },
  // v7.0 文本模型供应商（可插拔多供应商）：列表 / 当前所选 / 各供应商候选模型缓存
  textProviders: [] as any[],
  textProviderSelected: '' as string, // 当前所选供应商 route key（'' = agnes）
  providerModelCache: {} as Record<string, string[]>,
  // v6.2：视频模型能力元数据（来自 /api/models video_capabilities）
  videoCapabilities: {} as Record<string, any>,
  // v8.1：图片侧能力元数据（来自 /api/models image_capabilities，参考图上限）
  imageCapabilities: {} as Record<string, any>,
  // v8.0：简单视频一键预设（来自 /api/models simple_default，后端单一来源）
  simpleDefault: {} as Record<string, any>,
  // 音色目录
  voiceCatalog: null as VoiceCatalog | null,
  voiceIndex: {} as Record<string, any>,
  // v6.0 手动模式：创建时的执行模式与暂停点（写入表单提交）
  // v7.6 外部素材模式：execMode 增加第三值 'external'
  execMode: 'auto' as 'auto' | 'manual' | 'external',
  pausePoints: [] as string[],
  // v7.6 外部素材模式：可选外部工具列表（GET /api/providers）与当前所选
  providers: [] as any[],
  providerSelected: '' as string,
  // v7.6 外部素材模式：音频来源（video=用视频自带音频 / project=本项目配音）
  externalAudioSource: 'video' as 'video' | 'project',
  // v7.6 外部素材模式：字幕来源（narration=旁白 / dialogue=人物对白）
  externalSubtitleSource: 'narration' as 'narration' | 'dialogue',
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
