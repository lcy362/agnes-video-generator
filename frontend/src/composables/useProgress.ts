import { ref, computed } from 'vue'
import { appState } from '@/store'
import { getStepsForType, isStepDoneInState } from '@/steps'
import * as api from '@/api'
import { t, escapeHtml } from '@/i18n'
import { useGa } from './useGa'
import { useArtifacts } from './useArtifacts'
import { useToast } from './useToast'
import { getRetryCount, bumpRetryCount, clearRetryCount } from '@/utils/feedback'
import type { TaskState, StepDef } from '@/types'

const POLL_INTERVAL = 30000

const { trackTaskResultOnce } = useGa()
const { showToast } = useToast()

// 产物刷新（模块级单例，进度页共享状态）
const { loadArtifacts, scheduleArtifactRefresh } = useArtifacts()

// 进度展示状态
const progressVisible = ref(false)
const progressPct = ref(0)
const progressMessage = ref('')
const resultVideoVisible = ref(false)
const resultVideoSrc = ref('')
const steps = ref<StepDef[]>([])
const stepStates = ref<Record<string, 'done' | 'running' | 'pending'>>({})
const failedMessage = ref('')
const taskFailed = ref(false)
// v6.0 手动模式：当前检查点（暂停等待用户操作时非空）
const awaitingCheckpoint = ref('')
// v6.1 问题反馈：当前任务的重试次数（驱动反馈区渐进展开）
const retryCount = ref(0)
// v6.1：任务未完成但后台无活跃 pipeline → 待续传（展示续传入口）
const needsResume = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

// 1.7 前端轮询体验：in-flight 守卫 + 连续失败退避提示 + 后台标签页暂停
let pollInFlight = false
let consecutivePollFailures = 0
const connectionLost = ref(false)
const MAX_CONSECUTIVE_POLL_FAILURES = 3

function resetSteps(taskType: string) {
  steps.value = getStepsForType(taskType)
  const st: Record<string, 'done' | 'running' | 'pending'> = {}
  steps.value.forEach((s) => (st[s.key] = 'pending'))
  stepStates.value = st
}

function markStep(stepKey: string, status: 'done' | 'running' | 'pending') {
  stepStates.value[stepKey] = status
}

function markCompletedStepsFromState(state: TaskState) {
  const taskType = state.task_type || appState.currentTaskType || 'creative'
  steps.value.forEach((s) => {
    if (isStepDoneInState(state, s.key, taskType)) {
      markStep(s.key, 'done')
    }
  })
}

function setProgressMessageHtml(html: string) {
  progressMessage.value = html
}

const currentRunningStep = computed(() => {
  return steps.value.find((s) => stepStates.value[s.key] === 'running')
})

async function showProgress(taskId: string, dirName?: string | null): Promise<TaskState | null> {
  progressVisible.value = true
  taskFailed.value = false
  resultVideoVisible.value = false
  progressPct.value = 0

  let state: TaskState | null = null
  try {
    state = await api.getTask(taskId)
    if (state && state.task_type) appState.currentTaskType = state.task_type
  } catch {
    /* ignore */
  }

  resetSteps(appState.currentTaskType)

  // 标记已完成步骤
  if (state) {
    markCompletedStepsFromState(state)
    const step = (state.current_step || '').replace(/^step_/, '')
    const status = state.current_status || ''
    if (step && status === 'running') {
      markStep(step, 'running')
    }
  }

  // 优化路线图 0.8：dirName / taskId 均来自后端（目录名可含用户输入），
  // 而 progressMessage 最终由 v-html 渲染，必须先转义再拼接，否则构成 XSS
  const dirInfo = dirName ? `<br><span class="text-muted text-xs">${t('dir')}: <span class="font-mono">${escapeHtml(dirName)}</span></span>` : ''
  progressMessage.value = `<span class="text-accent animate-pulse">${t('taskStarting')}</span><br><span class="text-muted">${t('task_')}: ${escapeHtml(taskId)}</span>${dirInfo}`

  // 加载已有中间产物（任务运行中也可查看）
  appState.currentArtifactsTaskId = taskId
  loadArtifacts()
  return state
}

