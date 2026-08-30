<script setup lang="ts">
import { useConfirm } from '@/composables/useConfirm'
import { useModalA11y } from '@/composables/useModalA11y'
import { t } from '@/i18n'

const { visible, message, title, confirmYes, confirmNo } = useConfirm()
const { containerRef } = useModalA11y(visible, confirmNo)
</script>

<template>
  <teleport to="body">
    <div
      v-if="visible"
      ref="containerRef"
      class="fixed inset-0 z-[60] flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      :aria-label="title || message"
    >
      <div class="absolute inset-0 bg-black/40" @click="confirmNo"></div>
      <div
        class="relative bg-paper rounded-2xl p-6 max-w-sm w-full mx-4 shadow-2xl border border-rule"
      >
        <h3 v-if="title" class="text-base font-semibold text-ink mb-2" id="confirm-title">{{ title }}</h3>
        <p class="text-sm text-ink-2 whitespace-pre-line leading-relaxed">{{ message }}</p>
        <div class="flex justify-end gap-3 mt-6">
          <button
            class="px-4 py-2 rounded-lg text-sm text-ink-2 bg-paper-3 hover:bg-paper-2 border border-rule transition"
            @click="confirmNo"
          >
            {{ t('cancel') }}
          </button>
          <button
            class="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 transition"
            @click="confirmYes"
          >
            {{ t('confirm') }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>
