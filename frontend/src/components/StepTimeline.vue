<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { useProgress } from '@/composables/useProgress'

const props = defineProps<{ horizontal?: boolean }>()
const emit = defineEmits<{ (e: 'locate', stepKey: string): void }>()

const { steps, stepStates, awaitingCheckpoint } = useProgress()

// checkpoint -> 最近似的 step key（用于暂停时在时间线中高亮对应环节）
const CHECKPOINT_TO_STEP: Record<string, string> = {
  image_analysis: 'image_analysis',
  story: 'story',
  script: 'script',
  character_ref: 'character_ref',
  end_frame_prompts: 'end_frame_prompts',
  end_frame_gen: 'end_frame_gen',
  scenes: 'script',
  references: 'character_ref',
  videos: 'video_gen',
  audio: 'audio',
  subtitle: 'subtitle',
  final: 'concatenate',
}

const checkpointLabelKey: Record<string, string> = {
  image_analysis: 'cpImageAnalysis',
  story: 'cpStory',
  script: 'cpScript',
  character_ref: 'cpCharacterRef',
  end_frame_prompts: 'cpEndFramePrompts',
  end_frame_gen: 'cpEndFrameGen',
  scenes: 'cpScenes',
  references: 'cpReferences',
  videos: 'cpVideos',
  audio: 'cpAudio',
  subtitle: 'cpSubtitle',
  final: 'cpFinal',
}

type Item = { key: string; label: string; state: 'done' | 'running' | 'awaiting' | 'pending' }

const items = computed<Item[]>(() => {
  const cp = awaitingCheckpoint.value
  const highlightStep = cp ? CHECKPOINT_TO_STEP[cp] : ''
  const hasHighlight = cp && highlightStep && steps.value.some((s) => s.key === highlightStep)

  const list: Item[] = steps.value.map((s) => {
    let state: Item['state'] = stepStates.value[s.key] || 'pending'
    if (cp && hasHighlight && s.key === highlightStep) state = 'awaiting'
    return { key: s.key, label: t(s.labelKey), state }
  })

  // 暂停点无对应 step 时，在末尾追加独立条目
  if (cp && !hasHighlight) {
    list.push({ key: cp, label: t(checkpointLabelKey[cp] || cp), state: 'awaiting' })
  }
  return list
})

function onLocate(item: Item) {
  if (item.state !== 'pending') emit('locate', item.key)
}

function iconFor(state: Item['state']): string {
  if (state === 'done') return '✓'
  if (state === 'awaiting') return '!'
  return ''
}
</script>

<template>
  <div v-if="!props.horizontal">
    <p class="eyebrow mb-2.5">{{ t('ppStages') }}</p>
    <div class="tl">
      <button
        v-for="item in items"
        :key="item.key"
        class="tl-item"
        :class="'is-' + item.state"
        @click="onLocate(item)"
      >
        <span class="tl-dot" :class="item.state === 'running' ? 'animate-pulse-dot' : ''">{{ iconFor(item.state) }}</span>
        <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
        <span v-if="item.state === 'awaiting'" class="mono shrink-0 text-[9px] tracking-[0.08em]">{{ t('ppWaiting') }}</span>
      </button>
    </div>
  </div>

  <!-- 移动端：横向滚动胶囊 -->
  <div v-else class="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-2">
    <button
      v-for="item in items"
      :key="item.key"
      class="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded border px-2.5 py-1 text-[11px] transition-colors"
      :class="[
        item.state === 'awaiting' ? 'border-accent/40 bg-accent/10 text-accent' : '',
        item.state === 'running' ? 'border-accent/30 text-accent' : '',
        item.state === 'done' ? 'border-rule text-ink-2' : '',
        item.state === 'pending' ? 'border-rule text-muted' : '',
      ]"
      @click="onLocate(item)"
    >
      <span class="text-[9px] leading-none">{{ iconFor(item.state) }}</span>
      <span>{{ item.label }}</span>
    </button>
  </div>
</template>
