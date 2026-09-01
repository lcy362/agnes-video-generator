// 统一 API 封装：与后端 21 个端点一一对应
// 任务提交类用 FormData（含文件上传），其余用 JSON

async function request<T = any>(url: string, options?: RequestInit): Promise<T> {
  const r = await fetch(url, options)
  // 3.1：统一检查 r.ok——此前 5xx / 错误页（HTML）会被误解析成 JSON 抛出
  // 误导性错误；现在抛带后端 detail 的可读错误
  if (!r.ok) {
    let detail = ''
    try {
      const d = await r.json()
      detail = d?.detail || d?.error || ''
    } catch {
      /* 非 JSON 响应体（如 502 错误页） */
    }
    throw new Error(detail || `请求失败 (HTTP ${r.status})`)
  }
  return r.json()
}

// ── 配置 ──
export function getConfig() {
  return request('/api/config')
}
export function saveApiKey(apiKey: string) {
  const form = new FormData()
  form.append('api_key', apiKey)
  return fetch('/api/config', { method: 'POST', body: form })
}
export function clearApiKey() {
  return fetch('/api/config', { method: 'DELETE' })
}
// 多 API Key（v5.0 优化：多 Key 轮询 + 限流整合）
export function getConfigKeys() {
  return request('/api/config/keys')
}
export function saveConfigKeys(keys: string[], append = false) {
  const form = new FormData()
  form.append('keys_json', JSON.stringify(keys))
  if (append) form.append('append', 'true')
  return fetch('/api/config/keys', { method: 'POST', body: form }).then((r) => r.json())
}
export function removeConfigKey(id: string) {
  // 用掩码接口返回的稳定 id 定位删除，不回传 Key 明文
  const form = new FormData()
  form.append('id', id)
  return fetch('/api/config/keys', { method: 'DELETE', body: form }).then((r) => r.json())
}
export function saveDomain(domain: string) {
  const form = new FormData()
  form.append('domain', domain)
  return fetch('/api/config/domain', { method: 'POST', body: form })
}
// per-key 域名绑定（v2.3）：为单个 config Key 保存其绑定的域名后缀
export function saveConfigKeyDomain(id: string, domain: string) {
  const form = new FormData()
  form.append('id', id)
  form.append('domain', domain)
  return fetch('/api/config/keys/domain', { method: 'POST', body: form }).then((r) => r.json())
}
// per-key 域名自动探测：逐 key 按候选域名探测，返回每个 key 的探测结果
export function detectConfigKeyDomains(force = false) {
  const form = new FormData()
  if (force) form.append('force', 'true')
  return fetch('/api/config/keys/detect', { method: 'POST', body: form }).then((r) => r.json())
}
export function saveModels(models: { text?: string; image?: string; video?: string }) {
  const form = new FormData()
  if (models.text) form.append('text', models.text)
  if (models.image) form.append('image', models.image)
  if (models.video) form.append('video', models.video)
  return fetch('/api/config/models', { method: 'POST', body: form })
}
export function setWatermark(enabled: boolean) {
  const form = new FormData()
  form.append('enabled', String(enabled))
  return fetch('/api/config/watermark', { method: 'POST', body: form })
}

// ── 模型 ──
export function getModels(refresh = false) {
  return request('/api/models' + (refresh ? '?refresh=1' : ''))
}

// ── 音色 ──
export function getVoices() {
  return request('/api/voices')
}

// ── 工作区 ──
export function getWorkspaces() {
  return request('/api/workspaces')
}
export function activateWorkspace(path: string) {
  const form = new FormData()
  form.append('path', path)
  return fetch('/api/workspaces/active', { method: 'POST', body: form })
}
export function addWorkspace(path: string, name: string) {
  const form = new FormData()
  form.append('path', path)
  form.append('name', name)
  return fetch('/api/workspaces', { method: 'POST', body: form })
}
export function removeWorkspace(path: string) {
  const form = new FormData()
  form.append('path', path)
  return fetch('/api/workspaces', { method: 'DELETE', body: form })
}
export function pickDirectory() {
  return request('/api/workspaces/pick-directory')
}

