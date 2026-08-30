<script setup lang="ts">
import { computed } from 'vue'
import type { ToastType } from '@/composables/useToast'

const props = defineProps<{
  visible: boolean
  message: string
  type?: ToastType
}>()

const styleClass = computed(() => {
  switch (props.type) {
    case 'success':
      return 'bg-emerald-600 text-white'
    case 'info':
      return 'bg-sky-600 text-white'
    case 'error':
    default:
      return 'bg-red-600 text-white'
  }
})
</script>

<template>
  <transition
    enter-active-class="transition-all duration-300"
    enter-from-class="opacity-0 translate-y-4"
    enter-to-class="opacity-100 translate-y-0"
    leave-active-class="transition-all duration-300"
    leave-from-class="opacity-100 translate-y-0"
    leave-to-class="opacity-0 translate-y-4"
  >
    <div
      v-if="visible"
      class="fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-xl text-sm font-medium border border-rule z-50 shadow-lg"
      :class="styleClass"
      role="alert"
      aria-live="polite"
    >
      {{ message }}
    </div>
  </transition>
</template>
