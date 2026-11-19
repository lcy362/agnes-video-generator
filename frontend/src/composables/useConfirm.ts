import { ref } from 'vue'

// 全局确认弹窗单例状态（模块级，与 useToast 同模式）
const visible = ref(false)
const message = ref('')
const title = ref('')
// 触发本次确认的业务动作（稳定英文键，如 stop_task / delete_task）：
// 供 ConfirmModal 上报 dialog_confirm 时带上，避免所有确认按钮混成一个维度。
const action = ref('')
let resolver: ((v: boolean) => void) | null = null

export interface ConfirmOptions {
  title?: string
  /** 业务动作稳定键（非翻译文案），用于确认弹窗埋点归因 */
  action?: string
}

function confirmAsync(msg: string, opts: ConfirmOptions = {}): Promise<boolean> {
  message.value = msg
  title.value = opts.title || ''
  action.value = opts.action || ''
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
    action,
    confirmAsync,
    confirmYes: () => resolveConfirm(true),
    confirmNo: () => resolveConfirm(false),
  }
}
