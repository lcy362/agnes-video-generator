<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useVoice } from '@/composables/useVoice'
import { useTaskSubmit, collectAudioSubtitleFields } from '@/composables/useTaskSubmit'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'

const { voiceSelections } = useVoice()
const { submitting, runSubmit } = useTaskSubmit()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  name: '',
  text: '',
  resolution: '768x1152',
})

const charCount = computed(() => form.text.length)

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

async function submitManuscript() {
  let ev: Record<string, any> = {}
  await runSubmit({
    taskType: 'manuscript',
    buildForm: () => {
      const text = form.text.trim()
      if (!text) throw new Error(t('enterText'))
      const fd = new FormData()
      fd.append('manuscript_text', text)
      fd.append('creative_name', form.name.trim())
      const res = parseResolution(form.resolution)
      fd.append('video_width', String(res.width))
      fd.append('video_height', String(res.height))

      const sc = subtitleRef.value
      collectAudioSubtitleFields(fd, sc, voiceSelections, 'm')

      // v6.0 手动模式：执行模式 + 暂停点
      fd.append('execution_mode', appState.execMode)
      fd.append('pause_points', JSON.stringify(appState.execMode === 'manual' ? appState.pausePoints : []))

      ev = {
        resolution: form.resolution,
        text_len: text.length,
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
    <div class="flex items-center gap-2 mb-4 text-xs text-muted">
      <span class="text-muted">💡</span>
      <a href="https://video.lichuanyang.top/guides/prompt-examples-manuscript" target="_blank" rel="noopener" class="hover:text-accent transition-colors">{{ t('exampleLinkManuscript') }}</a>
    </div>

    <div class="glass-card rounded-2xl p-6 mb-4">
      <h2 class="text-lg font-semibold text-accent mb-4">{{ t('manuscriptSettings') }}</h2>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('taskName') }}</label>
        <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('manuscriptText') }} <span class="text-red-400">*</span></label>
        <textarea v-model="form.text" rows="10" :placeholder="t('manuscriptPlaceholder')" class="w-full glass-input rounded-lg px-4 py-2.5 text-sm resize-y text-ink placeholder-muted font-mono"></textarea>
        <p class="text-xs text-muted mt-1">{{ t('charCount') }}: {{ charCount }}</p>
      </div>

      <div class="mb-4">
        <label class="block text-sm text-muted mb-1.5">{{ t('resolution') }}</label>
        <select v-model="form.resolution" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
          <option value="768x1152">{{ t('resPortrait') }}</option>
          <option value="1152x768">{{ t('resLandscape') }}</option>
          <option value="1024x1024">{{ t('resSquare') }}</option>
        </select>
      </div>
    </div>

    <SubtitleConfig ref="subtitleRef" task="m" :with-style="true" />

    <WatermarkToggle />

    <button
      class="w-full py-3.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-xl text-base font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed glow-btn"
      :disabled="submitting"
      @click="submitManuscript"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
