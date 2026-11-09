<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { t } from '@/i18n'
import { appState, rememberTaskType } from '@/store'
import { useGa } from '@/composables/useGa'
import * as api from '@/api'
import SimpleForm from './forms/SimpleForm.vue'
import CreativeForm from './forms/CreativeForm.vue'
import ManuscriptForm from './forms/ManuscriptForm.vue'
import AnchorForm from './forms/AnchorForm.vue'
import PoetryForm from './forms/PoetryForm.vue'
import ExperimentalBadge from './shared/ExperimentalBadge.vue'
import { JIMENG_FAQ_PATH, JIMENG_GUIDE_PATH, siteUrl } from '@/utils/siteLinks'

const { trackEvent } = useGa()

const taskTypes = [
  { key: 'simple', icon: '🎬🖼️', label: 'ttSimple' },
  { key: 'creative', icon: '🎥', label: 'ttCreative' },
  { key: 'manuscript', icon: '📝', label: 'ttManuscript' },
  { key: 'anchor', icon: '🎙️', label: 'ttAnchor' },
  { key: 'poetry', icon: '📜', label: 'ttPoetry' },
]

// v6.0/6.1 手动模式：暂停点选项（按任务类型）
// creative 细粒度（每个有产物的环节独立，v6.1）；其余粗粒度（PRD §4.3 顺序）
const pausePointOptions: Record<string, { key: string; label: string }[]> = {
  creative: [
    { key: 'image_analysis', label: 'cpImageAnalysis' },
    { key: 'story', label: 'cpStory' },
    { key: 'script', label: 'cpScript' },
    { key: 'character_ref', label: 'cpCharacterRef' },
    { key: 'end_frame_prompts', label: 'cpEndFramePrompts' },
    { key: 'end_frame_gen', label: 'cpEndFrameGen' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
  manuscript: [
    { key: 'scenes', label: 'cpScenes' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
  poetry: [
    { key: 'scenes', label: 'cpScenes' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
  anchor: [
    { key: 'scenes', label: 'cpScenes' },
    { key: 'references', label: 'cpReferences' },
    { key: 'videos', label: 'cpVideos' },
    { key: 'audio', label: 'cpAudio' },
    { key: 'subtitle', label: 'cpSubtitle' },
    { key: 'final', label: 'cpFinal' },
  ],
}

// 手动模式支持的任务类型（simple/simple_image 不支持暂停，PRD §4.3）
const manualSupported = computed(() => !['simple', 'image'].includes(appState.currentTaskType))

// 当前任务类型可选的暂停点
const currentPausePoints = computed(() => pausePointOptions[appState.currentTaskType] || [])

// 默认暂停点（PRD §4.8 预填，用户可增删）
const defaultPausePoints: Record<string, string[]> = {
  creative: ['story', 'script', 'character_ref', 'videos', 'subtitle'],
  manuscript: ['scenes', 'videos', 'subtitle'],
  poetry: ['scenes', 'videos', 'subtitle'],
  anchor: ['scenes', 'videos'],
}

// v7.6 外部素材模式：各类型默认暂停点（后端亦有默认，前端预填保持一致）
const externalDefaultPausePoints: Record<string, string[]> = {
  creative: ['scenes', 'references', 'videos', 'subtitle'],
  manuscript: ['scenes', 'videos', 'subtitle'],
  poetry: ['scenes', 'videos', 'subtitle'],
  anchor: ['scenes', 'videos'],
}

// v7.6 外部素材模式：拉取外部工具注册表（GET /api/providers），默认选中第一项
onMounted(async () => {
  try {
    const d = await api.getProviders()
    if (d?.ok && Array.isArray(d.providers)) {
      appState.providers = d.providers
      if (!appState.providerSelected && d.providers.length) appState.providerSelected = d.providers[0].id
    }
  } catch {
    /* 拉取失败：保持为空，用户仍可提交（后端默认回退 jimeng） */
  }
})

// v7.6 即梦协作处于试验阶段：气泡与官网说明链接按所选工具的注册表元数据渲染
// （注册表拉取失败时按默认工具即梦处理——后端同样回退 jimeng）
const selectedProvider = computed<any>(() =>
  appState.providers.find((p: any) => p.id === appState.providerSelected) || null,
)
const externalExperimental = computed(() => (selectedProvider.value ? !!selectedProvider.value.experimental : true))
const providerGuideHref = computed(() => siteUrl(selectedProvider.value?.guide_path || JIMENG_GUIDE_PATH))
const providerFaqHref = computed(() => siteUrl(selectedProvider.value?.faq_path || JIMENG_FAQ_PATH))

function switchTaskType(type: string) {
  trackEvent('ui_action', { action: 'switch_task_type', type })
  appState.currentTaskType = type
  // v8.0：记住上次选择（下次打开直接回到该类型）
  rememberTaskType(type)
  // 切换任务类型时按 PRD §4.8 预填默认暂停点
  appState.pausePoints = [...(defaultPausePoints[type] || [])]
}

function togglePausePoint(key: string) {
  const i = appState.pausePoints.indexOf(key)
  if (i >= 0) appState.pausePoints.splice(i, 1)
  else appState.pausePoints.push(key)
}

function selectExecMode(mode: 'auto' | 'manual' | 'external') {
  if (mode !== 'auto' && !manualSupported.value) return
  appState.execMode = mode
  if (mode === 'manual' && appState.pausePoints.length === 0) {
    appState.pausePoints = [...(defaultPausePoints[appState.currentTaskType] || [])]
  }
  if (mode === 'external') {
    if (!appState.providerSelected && appState.providers.length) appState.providerSelected = appState.providers[0].id
    appState.pausePoints = [...(externalDefaultPausePoints[appState.currentTaskType] || [])]
  }
}
</script>

<template>
  <div>
    <!-- v6.0 执行模式条（创建面板全局，PRD §6.1） -->
    <div class="glass-card rounded-2xl p-4 mb-4">
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2">
        <span class="text-sm font-medium text-accent">{{ t('execMode') }}</span>
        <div class="flex gap-2">
          <button
            class="px-4 py-2 rounded-lg text-sm font-medium transition border"
            :class="appState.execMode === 'auto' ? 'bg-accent text-accent-ink border-accent' : 'bg-paper-2/50 border-rule text-ink-2 hover:border-accent/40'"
            @click="selectExecMode('auto')"
          >
            {{ t('execAuto') }}
          </button>
          <button
            class="px-4 py-2 rounded-lg text-sm font-medium transition border"
            :class="appState.execMode === 'manual' ? 'bg-accent text-accent-ink border-accent' : 'bg-paper-2/50 border-rule text-ink-2 hover:border-accent/40'"
            :disabled="!manualSupported"
            :title="!manualSupported ? t('manualUnsupported') : ''"
            @click="selectExecMode('manual')"
          >
            {{ t('execManual') }}
          </button>
          <!-- v7.6 即梦协作仍在试验阶段：气泡放在按钮外侧，避免选中态（accent 底）
               与气泡的琥珀色撞在一起看不清 -->
          <span class="inline-flex items-center gap-1.5">
            <button
              class="px-4 py-2 rounded-lg text-sm font-medium transition border"
              :class="appState.execMode === 'external' ? 'bg-accent text-accent-ink border-accent' : 'bg-paper-2/50 border-rule text-ink-2 hover:border-accent/40'"
              :disabled="!manualSupported"
              :title="!manualSupported ? t('manualUnsupported') : ''"
              @click="selectExecMode('external')"
            >
              {{ t('execMode.external') }}
            </button>
            <ExperimentalBadge v-if="externalExperimental" />
          </span>
        </div>
        <span class="text-xs text-muted">{{ t('execModeHint') }}</span>
      </div>

      <!-- v7.6 外部素材模式：工具下拉 + 音频来源 + 提示 -->
      <div v-if="appState.execMode === 'external' && manualSupported" class="mt-3 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <label class="flex items-center gap-1.5 text-xs text-muted mb-1">
            {{ t('execMode.provider') }}
            <ExperimentalBadge v-if="externalExperimental" />
          </label>
          <select v-model="appState.providerSelected" class="glass-input rounded-lg px-3 py-2 text-sm text-ink min-w-48">
            <option v-for="p in appState.providers" :key="p.id" :value="p.id">{{ p.icon }} {{ p.name }}</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-muted mb-1">{{ t('execMode.audio_source') }}</label>
          <div class="flex flex-col gap-1.5">
            <label class="flex items-center gap-2 text-sm text-ink-2 cursor-pointer">
              <input v-model="appState.externalAudioSource" type="radio" name="ext_audio_source" value="video" class="text-accent" />
              <span>{{ t('execMode.audio_source.video') }}</span>
            </label>
            <label class="flex items-center gap-2 text-sm text-ink-2 cursor-pointer">
              <input v-model="appState.externalAudioSource" type="radio" name="ext_audio_source" value="project" class="text-accent" />
              <span>{{ t('execMode.audio_source.project') }}</span>
            </label>
          </div>
        </div>
        <div>
          <label class="block text-xs text-muted mb-1">{{ t('execMode.subtitle_source') }}</label>
          <div class="flex flex-col gap-1.5">
            <label class="flex items-center gap-2 text-sm text-ink-2 cursor-pointer">
              <input v-model="appState.externalSubtitleSource" type="radio" name="ext_subtitle_source" value="narration" class="text-accent" />
              <span>{{ t('execMode.subtitle_source.narration') }}</span>
            </label>
            <label class="flex items-center gap-2 text-sm text-ink-2 cursor-pointer">
              <input v-model="appState.externalSubtitleSource" type="radio" name="ext_subtitle_source" value="dialogue" class="text-accent" />
              <span>{{ t('execMode.subtitle_source.dialogue') }}</span>
            </label>
          </div>
        </div>
        <p class="text-xs text-muted max-w-2xl basis-full">{{ t('execMode.external_hint') }}</p>
        <!-- 官网新增的即梦说明与常见问题（语言前缀随 UI 语言切换） -->
        <div class="basis-full flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <a :href="providerGuideHref" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">📖 {{ t('experimentalGuideLink') }}</a>
          <span class="text-ink/10 select-none">·</span>
          <a :href="providerFaqHref" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">❓ {{ t('experimentalFaqLink') }}</a>
        </div>
      </div>

      <!-- 手动模式：暂停点多选（PRD §6.1） -->
      <div v-if="appState.execMode === 'manual' && manualSupported" class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span class="text-xs text-muted">{{ t('pausePoints') }}:</span>
        <label v-for="p in currentPausePoints" :key="p.key" class="flex items-center gap-1.5 text-sm text-ink-2 cursor-pointer">
          <input type="checkbox" class="rounded bg-paper-2 border-rule" :checked="appState.pausePoints.includes(p.key)" @change="togglePausePoint(p.key)" />
          <span>{{ t(p.label) }}</span>
        </label>
        <span class="text-xs text-muted">{{ t('pausePointsHint') }}</span>
      </div>
      <!-- 不支持的类型提示 -->
      <div v-else-if="appState.execMode === 'manual'" class="mt-3 text-xs text-amber-400">
        {{ t('manualUnsupported') }}
      </div>
    </div>

    <!-- Task Type Tabs -->
    <div class="flex gap-2 mb-4">
      <button
        v-for="tt in taskTypes"
        :key="tt.key"
        class="ttype-btn flex-1 px-4 py-3 rounded-xl text-sm font-medium transition text-center"
        :class="appState.currentTaskType === tt.key ? 'tab-active' : 'tab-inactive'"
        @click="switchTaskType(tt.key)"
      >
        <span class="text-lg">{{ tt.icon }}</span><br /><span>{{ t(tt.label) }}</span>
      </button>
    </div>

    <!-- 官网引导 -->
    <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mb-4 text-xs text-muted">
      <span class="text-muted">💡</span>
      <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="hover:text-accent transition-colors">🎯 {{ t('formTipTips') }}</a>
      <span class="text-ink/10 select-none">·</span>
      <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="hover:text-accent transition-colors">🧠 {{ t('formTipModels') }}</a>
    </div>

    <!-- 6 种任务表单 -->
    <SimpleForm v-if="appState.currentTaskType === 'simple'" />
    <CreativeForm v-else-if="appState.currentTaskType === 'creative'" />
    <ManuscriptForm v-else-if="appState.currentTaskType === 'manuscript'" />
    <AnchorForm v-else-if="appState.currentTaskType === 'anchor'" />
    <PoetryForm v-else-if="appState.currentTaskType === 'poetry'" />
  </div>
</template>
