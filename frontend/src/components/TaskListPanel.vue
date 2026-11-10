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

const statusChip: Record<string, string> = {
  completed: 'chip-success',
  running: 'chip-warning',
  failed: 'chip-danger',
  pending: '',
  queued: 'chip-accent',
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
  <div>
    <p v-if="!tasks.length" class="panel px-4 py-12 text-center text-[12.5px] text-muted">
      {{ t('noTasks') }}
    </p>

    <div v-else class="panel overflow-hidden">
      <div
        v-for="(task, i) in tasks"
        :key="task.task_id"
        class="flex flex-wrap items-center gap-x-4 gap-y-2.5 px-4 py-3 transition-colors hover:bg-paper-3/40"
        :class="i > 0 ? 'border-t border-rule' : ''"
      >
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="chip chip-accent">{{ t(typeLabelKey[task.task_type || ''] || '') || task.task_type }}</span>
            <p class="truncate text-[13px] font-medium text-ink">{{ task.creative_name || task.task_id }}</p>
            <!-- v6.0 模式徽标 -->
            <span v-if="task.awaiting_user" class="chip chip-warning">{{ t('awaitingUser') }}</span>
            <span v-else-if="task.current_mode === 'manual'" class="chip">{{ t('execManual') }}</span>
          </div>
          <p class="mono mt-1 text-[10.5px] tracking-wide text-muted/80">{{ task.task_id }}{{ taskExtra(task) }}</p>
          <p v-if="taskDesc(task)" class="mt-1 line-clamp-1 max-w-lg text-[11.5px] text-muted">{{ taskDesc(task) }}</p>
        </div>

        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <span class="chip" :class="statusChip[task.status || ''] || ''">
            {{ t(statusLabelKey[task.status || ''] || '') || task.status }}
          </span>
          <!-- v6.0 运行时切换（已完成/失败任务不显示） -->
          <button
            v-if="task.current_mode && !isCompleted(task) && task.status !== 'failed' && task.task_type !== 'simple' && task.task_type !== 'image'"
            class="btn btn-ghost btn-xs"
            :title="t(task.current_mode === 'manual' ? 'switchToAuto' : 'switchToManual')"
            @click="toggleMode(task)"
          >
            {{ task.current_mode === 'manual' ? t('switchToAuto') : t('switchToManual') }}
          </button>
          <button
            v-if="!isCompleted(task) && !isRunning(task)"
            class="btn btn-ghost btn-xs"
            @click="viewTask(task.task_id)"
          >
            {{ t('btnView') }}
          </button>
          <button class="btn btn-secondary btn-xs" @click="onMainBtn(task)">
            {{ mainBtnLabel(task) }}
          </button>
          <button
            v-if="isRunning(task)"
            class="btn btn-danger btn-xs"
            @click="stopTaskById(task.task_id)"
          >
            {{ t('btnStop') }}
          </button>
          <button
            v-if="!isRunning(task)"
            class="btn btn-quiet btn-xs text-muted transition-colors hover:text-danger"
            @click="deleteTaskById(task.task_id)"
          >
            {{ t('deleteTask') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
