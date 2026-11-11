<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { t } from '@/i18n'
import { stripEmoji } from '@/utils/text'
import { siteUrl } from '@/utils/siteLinks'
import { appState } from '@/store'
import { useVoice } from '@/composables/useVoice'
import { useTaskSubmit, collectAudioSubtitleFields } from '@/composables/useTaskSubmit'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import SubtitleConfig from '@/components/shared/SubtitleConfig.vue'
import RefImagesInput from '@/components/shared/RefImagesInput.vue'

const { voiceSelections } = useVoice()
const { submitting, runSubmit } = useTaskSubmit()

const subtitleRef = ref<InstanceType<typeof SubtitleConfig>>()

const form = reactive({
  prompt: '',
  // v8.1：多参考图；第 1 张为数字人形象，其余为服饰/场景辅助
  refImages: [] as File[],
  script: '',
  resolution: '768x1344',
  audioSource: 'post_stitch' as 'post_stitch' | 'model',
})

const charCount = computed(() => form.script.length)

// v8.1：图片侧参考图上限（/api/models image_capabilities，默认 5）
const maxRefImages = computed(() => Number(appState.imageCapabilities?.max_ref_images ?? 5))

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

async function submitAnchor() {
  let ev: Record<string, any> = {}
  await runSubmit({
    taskType: 'anchor',
    buildForm: () => {
      const script = form.script.trim()
      if (!script) throw new Error(t('enterText'))
      const fd = new FormData()
      fd.append('script_text', script)
      const prompt = form.prompt.trim()
      if (prompt) fd.append('anchor_prompt', prompt)
      const res = parseResolution(form.resolution)
      fd.append('video_width', String(res.width))
      fd.append('video_height', String(res.height))
      // v8.1：多参考图（后端 anchor_reference_images，旧单数字段仍兼容）
      form.refImages.forEach((f) => fd.append('anchor_reference_images', f))
      // v7.6 外部素材模式：音频来源改由外部模式决定；否则用数字人自身的音频模式
      if (appState.execMode === 'external') {
        fd.append('audio_source', appState.externalAudioSource)
        fd.append('provider', appState.providerSelected || 'jimeng')
        fd.append('subtitle_source', appState.externalSubtitleSource)
      } else {
        fd.append('audio_source', form.audioSource)
      }

      const sc = subtitleRef.value
      collectAudioSubtitleFields(fd, sc, voiceSelections, 'a')
      // 特例：model 自带口型音频 → 强制关闭 TTS 旁白
      if (appState.execMode !== 'external' && form.audioSource === 'model') fd.set('audio_enabled', 'false')

      // v6.0 手动模式 / v7.6 外部素材模式：执行模式 + 暂停点
      fd.append('execution_mode', appState.execMode)
      fd.append('pause_points', JSON.stringify(appState.execMode !== 'auto' ? appState.pausePoints : []))

      ev = {
        resolution: form.resolution,
        audio_source: form.audioSource,
        audio: form.audioSource === 'model' ? 'off' : sc?.audioEnabled ? 'on' : 'off',
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
    <div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
      <!-- v8.0：模式示例统一指到官网新版示例页（/showcase，带 UI 语言前缀） -->
      <a :href="siteUrl('/showcase')" target="_blank" rel="noopener" class="transition-colors hover:text-accent">{{ stripEmoji(t('exampleLinkAnchor')) }}</a>
    </div>

    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('anchorSettings') }}</h2>
      </header>

      <div class="panel-body space-y-4">
        <div>
          <label class="label">{{ t('anchorPrompt') }}</label>
          <textarea v-model="form.prompt" rows="3" :placeholder="t('anchorPromptPlaceholder')" class="field"></textarea>
        </div>

        <RefImagesInput
          v-model="form.refImages"
          :max="maxRefImages"
          :label="t('anchorRefImage')"
          :hint="t('anchorRefImageHint')"
        />

        <div>
          <label class="label">{{ t('scriptText') }} <span class="text-danger">*</span></label>
          <textarea v-model="form.script" rows="8" :placeholder="t('scriptTextPlaceholder')" class="field font-mono"></textarea>
          <p class="hint mt-1.5"><span class="mono">{{ charCount }}</span> {{ t('charCount') }}</p>
        </div>

        <div class="max-w-64">
          <label class="label">{{ t('resolution') }}</label>
          <select v-model="form.resolution" class="field">
            <option value="768x1344">{{ t('resPortraitHD') }}</option>
            <option value="1280x720">{{ t('resLandscape') }}</option>
            <option value="1024x1024">{{ t('resSquare') }}</option>
          </select>
        </div>
      </div>
    </section>

    <!-- Audio Source (Anchor only) -->
    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('audioSource') }}</h2>
      </header>
      <div class="panel-body">
        <div class="grid gap-2 sm:grid-cols-2">
          <label
            class="flex cursor-pointer items-start gap-3 rounded border px-3 py-2.5 transition-colors"
            :class="form.audioSource === 'post_stitch' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'"
          >
            <input v-model="form.audioSource" type="radio" name="a_audio_source" value="post_stitch" class="check mt-0.5" />
            <span class="min-w-0">
              <span class="block text-[12.5px] text-ink">{{ t('audioPostStitch') }}</span>
              <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('audioPostStitchDesc') }}</span>
            </span>
          </label>
          <label
            class="flex cursor-pointer items-start gap-3 rounded border px-3 py-2.5 transition-colors"
            :class="form.audioSource === 'model' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'"
          >
            <input v-model="form.audioSource" type="radio" name="a_audio_source" value="model" class="check mt-0.5" />
            <span class="min-w-0">
              <span class="block text-[12.5px] text-ink">{{ t('audioModel') }}</span>
              <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('audioModelDesc') }}</span>
            </span>
          </label>
        </div>
      </div>
    </section>

    <!-- Audio & Subtitle（model 模式禁用音频） -->
    <div :class="{ 'opacity-40 pointer-events-none': form.audioSource === 'model' }">
      <SubtitleConfig ref="subtitleRef" task="a" :with-style="true" :external="appState.execMode === 'external'" />
    </div>

    <WatermarkToggle />

    <button
      class="btn btn-primary btn-block"
      :disabled="submitting"
      @click="submitAnchor"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
