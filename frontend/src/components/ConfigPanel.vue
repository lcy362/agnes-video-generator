<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { t } from '@/i18n'
import { appState, getCollapsePrefs, setCollapsePref } from '@/store'
import { useConfig } from '@/composables/useConfig'
import { useVoice } from '@/composables/useVoice'
import { useGa } from '@/composables/useGa'
import { useVideoModelCaps } from '@/composables/useVideoModelCaps'
import { useToast } from '@/composables/useToast'

const { trackEvent, isGaOptedOut, setGaOptOut } = useGa()
const { showToast } = useToast()

// 3.4：匿名统计隐私开关（localStorage 'ga_opt_out'）
const gaOptOut = ref(isGaOptedOut())
function toggleGaOptOut() {
  setGaOptOut(gaOptOut.value)
}
const {
  apiKeyStatus,
  keyCount,
  keySource,
  keyList,
  saveMultiKeys,
  loadKeyInfo,
  removeKey,
  clearApiKey,
  modelSyncStatus,
  modelSaveStatus,
  modelErrorMsg,
  betaHintVisible,
  isBetaModel,
  isPaidModel,
  syncModels,
  saveModels,
  domainSaveStatus,
  domainErrorMsg,
  saveDomain,
  toggleWatermark,
  isRegression,
  wsDisplayName,
  renderWorkspaces,
  activateWorkspace,
  removeWorkspaceEntry,
  browseDirectory,
  addWorkspace,
} = useConfig()

// v6.2：视频模型能力（选模型阶段差异说明）
const vmCaps = useVideoModelCaps()

// 模板渲染 helper（vue-tsc 严格模式：避免模板箭头函数隐式 any）
function vmDurationsLabel(ds: unknown[]): string {
  return (Array.isArray(ds) ? ds : []).map((x) => String(x) + 's').join(' / ')
}
function vmPixelLabel(opts: { value: string }[]): string {
  return (Array.isArray(opts) ? opts : []).map((o) => o.value).join(' / ')
}
function vmRatioListText(item: { model: string; caps: Record<string, any> }): string {
  const res = item.caps?.resolution || {}
  const ratios = Array.isArray(res.ratios) ? res.ratios : []
  return ratios.map((r: string) => vmCaps.ratioWHText(r, item.model)).join(' / ')
}

// 折叠状态（5 个配置面板）
const collapsed = reactive<Record<string, boolean>>({
  apikey: false,
  model: false,
  domain: false,
  workspace: false,
  privacy: true,
})

function initCollapse() {
  const prefs = getCollapsePrefs()
  const keys = ['apikey', 'model', 'domain', 'workspace', 'privacy']
  keys.forEach((k) => {
    const manual = prefs[k + '_manual']
    if (manual !== undefined) {
      collapsed[k] = manual
    }
  })
}

function toggleConfigPanel(section: string) {
  collapsed[section] = !collapsed[section]
  setCollapsePref(section + '_manual', collapsed[section])
}

// API Key 输入
const apiKeyInput = ref('')
// 是否已有 Key（env 或 config）：有 Key 时输入框变「添加 Key」追加语义
const hasApiKey = computed(() => apiKeyStatus.value !== 'none')

// 模型下拉展示：付费模型 → "名称（付费）"；beta 模型 → "名称（内测）"；其余 → 名称
function modelDisplayLabel(m: string): string {
  if (isPaidModel(m)) return m + t('modelPaidTag')
  if (isBetaModel(m)) return m + t('modelBetaTag')
  return m
}

async function onSaveApiKey() {
  const key = apiKeyInput.value.trim()
  if (!key) {
    showToast(t('enterApiKey'), 3500)
    return
  }
  // 多 Key 输入框：按换行/逗号拆分保存（单个 Key 同样适用）
  const ok = await saveMultiKeys(key)
  if (ok) {
    apiKeyInput.value = ''
  }
}

// 页面加载时刷新 Key 数量/来源展示
loadKeyInfo()

// 工作区
const workspacePath = ref('')
const workspaceName = ref('')

async function onBrowse() {
  const path = await browseDirectory()
  if (path) workspacePath.value = path
}

async function onAddWorkspace() {
  await addWorkspace(workspacePath.value.trim(), workspaceName.value.trim())
  workspacePath.value = ''
  workspaceName.value = ''
}

initCollapse()
</script>

