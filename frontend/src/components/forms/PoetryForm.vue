<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { t, tf, currentLang } from '@/i18n'
import { appState } from '@/store'
import { useVoice } from '@/composables/useVoice'
import { useTaskSubmit } from '@/composables/useTaskSubmit'
import { usePresets } from '@/composables/usePresets'
import { copyText } from '@/utils/clipboard'
import * as api from '@/api'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'
import PresetPicker from '@/components/presets/PresetPicker.vue'
import RefImagesInput from '@/components/shared/RefImagesInput.vue'

const { voiceSelections } = useVoice()
const { submitting, runSubmit } = useTaskSubmit()
const { defaultStylePrompt, loadPresets } = usePresets()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  name: '',
  poem: '',
  sceneCount: 3,
  uniform: true,
  uniformDuration: 5,
  independentDurations: [] as number[],
  scenePrompts: '',
  style: '',
  resolution: '768x1152',
  // v8.1：人物板 / 风格板（各 ≤2）+ 逐句内容图 + 句间衔接
  characterImages: [] as File[],
  styleImages: [] as File[],
  sceneRefs: [] as File[][],
  linkShots: false,
})

// v8.1：本句内容图剩余额度 = 模型上限 − 人物板 − 风格板 −（衔接 1 张）
const sceneRefMax = computed(() => {
  const limit = Number(appState.videoCapabilities?.[appState.models.video]?.max_ref_images ?? 5)
  const system = form.characterImages.length + form.styleImages.length + (form.linkShots ? 1 : 0)
  return Math.max(1, limit - system)
})

const promptPanelVisible = ref(false)
const promptSystem = ref('')
const promptUser = ref('')
const copyBtnText = ref('')

