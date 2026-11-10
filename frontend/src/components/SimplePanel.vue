<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { t, currentLang } from '@/i18n'
import { appState } from '@/store'
import * as api from '@/api'
import { useVoice } from '@/composables/useVoice'
import { useToast } from '@/composables/useToast'

const { voiceSelections, voiceIndex, voiceName, voiceDescription, openVoicePicker, initVoiceSelector } = useVoice()
const { showToast } = useToast()

const emit = defineEmits<{ (e: 'go-list'): void }>()

// 简易模式使用独立的音色选择 key（与 c/m/a/p 互不干扰）
const VOICE_KEY = 's'

// ── 状态 ──
const idea = ref('')
const sceneCount = ref(3)
const previewData = ref<any>(null)
const previewLoading = ref(false)
const generating = ref(false)
const audioEnabled = ref(true)
const subtitleEnabled = ref(true)
const resolution = ref('768x1152')

const resolutions = [
  { value: '768x1152', label: 'resPortrait' },
  { value: '1280x720', label: 'resLandscape' },
  { value: '1024x1024', label: 'resSquare' },
]

// preview-script 白名单仅 ar/en，默认按 UI 语言降级；实际配音语言由所选音色驱动
const contentLang = computed(() => (currentLang.value === 'ar' ? 'ar' : 'en'))

const currentVoiceId = computed(() => voiceSelections[VOICE_KEY] || 'zh-CN-XiaoxiaoNeural')

onMounted(async () => {
  if (!voiceSelections[VOICE_KEY]) voiceSelections[VOICE_KEY] = 'zh-CN-XiaoxiaoNeural'
  // 音色目录未加载时补齐（App 已初始化时跳过）
  if (!appState.voiceCatalog) {
    await initVoiceSelector()
  }
})

async function generatePreview() {
  if (!idea.value.trim()) {
    showToast(t('enterIdea'), 3500)
    return
  }
  previewLoading.value = true
  try {
    const d = await api.creativePreview(idea.value.trim(), contentLang.value, sceneCount.value)
    if (d.ok === false) throw new Error(d.detail || t('failCreate'))
    previewData.value = d
  } catch (e: any) {
    showToast(e?.message || t('failCreate'), 4500)
  } finally {
    previewLoading.value = false
  }
}

function pickVoice() {
  openVoicePicker(VOICE_KEY)
}

async function generate() {
  if (!idea.value.trim()) {
    showToast(t('enterIdea'), 3500)
    return
  }
  generating.value = true
  try {
    const fd = new FormData()
    fd.append('idea', idea.value.trim())
    fd.append('scene_count', String(sceneCount.value))
    fd.append('scene_durations_json', JSON.stringify(Array(sceneCount.value).fill(5)))
    fd.append('audio_enabled', String(audioEnabled.value))
    fd.append('audio_voice', currentVoiceId.value)
    // audio_lang 用页面语言：创意旁白由 LLM 按页面语言生成，音色兼容性按此校验
    fd.append('audio_lang', currentLang.value)
    fd.append('subtitle_enabled', String(subtitleEnabled.value))
    const [w, h] = resolution.value.split('x').map(Number)
    fd.append('video_width', String(w))
    fd.append('video_height', String(h))
    fd.append('execution_mode', 'auto')

    const d = await api.submitCreative(fd)
    if (!d.ok) throw new Error(d.detail || t('failCreate'))
    showToast(t('simpleGenerated'), 5000, 'success')
    emit('go-list')
  } catch (e: any) {
    showToast(t('failCreate') + ': ' + (e?.message || ''), 4500)
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <div>
    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('simpleTitle') }}</h2>
        <span class="chip">01</span>
      </header>

      <div class="panel-body space-y-4">
        <!-- 步骤 1：主题输入 -->
        <div>
          <label class="label">{{ t('simpleIdea') }} <span class="text-danger">*</span></label>
          <textarea
            v-model="idea"
            rows="3"
            :placeholder="t('simpleIdeaPlaceholder')"
            class="field"
          ></textarea>
        </div>
        <div class="max-w-40">
          <label class="label">{{ t('sceneCount') }}</label>
          <input
            v-model.number="sceneCount"
            type="number"
            min="1"
            max="30"
            class="field"
          />
        </div>
      </div>
    </section>

    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('simpleSetting') }}</h2>
        <span class="chip">02</span>
      </header>

      <div class="panel-body">
        <!-- 步骤 2：生成预览 & 设置 -->
        <button
          class="btn btn-secondary btn-block mb-5"
          :disabled="previewLoading"
          @click="generatePreview"
        >
          {{ previewLoading ? t('simplePreviewing') : t('simplePreview') }}
        </button>

        <template v-if="previewData && previewData.scenes">
          <p class="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{{ t('simpleScenes') }}</p>
          <div class="mb-5 space-y-2">
            <div v-for="(s, i) in previewData.scenes" :key="i" class="rounded border border-rule bg-paper px-3 py-2.5">
              <div class="mb-1 flex items-baseline gap-2">
                <span class="mono text-[10px] text-accent">{{ String(i + 1).padStart(2, '0') }}</span>
                <span class="text-[12.5px] font-medium text-ink">{{ s.title }}</span>
              </div>
              <div class="text-[11.5px] leading-relaxed text-muted"><span class="text-ink-2">{{ t('simpleScenePrompt') }}:</span> {{ s.prompt }}</div>
              <div class="mt-1 text-[11.5px] leading-relaxed text-muted"><span class="text-ink-2">{{ t('simpleSceneVoiceover') }}:</span> {{ s.voiceover }}</div>
            </div>
          </div>
        </template>

        <!-- 设置面板 -->
        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label class="label">{{ t('voiceRole') }}</label>
            <button
              class="field flex items-center justify-between gap-2 text-start"
              @click="pickVoice"
            >
              <span class="truncate">{{ voiceName(VOICE_KEY) || voiceDescription(VOICE_KEY) || currentVoiceId }}</span>
              <span class="shrink-0 text-[10px] text-muted">▾</span>
            </button>
          </div>
          <div>
            <label class="label">{{ t('resolution') }}</label>
            <select v-model="resolution" class="field">
              <option v-for="r in resolutions" :key="r.value" :value="r.value">{{ t(r.label) }}</option>
            </select>
          </div>
        </div>
        <div class="mt-4 flex flex-wrap gap-6">
          <label class="flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-2">
            <input v-model="audioEnabled" type="checkbox" class="check" />
            <span>{{ t('enableNarration') }}</span>
          </label>
          <label class="flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-2">
            <input v-model="subtitleEnabled" type="checkbox" class="check" />
            <span>{{ t('enableSubtitle') }}</span>
          </label>
        </div>
      </div>
    </section>

    <!-- 步骤 3：一键生成 -->
    <button
      class="btn btn-primary btn-block"
      :disabled="generating"
      @click="generate"
    >
      {{ generating ? t('simpleGenerating') : t('simpleGenerate') }}
    </button>
  </div>
</template>