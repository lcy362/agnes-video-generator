// 风格预设库（P0-1）：拉取系统/用户预设 + 保存/删除用户预设 + 本地最近使用
import { ref } from 'vue'
import * as api from '@/api'
import type { Preset } from '@/types'

const system = ref<Preset[]>([])
const user = ref<Preset[]>([])
const loaded = ref(false)

const RECENT_KEY = 'agnes_preset_recent'

function recents(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
  } catch {
    return []
  }
}

function markRecent(id: string) {
  const arr = recents().filter((x) => x !== id)
  arr.unshift(id)
  localStorage.setItem(RECENT_KEY, JSON.stringify(arr.slice(0, 20)))
}

async function loadPresets() {
  try {
    const d = await api.getPresets()
    system.value = (d && d.system) || []
    user.value = (d && d.user) || []
    loaded.value = true
  } catch {
    /* 静默：轮询/初始化失败不阻断表单 */
  }
}

async function savePreset(name: string, prompt: string): Promise<Preset> {
  const d = await api.savePreset(name, prompt)
  if (!d.ok) throw new Error(d.detail || 'save failed')
  // 重新拉取更新列表
  const fresh = await api.getPresets().catch(() => null)
  if (fresh) user.value = fresh.user || []
  return d
}

async function removePreset(id: string) {
  const d = await api.deletePreset(id)
  if (!d.ok) throw new Error(d.detail || 'delete failed')
  user.value = user.value.filter((p) => p.id !== id)
  return d
}

export function usePresets() {
  return {
    system,
    user,
    loaded,
    loadPresets,
    savePreset,
    removePreset,
    recents,
    markRecent,
  }
}