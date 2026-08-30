<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { t, LANGS, useI18n } from '@/i18n'
import { useTheme } from '@/composables/useTheme'
import { useToast } from '@/composables/useToast'
import { useConfig } from '@/composables/useConfig'
import { useVoice } from '@/composables/useVoice'
import { useTasks } from '@/composables/useTasks'
import { useProgress } from '@/composables/useProgress'
import { useNavigation } from '@/composables/useNavigation'
import { appState } from '@/store'
import ConfigPanel from '@/components/ConfigPanel.vue'
import CreatePanel from '@/components/CreatePanel.vue'
import TaskListPanel from '@/components/TaskListPanel.vue'
import ProgressPage from '@/components/ProgressPage.vue'
import VoicePickerModal from '@/components/VoicePickerModal.vue'
import Toast from '@/components/Toast.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'

const { switchLang } = useI18n()
const { themeIcon, themeLabel, cycleTheme } = useTheme()
const { visible: toastVisible, message: toastMessage, type: toastType } = useToast()
const { loadModels, renderWorkspaces } = useConfig()
const { initVoiceSelector } = useVoice()
const { loadTaskList, startTaskListTimer, stopTaskListTimer } = useTasks()
const { parseHash } = useNavigation()

function switchMainTab(tab: 'create' | 'list') {
  appState.view = tab
  location.hash = tab === 'list' ? '#/list' : '#/create'
  if (tab === 'list') {
    loadTaskList()
    startTaskListTimer()
  } else {
    stopTaskListTimer()
  }
}

const isConfigLoaded = ref(false)

onMounted(async () => {
  // 解析 hash：直达进度页 / 列表页（刷新保留视图）
  const parsed = parseHash()
  if (parsed.view === 'progress' && parsed.taskId) {
    appState.view = 'progress'
    appState.progressTaskId = parsed.taskId
    appState.currentTaskId = parsed.taskId
    // 其余恢复逻辑由 ProgressPage 挂载时统一处理
  } else {
    appState.view = parsed.view
  }

  try {
    const cfg = await fetch('/api/config').then((r) => r.json())
    if (cfg.api_key) {
      appState.apiKeySource = cfg.source
    }
    // v6.1 问题反馈：记录应用版本（诊断信息用；缺失时 FeedbackPanel 自兜底拉取）
    if (cfg.app_version) {
      appState.appVersion = cfg.app_version
    }
    await renderWorkspaces()
    if (cfg.watermark !== undefined) {
      appState.watermarkEnabled = !!cfg.watermark.enabled
    }
    if (cfg.agnes_domain) {
      appState.agnesDomain = cfg.agnes_domain
    }
    await loadModels()
    isConfigLoaded.value = true
  } catch (e) {
    console.error('init config load error:', e)
  }

  try {
    await initVoiceSelector()
  } catch (e) {
    console.error('init voice selector error:', e)
  }

  // 自动重连运行中的任务（已在进度页时跳过，由 ProgressPage 恢复）
  if (appState.view !== 'progress') {
    autoReconnectRunningTask()
  }
})

async function autoReconnectRunningTask() {
  try {
    const d = await fetch('/api/tasks').then((r) => r.json())
    const running = (d.tasks || []).find((t: any) => t.status === 'running' || t.status === 'queued')
    if (running) {
      appState.currentTaskType = running.task_type || 'creative'
      appState.currentDirName = running.dir_name || running.task_id
      appState.progressTaskId = running.task_id
      appState.progressOrigin = 'create'
      appState.view = 'progress'
      location.hash = '#/progress/' + encodeURIComponent(running.task_id)
    }
  } catch {
    /* ignore */
  }
}
</script>

