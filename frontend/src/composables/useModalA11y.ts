import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

/**
 * 3.4：通用弹窗可访问性——ESC 关闭 + Tab focus trap + 关闭后焦点还原。
 *
 * 用法（组件根节点绑定 containerRef）：
 * ```vue
 * const { containerRef } = useModalA11y(visible, onClose)
 * <div v-if="visible" ref="containerRef" role="dialog">...</div>
 * ```
 */
export function useModalA11y(visible: Ref<boolean>, onClose: () => void) {
  const containerRef = ref<HTMLElement | null>(null)
  let previouslyFocused: HTMLElement | null = null

  function focusFirst() {
    if (!containerRef.value) return
    const el = containerRef.value.querySelector<HTMLElement>(
      '[autofocus], button, input, select, textarea, a[href]',
    )
    el?.focus?.()
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
      return
    }
    if (e.key !== 'Tab' || !containerRef.value) return
    const focusables = containerRef.value.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
    if (!focusables.length) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  function restoreFocus() {
    try {
      previouslyFocused?.focus?.()
    } catch {
      /* ignore */
    }
    previouslyFocused = null
  }

  watch(visible, (v) => {
    if (v) {
      previouslyFocused = document.activeElement as HTMLElement | null
      document.addEventListener('keydown', onKeydown)
      // 等待渲染后聚焦首个可聚焦元素
      requestAnimationFrame(focusFirst)
    } else {
      document.removeEventListener('keydown', onKeydown)
      restoreFocus()
    }
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown)
    restoreFocus()
  })

  return { containerRef }
}
