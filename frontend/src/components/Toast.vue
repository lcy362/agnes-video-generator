<script setup lang="ts">
import { computed } from 'vue'
import type { ToastType } from '@/composables/useToast'

const props = defineProps<{
  visible: boolean
  message: string
  type?: ToastType
}>()

// toast 用「暗底 + 语义色点」表达状态，避免整块高饱和背景在小尺寸下过于吵
const dotColor = computed(() => {
  switch (props.type) {
    case 'success':
      return 'var(--color-success)'
    case 'info':
      return 'var(--color-accent)'
    case 'error':
    default:
      return 'var(--color-danger)'
  }
})
</script>

<template>
  <transition
    enter-active-class="transition-all duration-200"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition-all duration-200"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="visible"
      class="fixed bottom-6 left-1/2 z-50 flex max-w-[85vw] -translate-x-1/2 items-start gap-2.5 rounded border px-4 py-2.5 text-[12.5px] leading-relaxed text-ink whitespace-pre-line"
      style="
        background: color-mix(in oklab, var(--color-paper-2) 96%, black);
        border-color: var(--color-rule-2);
        box-shadow: 0 20px 44px -22px rgb(0 0 0 / 0.8);
      "
      role="alert"
      aria-live="polite"
    >
      <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" :style="{ background: dotColor }"></span>
      <span>{{ message }}</span>
    </div>
  </transition>
</template>
