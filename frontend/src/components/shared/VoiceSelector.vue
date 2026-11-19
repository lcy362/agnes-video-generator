<script setup lang="ts">
import { t } from '@/i18n'
import { useVoice } from '@/composables/useVoice'

const props = defineProps<{
  task: string // c/m/a/p
}>()

const { voiceName, voiceDescription, openVoicePicker } = useVoice()
</script>

<template>
  <div
    class="voice-selector"
    role="button"
    tabindex="0"
    data-track="open_voice_picker"
    :data-track-params="JSON.stringify({ task: props.task })"
    @click="openVoicePicker(props.task)"
    @keydown.enter.prevent="openVoicePicker(props.task)"
    @keydown.space.prevent="openVoicePicker(props.task)"
  >
    <span class="vs-main">
      <span class="vs-name">{{ voiceName(props.task) }}</span>
      <span class="vs-desc">{{ voiceDescription(props.task) || t('voiceDefaultDesc') }}</span>
    </span>
    <span class="vs-arrow">▾</span>
  </div>
</template>
