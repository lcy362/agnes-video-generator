<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useProgress } from '@/composables/useProgress'
import { useTasks } from '@/composables/useTasks'
import { useNavigation } from '@/composables/useNavigation'
import LangSwitcher from '@/components/shared/LangSwitcher.vue'

const { progressPct, awaitingCheckpoint, taskFailed, needsResume, resumeTask } = useProgress()
const { stopTaskById, switchMode } = useTasks()
const { goBack, goHome } = useNavigation()

const taskId = computed(() => appState.currentTaskId || appState.progressTaskId || '')
const dirName = computed(() => appState.currentDirName || '')

const typeLabelKey: Record<string, string> = {
  simple: 'typeSimple',
  creative: 'typeCreative',
  manuscript: 'typeManuscript',
  anchor: 'typeAnchor',
  poetry: 'typePoetry',
  image: 'typeImage',
}

const statusInfo = computed(() => {
  if (taskFailed.value) return { key: 'statusFailed', cls: 'chip-danger' }
  if (needsResume.value) return { key: 'statusNeedsResume', cls: 'chip-warning' }
  if (awaitingCheckpoint.value) return { key: 'statusAwaitingUser', cls: 'chip-accent' }
  if (appState.isTaskRunning || (progressPct.value > 0 && progressPct.value < 100)) {
    return { key: 'statusRunning', cls: 'chip-warning' }
  }
  return { key: 'statusCompleted', cls: 'chip-success' }
})

function onBack() {
  goBack()
}

function onHome() {
  goHome()
}

async function onStop() {
  if (taskId.value) await stopTaskById(taskId.value)
}

async function onResume() {
  if (taskId.value) await resumeTask(taskId.value)
}

async function onSwitchAuto() {
  if (taskId.value) await switchMode(taskId.value, 'auto')
}
</script>

<template>
  <header
    class="sticky top-0 z-40 border-b border-rule/60"
    style="background: color-mix(in oklab, var(--color-paper) 90%, transparent); backdrop-filter: blur(12px)"
  >
    <div class="mx-auto flex w-full max-w-content items-center gap-2 px-4 py-2.5 lg:px-10">
      <button class="btn btn-quiet h-8 shrink-0 gap-1.5 px-2" @click="onBack">
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M15 6l-6 6 6 6" />
        </svg>
        <span class="hidden text-[11.5px] sm:inline">{{ t('progressBack') }}</span>
      </button>

      <a
        href="#"
        class="btn btn-quiet h-8 shrink-0 gap-1.5 px-2"
        @click.prevent="onHome"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" />
        </svg>
        <span class="hidden text-[11.5px] sm:inline">{{ t('goHome') }}</span>
      </a>

      <span class="mx-0.5 hidden h-4 w-px shrink-0 bg-rule sm:block"></span>

      <div class="flex min-w-0 items-center gap-2">
        <span class="chip chip-accent shrink-0">
          {{ t(typeLabelKey[appState.currentTaskType] || '') || appState.currentTaskType }}
        </span>
        <span class="truncate text-[11.5px] text-ink-2">
          <span class="text-muted">{{ t('task_') }}</span>
          <span class="mono ms-1">{{ taskId }}</span>
        </span>
        <span v-if="dirName" class="mono hidden truncate text-[10.5px] text-muted md:inline">{{ dirName }}</span>
      </div>

      <div class="ms-auto flex shrink-0 items-center gap-1.5">
        <span class="chip" :class="statusInfo.cls">{{ t(statusInfo.key) }}</span>
        <button
          v-if="needsResume"
          class="btn btn-primary btn-sm"
          @click="onResume"
        >
          {{ t('resumeTaskBtn') }}
        </button>
        <button
          v-if="awaitingCheckpoint"
          class="btn btn-ghost btn-sm"
          @click="onSwitchAuto"
        >
          {{ t('switchToAuto') }}
        </button>
        <button
          v-if="appState.isTaskRunning"
          class="btn btn-danger btn-sm"
          @click="onStop"
        >
          {{ t('stopTask') }}
        </button>
        <LangSwitcher compact />
      </div>
    </div>
  </header>
</template>
