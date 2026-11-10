<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { t } from '@/i18n'
import { useTheme } from '@/composables/useTheme'
import { useToast } from '@/composables/useToast'
import { useConfig } from '@/composables/useConfig'
import { useVoice } from '@/composables/useVoice'
import { useTasks } from '@/composables/useTasks'
import { useProgress } from '@/composables/useProgress'
import { useNavigation } from '@/composables/useNavigation'
import { useGallery } from '@/composables/useGallery'
import { useModalA11y } from '@/composables/useModalA11y'
import { appState } from '@/store'
import { stripEmoji } from '@/utils/text'
import ConfigPanel from '@/components/ConfigPanel.vue'
import CreatePanel from '@/components/CreatePanel.vue'
import SimplePanel from '@/components/SimplePanel.vue'
import TaskListPanel from '@/components/TaskListPanel.vue'
import GalleryPanel from '@/components/GalleryPanel.vue'
import ProgressPage from '@/components/ProgressPage.vue'
import VoicePickerModal from '@/components/VoicePickerModal.vue'
import Toast from '@/components/Toast.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import RealNameNoticeModal from '@/components/RealNameNoticeModal.vue'
import LangSwitcher from '@/components/shared/LangSwitcher.vue'

const { themeIcon, themeLabel, cycleTheme } = useTheme()
const { visible: toastVisible, message: toastMessage, type: toastType } = useToast()
const { loadModels, renderWorkspaces } = useConfig()
const { initVoiceSelector } = useVoice()
const { loadTaskList, startTaskListTimer, stopTaskListTimer } = useTasks()
const { parseHash } = useNavigation()
const { loadGallery, startGalleryTimer, stopGalleryTimer } = useGallery()

// ── 视图导航（结构重构：顶部标签 → 左侧导航栏）──
// 图标为 24×24 stroke path，序号用等宽字体承担「工位编号」的顺序感。
const NAV = [
  { key: 'create', labelKey: 'tabCreate', num: '01', d: 'M12 5v14M5 12h14' },
  { key: 'simple', labelKey: 'tabSimple', num: '02', d: 'M13 3 4.5 13.5H10l-1 7.5 9-11h-5.5L13 3Z' },
  { key: 'list', labelKey: 'tabList', num: '03', d: 'M4 7h16M4 12h16M4 17h10' },
  { key: 'gallery', labelKey: 'tabGallery', num: '04', d: 'M4 5h16v14H4zM4 15.5l4.5-4.5L12 14.5l3-3L20 15.5' },
] as const

/** 去掉语言包标签里自带的表情前缀（如「⚡ 一键创作」），图标位置交给 SVG。 */
function navLabel(key: string): string {
  return stripEmoji(t(key))
}

function switchMainTab(tab: 'create' | 'list' | 'simple' | 'gallery') {
  appState.view = tab
  location.hash =
    tab === 'list' ? '#/list' : tab === 'simple' ? '#/simple' : tab === 'gallery' ? '#/gallery' : '#/create'
  if (tab === 'list') {
    loadTaskList()
    startTaskListTimer()
  } else if (tab === 'gallery') {
    loadGallery()
    startGalleryTimer()
  } else {
    stopTaskListTimer()
    stopGalleryTimer()
  }
}

