import { ref } from 'vue'

export type ToastType = 'error' | 'success' | 'info'

const visible = ref(false)
const message = ref('')
const type = ref<ToastType>('error')
let timer: ReturnType<typeof setTimeout> | null = null

function showToast(msg: string, duration = 2500, t: ToastType = 'error') {
  message.value = msg
  type.value = t
  visible.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    visible.value = false
  }, duration)
}

export function useToast() {
  return { visible, message, type, showToast }
}
