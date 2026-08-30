<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t, currentLang } from '@/i18n'
import { appState } from '@/store'
import { useVoice } from '@/composables/useVoice'
import { useTaskSubmit } from '@/composables/useTaskSubmit'
import { copyText } from '@/utils/clipboard'
import * as api from '@/api'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'

const { voiceSelections } = useVoice()
const { submitting, runSubmit } = useTaskSubmit()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  name: '',
  poem: '',
  sceneCount: 3,
  uniform: true,
  uniformDuration: 5,
  independentDurations: [] as number[],
  scenePrompts: '',
  style: '电影质感写实风格',
  resolution: '768x1152',
})

const promptPanelVisible = ref(false)
const promptSystem = ref('')
const promptUser = ref('')
const copyBtnText = ref('')

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

function collectPoetrySceneArgs() {
  const poem = form.poem.trim()
  const count = form.sceneCount || 3
  let durations: number[] = []
  if (form.uniform) {
    durations = Array(count).fill(form.uniformDuration || 5)
  } else {
    durations = form.independentDurations.slice(0, count)
    while (durations.length < count) durations.push(5)
  }
  const total = durations.reduce((a, b) => a + b, 0) || 30
  return { poem, scene_count: count, scene_durations: durations, total_duration: total, style: form.style.trim() }
}

async function loadPoetryPrompt() {
  try {
    const a = collectPoetrySceneArgs()
    const resp = await api.getPoetryScenePrompt({
      poem: a.poem,
      scene_count: String(a.scene_count),
      scene_durations: JSON.stringify(a.scene_durations),
      total_duration: String(a.total_duration),
      style: a.style,
    })
    promptSystem.value = resp.system_prompt || ''
    promptUser.value = resp.user_prompt || ''
  } catch (e) {
    console.error('loadPoetryPrompt error:', e)
  }
}

async function togglePoetryPrompt() {
  promptPanelVisible.value = !promptPanelVisible.value
  if (promptPanelVisible.value) {
    await loadPoetryPrompt()
  }
}

async function copyPoetryPromptWithPoem() {
  await loadPoetryPrompt()
  const full = promptSystem.value + '\n\n' + promptUser.value
  await copyText(full)
  const old = copyBtnText.value
  copyBtnText.value = t('copied')
  setTimeout(() => (copyBtnText.value = old), 1500)
}

async function submitPoetry() {
  let ev: Record<string, any> = {}
  await runSubmit({
    taskType: 'poetry',
    buildForm: () => {
      const poem = form.poem.trim()
      if (!poem) throw new Error(t('enterPoem'))
      const sceneLines = form.scenePrompts.split('\n').map((s) => s.trim()).filter(Boolean)

      const fd = new FormData()
      fd.append('poem_text', poem)
      fd.append('creative_name', form.name.trim())
      fd.append('user_scene_prompts_json', JSON.stringify(sceneLines))
      fd.append('style', form.style)
      const res = parseResolution(form.resolution)
      fd.append('video_width', String(res.width))
      fd.append('video_height', String(res.height))
      fd.append('video_duration', '30')

      fd.append('duration_source', 'manual')
      fd.append('scene_count', String(form.sceneCount))
      fd.append('uniform_duration', String(form.uniform))
      if (form.uniform) {
        fd.append('scene_durations_json', JSON.stringify(Array(form.sceneCount).fill(form.uniformDuration)))
      } else {
        fd.append('scene_durations_json', JSON.stringify(form.independentDurations.slice(0, form.sceneCount)))
      }

      const sc = subtitleRef.value
      if (sc) {
        fd.append('audio_enabled', String(sc.audioEnabled))
        fd.append('audio_voice', voiceSelections.p)
        fd.append('audio_lang', currentLang.value)
        fd.append('audio_rate', sc.rate)
        fd.append('subtitle_enabled', String(sc.subtitleEnabled))
      }

      // v6.0 手动模式：执行模式 + 暂停点
      fd.append('execution_mode', appState.execMode)
      fd.append('pause_points', JSON.stringify(appState.execMode === 'manual' ? appState.pausePoints : []))

      ev = {
        style: form.style,
        scene_count: form.sceneCount,
        resolution: form.resolution,
        audio: sc?.audioEnabled ? 'on' : 'off',
        subtitle: sc?.subtitleEnabled ? 'on' : 'off',
      }
      return fd
    },
    extraEvent: ev,
  })
}
</script>

