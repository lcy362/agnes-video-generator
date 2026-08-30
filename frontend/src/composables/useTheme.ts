import { ref, computed } from 'vue'
import { currentLang } from '@/i18n'

const THEME_MODES = ['system', 'light', 'dark'] as const
type ThemeMode = (typeof THEME_MODES)[number]

const THEME_ICON_PATHS: Record<ThemeMode, string> = {
  system: 'M8 4h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm-3 12h14',
  light: 'M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
  dark: 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z',
}

const THEME_LABELS: Record<string, Record<ThemeMode, string>> = {
  zh: { system: '主题：跟随系统', light: '主题：亮色', dark: '主题：暗色' },
  en: { system: 'Theme: System', light: 'Theme: Light', dark: 'Theme: Dark' },
}

const storedMode = ref<ThemeMode>('system')

function themeResolved(mode: ThemeMode): 'dark' | 'light' {
  if (mode === 'system') {
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    } catch {
      return 'dark'
    }
  }
  return mode
}

function themeStored(): ThemeMode {
  try {
    const v = localStorage.getItem('theme')
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    /* ignore */
  }
  return 'system'
}

function themeApply(mode: ThemeMode) {
  storedMode.value = mode
  try {
    localStorage.setItem('theme', mode)
  } catch {
    /* ignore */
  }
  document.documentElement.setAttribute('data-theme', themeResolved(mode))
}

const themeIcon = computed(() => THEME_ICON_PATHS[storedMode.value])

const themeLabel = computed(() => {
  const table = THEME_LABELS[currentLang.value] || THEME_LABELS.zh
  return table[storedMode.value]
})

function cycleTheme() {
  const idx = THEME_MODES.indexOf(storedMode.value)
  const next = THEME_MODES[(idx + 1) % THEME_MODES.length]
  themeApply(next)
}

// 3.4：system 模式下跟随系统切换（保存 mql 引用以便卸载时清理）
let themeMql: MediaQueryList | null = null
let themeMqlHandler: (() => void) | null = null

function initThemeListener() {
  if (!window.matchMedia || themeMqlHandler) return
  themeMql = window.matchMedia('(prefers-color-scheme: dark)')
  themeMqlHandler = () => {
    if (storedMode.value === 'system') themeApply('system')
  }
  themeMql.addEventListener('change', themeMqlHandler)
}

function disposeThemeListener() {
  if (themeMql && themeMqlHandler) {
    themeMql.removeEventListener('change', themeMqlHandler)
  }
  themeMql = null
  themeMqlHandler = null
}

export function useTheme() {
  return {
    storedMode,
    themeIcon,
    themeLabel,
    themeResolved,
    themeStored,
    themeApply,
    cycleTheme,
    initThemeListener,
    disposeThemeListener,
  }
}