// ── 系统配置抽屉（原创建页顶部的 4 个配置面板，逻辑与挂载时机不变）──
const settingsOpen = ref(false)
const { containerRef: settingsRef } = useModalA11y(settingsOpen, () => (settingsOpen.value = false))

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
    if (parsed.view === 'gallery') {
      loadGallery()
      startGalleryTimer()
    }
    // 直达/刷新 #/list 时同步拉起任务列表轮询（原先只有点标签才会加载，刷新会误显示空列表）
    if (parsed.view === 'list') {
      loadTaskList()
      startTaskListTimer()
    }
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

  <div v-else class="min-h-screen">
    <!-- ══ 桌面：左侧固定导航 ══ -->
    <aside class="rail hidden lg:flex">
      <div class="pb-6">
        <p class="eyebrow">Agnes · Workbench</p>
        <p class="mt-2.5 text-[14px] font-semibold leading-tight tracking-[-0.01em] text-ink">
          Video Generator
        </p>
      </div>

      <nav class="flex flex-col gap-0.5" :aria-label="navLabel('tabCreate')">
        <button
          v-for="n in NAV"
          :key="n.key"
          type="button"
          class="nav-item"
          :class="appState.view === n.key ? 'is-active' : ''"
          :aria-current="appState.view === n.key ? 'page' : undefined"
          @click="switchMainTab(n.key)"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path :d="n.d" />
          </svg>
          <span class="flex-1 truncate text-start">{{ navLabel(n.labelKey) }}</span>
          <span class="nav-num">{{ n.num }}</span>
        </button>
      </nav>

      <div class="mt-auto">
        <div class="border-t border-rule/60 pt-3">
          <button type="button" class="nav-item" @click="settingsOpen = true">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.4-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.9 1.4l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 11a2 2 0 1 1 0 4Z" />
            </svg>
            <span class="flex-1 truncate text-start">{{ t('navSettings') }}</span>
            <span
              v-if="!appState.apiKeySource"
              class="h-1.5 w-1.5 shrink-0 rounded-full"
              style="background: var(--color-warning)"
              aria-hidden="true"
            ></span>
          </button>
        </div>

        <div class="mt-4 border-t border-rule/60 pt-4">
          <p class="eyebrow px-2.5">{{ t('adSupportTitle') }}</p>
          <p class="mt-1.5 px-2.5 text-[10.5px] leading-relaxed text-muted/75">{{ t('adSupportDesc') }}</p>
          <div class="mt-2.5 space-y-2.5">
            <div>
              <a
                href="https://github.com/lcy362/agnes-video-generator"
                target="_blank"
                rel="noopener"
                class="block rounded px-2.5 text-[11.5px] text-muted transition-colors hover:text-ink-2"
              >{{ stripEmoji(t('adStar')) }}</a>
              <p class="px-2.5 text-[10.5px] leading-snug text-muted/75">{{ t('adStarDesc') }}</p>
            </div>
            <div>
              <a
                href="https://github.com/lcy362/flint"
                target="_blank"
                rel="noopener"
                class="block rounded px-2.5 text-[11.5px] text-muted transition-colors hover:text-ink-2 break-words"
              >{{ stripEmoji(t('adSkewStar')) }}</a>
              <p class="px-2.5 text-[10.5px] leading-snug text-muted/75">{{ t('adSkewStarDesc') }}</p>
            </div>
            <div>
              <a
                href="https://video.lichuanyang.top"
                target="_blank"
                rel="noopener"
                class="block rounded px-2.5 text-[11.5px] text-muted transition-colors hover:text-ink-2"
              >{{ stripEmoji(t('adAdblock')) }}</a>
              <p class="px-2.5 text-[10.5px] leading-snug text-muted/75">{{ t('adAdblockDesc') }}</p>
            </div>
            <div>
              <a
                href="https://video.lichuanyang.top"
                target="_blank"
                rel="noopener"
                class="block rounded px-2.5 text-[11.5px] text-muted transition-colors hover:text-ink-2"
              >{{ stripEmoji(t('adClick')) }}</a>
              <p class="px-2.5 text-[10.5px] leading-snug text-muted/75">{{ t('adClickDesc') }}</p>
            </div>
          </div>
          <p class="mt-3 px-2.5 text-[10.5px] leading-relaxed text-muted/70">{{ t('adThanks') }}</p>
        </div>
      </div>
    </aside>

    <!-- ══ 主内容区 ══ -->
    <div class="lg:ms-[236px]">
      <!-- 移动端顶栏 -->
      <div
        class="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-rule/60 px-4 lg:hidden"
        style="height: 52px; background: color-mix(in oklab, var(--color-paper) 88%, transparent); backdrop-filter: blur(12px)"
      >
        <div class="min-w-0">
          <p class="eyebrow leading-none">Agnes · Workbench</p>
          <p class="mt-1 truncate text-[12.5px] font-semibold text-ink">Video Generator</p>
        </div>
        <div class="flex shrink-0 items-center gap-1">
          <button
            type="button"
            class="btn btn-quiet h-8 w-8 px-0"
            :title="t('navSettings')"
            :aria-label="t('navSettings')"
            @click="settingsOpen = true"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M4 7h8M16 7h4M4 17h4M12 17h8" />
              <circle cx="14" cy="7" r="2" />
              <circle cx="10" cy="17" r="2" />
            </svg>
          </button>
        </div>
      </div>

      <main class="mx-auto w-full max-w-content px-4 py-6 sm:px-7 lg:px-10 lg:py-9">
        <!-- 页头 -->
        <header class="mb-6 flex items-start justify-between gap-4 border-b border-rule/60 pb-5">
          <div class="min-w-0">
            <h1 class="text-[21px] font-semibold leading-[1.15] tracking-[-0.025em] text-ink sm:text-[25px]">
              Agnes Video Generator
            </h1>
            <p class="mt-1.5 text-[12.5px] tracking-wide text-muted">{{ t('subtitle') }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-1">
            <button
              type="button"
              class="btn btn-quiet h-8 gap-1.5 px-2"
              :title="themeLabel"
              :aria-label="themeLabel"
              @click="cycleTheme"
            >
              <svg class="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.6" :d="themeIcon"></path>
              </svg>
              <span class="hidden text-[11.5px] whitespace-nowrap sm:inline">{{ themeLabel }}</span>
            </button>
            <LangSwitcher />
          </div>
        </header>

        <!-- 移动端横向导航 -->
        <nav class="mb-5 flex gap-1.5 overflow-x-auto pb-1 lg:hidden" :aria-label="navLabel('tabCreate')">
          <button
            v-for="n in NAV"
            :key="n.key"
            type="button"
            class="flex shrink-0 items-center gap-1.5 rounded border px-3 py-1.5 text-[12.5px] transition-colors"
            :class="appState.view === n.key ? 'border-rule-2 bg-paper-3 text-ink' : 'border-rule text-muted'"
            :aria-current="appState.view === n.key ? 'page' : undefined"
            @click="switchMainTab(n.key)"
          >
            <span class="mono text-[9px]" :class="appState.view === n.key ? 'text-accent' : ''">{{ n.num }}</span>
            <span>{{ navLabel(n.labelKey) }}</span>
          </button>
        </nav>

        <!-- 创建 -->
        <div v-show="appState.view === 'create'">
          <CreatePanel />
        </div>

        <!-- 一键创作 -->
        <div v-show="appState.view === 'simple'">
          <SimplePanel @go-list="switchMainTab('list')" />
        </div>

        <!-- 任务列表 -->
        <div v-show="appState.view === 'list'">
          <TaskListPanel />
        </div>

        <!-- 产物画廊 -->
        <div v-show="appState.view === 'gallery'">
          <GalleryPanel />
        </div>

        <!-- 页脚：资源索引 -->
        <footer class="mt-12 border-t border-rule/60 pt-6">
          <p class="eyebrow mb-3">{{ t('moreResources') }}</p>
          <div class="flex flex-wrap gap-x-5 gap-y-2 text-[11.5px]">
            <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('projectHome') }}</a>
            <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-accent transition-colors hover:text-ink">{{ t('onlineDemo') }}</a>
            <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('usageGuide') }}</a>
            <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('faqTitle') }}</a>
            <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('apiDocs') }}</a>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('appScenarios') }}</a>
            <a href="https://github.com/lcy362/flint" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('flintLinkLabel') }}</a>
            <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">GitHub</a>
          </div>
          <!-- v7.0 U8：暴露应用版本，便于判断「模型档位未适配是否因版本过旧」 -->
          <p v-if="appState.appVersion" class="mono mt-4 text-[10.5px] tracking-wide text-muted/70">
            {{ t('footerVersion') }} v{{ appState.appVersion }}
          </p>
        </footer>
      </main>
    </div>

    <!-- ══ 系统配置抽屉 ══ -->
    <div v-if="settingsOpen" class="drawer-backdrop" @click="settingsOpen = false"></div>
    <div
      v-show="settingsOpen"
      ref="settingsRef"
      class="drawer"
      role="dialog"
      aria-modal="true"
      :aria-label="t('navSettings')"
    >
      <div class="drawer-head">
        <div class="min-w-0">
          <p class="eyebrow">System</p>
          <h2 class="mt-1 text-[15px] font-semibold tracking-[-0.01em] text-ink">{{ t('navSettings') }}</h2>
        </div>
        <button
          type="button"
          class="btn btn-quiet h-8 w-8 px-0 text-[15px]"
          :aria-label="t('close')"
          @click="settingsOpen = false"
        >✕</button>
      </div>
      <div class="drawer-body">
        <!-- 首次使用：Key 未配置时给出显式入口提示 -->
        <div
          v-if="!appState.apiKeySource"
          class="mb-4 flex items-start gap-2 rounded border px-3 py-2.5"
          style="border-color: color-mix(in oklab, var(--color-warning) 30%, transparent); background: color-mix(in oklab, var(--color-warning) 8%, transparent)"
        >
          <span class="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full" style="background: var(--color-warning)"></span>
          <p class="text-[11.5px] leading-relaxed text-warning">{{ t('simpleKeyMissing') }}</p>
        </div>
        <ConfigPanel />
      </div>
    </div>
  </div>

  <!-- Voice Picker Modal -->
  <VoicePickerModal />

  <!-- Toast / Confirm -->
  <Toast :visible="toastVisible" :message="toastMessage" :type="toastType" />
  <ConfirmModal />

  <!-- 一次性公告：中国站实名认证提醒（localStorage 记录已读，只弹一次） -->
  <RealNameNoticeModal />
</template>
