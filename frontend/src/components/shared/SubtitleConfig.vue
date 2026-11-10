<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { t } from '@/i18n'
import VoiceSelector from './VoiceSelector.vue'

// 共享字幕样式配置（创意/稿件/数字人共用；诗词仅开关）
const props = defineProps<{
  task: string // c/m/a/p
  withStyle?: boolean // 诗词为 false（仅开关）
  defaultFontsize?: number
  // v7.6 外部素材模式：音频来自视频自身 → 默认关配音、开字幕
  external?: boolean
}>()

const audioEnabled = ref(true)
const subtitleEnabled = ref(true)
const rate = ref('+0%')

// 切到外部素材模式时套用默认值（用户仍可手动改回）
watch(
  () => props.external,
  (v) => {
    if (v) {
      audioEnabled.value = false
      subtitleEnabled.value = true
    }
  },
  { immediate: true },
)

const styleMode = ref<'fixed' | 'llm'>('fixed')
const style = reactive({
  font: 'STHeitiMedium.ttc',
  color: 'white',
  fontsize: props.defaultFontsize ?? 48,
  position: 'bottom',
  stroke_color: 'black',
  stroke_width: 2,
  bg_color: 'black@0.5',
  hints: '',
})

const collapsed = reactive({ audio: true, subtitle: true })

function toggleCollapse(key: 'audio' | 'subtitle') {
  collapsed[key] = !collapsed[key]
}

// 暴露表单数据给父组件
defineExpose({
  audioEnabled,
  subtitleEnabled,
  rate,
  styleMode,
  style,
})
</script>

<template>
  <!-- Audio Config -->
  <section class="panel mb-4">
    <button type="button" class="panel-head collapse-header w-full text-start" @click="toggleCollapse('audio')">
      <h2 class="panel-title">{{ t('audioConfig') }}</h2>
      <span class="mono text-[11px] text-muted">{{ collapsed.audio ? '+' : '−' }}</span>
    </button>
    <div v-show="!collapsed.audio" class="panel-body">
      <label class="mb-4 flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-2">
        <input v-model="audioEnabled" type="checkbox" class="check" />
        <span>{{ t('enableNarration') }}</span>
      </label>
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <label class="label">{{ t('voiceRole') }}</label>
          <VoiceSelector :task="task" />
        </div>
        <div>
          <label class="label">{{ t('speechRate') }}</label>
          <select v-model="rate" class="field">
            <option value="-30%">{{ t('rateSlow') }}</option>
            <option value="-15%">-15%</option>
            <option value="+0%">{{ t('rateNormal') }}</option>
            <option value="+15%">+15%</option>
            <option value="+30%">{{ t('rateFast') }}</option>
          </select>
        </div>
      </div>
    </div>
  </section>

  <!-- Subtitle Config -->
  <section class="panel mb-4">
    <button type="button" class="panel-head collapse-header w-full text-start" @click="toggleCollapse('subtitle')">
      <h2 class="panel-title">{{ t('subtitleConfig') }}</h2>
      <span class="mono text-[11px] text-muted">{{ collapsed.subtitle ? '+' : '−' }}</span>
    </button>
    <div v-show="!collapsed.subtitle" class="panel-body">
      <label class="mb-4 flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-2">
        <input v-model="subtitleEnabled" type="checkbox" class="check" />
        <span>{{ t('enableSubtitle') }}</span>
      </label>

      <template v-if="withStyle">
        <div class="border-t border-rule/60 pt-4">
          <div class="mb-4 max-w-64">
            <label class="label">{{ t('subStyleMode') }}</label>
            <select v-model="styleMode" class="field">
              <option value="fixed">{{ t('subStyleFixed') }}</option>
              <option value="llm">{{ t('subStyleLLM') }}</option>
            </select>
          </div>

          <div v-if="styleMode === 'fixed'">
            <p class="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{{ t('subtitleStyle') }}</p>
            <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
              <div>
                <label class="label">{{ t('subFont') }}</label>
                <input v-model="style.font" class="field" />
              </div>
              <div>
                <label class="label">{{ t('subColor') }}</label>
                <input v-model="style.color" class="field" />
              </div>
              <div>
                <label class="label">{{ t('subSize') }}</label>
                <input v-model.number="style.fontsize" type="number" class="field" />
              </div>
              <div>
                <label class="label">{{ t('subPosition') }}</label>
                <select v-model="style.position" class="field">
                  <option value="bottom">{{ t('posBottom') }}</option>
                  <option value="top">{{ t('posTop') }}</option>
                </select>
              </div>
            </div>
            <div class="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
              <div>
                <label class="label">{{ t('subStrokeColor') }}</label>
                <input v-model="style.stroke_color" class="field" />
              </div>
              <div>
                <label class="label">{{ t('subStrokeWidth') }}</label>
                <input v-model.number="style.stroke_width" type="number" class="field" />
              </div>
              <div>
                <label class="label">{{ t('subBgColor') }}</label>
                <input v-model="style.bg_color" class="field" />
              </div>
            </div>
          </div>

          <div v-else>
            <label class="label">{{ t('subStyleHints') }}</label>
            <textarea v-model="style.hints" rows="3" class="field" :placeholder="t('subStyleHintsPlaceholder')"></textarea>
            <p class="hint mt-1.5">{{ t('subStyleHintsHint') }}</p>
          </div>
        </div>
      </template>
      <p v-else class="hint">{{ t('poetrySubtitleFixed') }}</p>
    </div>
  </section>
</template>
