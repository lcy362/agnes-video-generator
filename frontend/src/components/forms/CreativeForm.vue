<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { t, tf, currentLang } from '@/i18n'
import { stripEmoji } from '@/utils/text'
import { siteUrl } from '@/utils/siteLinks'
import { appState } from '@/store'
import { useVoice } from '@/composables/useVoice'
import { useTaskSubmit, collectAudioSubtitleFields } from '@/composables/useTaskSubmit'
import { useDraft } from '@/composables/useDraft'
import { usePresets } from '@/composables/usePresets'
import { normalizeResolution } from '@/composables/useVideoModelCaps'
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
  idea: '',
  durationSource: 'manual' as 'manual' | 'prompt',
  sceneCount: 3,
  uniform: true,
  uniformDuration: 5,
  independentDurations: [] as number[],
  style: '',
  chaining: 'keyframes',
  resolution: '768x1152',
  refImage: null as File | null,
  refName: '',
  useEndFrames: false,
  genEndFromRef: false,
  endFrames: [] as File[],
  // v8.1：逐场景多图（索引 = 场景 index，顺序即 <Picture N>）
  sceneRefs: [] as File[][],
  // v8.1：风格板（≤2）；空则由 style 文本生成 style_plate.png
  styleImages: [] as File[],
})

// v8.1：本段内容图剩余额度 = 模型上限 − 人物图 − 风格板 −（链式 1 张衔接静帧）
// 逐段参考图只在 ti2vid / none 模式使用；关键帧模式没有这个上传入口（首帧由
// 角色参考图与上一段尾帧衔接决定）。
const sceneRefMax = computed(() => {
  const limit = Number(appState.videoCapabilities?.[appState.models.video]?.max_ref_images ?? 5)
  const system = (form.refImage ? 1 : 0) + form.styleImages.length + (form.chaining === 'ti2vid' ? 1 : 0)
  return Math.max(1, limit - system)
})

// 切换衔接方式 / 增减人物板、风格板后会改变每段上限，把已选但超出上限的图裁掉，
// 保证界面上看到的张数就是实际会提交的张数。
watch(sceneRefMax, (max) => {
  let trimmed = false
  const next = form.sceneRefs.map((files) => {
    const list = files || []
    if (list.length <= max) return list
    trimmed = true
    return list.slice(0, max)
  })
  if (trimmed) form.sceneRefs = next
})

// 尾帧 / 首尾帧只属于关键帧模式：切到其他衔接方式时清掉隐藏字段，避免带着
// 不会生效的配置提交（后端同样会忽略非关键帧模式的尾帧上传）。反向切换时
// 一并清掉逐段参考图，避免它在关键帧模式下"看得见但没用"。
watch(() => form.chaining, (mode) => {
  if (mode === 'keyframes') {
    form.sceneRefs = []
    form.styleImages = []
    return
  }
  form.useEndFrames = false
  form.genEndFromRef = false
  form.endFrames = []
})

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

// 本段剩余可传张数（0 = 已选满，组件会禁用选择）
function sceneRefRemaining(index: number) {
  return Math.max(0, sceneRefMax.value - (form.sceneRefs[index - 1]?.length || 0))
}

// 3.4：创意表单草稿（JSON 安全字段，File 不保存）
const draft = useDraft('creative')
;(() => {
  const d = draft.load()
  if (!d) return
  if (typeof d.name === 'string') form.name = d.name
  if (typeof d.idea === 'string') form.idea = d.idea
  if (d.durationSource === 'manual' || d.durationSource === 'prompt') form.durationSource = d.durationSource
  if (typeof d.sceneCount === 'number') form.sceneCount = d.sceneCount
  if (typeof d.uniform === 'boolean') form.uniform = d.uniform
  if (typeof d.uniformDuration === 'number') form.uniformDuration = d.uniformDuration
  if (Array.isArray(d.independentDurations)) form.independentDurations = d.independentDurations
  if (typeof d.style === 'string') form.style = d.style
  if (typeof d.chaining === 'string') form.chaining = d.chaining
  if (typeof d.resolution === 'string') form.resolution = normalizeResolution(d.resolution)
})()
draft.autoSave(form, (v) => ({
  name: v.name, idea: v.idea, durationSource: v.durationSource, sceneCount: v.sceneCount,
  uniform: v.uniform, uniformDuration: v.uniformDuration,
  independentDurations: v.independentDurations, style: v.style, chaining: v.chaining,
  resolution: v.resolution,
}))

