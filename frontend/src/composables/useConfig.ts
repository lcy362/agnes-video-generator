import { reactive, ref, computed } from 'vue'
import { appState } from '@/store'
import * as api from '@/api'
import { t } from '@/i18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useGa } from './useGa'

const { showToast } = useToast()
const { confirmAsync } = useConfirm()
const { trackEvent } = useGa()

// ── API Key ──
const apiKeyStatus = ref<'none' | 'configured' | 'env'>('none')
// 多 Key（v5.0 优化）：当前 Key 数 + 采集来源 + 去重后的 Key 列表（掩码 + 来源 + 稳定 id，无明文）
const keyCount = ref(0)
const keySource = ref('')
// domain: 该 Key 绑定的域名后缀（''=未绑定，回退全局域名）；persistable: 是否可持久化（仅 config 来源）
const keyList = ref<{ id: string; mask: string; source: string; domain: string; persistable: boolean }[]>([])

function isApiKeyConfigured() {
  return apiKeyStatus.value !== 'none'
}

async function saveApiKey(key: string) {
  const r = await api.saveApiKey(key)
  if (r.ok) {
    trackEvent('config_action', { action: 'save_api_key' })
    apiKeyStatus.value = 'configured'
    await loadKeyInfo()
  }
}

async function loadKeyInfo() {
  try {
    const d = await api.getConfigKeys()
    keyCount.value = d.key_count || 0
    keySource.value = d.source || ''
    keyList.value = d.keys || []
    // 同步 Key 状态：source 以 'env' 开头（env:1 / mixed:...）→ env；有 Key → configured
    if (keyCount.value > 0) {
      apiKeyStatus.value = keySource.value.startsWith('env') ? 'env' : 'configured'
    } else {
      apiKeyStatus.value = 'none'
    }
  } catch (e) {
    console.error('load /api/config/keys failed:', e)
  }
}

// 保存单个 Key 绑定的域名（config 来源可持久化；env 来源前端不会调用）
async function saveKeyDomain(id: string, domain: string) {
  const r = await api.saveConfigKeyDomain(id, domain)
  if (r.ok) {
    trackEvent('config_action', { action: 'save_key_domain', domain: domain || '(unset)' })
    showToast(t('keyDomainSaved'), 3000)
    keyList.value = (await api.getConfigKeys()).keys || []
    return true
  }
  showToast(r.detail || t('failSaveKeyDomain'), 4500)
  return false
}

// per-key 域名自动探测：逐 key 探测并补写 key -> domain 映射，返回结果供 UI 提示
const detectingKeys = ref(false)
let lastDetectAt = 0
async function detectKeyDomains(force = false): Promise<{ updated: number; failed: string[] } | null> {
  // 防抖：10 秒内不重复触发（避免频繁探测外部接口）
  if (detectingKeys.value || Date.now() - lastDetectAt < 10000) {
    showToast(t('detectKeysBusy'), 2500)
    return null
  }
  detectingKeys.value = true
  try {
    const d = await api.detectConfigKeyDomains(force)
    lastDetectAt = Date.now()
    showToast(t('detectKeysDone') + ': ' + (d.applied || 0), 3000)
    keyList.value = (await api.getConfigKeys()).keys || []
    const failed = (d.results || []).filter((x: any) => !x.ok).map((x: any) => x.mask)
    return { updated: d.applied || 0, failed }
  } catch (e: any) {
    showToast(e?.message || t('failDetectKeys'), 4500)
    return null
  } finally {
    detectingKeys.value = false
  }
}

async function removeKey(id: string) {
  if (!(await confirmAsync(t('removeKeyConfirm')))) return false
  const r = await api.removeConfigKey(id)
  if (r.ok) {
    trackEvent('config_action', { action: 'remove_api_key' })
    if (r.still_active) {
      showToast(t('keyStillActive') + ': ' + r.removed, 3500)
    } else {
      showToast(t('removedKey') + ': ' + r.removed, 3000)
    }
    keyCount.value = r.key_count || 0
    keySource.value = r.source || ''
    keyList.value = (await api.getConfigKeys()).keys || []
    if (keyCount.value > 0) {
      apiKeyStatus.value = keySource.value.startsWith('env') ? 'env' : 'configured'
    } else {
      apiKeyStatus.value = 'none'
    }
    return true
  }
  showToast(r.detail || t('failRemoveKey'), 4500)
  return false
}

