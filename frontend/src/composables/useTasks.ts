import { ref } from 'vue'
import { appState } from '@/store'
import * as api from '@/api'
import { t } from '@/i18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useGa } from './useGa'
import { useArtifacts } from './useArtifacts'
import { useNavigation } from './useNavigation'
import type { TaskListItem, TaskState } from '@/types'

const { showToast } = useToast()
const { confirmAsync } = useConfirm()
const { trackEvent } = useGa()
const { loadArtifacts } = useArtifacts()
const { goProgress } = useNavigation()

const tasks = ref<TaskListItem[]>([])
const loading = ref(false)
let taskListTimer: ReturnType<typeof setInterval> | null = null
// 1.7：in-flight 守卫，避免慢请求下 5s 轮询请求堆积
let listInFlight = false

async function loadTaskList() {
  // 1.7：in-flight 守卫 + loading 状态正确赋值（此前只在 catch 置 false，
  // 正常路径从不置 true，loading 从未真正生效）
  if (listInFlight) return
  listInFlight = true
  loading.value = true
  try {
    const d = await api.getTasks()
    tasks.value = d.tasks || []
  } catch (e) {
    // 保留旧列表，不覆盖为失败态（轮询失败静默，下次重试）
  } finally {
    loading.value = false
    listInFlight = false
  }
}

function startTaskListTimer() {
  if (taskListTimer) return
  taskListTimer = setInterval(loadTaskList, 5000)
  // 1.7：后台标签页暂停轮询，恢复可见时立即补一次
  document.addEventListener('visibilitychange', handleTaskListVisibility)
}

function stopTaskListTimer() {
  if (taskListTimer) {
    clearInterval(taskListTimer)
    taskListTimer = null
  }
  document.removeEventListener('visibilitychange', handleTaskListVisibility)
}

function handleTaskListVisibility() {
  if (document.hidden) {
    if (taskListTimer) {
      clearInterval(taskListTimer)
      taskListTimer = null
    }
  } else {
    loadTaskList()
    startTaskListTimer()
  }
}

// 统一入口：跳转进度页（任务加载/轮询/暂停审查由 ProgressPage 挂载时统一处理）
async function viewTask(taskId: string) {
  try {
    const state = await api.getTask(taskId)
    appState.currentTaskType = state.task_type || 'creative'
    appState.currentDirName = state.dir_name || taskId
    goProgress(taskId, 'list')
    return state
  } catch (e: any) {
    showToast(t('failLoad') + ': ' + e.message, 4500)
    return null
  }
}

async function viewRunningTask(taskId: string) {
  return viewTask(taskId)
}

async function resumeTask(taskId: string) {
  try {
    const d = await api.resumeTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failResume'))
    let taskType = 'creative'
    try {
      const st = await api.getTask(taskId)
      taskType = st.task_type || 'creative'
    } catch {
      /* ignore */
    }
    appState.currentTaskType = taskType
    appState.currentDirName = d.dir_name || taskId
    goProgress(taskId, 'list')
    showToast(t('resumed'), 5000, 'success')
  } catch (e: any) {
    showToast(t('failResume') + ': ' + e.message, 4500)
  }
}

async function stopTaskById(taskId: string) {
  if (!(await confirmAsync(t('stopConfirmById')))) return
  try {
    const d = await api.stopTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failStop'))
    trackEvent('task_stopped', { task_type: appState.currentTaskType || '', source: 'list' })
    showToast(t('stoppedById'), 3000, 'success')
    loadTaskList()
  } catch (e: any) {
    showToast(t('failStop') + ': ' + e.message, 4500)
  }
}

async function deleteTaskById(taskId: string) {
  if (!(await confirmAsync(t('deleteTaskConfirm')))) return
  try {
    const d = await api.deleteTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failDelete'))
    trackEvent('task_deleted', { task_type: appState.currentTaskType || '', source: 'list' })
    showToast(t('deletedTask'), 3000, 'success')
    loadTaskList()
  } catch (e: any) {
    showToast(t('failDelete') + ': ' + e.message, 4500)
  }
}

// v6.0 手动模式：运行时切换执行模式
async function switchMode(taskId: string, mode: 'auto' | 'manual') {
  try {
    const d = await api.switchTaskMode(taskId, mode)
    if (!d.ok) throw new Error(d.detail || t('failSwitchMode'))
    showToast(t('modeSwitched'), 3000, 'success')
    loadTaskList()
    // 若正展示该任务进度，刷新
    if (appState.currentTaskId === taskId) {
      await loadArtifactsFor(taskId)
    }
    return d
  } catch (e: any) {
    showToast(t('failSwitchMode') + ': ' + e.message, 4500)
    return null
  }
}

async function loadArtifactsFor(taskId: string) {
  try {
    appState.currentArtifactsTaskId = taskId
    loadArtifacts()
  } catch {
    /* ignore */
  }
}

// 详情展示（由组件消费）
const detailState = ref<TaskState | null>(null)

function showTaskDetail(taskId: string, state: TaskState) {
  detailState.value = state
}

export function useTasks() {
  return {
    tasks,
    loading,
    detailState,
    loadTaskList,
    startTaskListTimer,
    stopTaskListTimer,
    viewTask,
    viewRunningTask,
    resumeTask,
    stopTaskById,
    deleteTaskById,
    switchMode,
    showTaskDetail,
  }
}