<template>
  <!-- API Key -->
  <div class="glass-card rounded-2xl mb-6 overflow-hidden transition-all duration-300">
    <div
      v-if="collapsed.apikey"
      class="flex items-center justify-between px-6 py-3 cursor-pointer hover:bg-paper-3 transition"
      role="button"
      tabindex="0"
      :aria-expanded="!collapsed.apikey"
      @click="toggleConfigPanel('apikey')"
    >
      <div class="flex items-center gap-3">
        <span class="text-sm">🔑</span>
        <span class="text-sm text-muted">
          <span class="text-ink-2 font-medium">{{ t('apiKeyTitle') }}</span>
          <span class="text-muted mx-2">·</span>
          <span :class="apiKeyStatus !== 'none' ? 'text-green-400' : 'text-muted'">
            {{ apiKeyStatus === 'env' ? t('apiKeyFromEnv') : apiKeyStatus === 'configured' ? t('apiKeyConfigured') : t('apiKeyNotConfigured') }}
          </span>
        </span>
      </div>
      <span class="text-muted text-xs">▶</span>
    </div>
    <div v-else class="p-6 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-accent">{{ t('apiKeyTitle') }}</h2>
        <div class="flex items-center gap-2">
          <span
            class="text-xs px-2 py-1 rounded-full"
            :class="apiKeyStatus !== 'none' ? 'bg-green-900 text-green-300' : 'bg-paper-2 text-muted'"
          >
            {{ apiKeyStatus === 'env' ? t('apiKeyFromEnv') : apiKeyStatus === 'configured' ? t('apiKeyConfigured') : t('apiKeyNotConfigured') }}
          </span>
          <button class="text-xs text-muted hover:text-ink-2 transition px-2 py-1 rounded" @click="toggleConfigPanel('apikey')">▲</button>
        </div>
      </div>
      <div class="flex gap-3 items-start">
        <textarea
          v-model="apiKeyInput"
          rows="2"
          :placeholder="hasApiKey ? t('apiKeyAppendPlaceholder') : t('apiKeyPlaceholder')"
          class="flex-1 glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted resize-y"
        ></textarea>
        <button
          class="px-5 py-2.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition whitespace-nowrap"
          @click="onSaveApiKey"
        >
          {{ hasApiKey ? t('addKey') : t('save') }}
        </button>
        <button
          v-if="apiKeyStatus !== 'none'"
          class="px-5 py-2.5 bg-red-600/80 hover:bg-red-500 rounded-lg text-sm font-medium transition whitespace-nowrap"
          @click="clearApiKey"
        >
          {{ t('clear') }}
        </button>
      </div>
      <div v-if="keyCount > 0" class="mt-2 flex items-center gap-2 flex-wrap">
        <span class="text-xs px-2 py-0.5 rounded-full bg-green-900 text-green-300">
          {{ t('keyCountLabel') }}: {{ keyCount }} <span class="opacity-70">({{ keySource }})</span>
        </span>
        <span v-if="keyCount > 1" class="text-xs px-2 py-0.5 rounded-full bg-blue-900 text-blue-300">
          {{ t('multiKeyActive') }}
        </span>
      </div>
      <!-- Key 列表：后端掩码展示 + 来源 + 按稳定 id 单个移除 -->
      <div v-if="keyList.length > 0" class="mt-3 space-y-1.5">
        <div
          v-for="(item, idx) in keyList"
          :key="item.id + idx"
          class="flex items-center gap-2 rounded-lg px-3 py-1.5 bg-paper-3/70 text-xs"
        >
          <code class="flex-1 font-mono text-ink-2 truncate">{{ item.mask }}</code>
          <span
            class="px-1.5 py-0.5 rounded text-[10px] uppercase"
            :class="item.source === 'env' ? 'bg-amber-900/60 text-amber-300' : 'bg-paper-3 text-muted'"
          >{{ item.source === 'env' ? t('keySrcEnv') : t('keySrcConfig') }}</span>
          <button
            v-if="item.source !== 'env'"
            class="text-red-300 hover:text-red-200 transition"
            :title="t('removeKeyBtn')"
            @click="removeKey(item.id)"
          >
            ✕
          </button>
          <span v-else class="text-muted/50" :title="t('keySrcEnvHint')">•</span>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 mt-3 text-xs">
        <a href="https://platform.agnes-ai.com" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">🚀 {{ t('apiKeyGetLink') }}</a>
        <a href="https://video.lichuanyang.top/guides/api-key" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">📖 {{ t('apiKeyGuideLink') }}</a>
        <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">⚡ {{ t('apiKeyDemoLink') }}</a>
      </div>
    </div>
  </div>

  <!-- 模型选择 -->
  <div class="glass-card rounded-2xl mb-6 overflow-hidden transition-all duration-300">
    <div
      v-if="collapsed.model"
      class="flex items-center justify-between px-6 py-3 cursor-pointer hover:bg-paper-3 transition"
      role="button"
      tabindex="0"
      @click="toggleConfigPanel('model')"
    >
      <div class="flex items-center gap-3">
        <span class="text-sm">🧠</span>
        <span class="text-sm text-muted">
          <span class="text-ink-2 font-medium">{{ t('modelTitle') }}</span>
          <span class="text-muted mx-2">·</span>
          <span v-if="appState.models.text || appState.models.image || appState.models.video" class="text-muted">
            {{ t('modelTagText') }} {{ appState.models.text }} {{ t('modelTagImage') }} {{ appState.models.image }} {{ t('modelTagVideo') }} {{ appState.models.video }}
          </span>
          <span v-else class="text-muted">—</span>
        </span>
      </div>
      <span class="text-muted text-xs">▶</span>
    </div>
    <div v-else class="p-6 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-accent">{{ t('modelTitle') }}</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-1 rounded-full bg-paper-2 text-muted">{{ t('modelSyncIdle') }}</span>
          <button class="text-xs text-muted hover:text-ink-2 transition px-2 py-1 rounded" @click="toggleConfigPanel('model')">▲</button>
        </div>
      </div>
      <p class="text-xs text-muted mb-4">{{ t('modelHint') }}</p>
      <div class="space-y-3">
        <div>
          <label class="block text-xs text-muted mb-1">{{ t('modelTextLabel') }}</label>
          <div class="flex gap-3">
            <select v-model="appState.models.text" class="flex-1 glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
              <option v-for="m in appState.modelListCache.text" :key="m" :value="m">{{ modelDisplayLabel(m) }}</option>
            </select>
            <button class="px-4 py-2.5 bg-paper-3 hover:bg-paper-3 rounded-lg text-sm font-medium transition whitespace-nowrap" @click="syncModels">
              {{ t('modelSync') }}
            </button>
          </div>
          <p v-if="betaHintVisible" class="text-xs text-accent mt-1.5">{{ t('modelBetaHint') }}</p>
          <p v-if="isPaidModel(appState.models.text)" class="text-xs text-amber-400 mt-1.5">{{ t('modelPaidHint') }}</p>
        </div>
        <div>
          <label class="block text-xs text-muted mb-1">{{ t('modelImageLabel') }}</label>
          <select v-model="appState.models.image" disabled class="flex-1 glass-input rounded-lg px-3 py-2.5 text-sm text-ink opacity-50 cursor-not-allowed"></select>
        </div>
        <!-- v6.2：开放视频模型选择 + 三模型差异说明 -->
        <div>
          <label class="block text-xs text-muted mb-1">{{ t('modelVideoLabel') }} (v6.2)</label>
          <select v-model="appState.models.video" class="flex-1 glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option v-for="m in appState.modelListCache.video" :key="m" :value="m">{{ modelDisplayLabel(m) }}</option>
          </select>
          <p v-if="vmCaps.isPaidTag(appState.models.video)" class="text-xs text-amber-400 mt-1.5">{{ t('modelPaidHint') }}</p>
          <p v-else-if="vmCaps.priceText(appState.models.video)" class="text-xs text-green-400 mt-1.5">{{ vmCaps.priceText(appState.models.video) }}</p>

          <!-- 三模型差异对比（选模型阶段详细说明） -->
          <div v-if="vmCaps.allCapabilities().length > 0" class="mt-3 rounded-lg bg-paper-3/60 p-3">
            <p class="text-xs font-medium text-ink-2 mb-2">{{ t('vmDiffTitle') }}</p>
            <div class="overflow-x-auto">
              <table class="w-full text-[11px] leading-relaxed">
                <thead>
                  <tr class="text-muted">
                    <th class="text-left font-normal pr-3 py-0.5">{{ t('vmColCapability') }}</th>
                    <th v-for="item in vmCaps.allCapabilities()" :key="item.model" class="text-left font-normal px-2 py-0.5 whitespace-nowrap">
                      <span :class="item.model === appState.models.video ? 'text-accent' : ''">{{ item.caps.label }}</span>
                      <span v-if="item.caps.price === 'paid'" class="text-amber-400"> {{ t('vmTagPaid') }}</span>
                      <span v-else-if="item.caps.price === 'free'" class="text-green-400"> {{ t('vmTagFree') }}</span>
                    </th>
                  </tr>
                </thead>
                <tbody class="text-ink-2">
                  <tr>
                    <td class="text-muted pr-3 py-0.5">{{ t('vmColPrice') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'p' + item.model" class="px-2 py-0.5" :class="item.caps.price === 'paid' ? 'text-amber-400' : 'text-green-400'">
                      {{ vmCaps.priceText(item.model) }}
                    </td>
                  </tr>
                  <tr>
                    <td class="text-muted pr-3 py-0.5">{{ t('vmColMode') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'m' + item.model" class="px-2 py-0.5">
                      {{ vmCaps.modeOptions(item.model).map((x) => x.label).join(' · ') }}
                    </td>
                  </tr>
                  <tr>
                    <td class="text-muted pr-3 py-0.5">{{ t('vmColDuration') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'d' + item.model" class="px-2 py-0.5">
                      {{ vmDurationsLabel(item.caps.durations) }}
                    </td>
                  </tr>
                  <tr>
                    <td class="text-muted pr-3 py-0.5">{{ t('vmColResolution') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'r' + item.model" class="px-2 py-0.5">
                      <template v-if="item.caps.resolution && item.caps.resolution.type === 'pixels'">
                        {{ vmPixelLabel(item.caps.resolution.options) }}
                      </template>
                      <template v-else-if="item.caps.resolution">
                        {{ vmRatioListText(item) }}<span v-if="item.caps.resolution.sizes.length > 1">（{{ item.caps.resolution.sizes.join(' / ') }}）</span>
                      </template>
                    </td>
                  </tr>
                  <tr>
                    <td class="text-muted pr-3 py-0.5">{{ t('vmColNegative') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'n' + item.model" class="px-2 py-0.5">
                      {{ item.caps.supports_negative ? t('vmYes') : t('vmNo') }}
                    </td>
                  </tr>
                  <tr>
                    <td class="text-muted pr-3 py-0.5">{{ t('vmColRefVideo') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'v' + item.model" class="px-2 py-0.5">
                      {{ item.caps.supports_ref_video ? t('vmYes') : t('vmNo') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="text-xs text-muted mt-2">{{ vmCaps.descOf(appState.models.video) }}</p>
          </div>
        </div>
      </div>
      <div class="flex gap-3 mt-4">
        <button class="px-5 py-2.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition" @click="saveModels">{{ t('save') }}</button>
        <span v-if="modelSaveStatus === 'ok'" class="self-center text-xs text-green-400">{{ t('modelSaved') }}</span>
        <span v-if="modelSaveStatus === 'error'" class="self-center text-xs text-red-400">{{ modelErrorMsg }}</span>
      </div>
    </div>
  </div>

  <!-- 域名配置 -->
  <div class="glass-card rounded-2xl mb-6 overflow-hidden transition-all duration-300">
    <div
      v-if="collapsed.domain"
      class="flex items-center justify-between px-6 py-3 cursor-pointer hover:bg-paper-3 transition"
      role="button"
      tabindex="0"
      @click="toggleConfigPanel('domain')"
    >
      <div class="flex items-center gap-3">
        <span class="text-sm">🌐</span>
        <span class="text-sm text-muted">
          <span class="text-ink-2 font-medium">{{ t('domainTitle') }}</span>
          <span class="text-muted mx-2">·</span>
          <span :class="appState.agnesDomain === 'cn' ? 'text-green-400' : 'text-muted'">apihub.agnes-ai.{{ appState.agnesDomain }}</span>
        </span>
      </div>
      <span class="text-muted text-xs">▶</span>
    </div>
    <div v-else class="p-6 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-accent">{{ t('domainTitle') }}</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-1 rounded-full" :class="appState.agnesDomain === 'cn' ? 'bg-green-900/40 text-green-300' : 'bg-paper-2 text-muted'">
            apihub.agnes-ai.{{ appState.agnesDomain }}
          </span>
          <button class="text-xs text-muted hover:text-ink-2 transition px-2 py-1 rounded" @click="toggleConfigPanel('domain')">▲</button>
        </div>
      </div>
      <p class="text-xs text-muted mb-4">{{ t('domainHint') }}</p>
      <div class="space-y-3">
        <label class="flex items-center gap-3 glass-input rounded-lg px-4 py-3 cursor-pointer hover:border-blue-500/40 transition">
          <input v-model="appState.agnesDomain" type="radio" name="agnes-domain" value="com" class="accent-blue-500 w-4 h-4 cursor-pointer" />
          <div>
            <span class="text-sm text-ink-2 font-medium">apihub.agnes-ai.com</span>
            <span class="text-xs text-muted ml-2">{{ t('domainComLabel') }}</span>
          </div>
        </label>
        <label class="flex items-center gap-3 glass-input rounded-lg px-4 py-3 cursor-pointer hover:border-blue-500/40 transition">
          <input v-model="appState.agnesDomain" type="radio" name="agnes-domain" value="cn" class="accent-blue-500 w-4 h-4 cursor-pointer" />
          <div>
            <span class="text-sm text-ink-2 font-medium">apihub.agnes-ai.cn</span>
            <span class="text-xs text-muted ml-2">{{ t('domainCnLabel') }}</span>
          </div>
        </label>
      </div>
      <div class="flex gap-3 mt-4">
        <button class="px-5 py-2.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition" @click="saveDomain">{{ t('save') }}</button>
        <span v-if="domainSaveStatus === 'ok'" class="self-center text-xs text-green-400">{{ t('domainSaved') }}</span>
        <span v-if="domainSaveStatus === 'error'" class="self-center text-xs text-red-400">{{ domainErrorMsg }}</span>
      </div>
    </div>
  </div>

  <!-- 工作目录 -->
  <div class="glass-card rounded-2xl mb-6 overflow-hidden transition-all duration-300">
    <div
      v-if="collapsed.workspace"
      class="flex items-center justify-between px-6 py-3 cursor-pointer hover:bg-paper-3 transition"
      role="button"
      tabindex="0"
      @click="toggleConfigPanel('workspace')"
    >
      <div class="flex items-center gap-3">
        <span class="text-sm">📁</span>
        <span class="text-sm text-muted">
          <span class="text-ink-2 font-medium">{{ t('workspaceTitle') }}</span>
          <span class="text-muted mx-2">·</span>
          <span :class="appState.activeWorkspace ? 'text-green-400' : 'text-muted'">
            {{ appState.activeWorkspace ? (appState.workspaces.find((w) => w.path === appState.activeWorkspace)?.name || appState.activeWorkspace) : t('workspaceNone') }}
          </span>
        </span>
      </div>
      <span class="text-muted text-xs">▶</span>
    </div>
    <div v-else class="p-6 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-accent">{{ t('workspaceTitle') }}</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-1 rounded-full" :class="appState.activeWorkspace ? 'bg-green-900 text-green-300' : 'bg-paper-2 text-muted'">
            {{ appState.activeWorkspace ? t('workspaceActive') : t('workspaceNone') }}
          </span>
          <button class="text-xs text-muted hover:text-ink-2 transition px-2 py-1 rounded" @click="toggleConfigPanel('workspace')">▲</button>
        </div>
      </div>
      <div v-if="isRegression" class="mb-3 text-xs text-accent bg-accent/15/30 rounded-lg px-3 py-2">{{ t('workspaceRegressionHint') }}</div>
      <div v-if="appState.activeWorkspace" class="mb-3 glass-input rounded-lg px-4 py-2.5">
        <p class="text-xs text-muted mb-0.5">{{ t('workspaceCurrentActive') }}</p>
        <p class="text-sm text-green-300 font-medium">{{ appState.workspaces.find((w) => w.path === appState.activeWorkspace)?.name || appState.activeWorkspace }}</p>
        <p class="text-xs text-muted font-mono truncate">{{ appState.activeWorkspace }}</p>
      </div>
      <div class="flex gap-3 mb-4">
        <input v-model="workspacePath" :placeholder="t('workspacePathPlaceholder')" readonly class="flex-1 glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
        <input v-model="workspaceName" :placeholder="t('workspaceNamePlaceholder')" class="w-40 glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted" />
        <button class="px-4 py-2.5 bg-paper-3 hover:bg-paper-3 rounded-lg text-sm font-medium transition" @click="onBrowse">{{ t('workspaceBrowse') }}</button>
        <button class="px-5 py-2.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition" @click="onAddWorkspace">{{ t('workspaceAdd') }}</button>
      </div>
      <div class="flex items-center gap-2 mb-2">
        <h3 class="text-sm font-medium text-muted">{{ t('workspaceListTitle') }}</h3>
        <span class="text-xs text-muted">{{ t('workspaceListHint') }}</span>
      </div>
      <div class="space-y-2">
        <div
          v-for="ws in appState.workspaces"
          :key="ws.path"
          class="flex items-center justify-between glass-input rounded-lg px-4 py-2.5"
        >
          <div class="flex-1 min-w-0">
            <p class="text-sm text-ink truncate">{{ wsDisplayName(ws) }}</p>
            <p class="text-xs text-muted font-mono truncate">{{ ws.path }}</p>
          </div>
          <div class="flex gap-2 ml-3">
            <span v-if="ws.path === appState.activeWorkspace" class="text-xs px-2 py-1 rounded-full bg-green-900 text-green-300">{{ t('workspaceActiveBadge') }}</span>
            <button v-else class="px-3 py-1 bg-green-600 hover:bg-green-500 rounded-lg text-xs font-medium transition" @click="activateWorkspace(ws.path)">
              {{ t('workspaceActivate') }}
            </button>
            <button v-if="!ws.is_default" class="px-3 py-1 bg-red-600/80 hover:bg-red-500 rounded-lg text-xs font-medium transition" @click="removeWorkspaceEntry(ws.path)">
              {{ t('workspaceRemove') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 隐私设置（3.4：GA4 配置开关） -->
  <div class="glass-card rounded-2xl mb-6 overflow-hidden transition-all duration-300">
    <div
      v-if="collapsed.privacy"
      class="flex items-center justify-between px-6 py-3 cursor-pointer hover:bg-paper-3 transition"
      role="button"
      tabindex="0"
      :aria-expanded="!collapsed.privacy"
      @click="toggleConfigPanel('privacy')"
    >
      <div class="flex items-center gap-3">
        <span class="text-sm">🔒</span>
        <span class="text-sm text-muted">
          <span class="text-ink-2 font-medium">{{ t('privacyTitle') }}</span>
          <span class="text-muted mx-2">·</span>
          <span :class="gaOptOut ? 'text-green-400' : 'text-muted'">
            {{ gaOptOut ? t('gaStatOff') : t('gaStatOn') }}
          </span>
        </span>
      </div>
      <span class="text-muted text-xs">▶</span>
    </div>
    <div v-else class="p-6 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-accent">{{ t('privacyTitle') }}</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs px-2 py-1 rounded-full" :class="gaOptOut ? 'bg-green-900 text-green-300' : 'bg-paper-2 text-muted'">
            {{ gaOptOut ? t('gaStatOff') : t('gaStatOn') }}
          </span>
          <button class="text-xs text-muted hover:text-ink-2 transition px-2 py-1 rounded" @click="toggleConfigPanel('privacy')">▲</button>
        </div>
      </div>
      <label class="flex items-start gap-3 cursor-pointer select-none">
        <input v-model="gaOptOut" type="checkbox" class="mt-1 accent-red-500" @change="toggleGaOptOut" />
        <span>
          <span class="text-sm text-ink font-medium block">{{ t('gaOptOutLabel') }}</span>
          <span class="text-xs text-muted block mt-0.5">{{ t('gaOptOutHint') }}</span>
        </span>
      </label>

      <!-- 上报信息透明化说明（3.4：采集范围 + 隐私承诺） -->
      <div class="mt-4 rounded-lg bg-paper-3/60 p-4 text-xs leading-relaxed">
        <p class="font-medium text-ink-2 mb-2">{{ t('gaReportTitle') }}</p>
        <ul class="list-disc pl-4 space-y-1 text-muted">
          <li>{{ t('gaReportItem1') }}</li>
          <li>{{ t('gaReportItem2') }}</li>
          <li>{{ t('gaReportItem3') }}</li>
          <li>{{ t('gaReportItem4') }}</li>
        </ul>
        <p class="mt-3 pt-3 border-t border-rule/40 font-medium text-ink-2">{{ t('gaNeverUploadTitle') }}</p>
        <p class="text-muted">{{ t('gaNeverUploadText') }}</p>
      </div>
    </div>
  </div>
</template>
