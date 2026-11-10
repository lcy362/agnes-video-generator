<script setup lang="ts">
import { t } from '@/i18n'
import { appState } from '@/store'
import { useConfig } from '@/composables/useConfig'

const { toggleWatermark } = useConfig()

function onChange(e: Event) {
  toggleWatermark((e.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="mb-4 flex items-center justify-between gap-4 rounded border border-rule bg-paper-2 px-3 py-2">
    <p class="hint flex-1">{{ t('watermarkPromo') }}</p>
    <label class="relative inline-flex shrink-0 cursor-pointer items-center" title="Video Watermark">
      <input
        type="checkbox"
        class="watermark-toggle sr-only peer"
        :checked="appState.watermarkEnabled"
        @change="onChange"
      />
      <span
        class="relative inline-block h-[18px] w-8 rounded-full border transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2"
        :class="appState.watermarkEnabled ? 'border-accent bg-accent' : 'border-rule-2 bg-paper-3'"
        style="outline-color: var(--color-focus)"
      >
        <span
          class="absolute top-[2px] h-3 w-3 rounded-full transition-all"
          :class="appState.watermarkEnabled ? 'bg-accent-ink' : 'bg-muted'"
          :style="{ insetInlineStart: appState.watermarkEnabled ? '16px' : '2px' }"
        ></span>
      </span>
    </label>
  </div>
</template>
