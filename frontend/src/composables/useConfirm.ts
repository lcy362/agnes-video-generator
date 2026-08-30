import { ref } from 'vue'

// 全局确认弹窗单例状态（模块级，与 useToast 同模式）
const visible = ref(false)
const message = ref('')
const title = ref('')
let resolver: ((v: boolean) => void) | null = null

export interface ConfirmOptions {
  title?: string
}

function confirmAsync(msg: string, opts: ConfirmOptions = {}): Promise<boolean> {
  message.value = msg
  title.value = opts.title || ''
  visible.value = true
  return new Promise((resolve) => {
    resolver = resolve
  })
}

function resolveConfirm(v: boolean) {
  visible.value = false
  if (resolver) {
    resolver(v)
    resolver = null
  }
}

export function useConfirm() {
  return {
    visible,
    message,
    title,
    confirmAsync,
    confirmYes: () => resolveConfirm(true),
    confirmNo: () => resolveConfirm(false),
  }
}