// 打开表单且草稿未恢复风格时，用默认预设预填风格框（语言中性，取代旧的硬编码中文默认值）；
// 后台加载预设列表，加载后若用户未改动则对齐到真实默认预设的 prompt。
onMounted(async () => {
  if (form.style.trim()) return
  const prefill = defaultStylePrompt.value
  form.style = prefill
  await loadPresets()
  if (form.style === prefill) form.style = defaultStylePrompt.value
})

function onRefImageChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  form.refImage = file
  form.refName = file ? file.name : ''
}

// v7.6 外部素材模式：尾帧/角色参考图由外部工具（即梦）产出后导入，
// 本项目不再自动生成 → 取消并禁用两个尾帧选项（默认也不勾选）。
watch(() => appState.execMode, (mode) => {
  if (mode === 'external') {
    form.useEndFrames = false
    form.genEndFromRef = false
  }
}, { immediate: true })

function toggleEndFrames() {
  if (!form.useEndFrames) {
    form.genEndFromRef = false
  }
}

function toggleEndFrameMode() {
  if (form.genEndFromRef) {
    form.useEndFrames = false
  }
}

function addEndFrameInput() {
  form.endFrames.push(new File([], ''))
}

function onEndFrameChange(e: Event, idx: number) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  if (file) form.endFrames[idx] = file
}

