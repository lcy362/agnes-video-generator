<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { t } from '@/i18n'
import { appState, getCollapsePrefs, setCollapsePref } from '@/store'
import { useConfig } from '@/composables/useConfig'
import { useVoice } from '@/composables/useVoice'
import { useGa } from '@/composables/useGa'
import { useVideoModelCaps } from '@/composables/useVideoModelCaps'
import { useToast } from '@/composables/useToast'
import { useModalA11y } from '@/composables/useModalA11y'
import { GITHUB_REPO } from '@/utils/feedback'

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
  saveKeyDomain,
  detectKeyDomains,
  detectingKeys,
  clearApiKey,
  modelSyncStatus,
  modelSaveStatus,
  modelErrorMsg,
  betaHintVisible,
  isBetaModel,
  isPaidModel,
  syncModels,
  saveModels,
  providerName,
  providerApi,
  providerBaseUrl,
  providerApiKey,
  providerTestBusy,
  providerSaveStatus,
  providerErrorMsg,
  loadTextProviders,
  saveTextProvider,
  deleteTextProvider,
  testTextProvider,
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

// 域名展示：key → 接入端点。cn 为国内站 api.agnes-ai.cn，com 为国际站 apihub.agnes-ai.com，
// cn_bak 为国内站备用 apihub.agnes-ai.cn（官方文档未提及、可能下线，接受国际站 key）
const DOMAIN_ENTRIES = [
  { key: 'com', url: 'apihub.agnes-ai.com', labelKey: 'domainComLabel' },
  { key: 'cn', url: 'api.agnes-ai.cn', labelKey: 'domainCnLabel' },
  { key: 'cn_bak', url: 'apihub.agnes-ai.cn', labelKey: 'domainCnBakLabel' },
]
function domainEntry(root = appState.agnesDomain) {
  return DOMAIN_ENTRIES.find((d) => d.key === root) || DOMAIN_ENTRIES[0]
}
function displayDomain(root = appState.agnesDomain): string {
  return domainEntry(root).url
}
// per-key 域名下拉展示：给定域名后缀返回其 URL（未绑定/未知返回空串）
function keyDomainUrl(root?: string): string {
  if (!root) return ''
  const e = DOMAIN_ENTRIES.find((d) => d.key === root)
  return e ? e.url : ''
}
// 保存某 Key 的域名（下拉 change 触发；空值清除绑定 → 回退全局域名）
async function onKeyDomainChange(item: any, domain: string) {
  await saveKeyDomain(item.id, domain)
}

// 折叠状态（4 个配置面板）
const collapsed = reactive<Record<string, boolean>>({
  apikey: false,
  model: false,
  workspace: false,
  privacy: true,
})

