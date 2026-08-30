<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { useVoice } from '@/composables/useVoice'
import { useModalA11y } from '@/composables/useModalA11y'
import { appState } from '@/store'

const {
  pickerVisible,
  activeLang,
  query,
  selectedId,
  playingId,
  activeGroup,
  filteredVoices,
  closeVoicePicker,
  selectVoice,
  onVoiceSearch,
  previewVoice,
  confirmVoiceSelection,
} = useVoice()

// 3.4：ESC + focus trap + 焦点还原
const { containerRef } = useModalA11y(pickerVisible, closeVoicePicker)

const selectedVoiceName = computed(() => {
  const v = appState.voiceIndex[selectedId.value as string]
  return v ? `${v.name}（${v.region}）` : (selectedId.value || '—')
})
</script>

<template>
  <div v-if="pickerVisible" ref="containerRef" class="vp-overlay" @click.self="closeVoicePicker">
    <div class="vp-modal" role="dialog" aria-modal="true">
      <div class="vp-header">
        <h3>{{ t('selectVoice') }}</h3>
        <button class="vp-close" @click="closeVoicePicker">✕</button>
      </div>
      <div class="vp-search">
        <input
          :value="query"
          type="text"
          :placeholder="t('searchVoice')"
          @input="onVoiceSearch(($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="vp-tabs">
        <div
          v-for="g in appState.voiceCatalog?.languages || []"
          :key="g.code"
          class="vp-tab"
          :class="{ active: g.code === activeLang }"
          @click="activeLang = g.code"
        >
          {{ g.label }}<span class="vp-count">{{ g.count }}</span>
        </div>
      </div>
      <div class="vp-grid">
        <div v-if="!filteredVoices.length" class="vp-empty">{{ t('voiceEmpty') }}</div>
        <div
          v-for="v in filteredVoices"
          :key="v.id"
          class="vp-card"
          :class="{ selected: v.id === selectedId }"
          @click="selectVoice(v.id)"
        >
          <div class="vp-card-top">
            <span class="vp-card-name">{{ v.name }}</span>
            <span class="vp-card-region">{{ v.region }}</span>
          </div>
          <div class="vp-tags">
            <span class="vp-tag" :class="'gender-' + v.gender">{{ v.gender === 'female' ? t('voiceGenderFemale') : t('voiceGenderMale') }}</span>
            <span v-for="(s, i) in (v.style_tags || []).slice(0, 3)" :key="i" class="vp-tag">{{ s }}</span>
          </div>
          <button
            class="vp-preview-btn"
            :class="{ playing: playingId === v.id }"
            @click.stop="previewVoice(v.id)"
          >
            {{ playingId === v.id ? '⏸ ' + t('previewStop') : '▶ ' + t('previewPlay') }}
          </button>
        </div>
      </div>
      <div class="vp-selection">
        <div class="vp-current">{{ t('currentSelection') }}: <b>{{ selectedVoiceName }}</b></div>
        <div class="vp-actions">
          <button class="vp-btn vp-btn-cancel" @click="closeVoicePicker">{{ t('cancel') }}</button>
          <button class="vp-btn vp-btn-confirm" @click="confirmVoiceSelection">{{ t('confirmSelection') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