async function submitCreative() {
  let ev: Record<string, any> = {}
  await runSubmit({
    taskType: 'creative',
    buildForm: () => {
      const idea = form.idea.trim()
      if (!idea) throw new Error(t('enterIdea'))
      const fd = new FormData()
      fd.append('idea', idea)
      fd.append('creative_name', form.name.trim())
      fd.append('style', form.style)
      fd.append('chaining_mode', form.chaining)

      fd.append('duration_source', form.durationSource)
      if (form.durationSource === 'manual') {
        fd.append('scene_count', String(form.sceneCount))
        fd.append('uniform_duration', String(form.uniform))
        if (form.uniform) {
          fd.append('scene_durations_json', JSON.stringify(Array(form.sceneCount).fill(form.uniformDuration)))
        } else {
          const vals = form.independentDurations.slice(0, form.sceneCount)
          fd.append('scene_durations_json', JSON.stringify(vals))
        }
      } else {
        fd.append('scene_count', '0')
        fd.append('uniform_duration', 'true')
        fd.append('scene_durations_json', JSON.stringify([]))
      }

      const res = parseResolution(form.resolution)
      fd.append('video_width', String(res.width))
      fd.append('video_height', String(res.height))
      // 尾帧 / 首尾帧只属于关键帧模式；其他模式不上送，避免后端收到无效配置
      const keyframes = form.chaining === 'keyframes'
      fd.append('use_custom_end_frames', String(keyframes && form.useEndFrames))
      fd.append('generate_end_frames_from_ref', String(keyframes && form.genEndFromRef))

      if (form.refImage) fd.append('reference_image', form.refImage)
      if (keyframes && form.useEndFrames) {
        // 只上送非空槽位，并附带「文件 → 场景 index」映射，让后端按场景落盘，
        // 保持「图片 ↔ 场景」索引对应（此前按顺序上送会让空槽位后的文件整体前移、
        // 造成图场景错位，issue #88）。空文件无法作为 multipart 文件上送，故不占位。
        const efIdx: number[] = []
        for (let i = 0; i < form.sceneCount; i++) {
          const f = form.endFrames[i]
          if (f && f.size > 0) {
            fd.append('end_frame_images', f)
            efIdx.push(i)
          }
        }
        fd.append('end_frame_indices_json', JSON.stringify(efIdx))
      }
      // v8.1：逐场景多图 —— 顺序 append 文件 + 同步映射（与稿件契约同形）
      // 关键帧模式不用逐段参考图（首帧由角色图 / 上一段尾帧决定），不上送。
      if (!keyframes) {
        const sceneFiles: File[] = []
        const sceneMap: number[][] = []
        form.sceneRefs.forEach((files, sceneIdx) => {
          ;(files || []).forEach((f) => {
            if (f && f.size > 0) {
              sceneFiles.push(f)
              sceneMap.push([sceneIdx])
            }
          })
        })
        sceneFiles.forEach((f) => fd.append('scene_reference_images', f))
        fd.append('scene_reference_images_map', JSON.stringify(sceneMap))
      }
      // v8.1：风格板（用户上传优先；关键帧模式用不到，不上送）
      if (!keyframes) form.styleImages.forEach((f) => fd.append('style_images', f))

      // Audio & Subtitle
      const sc = subtitleRef.value
      collectAudioSubtitleFields(fd, sc, voiceSelections, 'c', currentLang.value)

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
        chaining_mode: form.chaining,
        duration_source: form.durationSource,
        resolution: form.resolution,
        audio: sc?.audioEnabled ? 'on' : 'off',
        subtitle: sc?.subtitleEnabled ? 'on' : 'off',
      }
      return fd
    },
    extraEvent: ev,
    onSuccess: () => draft.clear(),
  })
}
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
      <!-- v8.0：模式示例统一指到官网新版示例页（/showcase，带 UI 语言前缀） -->
      <a :href="siteUrl('/showcase')" target="_blank" rel="noopener" class="transition-colors hover:text-accent">{{ stripEmoji(t('exampleLinkCreative')) }}</a>
    </div>

    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('creativeSettings') }}</h2>
      </header>

      <div class="panel-body space-y-4">
        <div>
          <label class="label">{{ t('taskName') }}</label>
          <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="field" />
        </div>

        <div>
          <label class="label">{{ t('ideaLabel') }} <span class="text-danger">*</span></label>
          <textarea v-model="form.idea" rows="4" :placeholder="t('ideaPlaceholder')" class="field"></textarea>
        </div>

        <!-- Scene Config -->
        <div class="subpanel">
          <h3 class="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{{ t('sceneConfig') }}</h3>

          <div class="mb-4">
            <span class="label">{{ t('durationSource') }}</span>
            <div class="grid grid-cols-2 gap-2">
              <label
                class="flex cursor-pointer items-center gap-2 rounded border px-3 py-2 text-[12.5px] transition-colors"
                :class="form.durationSource === 'manual' ? 'border-accent/40 bg-accent/10 text-ink' : 'border-rule bg-paper-2 text-ink-2 hover:border-rule-2'"
              >
                <input v-model="form.durationSource" type="radio" value="manual" class="check" />
                <span>{{ t('sourceManual') }}</span>
              </label>
              <label
                class="flex cursor-pointer items-center gap-2 rounded border px-3 py-2 text-[12.5px] transition-colors"
                :class="form.durationSource === 'prompt' ? 'border-accent/40 bg-accent/10 text-ink' : 'border-rule bg-paper-2 text-ink-2 hover:border-rule-2'"
              >
                <input v-model="form.durationSource" type="radio" value="prompt" class="check" />
                <span>{{ t('sourcePrompt') }}</span>
              </label>
            </div>
            <p class="hint mt-1.5">{{ form.durationSource === 'manual' ? t('sourceManualHint') : t('sourcePromptHint') }}</p>
          </div>

          <div v-if="form.durationSource === 'manual'" class="grid gap-4 sm:grid-cols-2">
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
                  <span class="mono w-10 text-[11px] text-muted">{{ i }}</span>
                  <input v-model.number="form.independentDurations[i - 1]" type="number" min="2" max="30" class="field w-20" />
                  <span class="hint">{{ t('seconds') }}</span>
                </div>
              </div>
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
        <div class="grid grid-cols-2 gap-4 md:grid-cols-3">
          <div>
            <label class="label">{{ t('chainingMode') }}</label>
            <select v-model="form.chaining" class="field">
              <option value="keyframes">{{ t('modeKeyframes') }}</option>
              <option value="ti2vid">{{ t('modeTi2vid') }}</option>
              <option value="none">{{ t('modeNone') }}</option>
            </select>
          </div>
          <div>
            <label class="label">{{ t('resolution') }}</label>
            <select v-model="form.resolution" class="field">
              <option value="768x1152">{{ t('resPortrait') }}</option>
              <option value="1280x720">{{ t('resLandscape') }}</option>
              <option value="1024x1024">{{ t('resSquare') }}</option>
            </select>
          </div>
        </div>

        <!-- Reference Image -->
        <div>
          <label class="label">{{ t('referenceImage') }}</label>
          <div class="flex items-center gap-3">
            <label class="btn btn-ghost shrink-0">
              <span>{{ t('chooseImage') }}</span>
              <input type="file" accept="image/*" class="hidden" @change="onRefImageChange" />
            </label>
            <span class="truncate text-[11.5px] text-muted">{{ form.refName || t('notSelected') }}</span>
          </div>
          <p class="hint mt-1.5">{{ t('refDescription') }}</p>
        </div>

        <!-- End Frames（仅关键帧模式：其他衔接方式没有首尾帧概念） -->
        <div v-if="form.chaining === 'keyframes'" class="border-t border-rule/60 pt-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <span class="label mb-0">{{ t('customEndFrames') }}</span>
            <div class="flex flex-wrap gap-4">
              <label class="flex cursor-pointer items-center gap-2 text-[12px] text-ink-2" :class="appState.execMode === 'external' ? 'cursor-not-allowed opacity-50' : ''">
                <input v-model="form.useEndFrames" type="checkbox" class="check" :disabled="appState.execMode === 'external'" @change="toggleEndFrames" />
                <span>{{ t('enableCustomEndFrames') }}</span>
              </label>
              <label class="flex cursor-pointer items-center gap-2 text-[12px] text-ink-2" :class="appState.execMode === 'external' ? 'cursor-not-allowed opacity-50' : ''">
                <input v-model="form.genEndFromRef" type="checkbox" class="check" :disabled="appState.execMode === 'external'" @change="toggleEndFrameMode" />
                <span>{{ t('genEndFramesFromRef') }}</span>
              </label>
            </div>
          </div>
          <div v-if="form.useEndFrames" class="mt-3 space-y-1.5">
            <p class="hint mb-2">{{ t('endFrameDesc') }}</p>
            <div v-for="i in form.sceneCount" :key="i" class="flex items-center gap-3">
              <span class="mono w-8 shrink-0 text-[11px] text-muted">{{ i }}</span>
              <input type="file" accept="image/*" class="end-frame-file field file-field" @change="onEndFrameChange($event, i - 1)" />
            </div>
          </div>
        </div>

        <!-- v8.1：风格板（仅 ti2vid / none：关键帧模式视频只提交首尾帧，用不到风格图） -->
        <div v-if="form.chaining !== 'keyframes'" class="border-t border-rule/60 pt-4">
          <RefImagesInput
            v-model="form.styleImages"
            :max="2"
            :label="t('plateStyle')"
            :hint="t('plateHint')"
          />
        </div>

        <!-- v8.1：逐场景参考图（仅 ti2vid / none；关键帧模式的起点由衔接决定） -->
        <div class="border-t border-rule/60 pt-4">
          <template v-if="form.chaining === 'keyframes'">
            <p class="hint">{{ t('sceneRefKeyframesHint') }}</p>
          </template>
          <template v-else>
            <label class="label">{{ t('sceneReferenceImages') }}</label>
            <p class="hint mb-2">{{ t('sceneRefDesc') }}</p>
            <div class="space-y-3">
              <div v-for="i in form.sceneCount" :key="i">
                <div class="mb-1 flex items-center gap-2">
                  <span class="mono w-8 shrink-0 text-[11px] text-muted">{{ i }}</span>
                  <span class="hint">{{ tf('sceneRefQuota', { n: sceneRefRemaining(i) }) }}</span>
                </div>
                <RefImagesInput
                  :model-value="form.sceneRefs[i - 1] || []"
                  :max="sceneRefMax"
                  input-class="scene-ref-file"
                  @update:model-value="(v: File[]) => (form.sceneRefs[i - 1] = v)"
                />
              </div>
            </div>
          </template>
        </div>
      </div>
    </section>

    <!-- Audio & Subtitle -->
    <SubtitleConfig ref="subtitleRef" task="c" :with-style="true" :external="appState.execMode === 'external'" />

    <WatermarkToggle />

    <button
      class="btn btn-primary btn-block"
      :disabled="submitting"
      @click="submitCreative"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