<template>
  <div>
    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('poetrySettings') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('taskName') }}</label>
        <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('poemLabel') }} <span class="text-red-400">*</span></label>
        <textarea v-model="form.poem" rows="5" :placeholder="t('poemPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
        <p class="text-xs text-muted mt-1.5">{{ t('poemHint') }}</p>
      </div>

      <!-- Scene config -->
      <div class="mb-4 p-4 rounded-xl bg-paper-2/30 border border-rule/50">
        <h3 class="text-sm font-medium text-accent mb-3">{{ t('sceneConfig') }}</h3>
        <p class="text-xs text-muted mb-3">{{ t('sourceManualHint') }}</p>
        <div class="mb-3">
          <label class="block text-xs text-muted mb-1">{{ t('sceneCount') }}</label>
          <input v-model.number="form.sceneCount" type="number" min="1" max="30" class="w-24 glass-input rounded-lg px-3 py-2 text-sm text-ink" />
        </div>
        <div class="mb-3">
          <label class="block text-xs text-muted mb-1.5">{{ t('durationMode') }}</label>
          <div class="flex gap-2 mb-2">
            <label class="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input v-model="form.uniform" type="radio" :value="true" class="text-accent" />
              <span>{{ t('uniformDuration') }}</span>
            </label>
            <label class="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input v-model="form.uniform" type="radio" :value="false" class="text-accent" />
              <span>{{ t('independentDuration') }}</span>
            </label>
          </div>
          <div v-if="form.uniform">
            <input v-model.number="form.uniformDuration" type="number" min="2" max="30" class="w-24 glass-input rounded-lg px-3 py-2 text-sm text-ink" />
            <span class="text-xs text-muted ml-1">{{ t('seconds') }}</span>
          </div>
          <div v-else class="space-y-2">
            <div v-for="i in form.sceneCount" :key="i" class="flex items-center gap-2 mb-1.5">
              <span class="text-xs text-muted w-12">{{ t('scene_') }}{{ i }}</span>
              <input v-model.number="form.independentDurations[i - 1]" type="number" min="2" max="30" class="w-20 glass-input rounded-lg px-3 py-1.5 text-sm text-ink" />
              <span class="text-xs text-muted">{{ t('seconds') }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('scenePromptsOptional') }}</label>
        <textarea v-model="form.scenePrompts" rows="3" :placeholder="t('scenePromptsPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
        <p class="text-xs text-muted mt-1.5">{{ t('scenePromptsHint') }}</p>
        <p class="text-xs text-muted mt-1.5 font-mono bg-paper-2/40 rounded px-2 py-1">{{ t('scenePromptsExample') }}</p>
        <div class="mt-3 p-3 rounded-lg bg-paper-2/40 border border-rule/50">
          <div class="flex items-center justify-between">
            <span class="text-xs text-ink-2 font-medium">{{ t('scenePromptTool') }}</span>
            <button type="button" class="text-xs text-accent hover:text-accent" @click="togglePoetryPrompt">{{ t('showPrompt') }}</button>
          </div>
          <div v-if="promptPanelVisible" class="mt-2">
            <p class="text-xs text-muted mb-1.5">{{ t('scenePromptToolHint') }}</p>
            <pre class="text-[11px] text-ink-2 whitespace-pre-wrap bg-paper/60 rounded p-2 max-h-40 overflow-auto">{{ promptSystem }}</pre>
            <pre class="text-[11px] text-muted whitespace-pre-wrap bg-paper/60 rounded p-2 mt-1 max-h-40 overflow-auto">{{ promptUser }}</pre>
            <button type="button" class="mt-2 w-full text-xs text-accent bg-accent/15 hover:bg-accent/25 rounded px-3 py-1.5 transition" @click="copyPoetryPromptWithPoem">
              {{ copyBtnText || t('copyPromptWithPoem') }}
            </button>
          </div>
        </div>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('visualStyle') }}</label>
        <input v-model="form.style" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
      </div>
    </div>

    <!-- Advanced Config -->
    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('advancedSettings') }}</h2>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
          <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option value="768x1152">{{ t('resPortrait') }}</option>
            <option value="1152x768">{{ t('resLandscape') }}</option>
            <option value="1024x1024">{{ t('resSquare') }}</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Audio & Subtitle（诗词仅开关） -->
    <SubtitleConfig ref="subtitleRef" task="p" :with-style="false" />

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitPoetry"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
