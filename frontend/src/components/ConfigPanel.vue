<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { t, tf } from '@/i18n'
import { appState, getCollapsePrefs, setCollapsePref } from '@/store'
import { useConfig } from '@/composables/useConfig'
import { useVoice } from '@/composables/useVoice'
import { useGa } from '@/composables/useGa'
import { useVideoModelCaps } from '@/composables/useVideoModelCaps'
import { useToast } from '@/composables/useToast'
import { useModalA11y } from '@/composables/useModalA11y'
import { FREE_TOKENS_GUIDE_URL, GITHUB_REPO } from '@/utils/feedback'
import { stripEmoji } from '@/utils/text'

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
  activeKeyCount,
  keySource,
  keyList,
  setKeyEnabled,
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
  fastRetryAuto,
  fastRetryPerMinute,
  fastRetryMinutes,
  fastRetrySaveStatus,
  syncFastRetrySettings,
  saveFastRetrySettings,
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

// v8.0：免费档排前，降低免费用户误选付费档的概率（仍保留「付费」标签与提示）
const sortedVideoModels = computed(() =>
  [...(appState.modelListCache.video || [])].sort(
    (a, b) => Number(vmCaps.isPaidTag(a)) - Number(vmCaps.isPaidTag(b)),
  ),
)

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
async function onToggleKeyPool(item: { id: string; enabled?: boolean }) {
  await setKeyEnabled(item.id, item.enabled === false)
}
const introOpen = ref(false)
async function onSaveAgnes() {
  const domainOk = await saveDomain()
  if (!domainOk) return
  if (apiKeyInput.value.trim()) await onSaveApiKey()
}
// 401 归因提示：后端 KeyRing 只登记事实（不剔除该 Key），是否删除由用户自行决定
function authFailedHint(item: { auth_failed?: { count: number; last_at: number } | null }): string {
  const f = item.auth_failed
  if (!f) return ''
  return tf('keyAuthFailedHint', {
    count: f.count,
    time: f.last_at ? new Date(f.last_at * 1000).toLocaleString() : '-',
  })
}

// 折叠状态（4 个配置面板）：默认全部折叠——供应商管理 / 模型选择 / 工作目录 /
// 隐私设置首屏均只显示标题行，用户手动展开后由 *_manual 偏好记忆（见 initCollapse）
const collapsed = reactive<Record<string, boolean>>({
  apikey: true,
  model: true,
  workspace: true,
  retry: true,
  privacy: true,
})