<template>
  <ProgressPage v-if="appState.view === 'progress'" />

  <div v-else class="flex justify-center gap-3 px-4">
    <!-- Left sidebar -->
    <aside class="hidden lg:block sticky top-[120px] self-start w-[130px] shrink-0 mt-8">
      <div class="sidebar-card">
        <div class="stitle">{{ t('adSupportTitle') }}</div>
        <p class="text-muted text-xs leading-relaxed mb-2">{{ t('adSupportDesc') }}</p>
        <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener">{{ t('adStar') }}</a>
        <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adStarDesc') }}</p>
        <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ t('adAdblock') }}</a>
        <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adAdblockDesc') }}</p>
        <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ t('adClick') }}</a>
        <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adClickDesc') }}</p>
        <p class="text-muted text-xs mt-2 leading-relaxed">{{ t('adThanks') }}</p>
      </div>
    </aside>

    <!-- Main content -->
    <div class="max-w-4xl flex-1 min-w-0 py-8">
      <!-- Header -->
      <div class="text-center mb-10">
        <div class="flex items-center justify-end gap-2 mb-5">
          <button
            class="glass-input rounded-lg px-3 py-1.5 text-sm cursor-pointer text-ink flex items-center gap-1.5 hover:border-accent/40 transition"
            :title="themeLabel"
            :aria-label="themeLabel"
            @click="cycleTheme"
          >
            <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" :d="themeIcon"></path>
            </svg>
            <span class="text-xs whitespace-nowrap">{{ themeLabel }}</span>
          </button>
          <select
            class="glass-input rounded-lg px-3 py-1.5 text-sm cursor-pointer text-ink"
            @change="switchLang(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</option>
          </select>
        </div>
        <h1 class="text-2xl sm:text-4xl font-bold text-ink px-2" style="position: relative; z-index: 0">Agnes Video Generator</h1>
        <p class="text-muted mt-2 text-sm tracking-wide px-2">{{ t('subtitle') }}</p>
      </div>

      <!-- Resource links（窄屏可换行） -->
      <nav class="flex justify-center items-center gap-x-4 gap-y-1.5 flex-wrap mb-8 text-xs tracking-wide">
        <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="flex items-center gap-1 text-accent hover:text-ink transition-colors">🎬 Demo</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">🏠 Home</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">📖 Guides</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">❓ FAQ</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">📖 GitHub</a>
      </nav>

      <!-- Config Panel -->
      <ConfigPanel />

      <!-- Main Tabs -->
      <div class="flex gap-2 mb-6">
        <button
          class="px-5 py-2.5 rounded-lg text-sm font-medium transition"
          :class="appState.view === 'create' ? 'tab-active' : 'tab-inactive'"
          @click="switchMainTab('create')"
        >
          {{ t('tabCreate') }}
        </button>
        <button
          class="px-5 py-2.5 rounded-lg text-sm font-medium transition"
          :class="appState.view === 'list' ? 'tab-active' : 'tab-inactive'"
          @click="switchMainTab('list')"
        >
          {{ t('tabList') }}
        </button>
      </div>

      <!-- Create Panel -->
      <div v-show="appState.view === 'create'">
        <CreatePanel />
      </div>

      <!-- List Panel -->
      <div v-show="appState.view === 'list'">
        <TaskListPanel />
      </div>

      <!-- Footer -->
      <footer class="text-center pb-8">
        <div class="border-t border-rule/30 pt-8 mt-4">
          <p class="text-xs text-muted mb-3">{{ t('moreResources') }}</p>
          <div class="flex justify-center flex-wrap gap-x-5 gap-y-2 text-xs">
            <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('projectHome') }}</a>
            <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">{{ t('onlineDemo') }}</a>
            <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('usageGuide') }}</a>
            <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('faqTitle') }}</a>
            <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('apiDocs') }}</a>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('appScenarios') }}</a>
            <a href="https://video.lichuanyang.top/zh/guides/free-ai-tools" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('agentMoreTools') }}</a>
            <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">📖 GitHub</a>
          </div>
        </div>
      </footer>
    </div>

    <!-- Right sidebar -->
    <aside class="hidden lg:block sticky top-[120px] self-start w-[115px] shrink-0 mt-8">
      <div class="sidebar-card">
        <div class="stitle">{{ t('quickLinks') }}</div>
        <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener">{{ t('onlineDemo') }}</a>
        <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener">{{ t('promptTips') }}</a>
        <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener">{{ t('modelOverview') }}</a>
        <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener">{{ t('apiCall') }}</a>
        <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener">{{ t('faqTitle') }}</a>
        <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener">{{ t('apiDocs') }}</a>
        <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener">{{ t('appScenarios') }}</a>
      </div>
    </aside>
  </div>

  <!-- Voice Picker Modal -->
  <VoicePickerModal />

  <!-- Toast / Confirm -->
  <Toast :visible="toastVisible" :message="toastMessage" :type="toastType" />
  <ConfirmModal />
</template>
