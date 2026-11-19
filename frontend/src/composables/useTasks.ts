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
const { trackEvent, trackTaskCompletedOnce, seedCompletedTasks } = useGa()
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
    reportCompletedTasks(tasks.value)
  } catch (e) {
    // 保留旧列表，不覆盖为失败态（轮询失败静默，下次重试）
  } finally {
    loading.value = false
    listInFlight = false
  }
}

/**
 * 列表轮询补报「生成成功」。
 *
 * 进度页只在用户停留观察时上报 task_completed，会漏掉：一键创作（提交后回列表）、
 * 图片任务（结果留在表单内）、用户中途离开/刷新。列表每 5s 轮询一次状态，
 * 因此在这里补报：首次运行只播种历史已完成任务（不上报，避免历史数据突增），
 * 之后新出现的 completed 才会计数，且与进度页共享 taskId 级去重。
 */
function reportCompletedTasks(list: TaskListItem[]) {
  const done = list.filter((it) => it.status === 'completed' && it.task_id)
  if (!done.length) return
  if (seedCompletedTasks(done.map((it) => it.task_id))) return
  for (const it of done) {
    trackTaskCompletedOnce(it.task_id, {
      task_type: it.task_type || '',
      ...(it.mode ? { mode: it.mode } : {}),
      source: 'list_sweep',
    })
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

/** 操作来源：列表页 / 进度页。此前写死 'list'，进度页停止会被统计成列表页停止 */
export interface TaskActionContext {
  source?: 'list' | 'progress'
  /** 被操作任务自身的类型（不能用 appState.currentTaskType，跨类型操作会归因错） */
  taskType?: string
}

async function stopTaskById(taskId: string, ctx: TaskActionContext = {}) {
  if (!(await confirmAsync(t('stopConfirmById'), { action: 'stop_task' }))) return
  try {
    const d = await api.stopTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failStop'))
    trackEvent('task_stopped', {
      task_type: ctx.taskType || appState.currentTaskType || '',
      source: ctx.source || 'list',
    })
    showToast(t('stoppedById'), 3000, 'success')
    loadTaskList()
  } catch (e: any) {
    showToast(t('failStop') + ': ' + e.message, 4500)
  }
}

async function deleteTaskById(taskId: string, ctx: TaskActionContext = {}) {
  if (!(await confirmAsync(t('deleteTaskConfirm'), { action: 'delete_task' }))) return
  try {
    const d = await api.deleteTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failDelete'))
    trackEvent('task_deleted', {
      task_type: ctx.taskType || appState.currentTaskType || '',
      source: ctx.source || 'list',
    })
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
    trackEvent('task_mode_switched', { mode, task_type: appState.currentTaskType || '' })
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
