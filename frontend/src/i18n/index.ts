import { ref, reactive, computed } from 'vue'
// 1.8：i18n 懒加载——zh/en 静态预载（首屏用），其余 20 语言经
// import.meta.glob 动态分包，切换时按需加载（首屏 JS 体积显著下降）
import zh from './langs/zh.json'
import en from './langs/en.json'

// 支持的语言列表（与 lang-selector 选项一致）
export const LANGS: { code: string; label: string }[] = [
  { code: 'zh', label: '🇨🇳 中文' },
  { code: 'en', label: '🇺🇸 English' },
  { code: 'ru', label: '🇷🇺 Русский' },
  { code: 'ja', label: '🇯🇵 日本語' },
  { code: 'ko', label: '🇰🇷 한국어' },
  { code: 'ms', label: '🇲🇾 Bahasa Melayu' },
  { code: 'id', label: '🇮🇩 Bahasa Indonesia' },
  { code: 'de', label: '🇩🇪 Deutsch' },
  { code: 'fr', label: '🇫🇷 Français' },
  { code: 'nl', label: '🇳🇱 Nederlands' },
  { code: 'es', label: '🇪🇸 Español' },
  { code: 'pt', label: '🇵🇹 Português' },
  { code: 'it', label: '🇮🇹 Italiano' },
  { code: 'tr', label: '🇹🇷 Türkçe' },
  { code: 'vi', label: '🇻🇳 Tiếng Việt' },
  { code: 'th', label: '🇹🇭 ไทย' },
  { code: 'hi', label: '🇮🇳 हिन्दी' },
  { code: 'bn', label: '🇧🇩 বাংলা' },
  { code: 'tl', label: '🇵🇭 Tagalog' },
  { code: 'ar', label: '🇸🇦 العربية' },
  { code: 'fa', label: '🇮🇷 فارسی' },
  { code: 'ur', label: '🇵🇰 اردو' },
]

const RTL_LANGS = ['ar', 'fa', 'ur']

// 已加载的语言数据（zh/en 预载；其余按需加载后填入，响应式触发 UI 更新）
const langData = reactive<Record<string, Record<string, string>>>({ zh, en })

const currentLang = ref('zh')

function initLang(): string {
  try {
    return localStorage.getItem('lang') || 'zh'
  } catch {
    return 'zh'
  }
}

export function t(key: string): string {
  const lang = currentLang.value
  const data = langData[lang]
  const val = (data && data[key]) ?? (langData['zh'] && langData['zh'][key]) ?? key
  return val
}

export function applyLanguage(lang: string) {
  currentLang.value = lang || 'zh'
  try {
    localStorage.setItem('lang', currentLang.value)
  } catch {
    /* ignore */
  }
  document.documentElement.lang = currentLang.value === 'zh' ? 'zh-CN' : currentLang.value
  document.documentElement.dir = RTL_LANGS.includes(currentLang.value) ? 'rtl' : 'ltr'
}

// 1.8：懒加载语言包（import.meta.glob 静态收集 langs/*.json 为独立 chunk）
const langLoaders = import.meta.glob('./langs/*.json')
const loadingLang = ref<string | null>(null)

async function loadLang(lang: string): Promise<void> {
  if (!lang || langData[lang]) return
  const loader = langLoaders[`./langs/${lang}.json`]
  if (!loader) return
  loadingLang.value = lang
  try {
    const mod = (await loader()) as { default: Record<string, string> }
    langData[lang] = mod.default
  } catch (e) {
    // 加载失败：t() 自动回退 zh，无需阻断
  } finally {
    loadingLang.value = null
  }
}

// 转义动态文本，防止 innerHTML 注入（XSS 防护）
export function escapeHtml(s: unknown): string {
  if (s === null || s === undefined) return ''
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function useI18n() {
  const lang = computed(() => currentLang.value)

  function switchLang(l: string) {
    applyLanguage(l)
    // 1.8：目标语言未加载则异步加载（加载期间 t() 回退 zh，完成后响应式更新）
    void loadLang(l)
  }

  // 判断某值是否属于某 i18n key 的默认值集合（用于语言切换时刷新默认值）
  function isDefaultValue(value: string, i18nKey: string): boolean {
    const allDefaults = new Set(Object.values(langData).map((l) => l[i18nKey]).filter(Boolean))
    return allDefaults.has(value) || value === ''
  }

  return { lang, currentLang, t, switchLang, isDefaultValue, applyLanguage, loadingLang, loadLang }
}

// 初始化语言（模块加载后立即同步）
currentLang.value = initLang()
// 1.8：若存储语言非 zh/en（如上次选了日语），首屏异步加载，避免回退中文
void loadLang(currentLang.value)

export { currentLang }