function initCollapse() {
  const prefs = getCollapsePrefs()
  const keys = ['apikey', 'model', 'workspace', 'retry', 'privacy']
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
    // 注意：此处只改内存状态，**落盘需点「保存」**（与其它模型配置一致）。
    // 切回 agnes 时 text_provider 置空串，保存时由 api.saveModels 转成显式的
    // 'agnes' 发送（空串在表单层会丢失，见 frontend/src/api/index.ts）。
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
// v8.0：把 /api/config.fast_retry 回填到设置页表单（App 启动时已拉取）
syncFastRetrySettings()
</script>

<template>
  <!-- 供应商管理 -->
  <div class="panel mb-4 overflow-hidden">
    <div
      v-if="collapsed.apikey"
      class="panel-head collapse-header cursor-pointer"
      role="button"
      tabindex="0"
      :aria-expanded="!collapsed.apikey"
      @click="toggleConfigPanel('apikey')"
    >
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">01</span>
        <span class="truncate text-[12.5px] font-medium text-ink-2">{{ t('providerManageTitle') }}</span>
        <span class="mono text-[10px] text-muted">{{ manageProviders.length }}</span>
      </div>
      <span class="mono text-[11px] text-muted">＋</span>
    </div>
    <div v-else class="px-4 pb-4 pt-3.5">
      <div class="mb-3 flex items-center justify-between gap-3 border-b border-rule pb-3">
        <h2 class="panel-title">
          <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">01</span>
          {{ t('providerManageTitle') }}
        </h2>
        <div class="flex items-center gap-1">
          <button class="btn btn-quiet btn-xs text-accent whitespace-nowrap" @click="openAddProvider()">
            {{ t('providerAddBtn') }}
          </button>
          <button class="btn btn-quiet btn-xs" @click="toggleConfigPanel('apikey')">−</button>
        </div>
      </div>
      <p class="hint mb-4">{{ t('providerManageHint') }}</p>

      <!-- 第三方供应商使用说明：默认折叠，点 Read more 展开 -->
      <div class="rounded-lg bg-paper-3/60 px-4 py-3 text-xs leading-relaxed mb-4">
        <div class="flex items-center justify-between gap-3">
          <p class="font-medium text-ink-2">{{ t('providerIntroTitle') }}</p>
          <button
            type="button"
            class="text-accent hover:text-ink transition whitespace-nowrap"
            :aria-expanded="introOpen"
            @click="introOpen = !introOpen"
          >{{ introOpen ? t('providerReadLess') : t('providerReadMore') }}</button>
        </div>
        <div v-show="introOpen" class="mt-2">
        <!-- 官网教程导流：免费 Token / 供应商配置图文教程 -->
        <p class="mb-2">
          <a
            :href="FREE_TOKENS_GUIDE_URL"
            target="_blank"
            rel="noopener"
            class="text-accent hover:text-ink transition-colors underline decoration-dotted underline-offset-2"
          >{{ t('providerIntroGuide') }}</a>
        </p>
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
      </div>

      <!-- 供应商列表：agnes（内置）+ 自定义 -->
      <div class="space-y-1.5">
        <div
          v-for="p in manageProviders"
          :key="p.provider"
          class="flex items-center justify-between gap-3 rounded border border-rule bg-paper px-3 py-2"
        >
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5">
              <p class="truncate text-[12.5px] font-medium text-ink">{{ p.display_name || p.provider }}</p>
              <span v-if="p.builtin" class="chip chip-success">{{ t('providerBuiltin') }}</span>
              <span class="chip">{{ providerApiLabel(p) }}</span>
              <span
                v-if="p.provider === (appState.models.text_provider || 'agnes')"
                class="chip chip-accent"
              >{{ t('providerInUse') }}</span>
            </div>
            <p class="mono mt-1 truncate text-[10.5px] text-muted">
              {{ p.provider === 'agnes' ? displayDomain() : (p.base_url || '—') }}
            </p>
            <p class="mono truncate text-[10.5px] text-muted">
              <template v-if="p.provider === 'agnes'">{{ agnesApiKeyText() }}</template>
              <template v-else>{{ t('providerApiKeyLabel') }}: {{ p.api_key || '—' }}</template>
            </p>
          </div>
          <div class="flex shrink-0 items-center gap-1">
            <button
              class="btn btn-ghost btn-xs"
              @click="openEditProvider(p)"
            >{{ t('providerEditLabel') }}</button>
            <button
              v-if="!p.builtin"
              class="btn btn-quiet btn-xs text-danger"
              @click="onDeleteProvider(p.provider)"
            >{{ t('delete') }}</button>
            <span v-else class="px-1 text-muted/50" :title="t('providerBuiltinHint')">•</span>
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
      class="modal-backdrop"
      role="dialog"
      aria-modal="true"
      :aria-label="modalTitle"
    >
      <div class="absolute inset-0" @click="showProviderModal = false"></div>
      <div class="modal max-h-[85vh] w-full max-w-lg overflow-y-auto p-5">
        <div class="mb-4 flex items-center justify-between gap-3">
          <h3 class="text-[13.5px] font-semibold tracking-[-0.01em] text-ink">{{ modalTitle }}</h3>
          <button
            class="btn btn-quiet h-7 w-7 px-0 text-[14px] leading-none"
            :aria-label="t('cancel')"
            @click="showProviderModal = false"
          >✕</button>
        </div>

        <!-- ══ 编辑 agnes：供应商只读 + 域名 + API Key + per-key 域名映射 ══ -->
        <template v-if="editingProvider === 'agnes'">
          <div class="mb-5 flex items-center gap-1.5">
            <span class="text-[13px] font-semibold text-ink">Agnes</span>
            <span class="chip chip-success">{{ t('providerBuiltin') }}</span>
            <span class="chip">{{ t('providerEditReadonly') }}</span>
          </div>

          <!-- 域名 -->
          <div class="mb-5">
            <p class="label">{{ t('domainTitle') }}</p>
            <p class="hint mb-2.5">{{ t('domainHint') }}</p>
            <div class="space-y-1.5">
              <label
                v-for="d in DOMAIN_ENTRIES"
                :key="d.key"
                class="flex cursor-pointer items-center gap-3 rounded border px-3 py-2 transition-colors"
                :class="appState.agnesDomain === d.key ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'"
              >
                <input v-model="appState.agnesDomain" type="radio" name="agnes-domain-modal" :value="d.key" class="check" />
                <span class="min-w-0">
                  <span class="mono block truncate text-[11.5px] text-ink-2">{{ d.url }}</span>
                  <span class="mt-0.5 block text-[10.5px] text-muted">{{ t(d.labelKey) }}</span>
                </span>
              </label>
            </div>
          </div>

          <!-- API Key -->
          <div>
            <p class="label">{{ t('apiKeyTitle') }}</p>
            <textarea
              v-model="apiKeyInput"
              rows="2"
              :placeholder="hasApiKey ? t('apiKeyAppendPlaceholder') : t('apiKeyPlaceholder')"
              class="field"
            ></textarea>
            <div v-if="keyCount > 0" class="mt-2 flex flex-wrap items-center gap-1.5">
              <span class="chip chip-success">{{ t('keyCountLabel') }}: {{ keyCount }} <span class="opacity-70">({{ keySource }})</span></span>
              <span v-if="activeKeyCount > 1" class="chip chip-accent" :title="t('multiKeyHint')">{{ t('multiKeyActive') }}</span>
              <span v-if="activeKeyCount !== keyCount" class="text-[10.5px] text-muted">{{ t('keyPoolActive') }}: {{ activeKeyCount }}</span>
            </div>
            <!-- Key 列表 + per-key 域名映射 + 自动探测 -->
            <div v-if="keyList.length > 0" class="mt-3 space-y-1">
              <div
                v-for="(item, idx) in keyList"
                :key="item.id + idx"
                class="flex flex-wrap items-center gap-1.5 rounded border border-rule bg-paper px-2.5 py-1.5"
                :class="item.enabled === false ? 'opacity-60' : ''"
              >
                <button
                  type="button"
                  role="switch"
                  :aria-checked="item.enabled !== false"
                  :aria-label="t('keyPoolToggle')"
                  :title="item.enabled === false ? t('keyPoolOff') : t('keyPoolOn')"
                  class="relative h-3.5 w-7 shrink-0 rounded-full border transition-colors"
                  :class="item.enabled !== false ? 'border-accent bg-accent/25' : 'border-rule-2 bg-paper-3'"
                  @click="onToggleKeyPool(item)"
                >
                  <span
                    class="absolute top-[2px] h-[10px] w-[10px] rounded-full transition-all"
                    :class="item.enabled !== false ? 'bg-accent' : 'bg-muted'"
                    :style="{ insetInlineStart: item.enabled !== false ? '15px' : '2px' }"
                  ></span>
                </button>
                <code class="mono min-w-[7rem] flex-1 truncate text-[10.5px] text-ink-2">{{ item.mask }}</code>
                <span class="chip">{{ item.source === 'env' ? t('keySrcEnv') : t('keySrcConfig') }}</span>
                <span v-if="item.domain && keyDomainUrl(item.domain)" class="chip" :class="item.domain === 'cn' ? 'chip-success' : 'chip-accent'">{{ keyDomainUrl(item.domain) }}</span>
                <span v-else-if="item.source === 'env'" class="text-[10px] text-muted" :title="t('keySrcEnvHint')">{{ t('keyDomainEnvFollow') }}（{{ displayDomain() }}）</span>
                <span v-else class="chip chip-warning" :title="t('keyDomainNotSetHint')">{{ t('keyDomainNotSet') }}</span>
                <!-- 401 归因：后端只登记不剔除，是否移除该 Key 由用户决定（✕ 按钮） -->
                <span v-if="item.auth_failed" class="chip chip-danger cursor-help" :title="authFailedHint(item)">{{ tf('keyAuthFailed', { count: item.auth_failed.count }) }}</span>
                <label v-if="item.persistable" :for="'key-domain-select-' + item.id" class="sr-only">{{ t('keyDomainSelectTitle') }}</label>
                <select
                  :id="'key-domain-select-' + item.id"
                  v-if="item.persistable"
                  :value="item.domain || ''"
                  class="field h-6 w-auto px-1.5 py-0 text-[10px]"
                  :title="t('keyDomainSelectTitle')"
                  :aria-label="t('keyDomainSelectTitle')"
                  @change="onKeyDomainChange(item, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">{{ t('keyDomainAuto') }}（{{ displayDomain() }}）</option>
                  <option v-for="d in DOMAIN_ENTRIES" :key="d.key" :value="d.key">{{ d.url }}</option>
                </select>
                <button v-if="item.source !== 'env'" class="btn btn-quiet btn-xs text-danger" :title="t('removeKeyBtn')" @click="removeKey(item.id)">✕</button>
                <span v-else class="px-1 text-muted/50" :title="t('keySrcEnvHint')">•</span>
              </div>
              <div class="flex items-center gap-2 pt-1">
                <button class="btn btn-ghost btn-xs" :disabled="detectingKeys" @click="detectKeyDomains()">{{ detectingKeys ? t('detectKeysRunning') : t('detectKeysBtn') }}</button>
                <span class="hint">{{ t('detectKeysHint') }}</span>
              </div>
            </div>
            <div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
              <a href="https://platform.agnes-ai.com" target="_blank" rel="noopener" class="text-accent transition-colors hover:text-ink">{{ stripEmoji(t('apiKeyGetLink')) }}</a>
              <a href="https://video.lichuanyang.top/guides/api-key" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ stripEmoji(t('apiKeyGuideLink')) }}</a>
              <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ stripEmoji(t('apiKeyDemoLink')) }}</a>
            </div>
          </div>

          <div class="mt-5 flex items-center justify-end gap-2">
            <span v-if="domainSaveStatus === 'ok'" class="me-auto text-[11.5px] text-success">{{ t('domainSaved') }}</span>
            <span v-if="domainSaveStatus === 'error'" class="me-auto text-[11.5px] text-danger">{{ domainErrorMsg }}</span>
            <button v-if="apiKeyStatus !== 'none'" class="btn btn-danger" @click="clearApiKey">{{ t('clear') }}</button>
            <button class="btn btn-primary" @click="onSaveAgnes">{{ apiKeyInput.trim() ? (hasApiKey ? t('addKey') : t('save')) : t('save') }}</button>
          </div>
        </template>

        <!-- ══ 新增 / 编辑自定义供应商 ══ -->
        <template v-else>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="label">{{ t('providerNameLabel') }}</label>
              <input v-model="providerName" :placeholder="t('providerNamePlaceholder')" class="w-full field placeholder-muted" />
            </div>
            <div>
              <label class="label">{{ t('providerApiLabel') }}</label>
              <select v-model="providerApi" class="w-full field">
                <option value="openai-completions">{{ t('providerApiOpenai') }}</option>
                <option value="anthropic-messages">{{ t('providerApiAnthropic') }}</option>
              </select>
            </div>
            <div class="sm:col-span-2">
              <label class="label">{{ t('providerBaseUrlLabel') }}</label>
              <input v-model="providerBaseUrl" :placeholder="t('providerBaseUrlPlaceholder')" class="w-full field placeholder-muted" />
            </div>
            <div>
              <label class="label">{{ t('providerApiKeyLabel') }}</label>
              <input v-model="providerApiKey" type="password" :placeholder="isEditCustom ? t('providerApiKeyEditPlaceholder') : t('providerApiKeyPlaceholder')" class="w-full field placeholder-muted" />
              <p v-if="isEditCustom" class="text-[10px] text-muted mt-0.5">{{ t('providerApiKeyEditHint') }}</p>
            </div>
            <div class="flex items-end">
              <button
                class="btn btn-ghost whitespace-nowrap"
                :disabled="providerTestBusy"
                @click="onFetchProviderModels"
              >{{ providerTestBusy ? t('providerFetching') : t('providerFetchModels') }}</button>
            </div>
          </div>

          <!-- 模型列表：可增删（拉取并入 + 手动添加），唯一去重 -->
          <div class="mt-4">
            <div class="mb-1.5 flex items-center justify-between gap-2">
              <span class="label mb-0">{{ t('modelListLabel') }}</span>
              <span v-if="modelItems.length === 0" class="hint">{{ t('providerNoModels') }}</span>
            </div>
            <div v-if="modelItems.length > 0" class="mb-2 space-y-1">
              <div v-for="(m, idx) in modelItems" :key="m + idx" class="flex items-center gap-2 rounded border border-rule bg-paper px-2.5 py-1">
                <span class="mono min-w-0 flex-1 truncate text-[11px] text-ink">{{ m }}</span>
                <button class="btn btn-quiet btn-xs text-danger" :aria-label="t('delete')" @click="removeModelItem(idx)">✕</button>
              </div>
            </div>
            <div class="flex gap-2">
              <input v-model="modelInput" class="field flex-1 font-mono" :placeholder="t('modelInputPlaceholder')" @keyup.enter.prevent="onAddModel()" />
              <button class="btn btn-secondary whitespace-nowrap" @click="onAddModel()">{{ t('modelAdd') }}</button>
            </div>
            <p class="hint mt-1.5">{{ t('modelInputHint') }}</p>
          </div>

          <div class="mt-6 flex items-center justify-end gap-2">
            <span v-if="providerSaveStatus === 'ok'" class="me-auto text-[11.5px] text-success">{{ t('providerSaved') }}</span>
            <span v-if="providerSaveStatus === 'error'" class="me-auto text-[11.5px] text-danger">{{ providerErrorMsg }}</span>
            <button class="btn btn-ghost" @click="showProviderModal = false">{{ t('cancel') }}</button>
            <button class="btn btn-primary" @click="onSaveProvider">{{ t('save') }}</button>
          </div>
        </template>
      </div>
    </div>
  </teleport>
  <!-- 模型选择 -->
  <div class="panel mb-4 overflow-hidden">
    <div
      v-if="collapsed.model"
      class="panel-head collapse-header cursor-pointer"
      role="button"
      tabindex="0"
      @click="toggleConfigPanel('model')"
    >
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">02</span>
        <span class="shrink-0 text-[12.5px] font-medium text-ink-2">{{ t('modelTitle') }}</span>
        <span
          v-if="appState.models.text || appState.models.image || appState.models.video"
          class="mono truncate text-[10px] text-muted"
          :title="`${t('modelTagText')} ${appState.models.text} · ${t('modelTagImage')} ${appState.models.image} · ${t('modelTagVideo')} ${appState.models.video}`"
        >
          {{ t('modelTagText') }} {{ appState.models.text }} · {{ t('modelTagImage') }} {{ appState.models.image }} · {{ t('modelTagVideo') }} {{ appState.models.video }}
        </span>
        <span v-else class="text-muted">—</span>
      </div>
      <span class="mono text-[11px] text-muted">＋</span>
    </div>
    <div v-else class="px-4 pb-4 pt-3.5">
      <div class="mb-3 flex items-center justify-between gap-3 border-b border-rule pb-3">
        <h2 class="panel-title">
          <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">02</span>
          {{ t('modelTitle') }}
        </h2>
        <div class="flex items-center gap-1">
          <span class="chip">{{ t('modelSyncIdle') }}</span>
          <button class="btn btn-quiet btn-xs" @click="toggleConfigPanel('model')">−</button>
        </div>
      </div>
      <p class="hint mb-4">{{ t('modelHint') }}</p>
      <div class="space-y-3">
        <div>
          <label class="label">{{ t('modelSupplier') }}</label>
          <div class="mb-1 flex justify-end">
            <button
              class="btn btn-quiet btn-xs text-accent whitespace-nowrap"
              @click="openAddProvider()"
            >{{ t('providerAddBtn') }}</button>
          </div>
          <div class="flex gap-2">
            <select
              v-model="textProviderComposite"
              class="field flex-1"
              :aria-label="t('modelSupplier')"
            >
              <option v-for="opt in textProviderOptions" :key="opt.key" :value="opt.key">{{ opt.label }}</option>
            </select>
            <button class="btn btn-secondary whitespace-nowrap" @click="syncModels">
              {{ t('modelSync') }}
            </button>
          </div>
          <p class="hint mt-1">{{ t('providerTextHint') }}</p>
          <label class="label mt-3">{{ t('modelTextLabel') }}</label>
          <select
            v-model="appState.models.text"
            class="flex-1 field"
            :aria-label="t('modelTextLabel')"
          >
            <option v-if="textModelOptions.length === 0" value="">{{ t('providerNoModels') }}</option>
            <option v-for="m in textModelOptions" :key="m" :value="m">{{ modelDisplayLabel(m) }}</option>
          </select>
          <p v-if="textModelOptions.length === 0" class="hint mt-1.5">{{ t('providerNoModels') }}</p>
          <p v-if="betaHintVisible" class="mt-1.5 text-[11.5px] text-accent">{{ t('modelBetaHint') }}</p>
          <p v-if="isPaidModel(appState.models.text)" class="text-[11.5px] text-warning mt-1.5">{{ t('modelPaidHint') }}</p>
        </div>
        <div>
          <label class="label">{{ t('modelImageLabel') }}</label>
          <select v-model="appState.models.image" class="flex-1 field">
            <option v-for="m in appState.modelListCache.image" :key="m" :value="m">{{ modelDisplayLabel(m) }}</option>
          </select>
          <p v-if="isPaidModel(appState.models.image)" class="text-[11.5px] text-warning mt-1.5">{{ t('modelPaidHint') }}</p>
        </div>
        <!-- v6.2：开放视频模型选择 + 三模型差异说明 -->
        <div>
          <label class="label">{{ t('modelVideoLabel') }} (v6.2)</label>
          <select v-model="appState.models.video" class="flex-1 field">
            <option v-for="m in sortedVideoModels" :key="m" :value="m">{{ modelDisplayLabel(m) }}{{ vmCaps.isAdapted(m) ? '' : ' ⚠' }}</option>
          </select>
          <!-- v7.0 U8：上游有、本地能力表无的模型显式提示（避免「模型可见档位不能用」） -->
          <p v-if="appState.models.video && !vmCaps.isAdapted(appState.models.video)" class="text-[11.5px] text-warning mt-1.5">{{ t('vmUnadaptedHint') }}</p>
          <p v-if="vmCaps.isPaidTag(appState.models.video)" class="text-[11.5px] text-warning mt-1.5">{{ t('modelPaidHint') }}</p>
          <p v-else-if="vmCaps.priceText(appState.models.video)" class="mt-1.5 text-[11.5px] text-success">{{ vmCaps.priceText(appState.models.video) }}</p>

          <!-- 三模型差异对比（选模型阶段详细说明） -->
          <div v-if="vmCaps.allCapabilities().length > 0" class="mt-3 rounded border border-rule bg-paper p-3">
            <p class="mb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">{{ t('vmDiffTitle') }}</p>
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
                    <td class="whitespace-nowrap pr-3 py-0.5 text-muted">{{ t('vmColPrice') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'p' + item.model" class="px-2 py-0.5" :class="item.caps.price === 'paid' ? 'text-amber-400' : 'text-green-400'">
                      {{ vmCaps.priceText(item.model) }}
                    </td>
                  </tr>
                  <tr>
                    <td class="whitespace-nowrap pr-3 py-0.5 text-muted">{{ t('vmColMode') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'m' + item.model" class="px-2 py-0.5">
                      {{ vmCaps.modeOptions(item.model).map((x) => x.label).join(' · ') }}
                    </td>
                  </tr>
                  <tr>
                    <td class="whitespace-nowrap pr-3 py-0.5 text-muted">{{ t('vmColDuration') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'d' + item.model" class="px-2 py-0.5">
                      {{ vmDurationsLabel(item.caps.durations) }}
                    </td>
                  </tr>
                  <tr>
                    <td class="whitespace-nowrap pr-3 py-0.5 text-muted">{{ t('vmColResolution') }}</td>
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
                    <td class="whitespace-nowrap pr-3 py-0.5 text-muted">{{ t('vmColNegative') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'n' + item.model" class="px-2 py-0.5">
                      {{ item.caps.supports_negative ? t('vmYes') : t('vmNo') }}
                    </td>
                  </tr>
                  <tr>
                    <td class="whitespace-nowrap pr-3 py-0.5 text-muted">{{ t('vmColRefVideo') }}</td>
                    <td v-for="item in vmCaps.allCapabilities()" :key="'v' + item.model" class="px-2 py-0.5">
                      {{ item.caps.supports_ref_video ? t('vmYes') : t('vmNo') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="hint mt-2">{{ vmCaps.descOf(appState.models.video) }}</p>
          </div>
        </div>
      </div>
      <div class="mt-4 flex items-center gap-2">
        <button class="btn btn-primary" @click="saveModels">{{ t('save') }}</button>
        <span v-if="modelSaveStatus === 'ok'" class="text-[11.5px] text-success">{{ t('modelSaved') }}</span>
        <span v-if="modelSaveStatus === 'error'" class="text-[11.5px] text-danger">{{ modelErrorMsg }}</span>
      </div>
    </div>
  </div>

  <!-- 工作目录 -->
  <div class="panel mb-4 overflow-hidden">
    <div
      v-if="collapsed.workspace"
      class="panel-head collapse-header cursor-pointer"
      role="button"
      tabindex="0"
      @click="toggleConfigPanel('workspace')"
    >
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">03</span>
        <span class="shrink-0 text-[12.5px] font-medium text-ink-2">{{ t('workspaceTitle') }}</span>
        <span class="truncate text-[10.5px]" :class="appState.activeWorkspace ? 'text-ink-2' : 'text-muted'">
          {{ appState.activeWorkspace ? (appState.workspaces.find((w) => w.path === appState.activeWorkspace)?.name || appState.activeWorkspace) : t('workspaceNone') }}
        </span>
      </div>
      <span class="mono text-[11px] text-muted">＋</span>
    </div>
    <div v-else class="px-4 pb-4 pt-3.5">
      <div class="mb-3 flex items-center justify-between gap-3 border-b border-rule pb-3">
        <h2 class="panel-title">
          <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">03</span>
          {{ t('workspaceTitle') }}
        </h2>
        <div class="flex items-center gap-1">
          <span class="chip" :class="appState.activeWorkspace ? 'chip-success' : ''">
            {{ appState.activeWorkspace ? t('workspaceActive') : t('workspaceNone') }}
          </span>
          <button class="btn btn-quiet btn-xs" @click="toggleConfigPanel('workspace')">−</button>
        </div>
      </div>
      <div v-if="isRegression" class="mb-3 rounded border border-accent/40 bg-accent/10 px-3 py-2 text-[11.5px] text-accent">{{ t('workspaceRegressionHint') }}</div>
      <div v-if="appState.activeWorkspace" class="mb-3 rounded border border-accent/40 bg-accent/10 px-3 py-2">
        <p class="text-[10.5px] text-muted">{{ t('workspaceCurrentActive') }}</p>
        <p class="mt-0.5 text-[12.5px] font-medium text-ink">{{ appState.workspaces.find((w) => w.path === appState.activeWorkspace)?.name || appState.activeWorkspace }}</p>
        <p class="mono mt-0.5 truncate text-[10.5px] text-muted">{{ appState.activeWorkspace }}</p>
      </div>
      <div class="mb-4 flex flex-wrap gap-2">
        <input v-model="workspacePath" :placeholder="t('workspacePathPlaceholder')" readonly class="field min-w-40 flex-1" />
        <input v-model="workspaceName" :placeholder="t('workspaceNamePlaceholder')" class="field w-36" />
        <button class="btn btn-secondary" @click="onBrowse">{{ t('workspaceBrowse') }}</button>
        <button class="btn btn-primary" @click="onAddWorkspace">{{ t('workspaceAdd') }}</button>
      </div>
      <div class="mb-2 flex items-baseline gap-2">
        <h3 class="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">{{ t('workspaceListTitle') }}</h3>
        <span class="hint">{{ t('workspaceListHint') }}</span>
      </div>
      <div class="space-y-1.5">
        <div
          v-for="ws in appState.workspaces"
          :key="ws.path"
          class="flex items-center justify-between gap-3 rounded border border-rule bg-paper px-3 py-2"
        >
          <div class="min-w-0 flex-1">
            <p class="truncate text-[12.5px] text-ink">{{ wsDisplayName(ws) }}</p>
            <p class="mono truncate text-[10.5px] text-muted">{{ ws.path }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-1">
            <span v-if="ws.path === appState.activeWorkspace" class="chip chip-success">{{ t('workspaceActiveBadge') }}</span>
            <button v-else class="btn btn-ghost btn-xs" @click="activateWorkspace(ws.path)">
              {{ t('workspaceActivate') }}
            </button>
            <button v-if="!ws.is_default" class="btn btn-quiet btn-xs text-danger" @click="removeWorkspaceEntry(ws.path)">
              {{ t('workspaceRemove') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 快速重试（v8.0：到条件自动开启 + 频率） -->
  <div class="panel mb-4 overflow-hidden">
    <div
      v-if="collapsed.retry"
      class="panel-head collapse-header cursor-pointer"
      role="button"
      tabindex="0"
      :aria-expanded="!collapsed.retry"
      @click="toggleConfigPanel('retry')"
    >
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">04</span>
        <span class="shrink-0 text-[12.5px] font-medium text-ink-2">{{ t('fastRetry.settingsTitle') }}</span>
        <span class="truncate text-[10.5px] text-muted">
          {{ fastRetryAuto
            ? tf('fastRetry.autoOnShort', { x: fastRetryPerMinute, y: fastRetryMinutes })
            : t('fastRetry.autoOffShort') }}
        </span>
      </div>
      <span class="mono text-[11px] text-muted">＋</span>
    </div>
    <div v-else class="px-4 pb-4 pt-3.5">
      <div class="mb-3 flex items-center justify-between gap-3 border-b border-rule pb-3">
        <h2 class="panel-title">
          <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">04</span>
          {{ t('fastRetry.settingsTitle') }}
        </h2>
        <div class="flex items-center gap-1">
          <span class="chip" :class="fastRetryAuto ? 'chip-success' : ''">
            {{ fastRetryAuto
              ? tf('fastRetry.autoOnShort', { x: fastRetryPerMinute, y: fastRetryMinutes })
              : t('fastRetry.autoOffShort') }}
          </span>
          <button class="btn btn-quiet btn-xs" @click="toggleConfigPanel('retry')">−</button>
        </div>
      </div>

      <label class="flex cursor-pointer select-none items-start gap-3">
        <input v-model="fastRetryAuto" type="checkbox" class="check mt-0.5" />
        <span>
          <span class="block text-[12.5px] font-medium text-ink">{{ t('fastRetry.autoLabel') }}</span>
          <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('fastRetry.autoHint') }}</span>
        </span>
      </label>

      <div class="mt-3 flex flex-wrap items-end gap-3">
        <label>
          <span class="label">{{ t('fastRetry.perMinute') }}</span>
          <input
            v-model.number="fastRetryPerMinute"
            type="number"
            min="1"
            max="120"
            step="1"
            class="field w-24"
          />
        </label>
        <label>
          <span class="label">{{ t('fastRetry.minutes') }}</span>
          <input
            v-model.number="fastRetryMinutes"
            type="number"
            min="1"
            max="30"
            step="1"
            class="field w-24"
          />
        </label>
        <button class="btn btn-primary btn-sm" @click="saveFastRetrySettings">{{ t('save') }}</button>
        <span v-if="fastRetrySaveStatus === 'ok'" class="text-[11.5px] text-success">
          {{ t('fastRetry.autoSaved') }}
        </span>
      </div>
      <p class="hint mt-2">{{ t('fastRetry.autoScope') }}</p>
    </div>
  </div>

  <!-- 隐私设置（3.4：GA4 配置开关） -->
  <div class="panel mb-4 overflow-hidden">
    <div
      v-if="collapsed.privacy"
      class="panel-head collapse-header cursor-pointer"
      role="button"
      tabindex="0"
      :aria-expanded="!collapsed.privacy"
      @click="toggleConfigPanel('privacy')"
    >
      <div class="flex min-w-0 items-baseline gap-2.5">
        <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">05</span>
        <span class="shrink-0 text-[12.5px] font-medium text-ink-2">{{ t('privacyTitle') }}</span>
        <span class="truncate text-[10.5px] text-muted">
          {{ gaOptOut ? t('gaStatOff') : t('gaStatOn') }}
        </span>
      </div>
      <span class="mono text-[11px] text-muted">＋</span>
    </div>
    <div v-else class="px-4 pb-4 pt-3.5">
      <div class="mb-3 flex items-center justify-between gap-3 border-b border-rule pb-3">
        <h2 class="panel-title">
          <span class="mono text-[9.5px] tracking-[0.08em] text-muted/70">05</span>
          {{ t('privacyTitle') }}
        </h2>
        <div class="flex items-center gap-1">
          <span class="chip" :class="gaOptOut ? 'chip-success' : ''">
            {{ gaOptOut ? t('gaStatOff') : t('gaStatOn') }}
          </span>
          <button class="btn btn-quiet btn-xs" @click="toggleConfigPanel('privacy')">−</button>
        </div>
      </div>
      <label class="flex cursor-pointer select-none items-start gap-3">
        <input v-model="gaOptOut" type="checkbox" class="check mt-0.5" @change="toggleGaOptOut" />
        <span>
          <span class="block text-[12.5px] font-medium text-ink">{{ t('gaOptOutLabel') }}</span>
          <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('gaOptOutHint') }}</span>
        </span>
      </label>

      <!-- 上报信息透明化说明（3.4：采集范围 + 隐私承诺） -->
      <div class="mt-4 rounded border border-rule bg-paper px-3 py-3 text-[11px] leading-relaxed">
        <p class="mb-2 font-medium text-ink-2">{{ t('gaReportTitle') }}</p>
        <ul class="list-disc space-y-1 ps-4 text-muted">
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
