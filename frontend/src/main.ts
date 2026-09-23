import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import { applyLanguage, currentLang } from './i18n'
import { useTheme } from './composables/useTheme'
import { useGa } from './composables/useGa'
import { installFetchLangHeader } from './api/fetchPatch'

// 初始化语言
applyLanguage(currentLang.value)

// v7.0（issue #64）：在所有 fetch 上注入 X-Agnes-UI-Lang，让后端按当前 UI 语言
// 返回用户可见消息（网络诊断、任务排队中、AI 修改失败等）。必须在任何 API 调用
// 之前安装，因此紧跟 applyLanguage 之后。
installFetchLangHeader()

// 初始化主题
const { themeApply, themeStored, initThemeListener } = useTheme()
themeApply(themeStored())
initThemeListener()

// 初始化 GA 与全局错误捕获
const { initGA, initErrorListeners } = useGa()
initGA()
initErrorListeners()

createApp(App).mount('#app')