// 进度页挂载：加载任务 + 按状态决定轮询/结果/暂停审查
async function mountProgressPage(taskId: string, dirName?: string | null) {
  const state = await showProgress(taskId, dirName)
  if (!state) return state
  appState.currentTaskType = state.task_type || appState.currentTaskType
  appState.currentDirName = state.dir_name || dirName || taskId
  const st = state.status
  // 后台是否真有活跃 pipeline：false 且任务未完成 → 需要续传
  const hasActive = state.active === true
  if ((st === 'running' || st === 'queued') && hasActive) {
    setRunning(taskId)
    // 立即用后端实时进度消息（排队中/当前步骤），避免首次展示「任务启动中 + 0%」占位
    if (state.current_message) {
      setProgressMessageHtml(
        `<span class="text-accent animate-pulse">${escapeHtml(state.current_message)}</span>`,
      )
    }
    startPolling(taskId)
  } else if (st === 'completed') {
    if (state.final_video_file) showResult(state.final_video_file, taskId)
    clearRetryCount(taskId)
    retryCount.value = 0
    clearRunning()
  } else if (st === 'failed') {
    taskFailed.value = true
    failedMessage.value = state.current_message || t('genFailedMsg')
    retryCount.value = getRetryCount(taskId)
    clearRunning()
  } else if (st === 'pending' && state.current_status === 'awaiting_user') {
    // 暂停等待用户操作：释放并发槽位，不轮询
    const cp = (state as any).manual_config?.current_checkpoint || ''
    if (cp) awaitingCheckpoint.value = cp
    appState.isTaskRunning = false
  } else if (!hasActive) {
    // 未完成但后台无活跃 pipeline（服务重启后遗留 / 创建后未启动）：
    // 标记「待续传」，不轮询，提示用户点击续传恢复执行
    needsResume.value = true
    appState.isTaskRunning = false
    setProgressMessageHtml(
      `<span class="text-amber-400">${t('taskNotRunning')}</span><br><span class="text-muted text-xs">${t('taskNotRunningHint')}</span>`,
    )
  }
  return state
}

// 续传：调用后端 resume，恢复执行并立即进入轮询
async function resumeTask(taskId: string) {
  try {
    const d = await api.resumeTask(taskId)
    if (!d.ok) {
      showToast(t('failResume') + (d.detail ? ': ' + d.detail : ''), 3500)
      return
    }
    needsResume.value = false
    taskFailed.value = false
    setRunning(taskId)
    setProgressMessageHtml(`<span class="text-accent animate-pulse">${t('resuming')}</span>`)
    startPolling(taskId)
  } catch (e: any) {
    showToast(t('failResume') + (e.message ? ': ' + e.message : ''), 3500)
  }
}

// v6.1 问题反馈：失败任务重试（复用 resume 断点续传；被接受后重试计数 +1，
// 计数驱动失败面板「先重试、后上报」的渐进引导）
async function retryFailedTask(taskId: string) {
  try {
    const d = await api.resumeTask(taskId)
    if (!d.ok) {
      showToast(t('failResume') + (d.detail ? ': ' + d.detail : ''), 3500)
      return
    }
    retryCount.value = bumpRetryCount(taskId)
    needsResume.value = false
    taskFailed.value = false
    setRunning(taskId)
    setProgressMessageHtml(`<span class="text-accent animate-pulse">${t('resuming')}</span>`)
    startPolling(taskId)
  } catch (e: any) {
    showToast(t('failResume') + (e.message ? ': ' + e.message : ''), 3500)
  }
}

// 进度页卸载：停止一切轮询与临时状态
function unmountProgressPage() {
  stopPolling()
  appState.isTaskRunning = false
  appState.currentTaskId = null
  appState.currentArtifactsTaskId = null
  awaitingCheckpoint.value = ''
  needsResume.value = false
  taskFailed.value = false
  retryCount.value = 0
}

