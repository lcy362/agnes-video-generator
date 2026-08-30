import { watch } from 'vue'

const DRAFT_PREFIX = 'form_draft:'

/**
 * 3.4：表单草稿保留——表单内容自动存 localStorage，切走/刷新后恢复；
 * 提交成功后 clear()。仅序列化 JSON 安全字段（File 等需在接入处过滤）。
 */
export function useDraft(key: string) {
  const storageKey = DRAFT_PREFIX + key

  function load(): Record<string, any> | null {
    try {
      const raw = localStorage.getItem(storageKey)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }

  function save(data: Record<string, any>) {
    try {
      localStorage.setItem(storageKey, JSON.stringify(data))
    } catch {
      /* 存储满/禁用时静默 */
    }
  }

  function clear() {
    try {
      localStorage.removeItem(storageKey)
    } catch {
      /* ignore */
    }
  }

  /** 监听源对象变化自动保存（pick 指定 JSON 安全字段，避免 File 等）。 */
  function autoSave(source: any, pick: (v: any) => Record<string, any>) {
    watch(source, (v) => save(pick(v)), { deep: true })
  }

  return { load, save, clear, autoSave }
}