// 打开表单时用默认预设预填风格框（语言中性，取代旧的硬编码中文默认值），后台加载预设列表用于高亮当前项。
onMounted(async () => {
  if (form.style.trim()) return
  const prefill = defaultStylePrompt.value
  form.style = prefill
  await loadPresets()
  if (form.style === prefill) form.style = defaultStylePrompt.value
})

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
      // v8.1：人物板 / 风格板 + 逐句内容图（映射到句 index）
      form.characterImages.forEach((f) => fd.append('character_images', f))
      form.styleImages.forEach((f) => fd.append('style_images', f))
      const sceneFiles: File[] = []
      const sceneMap: number[][] = []
      form.sceneRefs.forEach((files, idx) => {
        ;(files || []).forEach((f) => {
          if (f && f.size > 0) {
            sceneFiles.push(f)
            sceneMap.push([idx])
          }
        })
      })
      sceneFiles.forEach((f) => fd.append('scene_reference_images', f))
      fd.append('scene_reference_images_map', JSON.stringify(sceneMap))
      fd.append('link_shots', String(form.linkShots))

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

      // v6.0 手动模式 / v7.6 外部素材模式：执行模式 + 暂停点 + 工具与音频来源
      fd.append('execution_mode', appState.execMode)
      fd.append('pause_points', JSON.stringify(appState.execMode !== 'auto' ? appState.pausePoints : []))
      if (appState.execMode === 'external') {
        fd.append('provider', appState.providerSelected || 'jimeng')
        fd.append('audio_source', appState.externalAudioSource)
        fd.append('subtitle_source', appState.externalSubtitleSource)
      }

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
    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('poetrySettings') }}</h2>
      </header>

      <div class="panel-body space-y-4">
        <div>
          <label class="label">{{ t('taskName') }}</label>
          <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="field" />
        </div>

        <div>
          <label class="label">{{ t('poemLabel') }} <span class="text-danger">*</span></label>
          <textarea v-model="form.poem" rows="5" :placeholder="t('poemPlaceholder')" class="field"></textarea>
          <p class="hint mt-1.5">{{ t('poemHint') }}</p>
        </div>

        <!-- Scene config -->
        <div class="subpanel">
          <h3 class="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{{ t('sceneConfig') }}</h3>
          <p class="hint mb-3">{{ t('sourceManualHint') }}</p>
          <div class="grid gap-4 sm:grid-cols-2">
            <div>
              <label class="label">{{ t('sceneCount') }}</label>
              <input v-model.number="form.sceneCount" type="number" min="1" max="30" class="field" />
            </div>
            <div>
              <span class="label">{{ t('durationMode') }}</span>
              <div class="mb-2 flex gap-4">
                <label class="flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-2">
                  <input v-model="form.uniform" type="radio" :value="true" class="check" />
                  <span>{{ t('uniformDuration') }}</span>
                </label>
                <label class="flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-2">
                  <input v-model="form.uniform" type="radio" :value="false" class="check" />
                  <span>{{ t('independentDuration') }}</span>
                </label>
              </div>
              <div v-if="form.uniform" class="flex items-center gap-2">
                <input v-model.number="form.uniformDuration" type="number" min="2" max="30" class="field w-24" />
                <span class="hint">{{ t('seconds') }}</span>
              </div>
              <div v-else class="max-h-56 space-y-1.5 overflow-y-auto pe-1">
                <div v-for="i in form.sceneCount" :key="i" class="flex items-center gap-2">
                  <span class="mono w-8 text-[11px] text-muted">{{ i }}</span>
                  <input v-model.number="form.independentDurations[i - 1]" type="number" min="2" max="30" class="field w-20" />
                  <span class="hint">{{ t('seconds') }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div>
          <label class="label">{{ t('scenePromptsOptional') }}</label>
          <textarea v-model="form.scenePrompts" rows="3" :placeholder="t('scenePromptsPlaceholder')" class="field"></textarea>
          <p class="hint mt-1.5">{{ t('scenePromptsHint') }}</p>
          <p class="mono mt-2 rounded border border-rule bg-paper px-2.5 py-1.5 text-[11px] leading-relaxed text-muted">{{ t('scenePromptsExample') }}</p>

          <div class="mt-3 rounded border border-rule bg-paper px-3 py-2">
            <div class="flex items-center justify-between gap-3">
              <span class="text-[11.5px] font-medium text-ink-2">{{ t('scenePromptTool') }}</span>
              <button type="button" class="btn btn-quiet btn-xs text-accent" @click="togglePoetryPrompt">{{ t('showPrompt') }}</button>
            </div>
            <div v-if="promptPanelVisible" class="mt-2 space-y-1.5">
              <p class="hint">{{ t('scenePromptToolHint') }}</p>
              <pre class="max-h-40 overflow-auto rounded border border-rule bg-paper-2 p-2 text-[11px] text-ink-2">{{ promptSystem }}</pre>
              <pre class="max-h-40 overflow-auto rounded border border-rule bg-paper-2 p-2 text-[11px] text-muted">{{ promptUser }}</pre>
              <button type="button" class="btn btn-secondary btn-sm w-full" @click="copyPoetryPromptWithPoem">
                {{ copyBtnText || t('copyPromptWithPoem') }}
              </button>
            </div>
          </div>
        </div>

        <div>
          <label class="label">{{ t('visualStyle') }}</label>
          <div class="flex items-center gap-2">
            <input v-model="form.style" class="field flex-1" />
            <PresetPicker v-model="form.style" />
          </div>
          <p class="hint mt-1.5 flex items-center gap-1.5">
            <span class="inline-block h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden="true"></span>
            {{ t('stylePresetHint') }}
          </p>
        </div>
      </div>
    </section>

    <!-- Advanced Config -->
    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('advancedSettings') }}</h2>
      </header>
      <div class="panel-body space-y-5">
        <div class="max-w-64">
          <label class="label">{{ t('resolution') }}</label>
          <select v-model="form.resolution" class="field">
            <option value="768x1152">{{ t('resPortrait') }}</option>
            <option value="1280x720">{{ t('resLandscape') }}</option>
            <option value="1024x1024">{{ t('resSquare') }}</option>
          </select>
        </div>

        <!-- v8.1：人物板 / 风格板（空则按诗句生成风格板；无人入画不生成人物板） -->
        <RefImagesInput
          v-model="form.characterImages"
          :max="2"
          :label="t('plateCharacter')"
          :hint="t('plateHint')"
        />
        <RefImagesInput
          v-model="form.styleImages"
          :max="2"
          :label="t('plateStyle')"
          :hint="t('plateHint')"
        />

        <!-- v8.1：逐句内容图（序号 = 句 index） -->
        <div class="border-t border-rule/60 pt-4">
          <label class="label">{{ t('sceneReferenceImages') }}</label>
          <p class="hint mb-2">{{ t('sceneRefDesc') }}</p>
          <div class="space-y-3">
            <div v-for="i in form.sceneCount" :key="i">
              <div class="mb-1 flex items-center gap-2">
                <span class="mono w-8 shrink-0 text-[11px] text-muted">{{ i }}</span>
                <span class="hint">{{ tf('sceneRefQuota', { n: sceneRefMax }) }}</span>
              </div>
              <RefImagesInput
                :model-value="form.sceneRefs[i - 1] || []"
                :max="sceneRefMax"
                input-class="scene-ref-file"
                @update:model-value="(v: File[]) => (form.sceneRefs[i - 1] = v)"
              />
            </div>
          </div>
        </div>

        <label class="flex cursor-pointer items-start gap-2 border-t border-rule/60 pt-4 text-[12px] text-ink-2">
          <input v-model="form.linkShots" type="checkbox" class="check mt-0.5" />
          <span class="min-w-0">
            <span class="block">{{ t('linkShots') }}</span>
            <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('linkShotsHint') }}</span>
          </span>
        </label>
      </div>
    </section>

    <!-- Audio & Subtitle（诗词仅开关） -->
    <SubtitleConfig ref="subtitleRef" task="p" :with-style="false" :external="appState.execMode === 'external'" />

    <WatermarkToggle />

    <button
      class="btn btn-primary btn-block"
      :disabled="submitting"
      @click="submitPoetry"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