function initCollapse() {
  const prefs = getCollapsePrefs()
  const keys = ['apikey', 'model', 'workspace', 'privacy']
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

// ── 文本模型供应商（v7.0）──
// 合并文本模型下拉：agnes（modelListCache.text）在前，随后为各自定义供应商模型（带前缀标注）
function providerDisplayName(p: any): string {
  return (p && (p.display_name || p.provider)) || p?.provider || ''
}
function providerApiLabel(p: any): string {
  const api = p?.api || ''
  return api === 'anthropic-messages' ? t('providerApiAnthropic') : api === 'openai-completions' ? t('providerApiOpenai') : api
}
// 供应商管理分节列表：恒含内置 agnes（缺位补 front）+ 自定义供应商
const manageProviders = computed(() => {
  const list = [...(appState.textProviders || [])]
  const hasAgnes = list.some((p: any) => p.builtin || p.provider === 'agnes')
  if (!hasAgnes) {
    list.unshift({ provider: 'agnes', display_name: 'Agnes', api: 'openai-completions', base_url: '', api_key: '', models: [], builtin: true })
  }
  return list
})
// agnes 的 Key 状态文案（列表行展示）
function agnesApiKeyText(): string {
  if (apiKeyStatus.value === 'env') return t('apiKeyFromEnv')
  if (apiKeyStatus.value === 'configured') return t('apiKeyConfigured')
  return t('apiKeyNotConfigured')
}
// 当前是否处于「编辑自定义供应商」态（false = 新增 或 agnes）
const isEditCustom = computed(() => editingProvider.value && editingProvider.value !== 'agnes')
// 弹窗标题：按模式区分（新增 / 编辑自定义 / 编辑 agnes）
const modalTitle = computed(() => {
  if (editingProvider.value === 'agnes') return t('providerAgnesTitle')
  if (editingProvider.value) return t('providerEditTitle')
  return t('providerAddTitle')
})

// 第一级「供应商」下拉：agnes（内置）+ 自定义供应商
const textProviderOptions = computed(() => {
  const opts: { key: string; label: string }[] = []
  const list = appState.textProviders || []
  const hasAgnes = list.some((p: any) => p.provider === 'agnes')
  // 后端列表通常已含内置 agnes（builtin）；缺失时才补一 front，避免重复
  if (!hasAgnes) opts.push({ key: 'agnes', label: t('providerBuiltinAgnes') })
  list.forEach((p: any) => {
    opts.push({ key: p.provider, label: providerDisplayName(p) || p.provider })
  })
  return opts
})
// 当前所选供应商（'' = agnes）；切换时自动选中该供应商第一个模型
const textProviderComposite = computed<string>({
  get() {
    return appState.models.text_provider || 'agnes'
  },
  set(val: string) {
    const cur = appState.models.text_provider || 'agnes'
    if (val === cur) return
    appState.models.text_provider = val === 'agnes' ? '' : val
    appState.textProviderSelected = val
    const models = textModelsForProvider(val)
    if (models.length > 0) appState.models.text = models[0]
  },
})
// 某供应商的模型列表（agnes → 内置列表；自定义 → providerModelCache）
function textModelsForProvider(provider: string): string[] {
  if (provider === 'agnes') return appState.modelListCache.text || []
  return appState.providerModelCache[provider] || []
}
// 第二级「模型」下拉：依据所选供应商过滤
const textModelOptions = computed(() => textModelsForProvider(textProviderComposite.value))
// 供应商新增表单：拉取候选模型（不落盘）
async function onFetchProviderModels() {
  const editingProviderId =
    editingProvider.value && editingProvider.value !== 'agnes' ? editingProvider.value : ''
  const payload: any = {
    base_url: providerBaseUrl.value.trim(),
    api_key: providerApiKey.value.trim(),
    api: providerApi.value,
  }
  // 编辑已配好 key 的供应商时，表单 api_key 可能为空（key 在其他会话存），
  // 传 provider 让后端回退用该供应商已存明文 key 探测，避免掩码/空 key 致 401。
  if (editingProviderId) payload.provider = editingProviderId
  const models = await testTextProvider(payload)
  models.forEach((m) => addModelItem(m))
}
// 由展示名生成唯一 route key（slug）；全非 ASCII（如中文名）时兜底时间戳
function slugifyProvider(s: string): string {
  const slug = (s || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug || 'provider-' + Date.now()
}
// 保存供应商（新增 = slugify(display_name)；编辑自定义 = 沿用原 provider，保留 models）
async function onSaveProvider() {
  if (!providerName.value.trim()) {
    showToast(t('providerNameRequired'), 3500)
    return
  }
  if (!providerBaseUrl.value.trim()) {
    showToast(t('providerBaseUrlRequired'), 3500)
    return
  }
  if (!isEditCustom.value && !providerApiKey.value.trim()) {
    showToast(t('providerApiKeyRequired'), 3500)
    return
  }
  const models = modelItems.value
    .map((m) => m.trim())
    .filter(Boolean)
    .filter((m, i, arr) => arr.indexOf(m) === i)
  const provider = isEditCustom.value && editingProvider.value
    ? editingProvider.value
    : slugifyProvider(providerName.value.trim())
  // 新增必填 key；编辑时留空 → 复用会话内已知明文 key（后端仅回掩码，无法回读落盘值）
  let apiKey = providerApiKey.value.trim()
  if (isEditCustom.value && !apiKey) apiKey = lastKnownProviderKeys[provider] || ''
  if (apiKey) lastKnownProviderKeys[provider] = apiKey
  const ok = await saveTextProvider({
    provider,
    display_name: providerName.value.trim(),
    api: providerApi.value,
    base_url: providerBaseUrl.value.trim(),
    api_key: apiKey,
    models_json: JSON.stringify(models),
  })
  if (ok) {
    showProviderModal.value = false
  }
}
// 删除供应商
async function onDeleteProvider(id: string) {
  await deleteTextProvider(id)
}
// 供应商弹窗模式与表单生命期
const editingProvider = ref<null | string>(null) // null=新增 | 'agnes'=编辑内置 | 其他=编辑自定义
// 会话内新增/编辑时用户输入的明文 key（后端仅回掩码，用于编辑留空时保留）
const lastKnownProviderKeys: Record<string, string> = {}
const showProviderModal = ref(false)
const { containerRef: providerModalRef } = useModalA11y(showProviderModal, () => (showProviderModal.value = false))
// 可增删的模型列表（拉取并入 + 手动添加，唯一去重）
const modelItems = ref<string[]>([])
const modelInput = ref('')
function addModelItem(value: string) {
  const m = (value || '').trim()
  if (!m) return
  if (!modelItems.value.includes(m)) modelItems.value.push(m)
}
function onAddModel() {
  addModelItem(modelInput.value)
  modelInput.value = ''
}
function removeModelItem(idx: number) {
  modelItems.value.splice(idx, 1)
}

function resetProviderForm() {
  providerName.value = ''
  providerApi.value = 'openai-completions'
  providerBaseUrl.value = ''
  providerApiKey.value = ''
  modelItems.value = []
  modelInput.value = ''
  providerSaveStatus.value = 'idle'
}
// 模型分节「添加供应商」：新增模式
function openAddProvider() {
  editingProvider.value = null
  resetProviderForm()
  showProviderModal.value = true
}
// 管理分节「编辑」：打开对应供应商编辑态（agnes 专项 / 自定义预填）
function openEditProvider(p: any) {
  editingProvider.value = p?.provider || 'agnes'
  providerSaveStatus.value = 'idle'
  if (p?.provider === 'agnes') {
    showProviderModal.value = true
    return
  }
  providerName.value = p.display_name || ''
  providerApi.value = p.api || 'openai-completions'
  providerBaseUrl.value = p.base_url || ''
  providerApiKey.value = lastKnownProviderKeys[p.provider] || ''
  // 编辑：已有 models 预填进列表，便于在此基础增删调整
  modelItems.value = Array.from(
    new Set((p.models && Array.isArray(p.models) ? p.models : []).map((m: string) => m.trim()).filter(Boolean)),
  )
  modelInput.value = ''
  showProviderModal.value = true
}

loadTextProviders()
initCollapse()
</script>

<template>
  <!-- 供应商管理 -->
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
        <span class="text-sm">🔌</span>
        <span class="text-sm text-muted">
          <span class="text-ink-2 font-medium">{{ t('providerManageTitle') }}</span>
          <span class="text-muted mx-2">·</span>
          <span class="text-muted">{{ manageProviders.length }}</span>
        </span>
      </div>
      <span class="text-muted text-xs">▶</span>
    </div>
    <div v-else class="p-6 pt-4">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold text-accent">{{ t('providerManageTitle') }}</h2>
        <div class="flex items-center gap-3">
          <button class="text-xs text-accent hover:text-ink transition whitespace-nowrap" @click="openAddProvider()">
            {{ t('providerAddBtn') }}
          </button>
          <button class="text-xs text-muted hover:text-ink-2 transition px-2 py-1 rounded" @click="toggleConfigPanel('apikey')">▲</button>
        </div>
      </div>
      <p class="text-xs text-muted mb-4">{{ t('providerManageHint') }}</p>

      <!-- 第三方供应商使用说明：免费模型支持范围 / AMD Radeon Cloud 推荐 / 图像视频暂不支持 -->
      <div class="rounded-lg bg-paper-3/60 p-4 text-xs leading-relaxed mb-4">
        <p class="font-medium text-ink-2 mb-2">{{ t('providerIntroTitle') }}</p>
        <ul class="list-disc pl-4 space-y-1.5 text-muted">
          <li>{{ t('providerIntroFree') }}</li>
          <li>
            {{ t('providerIntroText') }}
            <ul class="list-disc pl-4 mt-1.5 space-y-1">
              <li>
                <a
                  href="https://developer.amd.com.cn/radeon/modelapis"
                  target="_blank"
                  rel="noopener"
                  class="underline decoration-dotted underline-offset-2 hover:text-ink transition-colors"
                >{{ t('providerIntroAmdEntry') }}</a>
              </li>
              <li>
                {{ t('providerIntroAmdEndpoint') }}
                <code class="font-mono text-ink-2 select-all">https://developer.amd.com.cn/radeon/api/v1</code>
              </li>
              <li>{{ t('providerIntroAmdModels') }}</li>
              <li>{{ t('providerIntroAmdNote') }}</li>
            </ul>
          </li>
          <li>
            {{ t('providerIntroMedia') }}{{ t('providerIntroMediaRecommend') }}
            <a
              :href="GITHUB_REPO + '/issues/new'"
              target="_blank"
              rel="noopener"
              class="text-accent hover:text-ink transition-colors"
            >GitHub Issue</a>
            <span class="mx-1">/</span>
            <a
              :href="GITHUB_REPO + '/discussions'"
              target="_blank"
              rel="noopener"
              class="text-accent hover:text-ink transition-colors"
            >GitHub Discussion</a>
          </li>
        </ul>
      </div>

      <!-- 供应商列表：agnes（内置）+ 自定义 -->
      <div class="space-y-2">
        <div
          v-for="p in manageProviders"
          :key="p.provider"
          class="flex items-center justify-between glass-input rounded-lg px-4 py-2.5"
        >
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <p class="text-sm text-ink font-medium truncate">{{ p.display_name || p.provider }}</p>
              <span v-if="p.builtin" class="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">{{ t('providerBuiltin') }}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-paper-3 text-muted">{{ providerApiLabel(p) }}</span>
              <span
                v-if="p.provider === (appState.models.text_provider || 'agnes')"
                class="text-[10px] px-2 py-0.5 rounded-full bg-blue-900 text-blue-300"
              >{{ t('providerInUse') }}</span>
            </div>
            <p class="text-xs text-muted font-mono truncate mt-0.5">
              {{ p.provider === 'agnes' ? displayDomain() : (p.base_url || '—') }}
            </p>
            <p class="text-xs text-muted font-mono truncate">
              <template v-if="p.provider === 'agnes'">{{ agnesApiKeyText() }}</template>
              <template v-else>{{ t('providerApiKeyLabel') }}: {{ p.api_key || '—' }}</template>
            </p>
          </div>
          <div class="flex items-center gap-2 ml-3">
            <button
              class="px-3 py-1 bg-blue-600/80 hover:bg-blue-500 rounded-lg text-xs font-medium transition"
              @click="openEditProvider(p)"
            >{{ t('providerEditLabel') }}</button>
            <button
              v-if="!p.builtin"
              class="px-3 py-1 bg-red-600/80 hover:bg-red-500 rounded-lg text-xs font-medium transition"
              @click="onDeleteProvider(p.provider)"
            >{{ t('delete') }}</button>
            <span v-else class="text-muted/50" :title="t('providerBuiltinHint')">•</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 新增 / 编辑供应商弹窗（仿 ConfirmModal：遮罩 + role=dialog + @click.self/ESC 关闭） -->
  <teleport to="body">
    <div
      v-if="showProviderModal"
      ref="providerModalRef"
      class="fixed inset-0 z-[60] flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      :aria-label="modalTitle"
    >
      <div class="absolute inset-0 bg-black/40" @click="showProviderModal = false"></div>
      <div class="relative bg-paper rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl border border-rule max-h-[85vh] overflow-y-auto">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-semibold text-ink">{{ modalTitle }}</h3>
          <button
            class="text-muted hover:text-ink-2 transition text-xl leading-none"
            :aria-label="t('cancel')"
            @click="showProviderModal = false"
          >✕</button>
        </div>

        <!-- ══ 编辑 agnes：供应商只读 + 域名 + API Key + per-key 域名映射 ══ -->
        <template v-if="editingProvider === 'agnes'">
          <div class="flex items-center gap-2 mb-5">
            <span class="text-sm font-semibold text-ink-2">Agnes</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">{{ t('providerBuiltin') }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-paper-3 text-muted">{{ t('providerEditReadonly') }}</span>
          </div>

          <!-- 域名 -->
          <div class="mb-6">
            <p class="text-sm font-medium text-ink-2 mb-1">{{ t('domainTitle') }}</p>
            <p class="text-xs text-muted mb-3">{{ t('domainHint') }}</p>
            <div class="space-y-2">
              <label v-for="d in DOMAIN_ENTRIES" :key="d.key" class="flex items-center gap-3 glass-input rounded-lg px-4 py-3 cursor-pointer hover:border-blue-500/40 transition">
                <input v-model="appState.agnesDomain" type="radio" name="agnes-domain-modal" :value="d.key" class="accent-blue-500 w-4 h-4 cursor-pointer" />
                <div>
                  <span class="text-sm text-ink-2 font-medium">{{ d.url }}</span>
                  <span class="text-xs text-muted ml-2">{{ t(d.labelKey) }}</span>
                </div>
              </label>
            </div>
            <div class="flex items-center gap-3 mt-3">
              <button class="px-4 py-2 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition" @click="saveDomain">{{ t('save') }}</button>
              <span v-if="domainSaveStatus === 'ok'" class="text-xs text-green-400">{{ t('domainSaved') }}</span>
              <span v-if="domainSaveStatus === 'error'" class="text-xs text-red-400">{{ domainErrorMsg }}</span>
            </div>
          </div>

          <!-- API Key -->
          <div>
            <p class="text-sm font-medium text-ink-2 mb-1">{{ t('apiKeyTitle') }}</p>
            <div class="flex gap-3 items-start">
              <textarea
                v-model="apiKeyInput"
                rows="2"
                :placeholder="hasApiKey ? t('apiKeyAppendPlaceholder') : t('apiKeyPlaceholder')"
                class="flex-1 glass-input rounded-lg px-4 py-2.5 text-sm text-ink placeholder-muted resize-y"
              ></textarea>
              <button class="px-5 py-2.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition whitespace-nowrap" @click="onSaveApiKey">{{ hasApiKey ? t('addKey') : t('save') }}</button>
              <button v-if="apiKeyStatus !== 'none'" class="px-5 py-2.5 bg-red-600/80 hover:bg-red-500 rounded-lg text-sm font-medium transition whitespace-nowrap" @click="clearApiKey">{{ t('clear') }}</button>
            </div>
            <div v-if="keyCount > 0" class="mt-2 flex items-center gap-2 flex-wrap">
              <span class="text-xs px-2 py-0.5 rounded-full bg-green-900 text-green-300">{{ t('keyCountLabel') }}: {{ keyCount }} <span class="opacity-70">({{ keySource }})</span></span>
              <span v-if="keyCount > 1" class="text-xs px-2 py-0.5 rounded-full bg-blue-900 text-blue-300">{{ t('multiKeyActive') }}</span>
            </div>
            <!-- Key 列表 + per-key 域名映射 + 自动探测 -->
            <div v-if="keyList.length > 0" class="mt-3 space-y-1.5">
              <div v-for="(item, idx) in keyList" :key="item.id + idx" class="flex items-center gap-2 rounded-lg px-3 py-1.5 bg-paper-3/70 text-xs flex-wrap">
                <code class="flex-1 font-mono text-ink-2 truncate min-w-[8rem]">{{ item.mask }}</code>
                <span class="px-1.5 py-0.5 rounded text-[10px] uppercase" :class="item.source === 'env' ? 'bg-amber-900/60 text-amber-300' : 'bg-paper-3 text-muted'">{{ item.source === 'env' ? t('keySrcEnv') : t('keySrcConfig') }}</span>
                <span v-if="item.domain && keyDomainUrl(item.domain)" class="px-1.5 py-0.5 rounded text-[10px] font-mono" :class="item.domain === 'cn' ? 'bg-green-900/60 text-green-300' : 'bg-blue-900/60 text-blue-300'">{{ keyDomainUrl(item.domain) }}</span>
                <span v-else class="px-1.5 py-0.5 rounded text-[10px] text-amber-300/80 bg-amber-900/30" :title="t('keyDomainNotSetHint')">{{ t('keyDomainNotSet') }}</span>
                <label v-if="item.persistable" :for="'key-domain-select-' + item.id" class="sr-only">{{ t('keyDomainSelectTitle') }}</label>
                <select :id="'key-domain-select-' + item.id" v-if="item.persistable" :value="item.domain || ''" class="glass-input rounded px-1.5 py-0.5 text-[10px] text-ink cursor-pointer" :title="t('keyDomainSelectTitle')" :aria-label="t('keyDomainSelectTitle')" @change="onKeyDomainChange(item, ($event.target as HTMLSelectElement).value)">
                  <option value="">{{ t('keyDomainAuto') }}（{{ displayDomain() }}）</option>
                  <option v-for="d in DOMAIN_ENTRIES" :key="d.key" :value="d.key">{{ d.url }}</option>
                </select>
                <button v-if="item.source !== 'env'" class="text-red-300 hover:text-red-200 transition" :title="t('removeKeyBtn')" @click="removeKey(item.id)">✕</button>
                <span v-else class="text-muted/50" :title="t('keySrcEnvHint')">•</span>
              </div>
              <div class="flex items-center gap-2 pt-1">
                <button class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-xs font-medium transition" :disabled="detectingKeys" @click="detectKeyDomains()">{{ detectingKeys ? t('detectKeysRunning') : t('detectKeysBtn') }}</button>
                <span class="text-xs text-muted">{{ t('detectKeysHint') }}</span>
              </div>
            </div>
            <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 mt-3 text-xs">
              <a href="https://platform.agnes-ai.com" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">🚀 {{ t('apiKeyGetLink') }}</a>
              <a href="https://video.lichuanyang.top/guides/api-key" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">📖 {{ t('apiKeyGuideLink') }}</a>
              <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">⚡ {{ t('apiKeyDemoLink') }}</a>
            </div>
          </div>

          <div class="flex justify-end mt-5">
            <button class="px-4 py-2 rounded-lg text-sm text-ink-2 bg-paper-3 hover:bg-paper-2 border border-rule transition" @click="showProviderModal = false">{{ t('close') }}</button>
          </div>
        </template>

        <!-- ══ 新增 / 编辑自定义供应商 ══ -->
        <template v-else>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="block text-xs text-muted mb-1">{{ t('providerNameLabel') }}</label>
              <input v-model="providerName" :placeholder="t('providerNamePlaceholder')" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink placeholder-muted" />
            </div>
            <div>
              <label class="block text-xs text-muted mb-1">{{ t('providerApiLabel') }}</label>
              <select v-model="providerApi" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
                <option value="openai-completions">{{ t('providerApiOpenai') }}</option>
                <option value="anthropic-messages">{{ t('providerApiAnthropic') }}</option>
              </select>
            </div>
            <div class="sm:col-span-2">
              <label class="block text-xs text-muted mb-1">{{ t('providerBaseUrlLabel') }}</label>
              <input v-model="providerBaseUrl" :placeholder="t('providerBaseUrlPlaceholder')" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink placeholder-muted" />
            </div>
            <div>
              <label class="block text-xs text-muted mb-1">{{ t('providerApiKeyLabel') }}</label>
              <input v-model="providerApiKey" type="password" :placeholder="isEditCustom ? t('providerApiKeyEditPlaceholder') : t('providerApiKeyPlaceholder')" class="w-full glass-input rounded-lg px-3 py-2.5 text-sm text-ink placeholder-muted" />
              <p v-if="isEditCustom" class="text-[10px] text-muted mt-0.5">{{ t('providerApiKeyEditHint') }}</p>
            </div>
            <div class="flex items-end">
              <button
                class="px-4 py-2.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition whitespace-nowrap"
                :disabled="providerTestBusy"
                @click="onFetchProviderModels"
              >{{ providerTestBusy ? t('providerFetching') : t('providerFetchModels') }}</button>
            </div>
          </div>

          <!-- 模型列表：可增删（拉取并入 + 手动添加），唯一去重 -->
          <div class="mt-3">
            <div class="flex items-center justify-between mb-1.5">
              <label class="text-xs text-muted">{{ t('modelListLabel') }}</label>
              <span v-if="modelItems.length === 0" class="text-xs text-muted">{{ t('providerNoModels') }}</span>
            </div>
            <div v-if="modelItems.length > 0" class="space-y-1.5 mb-2">
              <div v-for="(m, idx) in modelItems" :key="m + idx" class="flex items-center gap-2 glass-input rounded-lg px-3 py-1.5">
                <span class="flex-1 min-w-0 font-mono text-xs text-ink truncate">{{ m }}</span>
                <button class="text-red-300 hover:text-red-200 transition text-xs" :aria-label="t('delete')" @click="removeModelItem(idx)">✕</button>
              </div>
            </div>
            <div class="flex gap-2">
              <input v-model="modelInput" class="flex-1 glass-input rounded-lg px-3 py-2 text-sm text-ink placeholder-muted font-mono" :placeholder="t('modelInputPlaceholder')" @keyup.enter.prevent="onAddModel()" />
              <button class="px-3 py-2 bg-blue-600/80 hover:bg-blue-500 rounded-lg text-sm font-medium transition whitespace-nowrap" @click="onAddModel()">{{ t('modelAdd') }}</button>
            </div>
            <p class="text-[10px] text-muted mt-1">{{ t('modelInputHint') }}</p>
          </div>

          <div class="flex items-center gap-3 justify-end mt-6">
            <span v-if="providerSaveStatus === 'ok'" class="self-center text-xs text-green-400">{{ t('providerSaved') }}</span>
            <span v-if="providerSaveStatus === 'error'" class="self-center text-xs text-red-400">{{ providerErrorMsg }}</span>
            <button class="px-4 py-2 rounded-lg text-sm text-ink-2 bg-paper-3 hover:bg-paper-2 border border-rule transition" @click="showProviderModal = false">{{ t('cancel') }}</button>
            <button class="px-5 py-2.5 bg-accent text-accent-ink hover:bg-accent/90 rounded-lg text-sm font-medium transition" @click="onSaveProvider">{{ t('save') }}</button>
          </div>
        </template>
      </div>
    </div>
  </teleport>
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
          <label class="block text-xs text-muted mb-1">{{ t('modelSupplier') }}</label>
          <div class="flex justify-end mb-1">
            <button
              class="text-xs text-accent hover:text-ink transition whitespace-nowrap"
              @click="openAddProvider()"
            >{{ t('providerAddBtn') }}</button>
          </div>
          <div class="flex gap-3">
            <select
              v-model="textProviderComposite"
              class="flex-1 glass-input rounded-lg px-3 py-2.5 text-sm text-ink"
              :aria-label="t('modelSupplier')"
            >
              <option v-for="opt in textProviderOptions" :key="opt.key" :value="opt.key">{{ opt.label }}</option>
            </select>
            <button class="px-4 py-2.5 bg-paper-3 hover:bg-paper-3 rounded-lg text-sm font-medium transition whitespace-nowrap" @click="syncModels">
              {{ t('modelSync') }}
            </button>
          </div>
          <p class="text-xs text-muted/70 mt-1">{{ t('providerTextHint') }}</p>
          <label class="block text-xs text-muted mb-1 mt-3">{{ t('modelTextLabel') }}</label>
          <select
            v-model="appState.models.text"
            class="flex-1 glass-input rounded-lg px-3 py-2.5 text-sm text-ink"
            :aria-label="t('modelTextLabel')"
          >
            <option v-if="textModelOptions.length === 0" value="">{{ t('providerNoModels') }}</option>
            <option v-for="m in textModelOptions" :key="m" :value="m">{{ modelDisplayLabel(m) }}</option>
          </select>
          <p v-if="textModelOptions.length === 0" class="text-xs text-muted mt-1.5">{{ t('providerNoModels') }}</p>
          <p v-if="betaHintVisible" class="text-xs text-accent mt-1.5">{{ t('modelBetaHint') }}</p>
          <p v-if="isPaidModel(appState.models.text)" class="text-xs text-amber-400 mt-1.5">{{ t('modelPaidHint') }}</p>
        </div>
        <div>
          <label class="block text-xs text-muted mb-1">{{ t('modelImageLabel') }}</label>
          <select v-model="appState.models.image" class="flex-1 glass-input rounded-lg px-3 py-2.5 text-sm text-ink">
            <option v-for="m in appState.modelListCache.image" :key="m" :value="m">{{ modelDisplayLabel(m) }}</option>
          </select>
          <p v-if="isPaidModel(appState.models.image)" class="text-xs text-amber-400 mt-1.5">{{ t('modelPaidHint') }}</p>
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