async function pollTaskProgress(taskId: string) {
  if (!appState.isTaskRunning || !taskId) return
  // 1.7：in-flight 守卫，避免慢请求下轮询请求堆积、响应乱序覆盖进度
  if (pollInFlight) return
  pollInFlight = true
  try {
    const state = await api.getTask(taskId)
    consecutivePollFailures = 0
    connectionLost.value = false

    progressPct.value = Math.round((state.current_progress || 0) * 100)
    if (state.current_message) {
      // 0.8：后端消息最终由 v-html 渲染，必须转义
      progressMessage.value = escapeHtml(state.current_message)
    }

    markCompletedStepsFromState(state)

    const step = (state.current_step || '').replace(/^step_/, '')
    const status = state.current_status || ''
    if (step && status === 'running') {
      markStep(step, 'running')
    }

    // 步骤 running 或完成时刷新产物列表（running 期间产物逐步生成）
    if (step) {
      scheduleArtifactRefresh()
    }

    if (state.status === 'completed') {
      trackTaskResultOnce('task_completed', taskId, {
        task_type: state.task_type || appState.currentTaskType,
        // simple 任务携带生成模式（t2v / i2v / ti2vid / keyframes），便于 GA 按模式统计生成量
        ...(state.mode ? { mode: state.mode } : {}),
      })
      showResult(state.final_video_file, taskId)
      clearRetryCount(taskId)
      retryCount.value = 0
      clearRunning()
      scheduleArtifactRefresh()
    }

    if (state.status === 'failed' || (step === 'error' && status === 'failed')) {
      trackTaskResultOnce('task_failed', taskId, {
        task_type: state.task_type || appState.currentTaskType,
        ...(state.mode ? { mode: state.mode } : {}),
        error: (state.current_message || '').slice(0, 120),
      })
      clearRunning()
      taskFailed.value = true
      failedMessage.value = state.current_message || t('genFailedMsg')
      retryCount.value = getRetryCount(taskId)
    }

    // v6.0 手动模式：检测暂停等待（PENDING + current_checkpoint）
    const mc = (state as any).manual_config
    const cp = mc?.current_checkpoint || ''
    if (state.status === 'pending' && state.current_status === 'awaiting_user' && cp) {
      awaitingCheckpoint.value = cp
      // 暂停时不视为运行中（释放并发槽位后前端也停止轮询视为等待）
      appState.isTaskRunning = false
      scheduleArtifactRefresh()
    } else if (awaitingCheckpoint.value && (state.status === 'running' || state.status === 'queued')) {
      // 已恢复执行（含排队阶段）：立即清除暂停 UI，避免「继续」按钮残留可点
      awaitingCheckpoint.value = ''
    }
  } catch {
    // 1.7：连续失败 N 次 → 提示连接异常（此前无限静默轮询，用户看不到原因）
    consecutivePollFailures += 1
    if (consecutivePollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
      connectionLost.value = true
    }
  } finally {
    pollInFlight = false
  }
}

function startPolling(taskId: string) {
  stopPolling()
  // 立即执行首次轮询：恢复/继续后无需等一个完整轮询周期（30s）即可刷新状态
  void pollTaskProgress(taskId)
  pollTimer = setInterval(() => pollTaskProgress(taskId), POLL_INTERVAL)
  // 1.7：后台标签页暂停轮询，恢复可见时立即补一次（省资源 + 状态不落后）
  document.addEventListener('visibilitychange', handlePollVisibility)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  document.removeEventListener('visibilitychange', handlePollVisibility)
  connectionLost.value = false
}

function handlePollVisibility() {
  if (document.hidden) {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } else if (appState.currentTaskId) {
    // 恢复可见：立即补一次轮询并恢复定时器
    void pollTaskProgress(appState.currentTaskId)
    startPolling(appState.currentTaskId)
  }
}

function showResult(videoPath?: string, taskId?: string | null) {
  if (videoPath && taskId) {
    resultVideoVisible.value = true
    resultVideoSrc.value = '/api/video/' + taskId
  }
}

function setRunning(taskId: string) {
  appState.isTaskRunning = true
  appState.currentTaskId = taskId
  // 进入运行态即代表暂停结束：乐观清除暂停审查 UI，避免「继续」按钮残留
  awaitingCheckpoint.value = ''
}

function clearRunning() {
  appState.isTaskRunning = false
  appState.currentTaskId = null
  stopPolling()
}

export function useProgress() {
  return {
    progressVisible,
    progressPct,
    progressMessage,
    resultVideoVisible,
    resultVideoSrc,
    steps,
    stepStates,
    taskFailed,
    failedMessage,
    awaitingCheckpoint,
    needsResume,
    retryCount,
    connectionLost,
    retryFailedTask,
    resumeTask,
    showProgress,
    mountProgressPage,
    unmountProgressPage,
    pollTaskProgress,
    startPolling,
    stopPolling,
    showResult,
    setRunning,
    clearRunning,
    markStep,
    markCompletedStepsFromState,
    resetSteps,
    setProgressMessageHtml,
  }
}
