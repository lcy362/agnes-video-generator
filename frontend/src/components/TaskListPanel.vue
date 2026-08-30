<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { useTasks } from '@/composables/useTasks'
import { useConfirm } from '@/composables/useConfirm'
import type { TaskListItem } from '@/types'

const { tasks, loading, loadTaskList, viewTask, viewRunningTask, resumeTask, stopTaskById, deleteTaskById, switchMode } = useTasks()
const { confirmAsync } = useConfirm()

async function toggleMode(task: TaskListItem) {
  const target = task.current_mode === 'manual' ? 'auto' : 'manual'
  if (!(await confirmAsync(target === 'auto' ? t('switchToAutoConfirm') : t('switchToManualConfirm')))) return
  const d = await switchMode(task.task_id, target as 'auto' | 'manual')
  if (d && task.awaiting_user && target === 'auto') {
    // 手动→自动：切换即继续（后端已 resume），刷新列表
    loadList()
  }
}

function loadList() {
  // useTasks 内部轮询 5s；此处立即刷新一次（1.7：收敛裸 fetch 到 useTasks，
  // 复用 in-flight 守卫与错误处理）
  void loadTaskList()
}

const statusColors: Record<string, string> = {
  completed: 'text-emerald-400',
  running: 'text-yellow-400',
  failed: 'text-red-400',
  pending: 'text-muted',
  queued: 'text-accent',
}

const statusLabelKey: Record<string, string> = {
  completed: 'statusCompleted',
  running: 'statusRunning',
  failed: 'statusFailed',
  pending: 'statusPending',
  queued: 'statusQueued',
}

const typeLabelKey: Record<string, string> = {
  simple: 'typeSimple',
  creative: 'typeCreative',
  manuscript: 'typeManuscript',
  anchor: 'typeAnchor',
  poetry: 'typePoetry',
  image: 'typeImage',
}

function taskDesc(task: TaskListItem): string {
  return task.idea || task.prompt || (task.manuscript_text || '').substring(0, 80) || (task.script_text || '').substring(0, 80) || ''
}

function taskExtra(task: TaskListItem): string {
  if (task.scene_count) return ` · ${task.scene_count}${t('sceneUnit')}`
  if (task.paragraph_count) return ` · ${task.paragraph_count}${t('paraUnit')}`
  return ''
}

function isRunning(task: TaskListItem): boolean {
  return task.status === 'running' || task.status === 'queued'
}

function isCompleted(task: TaskListItem): boolean {
  return task.status === 'completed'
}

function mainBtnLabel(task: TaskListItem): string {
  if (isCompleted(task)) return t('btnView')
  if (isRunning(task)) return t('btnViewProgress')
  return t('btnResume')
}

function onMainBtn(task: TaskListItem) {
  if (isCompleted(task)) viewTask(task.task_id)
  else if (isRunning(task)) viewRunningTask(task.task_id)
  else resumeTask(task.task_id)
}
</script>

<template>
  <div class="space-y-3">
    <p v-if="!tasks.length" class="text-muted text-sm">{{ t('noTasks') }}</p>
    <div
      v-for="task in tasks"
      :key="task.task_id"
      class="glass-card rounded-xl p-4 flex items-center justify-between"
    >
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-1">
          <span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent">
            {{ t(typeLabelKey[task.task_type || ''] || '') || task.task_type }}
          </span>
          <p class="text-sm font-medium truncate">{{ task.creative_name || task.task_id }}</p>
          <!-- v6.0 模式徽标 -->
          <span v-if="task.awaiting_user" class="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
            {{ t('awaitingUser') }}
          </span>
          <span v-else-if="task.current_mode === 'manual'" class="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-400">
            ✋ {{ t('execManual') }}
          </span>
        </div>
        <p class="text-xs text-muted mt-0.5">{{ task.task_id }}{{ taskExtra(task) }}</p>
        <p v-if="taskDesc(task)" class="text-xs text-muted mt-1 truncate max-w-xs">{{ taskDesc(task) }}</p>
      </div>
      <div class="flex items-center gap-3 ml-3">
        <span class="text-xs" :class="statusColors[task.status || ''] || 'text-muted'">
          {{ t(statusLabelKey[task.status || ''] || '') || task.status }}
        </span>
        <!-- v6.0 运行时切换（已完成/失败任务不显示） -->
        <button
          v-if="task.current_mode && !isCompleted(task) && task.status !== 'failed' && task.task_type !== 'simple' && task.task_type !== 'image'"
          class="text-xs px-2.5 py-1.5 rounded-lg transition border border-rule text-ink-2 hover:border-accent/40"
          :title="t(task.current_mode === 'manual' ? 'switchToAuto' : 'switchToManual')"
          @click="toggleMode(task)"
        >
          {{ task.current_mode === 'manual' ? t('switchToAuto') : t('switchToManual') }}
        </button>
        <button
          v-if="!isCompleted(task) && !isRunning(task)"
          class="text-xs px-3 py-1.5 bg-paper-3 hover:bg-paper-3 rounded-lg transition"
          @click="viewTask(task.task_id)"
        >
          {{ t('btnView') }}
        </button>
        <button class="text-xs px-3 py-1.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg transition" @click="onMainBtn(task)">
          {{ mainBtnLabel(task) }}
        </button>
        <button
          v-if="isRunning(task)"
          class="text-xs px-3 py-1.5 bg-red-700 hover:bg-red-600 text-red-100 rounded-lg transition"
          @click="stopTaskById(task.task_id)"
        >
          {{ t('btnStop') }}
        </button>
        <button
          v-if="!isRunning(task)"
          class="text-xs px-3 py-1.5 bg-red-900/60 hover:bg-red-700 text-red-200 rounded-lg transition"
          @click="deleteTaskById(task.task_id)"
        >
          {{ t('deleteTask') }}
        </button>
      </div>
    </div>
  </div>
</template>