// ── 任务列表与详情 ──
export function getTasks() {
  return request('/api/tasks')
}
export function getTask(taskId: string) {
  return request('/api/tasks/' + taskId)
}
export function resumeTask(taskId: string) {
  return fetch('/api/tasks/' + taskId + '/resume', { method: 'POST' }).then((r) => r.json())
}
export function stopTask(taskId: string) {
  return fetch('/api/tasks/' + taskId + '/stop', { method: 'POST' }).then((r) => r.json())
}
export function deleteTask(taskId: string) {
  return fetch('/api/tasks/' + taskId, { method: 'DELETE' }).then((r) => r.json())
}

// ── v6.1 问题反馈：任务诊断（二期）──
export function getTaskDiagnostics(taskId: string) {
  return request('/api/tasks/' + taskId + '/diagnostics')
}

// ── 产物 ──
export function getArtifacts(taskId: string) {
  return request('/api/tasks/' + taskId + '/artifacts')
}
export function getArtifactFileUrl(taskId: string, artifactId: string) {
  return '/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId) + '/file'
}
export function getArtifactCascadePreview(taskId: string, artifactId: string) {
  return request('/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId) + '/cascade-preview')
}
export function deleteArtifact(taskId: string, artifactId: string) {
  return fetch('/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId), { method: 'DELETE' }).then(
    (r) => r.json(),
  )
}

// ── 诗词场景提示词 ──
export function getPoetryScenePrompt(params: Record<string, string>) {
  const qs = new URLSearchParams(params)
  return request('/api/poetry-scene-prompt?' + qs.toString())
}

// ── 任务提交（FormData 多文件上传）──
export function submitSimple(form: FormData) {
  return fetch('/api/tasks/simple', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitCreative(form: FormData) {
  return fetch('/api/tasks/creative', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitManuscript(form: FormData) {
  return fetch('/api/tasks/manuscript', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitAnchor(form: FormData) {
  return fetch('/api/tasks/anchor', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitPoetry(form: FormData) {
  return fetch('/api/tasks/poetry', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitImage(form: FormData) {
  return fetch('/api/image/generate', { method: 'POST', body: form }).then((r) => r.json())
}

// ── v6.0 手动模式 ──
export function switchTaskMode(taskId: string, mode: 'auto' | 'manual') {
  const form = new FormData()
  form.append('mode', mode)
  return fetch('/api/tasks/' + taskId + '/mode', { method: 'POST', body: form }).then((r) => r.json())
}
export function getCheckpoints(taskId: string) {
  return request('/api/tasks/' + taskId + '/checkpoints')
}
export function getCheckpoint(taskId: string, checkpoint: string) {
  return request('/api/tasks/' + taskId + '/checkpoints/' + encodeURIComponent(checkpoint))
}
export function getImpact(
  taskId: string,
  checkpoint: string,
  modifiedArtifactIds: string[],
  paramUpdates?: Record<string, any>,
) {
  const qs = new URLSearchParams({
    modified_artifact_ids: JSON.stringify(modifiedArtifactIds),
    param_updates: JSON.stringify(paramUpdates || {}),
  })
  return request(
    '/api/tasks/' + taskId + '/checkpoints/' + encodeURIComponent(checkpoint) + '/impact?' + qs.toString(),
  )
}
export function approveCheckpoint(
  taskId: string,
  checkpoint: string,
  modifiedArtifactIds: string[],
  paramUpdates: Record<string, any>,
  confirmed: boolean,
) {
  const form = new FormData()
  form.append('modified_artifact_ids', JSON.stringify(modifiedArtifactIds))
  form.append('param_updates', JSON.stringify(paramUpdates))
  form.append('confirmed', String(confirmed))
  return fetch('/api/tasks/' + taskId + '/checkpoints/' + encodeURIComponent(checkpoint) + '/approve', {
    method: 'POST',
    body: form,
  }).then((r) => r.json())
}
export function regenCheckpoint(taskId: string, checkpoint: string) {
  return fetch('/api/tasks/' + taskId + '/checkpoints/' + encodeURIComponent(checkpoint) + '/regen', {
    method: 'POST',
  }).then((r) => r.json())
}
export function uploadArtifact(taskId: string, artifactId: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return fetch('/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId) + '/upload', {
    method: 'POST',
    body: form,
  }).then((r) => r.json())
}
