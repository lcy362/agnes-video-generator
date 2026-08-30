<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t, currentLang } from '@/i18n'
import { appState } from '@/store'
import { useVoice } from '@/composables/useVoice'
import { useTaskSubmit, collectAudioSubtitleFields } from '@/composables/useTaskSubmit'
import { useDraft } from '@/composables/useDraft'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'

const { voiceSelections } = useVoice()
const { submitting, runSubmit } = useTaskSubmit()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  name: '',
  idea: '',
  durationSource: 'manual' as 'manual' | 'prompt',
  sceneCount: 3,
  uniform: true,
  uniformDuration: 5,
  independentDurations: [] as number[],
  style: '电影质感写实风格',
  chaining: 'keyframes',
  resolution: '768x1152',
  refImage: null as File | null,
  refName: '',
  useEndFrames: false,
  genEndFromRef: true,
  endFrames: [] as File[],
  // v5.0 优化 5：用户上传分镜场景图（按场景 index 对齐）
  sceneRefs: [] as File[],
})

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
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
  if (typeof d.resolution === 'string') form.resolution = d.resolution
})()
draft.autoSave(form, (v) => ({
  name: v.name, idea: v.idea, durationSource: v.durationSource, sceneCount: v.sceneCount,
  uniform: v.uniform, uniformDuration: v.uniformDuration,
  independentDurations: v.independentDurations, style: v.style, chaining: v.chaining,
  resolution: v.resolution,
}))

function onRefImageChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  form.refImage = file
  form.refName = file ? file.name : ''
}

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

