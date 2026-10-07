// 风格预设库（P0-1）：拉取系统/用户预设 + 保存/删除用户预设 + 本地最近使用
import { ref, computed } from 'vue'
import * as api from '@/api'
import type { Preset } from '@/types'

const system = ref<Preset[]>([])
const user = ref<Preset[]>([])
const loaded = ref(false)

// 表单打开时用于预填风格的默认预设（语言中性的英文画面 prompt，取代旧的硬编码中文默认值）。
// 若系统预设尚未加载或不存在该 id，回退到与 styles.json 中同一条一致的常量，保证预填确定且即时。
export const DEFAULT_STYLE_PRESET_ID = 'blockbuster'
const FALLBACK_DEFAULT_STYLE_PROMPT =
  'epic cinematic look, anamorphic lens flare, shallow depth of field, dramatic lighting, teal-and-orange color grading, high contrast, Hollywood blockbuster feel'

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

async function loadPresets(force = false) {
  if (loaded.value && !force) return
  try {
    const d = await api.getPresets()
    system.value = (d && d.system) || []
    user.value = (d && d.user) || []
    loaded.value = true
  } catch {
    /* 静默：轮询/初始化失败不阻断表单 */
  }
}

// 供表单预填与 PresetPicker 高亮当前项使用的默认风格 prompt（响应式：预设加载后自动切到真实条目）。
const defaultStylePrompt = computed(() => {
  const p = system.value.find((x) => x.id === DEFAULT_STYLE_PRESET_ID)
  return p?.prompt || FALLBACK_DEFAULT_STYLE_PROMPT
})

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
    defaultStylePrompt,
  }
}