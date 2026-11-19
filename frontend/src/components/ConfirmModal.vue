<script setup lang="ts">
import { useConfirm } from '@/composables/useConfirm'
import { useModalA11y } from '@/composables/useModalA11y'
import { t } from '@/i18n'

const { visible, message, title, action, confirmYes, confirmNo } = useConfirm()
const { containerRef } = useModalA11y(visible, confirmNo)
</script>

<template>
  <teleport to="body">
    <div
      v-if="visible"
      ref="containerRef"
      class="modal-backdrop"
      role="dialog"
      aria-modal="true"
      :aria-label="title || message"
    >
      <!-- 确认/取消属于「同一个业务动作的第二步」，埋点沿用触发它的 action（见 useConfirm） -->
      <div class="absolute inset-0" data-track="dialog_cancel" :data-track-params="JSON.stringify({ action })" @click="confirmNo"></div>
      <div class="modal max-w-sm p-5">
        <h3 v-if="title" class="mb-2 text-[13.5px] font-semibold tracking-[-0.01em] text-ink" id="confirm-title">{{ title }}</h3>
        <p class="whitespace-pre-line text-[12.5px] leading-relaxed text-ink-2">{{ message }}</p>
        <div class="mt-6 flex justify-end gap-2">
          <button class="btn btn-ghost" data-track="dialog_cancel" :data-track-params="JSON.stringify({ action })" @click="confirmNo">
            {{ t('cancel') }}
          </button>
          <button class="btn btn-danger" data-track="dialog_confirm" :data-track-params="JSON.stringify({ action })" @click="confirmYes">
            {{ t('confirm') }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>
