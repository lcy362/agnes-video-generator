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
  name: '',
  text: '',
  resolution: '768x1152',
  // v8.1：人物板 / 风格板（各 ≤2，空则由流水线按正文生成）
  characterImages: [] as File[],
  styleImages: [] as File[],
  // v8.1：分镜衔接（路径 K）/ 生成前暂停补图
  linkShots: false,
  pauseForSceneRefs: false,
})

const advancedOpen = ref(false)

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
      // v8.1：人物板 / 风格板 + 衔接与补图开关
      form.characterImages.forEach((f) => fd.append('character_images', f))
      form.styleImages.forEach((f) => fd.append('style_images', f))
      fd.append('link_shots', String(form.linkShots))
      fd.append('pause_for_scene_refs', String(form.pauseForSceneRefs))

      const sc = subtitleRef.value
      collectAudioSubtitleFields(fd, sc, voiceSelections, 'm')

      // v6.0 手动模式 / v7.6 外部素材模式：执行模式 + 暂停点 + 工具与音频来源
      fd.append('execution_mode', appState.execMode)
      fd.append('pause_points', JSON.stringify(appState.execMode !== 'auto' ? appState.pausePoints : []))
      if (appState.execMode === 'external') {
        fd.append('provider', appState.providerSelected || 'jimeng')
        fd.append('audio_source', appState.externalAudioSource)
        fd.append('subtitle_source', appState.externalSubtitleSource)
      }

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
    <div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted">
      <!-- v8.0：模式示例统一指到官网新版示例页（/showcase，带 UI 语言前缀） -->
      <a :href="siteUrl('/showcase')" target="_blank" rel="noopener" class="transition-colors hover:text-accent">{{ stripEmoji(t('exampleLinkManuscript')) }}</a>
    </div>

    <section class="panel mb-4">
      <header class="panel-head">
        <h2 class="panel-title">{{ t('manuscriptSettings') }}</h2>
      </header>

      <div class="panel-body space-y-4">
        <div>
          <label class="label">{{ t('taskName') }}</label>
          <input v-model="form.name" :placeholder="t('taskNamePlaceholder')" class="field" />
        </div>

        <div>
          <label class="label">{{ t('manuscriptText') }} <span class="text-danger">*</span></label>
          <textarea v-model="form.text" rows="10" :placeholder="t('manuscriptPlaceholder')" class="field font-mono"></textarea>
          <p class="hint mt-1.5"><span class="mono">{{ charCount }}</span> {{ t('charCount') }}</p>
        </div>

        <div class="max-w-64">
          <label class="label">{{ t('resolution') }}</label>
          <select v-model="form.resolution" class="field">
            <option value="768x1152">{{ t('resPortrait') }}</option>
            <option value="1280x720">{{ t('resLandscape') }}</option>
            <option value="1024x1024">{{ t('resSquare') }}</option>
          </select>
        </div>
      </div>
    </section>

    <!-- v8.1：多参考图（默认折叠，不打扰不传图的用户） -->
    <section class="panel mb-4">
      <header class="panel-head">
        <button
          type="button"
          class="flex w-full items-center justify-between text-start"
          @click="advancedOpen = !advancedOpen"
        >
          <h2 class="panel-title">{{ t('advancedSettings') }}</h2>
          <span class="mono text-[11px] text-muted">{{ advancedOpen ? '−' : '+' }}</span>
        </button>
      </header>
      <div v-show="advancedOpen" class="panel-body space-y-5">
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
        <div class="space-y-2 border-t border-rule/60 pt-4">
          <label class="flex cursor-pointer items-start gap-2 text-[12px] text-ink-2">
            <input v-model="form.linkShots" type="checkbox" class="check mt-0.5" />
            <span class="min-w-0">
              <span class="block">{{ t('linkShots') }}</span>
              <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('linkShotsHint') }}</span>
            </span>
          </label>
          <label class="flex cursor-pointer items-start gap-2 text-[12px] text-ink-2">
            <input v-model="form.pauseForSceneRefs" type="checkbox" class="check mt-0.5" />
            <span class="min-w-0">
              <span class="block">{{ t('pauseSceneRefs') }}</span>
              <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('pauseSceneRefsHint') }}</span>
            </span>
          </label>
        </div>
      </div>
    </section>

    <SubtitleConfig ref="subtitleRef" task="m" :with-style="true" :external="appState.execMode === 'external'" />

    <WatermarkToggle />

    <button
      class="btn btn-primary btn-block"
      :disabled="submitting"
      @click="submitManuscript"
    >
      {{ submitting ? t('submitting') : t('startGenerate') }}
    </button>
  </div>
</template>
