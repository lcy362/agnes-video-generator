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
import { stripEmoji } from '@/utils/text'

const { trackEvent } = useGa()

// 图标为 24×24 stroke path（与左侧导航同一套线宽），避免表情符号在不同系统下的观感差异
const taskTypes = [
  { key: 'simple', icon: 'M3 5h13v14H3zM16 10.5 21 8v8l-5-2.5z', label: 'ttSimple' },
  { key: 'creative', icon: 'M3 9h18M3 9l2-4h14l2 4v10H3zM8 5v4M15 5v4', label: 'ttCreative' },
  { key: 'manuscript', icon: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h7', label: 'ttManuscript' },
  { key: 'anchor', icon: 'M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7', label: 'ttAnchor' },
  { key: 'poetry', icon: 'M20 4c-6 .5-11 3.5-13 8.5L4 20l7.5-3c5-2 8-6.5 8.5-13zM8 16l5.5-5.5', label: 'ttPoetry' },
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
    <!-- v6.0 执行模式（创建面板全局，PRD §6.1） -->
    <div class="sec-title">{{ t('execMode') }}</div>
    <div class="mb-6 flex flex-wrap items-center gap-x-4 gap-y-2">
      <div class="seg">
        <button class="seg-item" :class="appState.execMode === 'auto' ? 'is-active' : ''" @click="selectExecMode('auto')">
          {{ stripEmoji(t('execAuto')) }}
        </button>
        <button
          class="seg-item"
          :class="appState.execMode === 'manual' ? 'is-active' : ''"
          :disabled="!manualSupported"
          :title="!manualSupported ? t('manualUnsupported') : ''"
          @click="selectExecMode('manual')"
        >
          {{ stripEmoji(t('execManual')) }}
        </button>
        <!-- v7.6 即梦协作仍在试验阶段：气泡放在按钮外侧，避免选中态（accent 底）
             与气泡的琥珀色撞在一起看不清 -->
        <span class="inline-flex items-center gap-1.5">
          <button
            class="seg-item"
            :class="appState.execMode === 'external' ? 'is-active' : ''"
            :disabled="!manualSupported"
            :title="!manualSupported ? t('manualUnsupported') : ''"
            @click="selectExecMode('external')"
          >
            {{ stripEmoji(t('execMode.external')) }}
          </button>
          <ExperimentalBadge v-if="externalExperimental" />
        </span>
      </div>
      <p class="hint flex-1 basis-64">{{ t('execModeHint') }}</p>
    </div>

    <!-- v7.6 外部素材模式：工具下拉 + 音频来源 + 提示 -->
    <div v-if="appState.execMode === 'external' && manualSupported" class="panel mb-6">
      <div class="panel-body grid gap-5 sm:grid-cols-3">
        <div>
          <label class="label flex items-center gap-1.5">
            {{ t('execMode.provider') }}
            <ExperimentalBadge v-if="externalExperimental" />
          </label>
          <select v-model="appState.providerSelected" class="field">
            <option v-for="p in appState.providers" :key="p.id" :value="p.id">{{ p.icon }} {{ p.name }}</option>
          </select>
        </div>
        <div>
          <span class="label">{{ t('execMode.audio_source') }}</span>
          <div class="flex flex-col gap-1.5">
            <label class="flex items-center gap-2 text-[12.5px] text-ink-2 cursor-pointer">
              <input v-model="appState.externalAudioSource" type="radio" name="ext_audio_source" value="video" class="check" />
              <span>{{ t('execMode.audio_source.video') }}</span>
            </label>
            <label class="flex items-center gap-2 text-[12.5px] text-ink-2 cursor-pointer">
              <input v-model="appState.externalAudioSource" type="radio" name="ext_audio_source" value="project" class="check" />
              <span>{{ t('execMode.audio_source.project') }}</span>
            </label>
          </div>
        </div>
        <div>
          <span class="label">{{ t('execMode.subtitle_source') }}</span>
          <div class="flex flex-col gap-1.5">
            <label class="flex items-center gap-2 text-[12.5px] text-ink-2 cursor-pointer">
              <input v-model="appState.externalSubtitleSource" type="radio" name="ext_subtitle_source" value="narration" class="check" />
              <span>{{ t('execMode.subtitle_source.narration') }}</span>
            </label>
            <label class="flex items-center gap-2 text-[12.5px] text-ink-2 cursor-pointer">
              <input v-model="appState.externalSubtitleSource" type="radio" name="ext_subtitle_source" value="dialogue" class="check" />
              <span>{{ t('execMode.subtitle_source.dialogue') }}</span>
            </label>
          </div>
        </div>
        <p class="hint sm:col-span-3">{{ t('execMode.external_hint') }}</p>
        <!-- 官网新增的即梦说明与常见问题（语言前缀随 UI 语言切换） -->
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] sm:col-span-3">
          <a :href="providerGuideHref" target="_blank" rel="noopener" class="text-accent transition-colors hover:text-ink">{{ t('experimentalGuideLink') }}</a>
          <a :href="providerFaqHref" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('experimentalFaqLink') }}</a>
        </div>
      </div>
    </div>

    <!-- 手动模式：暂停点多选（PRD §6.1） -->
    <div v-if="appState.execMode === 'manual' && manualSupported" class="panel mb-6">
      <div class="panel-body">
        <span class="label">{{ t('pausePoints') }}</span>
        <div class="flex flex-wrap gap-1.5">
          <label
            v-for="p in currentPausePoints"
            :key="p.key"
            class="inline-flex cursor-pointer items-center gap-1.5 rounded border px-2.5 py-1 text-[11.5px] transition-colors"
            :class="appState.pausePoints.includes(p.key)
              ? 'border-accent/40 bg-accent/10 text-accent'
              : 'border-rule bg-paper text-ink-2 hover:border-rule-2'"
          >
            <input
              type="checkbox"
              class="check"
              :checked="appState.pausePoints.includes(p.key)"
              @change="togglePausePoint(p.key)"
            />
            <span>{{ t(p.label) }}</span>
          </label>
        </div>
        <p class="hint mt-2.5">{{ t('pausePointsHint') }}</p>
      </div>
    </div>
    <!-- 不支持的类型提示 -->
    <div v-else-if="appState.execMode === 'manual'" class="mb-6 flex items-start gap-2 text-[11.5px] text-warning">
      <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full" style="background: var(--color-warning)"></span>
      {{ t('manualUnsupported') }}
    </div>

    <!-- 任务类型 -->
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      <button
        v-for="tt in taskTypes"
        :key="tt.key"
        type="button"
        class="type-card"
        :class="appState.currentTaskType === tt.key ? 'is-active' : ''"
        :aria-pressed="appState.currentTaskType === tt.key"
        @click="switchTaskType(tt.key)"
      >
        <svg class="tt-icon h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path :d="tt.icon" />
        </svg>
        <span class="tt-name">{{ t(tt.label) }}</span>
      </button>
    </div>

    <!-- 官网引导 -->
    <div class="mt-5 mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
      <span class="mono text-[10px] uppercase tracking-[0.14em]">Tips</span>
      <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="transition-colors hover:text-accent">{{ stripEmoji(t('formTipTips')) }}</a>
      <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="transition-colors hover:text-accent">{{ stripEmoji(t('formTipModels')) }}</a>
    </div>

    <!-- 6 种任务表单 -->
    <SimpleForm v-if="appState.currentTaskType === 'simple'" />
    <CreativeForm v-else-if="appState.currentTaskType === 'creative'" />
    <ManuscriptForm v-else-if="appState.currentTaskType === 'manuscript'" />
    <AnchorForm v-else-if="appState.currentTaskType === 'anchor'" />
    <PoetryForm v-else-if="appState.currentTaskType === 'poetry'" />
  </div>
</template>