async function saveMultiKeys(keysText: string) {
  const parts = keysText
    .split(/[\n,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (parts.length === 0) return false
  // 已有 Key 时自动切换「追加」模式：新 Key 与现有 Key 合并，无需重输旧 Key
  const append = keyCount.value > 0
  const r = await api.saveConfigKeys(parts, append)
  if (r.ok) {
    trackEvent('config_action', { action: append ? 'add_api_key' : 'save_multi_api_keys', count: parts.length })
    keyCount.value = r.key_count || 0
    keySource.value = r.source || ''
    // source 以 'env' 开头（env:1 / mixed:...）→ env 优先；否则按 config 计
    if (keyCount.value > 0) {
      apiKeyStatus.value = keySource.value.startsWith('env') ? 'env' : 'configured'
    } else {
      apiKeyStatus.value = 'none'
    }
    return true
  }
  return false
}

async function clearApiKey() {
  if (apiKeyStatus.value === 'env') {
    showToast(t('clearEnvHint'), 3500)
    return
  }
  if (!(await confirmAsync(t('clearConfirm')))) return
  const r = await api.clearApiKey()
  if (r.ok) {
    trackEvent('config_action', { action: 'clear_api_key' })
    apiKeyStatus.value = 'none'
  } else {
    const d = await r.json().catch(() => ({}))
    showToast(d.detail || 'Failed to clear', 4500)
  }
}

// ── 模型 ──
const modelSyncStatus = ref<'idle' | 'syncing' | 'ok' | 'error'>('idle')
const modelSaveStatus = ref<'idle' | 'ok' | 'error'>('idle')
const modelErrorMsg = ref('')

// 2.5-flash 已正式上线（无内测标记）；pro 系列为付费模型
function isBetaModel(m: string): boolean {
  // 保留通用性：仍匹配任何带 "beta" 字样的模型（未来若有新 beta 模型）
  return typeof m === 'string' && /beta/i.test(m)
}

function isPaidModel(m: string): boolean {
  return (
    typeof m === 'string' &&
    (/agnes-2\.5-pro|agnes-2\.5-pro-alpha/.test(m) || m === 'agnes-video-2.5')
  )
}

const betaHintVisible = computed(() => {
  const val = (appState.models.text || '').replace(t('modelBetaTag'), '')
  return isBetaModel(val)
})

async function loadModels() {
  try {
    const r = await fetch('/api/models')
    if (r.ok) {
      const d = await r.json()
      if (d.models) appState.modelListCache = d.models
      if (d.video_capabilities) appState.videoCapabilities = d.video_capabilities
    }
  } catch (e) {
    console.error('load /api/models failed:', e)
  }
  try {
    const cd = await api.getConfig()
    const sel = cd.models || {}
    appState.models = { text: sel.text || '', image: sel.image || '', video: sel.video || '' }
  } catch (e) {
    console.error('load model config failed:', e)
  }
}

async function syncModels() {
  modelSyncStatus.value = 'syncing'
  try {
    const r = await fetch('/api/models?refresh=1')
    if (r.ok) {
      const d = await r.json()
      if (d.models) appState.modelListCache = d.models
      if (d.video_capabilities) appState.videoCapabilities = d.video_capabilities
      modelSyncStatus.value = 'ok'
      setTimeout(() => (modelSyncStatus.value = 'idle'), 1500)
    } else {
      modelSyncStatus.value = 'error'
      setTimeout(() => (modelSyncStatus.value = 'idle'), 1500)
    }
  } catch (e) {
    modelSyncStatus.value = 'error'
    setTimeout(() => (modelSyncStatus.value = 'idle'), 1500)
  }
}

async function saveModels() {
  if (!appState.models.text) {
    modelSaveStatus.value = 'error'
    modelErrorMsg.value = t('modelTextRequired')
    return
  }
  try {
    const r = await api.saveModels(appState.models)
    if (r.ok) {
      trackEvent('config_action', { action: 'save_models', text_model: appState.models.text })
      modelSaveStatus.value = 'ok'
      setTimeout(() => (modelSaveStatus.value = 'idle'), 2000)
    } else {
      const d = await r.json().catch(() => ({}))
      modelErrorMsg.value = d.detail || t('modelSaveFailed')
      modelSaveStatus.value = 'error'
    }
  } catch (e) {
    modelErrorMsg.value = t('networkError')
    modelSaveStatus.value = 'error'
  }
}

// ── 域名 ──
const domainSaveStatus = ref<'idle' | 'ok' | 'error'>('idle')
const domainErrorMsg = ref('')

async function saveDomain() {
  const domain = appState.agnesDomain
  try {
    const r = await api.saveDomain(domain)
    if (r.ok) {
      trackEvent('config_action', { action: 'save_domain', domain })
      domainSaveStatus.value = 'ok'
      setTimeout(() => (domainSaveStatus.value = 'idle'), 2000)
    } else {
      const d = await r.json().catch(() => ({}))
      domainErrorMsg.value = d.detail || t('domainSaveFailed')
      domainSaveStatus.value = 'error'
    }
  } catch (e) {
    domainErrorMsg.value = t('networkError')
    domainSaveStatus.value = 'error'
  }
}

// ── 水印 ──
async function toggleWatermark(enabled: boolean) {
  const r = await api.setWatermark(enabled)
  if (r.ok) {
    trackEvent('config_action', { action: 'toggle_watermark', enabled: enabled ? 'on' : 'off' })
    appState.watermarkEnabled = enabled
    showToast(enabled ? t('watermarkEnabled') : t('watermarkDisabled'))
  }
}

// ── 工作区 ──
const isRegression = computed(() => appState.workingDirSource === 'regression')

function wsDisplayName(ws: any): string {
  if (ws && ws.is_default) return t('workspaceDefault')
  return (ws && (ws.name || ws.path)) || ''
}

async function renderWorkspaces() {
  try {
    const d = await api.getWorkspaces()
    const cfg = await api.getConfig()
    appState.workspaces = d.workspaces || []
    appState.activeWorkspace = d.active_workspace || ''
    appState.workingDirSource = cfg.working_dir_source || 'config'
  } catch (e) {
    console.error('renderWorkspaces error:', e)
  }
}

async function activateWorkspace(path: string) {
  const r = await api.activateWorkspace(path)
  if (r.ok) {
    await renderWorkspaces()
  } else {
    const d = await r.json().catch(() => ({}))
    showToast(d.detail || t('failSwitchMode'), 4500)
  }
}

async function removeWorkspaceEntry(path: string) {
  if (!(await confirmAsync(t('workspaceRemoveConfirm')))) return
  const r = await api.removeWorkspace(path)
  if (r.ok) {
    await renderWorkspaces()
  } else {
    const d = await r.json().catch(() => ({}))
    showToast(d.detail || t('failSwitchMode'), 4500)
  }
}

async function browseDirectory(): Promise<string | null> {
  try {
    const d = await api.pickDirectory()
    if (d.ok && d.path) return d.path
  } catch (e) {
    showToast(t('networkError'), 3500)
  }
  return null
}

async function addWorkspace(path: string, name: string) {
  if (!path) return
  const r = await api.addWorkspace(path, name)
  if (r.ok) {
    await renderWorkspaces()
  } else {
    const d = await r.json().catch(() => ({}))
    showToast(d.detail || t('failSwitchMode'), 4500)
  }
}

export function useConfig() {
  return {
    apiKeyStatus,
    keyCount,
    keySource,
    keyList,
    isApiKeyConfigured,
    saveApiKey,
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
    loadModels,
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
  }
}