function onSceneRefChange(e: Event, idx: number) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  if (file) form.sceneRefs[idx] = file
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
      fd.append('use_custom_end_frames', String(form.useEndFrames))
      fd.append('generate_end_frames_from_ref', String(form.genEndFromRef))

      if (form.refImage) fd.append('reference_image', form.refImage)
      if (form.useEndFrames) {
        form.endFrames.forEach((f) => {
          if (f && f.size > 0) fd.append('end_frame_images', f)
        })
      }
      // v5.0 优化 5：用户上传分镜场景图（多文件，后端按上传顺序对应场景 index）
      if (form.sceneRefs.length > 0) {
        form.sceneRefs.forEach((f) => {
          if (f && f.size > 0) fd.append('scene_reference_images', f)
        })
      }

      // Audio & Subtitle
      const sc = subtitleRef.value
      collectAudioSubtitleFields(fd, sc, voiceSelections, 'c', currentLang.value)

      // v6.0 手动模式：执行模式 + 暂停点
      fd.append('execution_mode', appState.execMode)
      fd.append('pause_points', JSON.stringify(appState.execMode === 'manual' ? appState.pausePoints : []))

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
    <div class="flex items-center gap-2 mb-4 text-xs text-muted">
      <span class="text-muted">💡</span>
      <a href="https://video.lichuanyang.top/guides/prompt-examples-creative" target="_blank" rel="noopener" class="hover:text-accent transition-colors">{{ t('exampleLinkCreative') }}</a>
    </div>

    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('creativeSettings') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('taskName') }}</label>
        <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('ideaLabel') }} (idea) <span class="text-red-400">*</span></label>
        <textarea v-model="form.idea" rows="4" :placeholder="t('ideaPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted"></textarea>
      </div>

      <!-- Scene Config -->
      <div class="mb-4 p-4 rounded-xl bg-paper-2/30 border border-rule/50">
        <h3 class="text-sm font-medium text-accent mb-3">{{ t('sceneConfig') }}</h3>
        <div class="mb-4">
          <label class="block text-sm text-muted mb-2">{{ t('durationSource') }}</label>
          <div class="flex gap-2">
            <label class="flex-1 flex items-center gap-2 px-3 py-2.5 rounded-lg bg-paper-2/50 border border-rule cursor-pointer hover:border-blue-500/30 transition">
              <input v-model="form.durationSource" type="radio" value="manual" class="text-accent" />
              <span class="text-sm text-ink-2">{{ t('sourceManual') }}</span>
            </label>
            <label class="flex-1 flex items-center gap-2 px-3 py-2.5 rounded-lg bg-paper-2/50 border border-rule cursor-pointer hover:border-blue-500/30 transition">
              <input v-model="form.durationSource" type="radio" value="prompt" class="text-accent" />
              <span class="text-sm text-ink-2">{{ t('sourcePrompt') }}</span>
            </label>
          </div>
          <p class="text-xs text-muted mt-1.5">{{ form.durationSource === 'manual' ? t('sourceManualHint') : t('sourcePromptHint') }}</p>
        </div>

        <div v-if="form.durationSource === 'manual'">
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
          <label class="block text-sm text-muted mb-1.5">{{ t('chainingMode') }}</label>
          <select v-model="form.chaining" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option value="keyframes">{{ t('modeKeyframes') }}</option>
            <option value="ti2vid">{{ t('modeTi2vid') }}</option>
            <option value="none">{{ t('modeNone') }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
          <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option value="768x1152">{{ t('resPortrait') }}</option>
            <option value="1152x768">{{ t('resLandscape') }}</option>
            <option value="1024x1024">{{ t('resSquare') }}</option>
          </select>
        </div>
      </div>

      <!-- Reference Image -->
      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('referenceImage') }}</label>
        <div class="flex items-center gap-4">
          <label class="cursor-pointer px-4 py-2.5 glass-input rounded-lg text-sm transition inline-block hover:border-blue-500/30">
            <span>{{ t('chooseImage') }}</span>
            <input type="file" accept="image/*" class="hidden" @change="onRefImageChange" />
          </label>
          <span class="text-sm text-muted">{{ form.refName || t('notSelected') }}</span>
        </div>
        <p class="text-xs text-muted mt-2">{{ t('refDescription') }}</p>
      </div>

      <!-- End Frames -->
      <div class="mb-4">
        <div class="flex items-center justify-between mb-3">
          <label class="text-sm text-muted">{{ t('customEndFrames') }}</label>
          <div class="flex gap-3">
            <label class="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input v-model="form.useEndFrames" type="checkbox" class="rounded bg-paper-2 border-rule" @change="toggleEndFrames" />
              <span>{{ t('enableCustomEndFrames') }}</span>
            </label>
            <label class="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input v-model="form.genEndFromRef" type="checkbox" class="rounded bg-paper-2 border-rule" @change="toggleEndFrameMode" />
              <span>{{ t('genEndFramesFromRef') }}</span>
            </label>
          </div>
        </div>
        <div v-if="form.useEndFrames" class="space-y-2">
          <p class="text-xs text-muted mb-2">{{ t('endFrameDesc') }}</p>
          <div class="space-y-2">
            <div v-for="i in form.sceneCount" :key="i" class="flex items-center gap-3 mb-2">
              <span class="text-xs text-muted w-16">{{ t('scene_') }} {{ i }}</span>
              <input type="file" accept="image/*" class="end-frame-file flex-1 text-sm text-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:bg-paper-3 file:text-ink-2 hover:file:bg-paper-3" @change="onEndFrameChange($event, i - 1)" />
            </div>
          </div>
        </div>
      </div>

      <!-- Scene Reference Images (v5.0 优化 5) -->
      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('sceneReferenceImages') }}</label>
        <p class="text-xs text-muted mb-2">{{ t('sceneRefDesc') }}</p>
        <div class="space-y-2">
          <div v-for="i in form.sceneCount" :key="i" class="flex items-center gap-3 mb-2">
            <span class="text-xs text-muted w-16">{{ t('scene_') }} {{ i }}</span>
            <input type="file" accept="image/*" class="scene-ref-file flex-1 text-sm text-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:bg-paper-3 file:text-ink-2 hover:file:bg-paper-3" @change="onSceneRefChange($event, i - 1)" />
          </div>
        </div>
      </div>
    </div>

    <!-- Audio & Subtitle -->
    <SubtitleConfig ref="subtitleRef" task="c" :with-style="true" />

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitCreative"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
