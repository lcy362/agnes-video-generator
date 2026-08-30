import { ref } from 'vue'
import { appState } from '@/store'
import * as api from '@/api'
import { t } from '@/i18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import type { Artifact } from '@/types'

const { showToast } = useToast()
const { confirmAsync } = useConfirm()

const artifactsAreaVisible = ref(false)
const artifactGroups = ref<{ stepKey: string; items: Artifact[] }[]>([])
const isRunning = ref(false)

const previewCache: Record<string, string> = {}

let refreshTimer: ReturnType<typeof setTimeout> | null = null

function scheduleArtifactRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => {
    if (appState.currentArtifactsTaskId) loadArtifacts()
    refreshTimer = null
  }, 800)
}

const stepLabelMap: Record<string, string> = {
  scene_config: 'cStepSceneConfig',
  image_analysis: 'cStepImageAnalysis',
  story: 'cStepStory',
  character_ref: 'cStepCharacterRef',
  script: 'cStepScript',
  end_frame_prompts: 'cStepEndFramePrompts',
  end_frame_gen: 'cStepEndFrameGen',
  video_gen: 'cStepVideoGen',
  audio: 'cStepAudio',
  subtitle: 'cStepSubtitle',
  concatenate: 'cStepConcat',
  split_text: 'mStepSplit',
  scene_prompts: 'mStepScenePrompts',
  generate_anchor: 'aStepGenerateAnchor',
  clip_prompts: 'aStepClipPrompts',
  clip_gen: 'aStepClipGen',
}

async function loadArtifacts() {
  const taskId = appState.currentArtifactsTaskId
  if (!taskId) return
  try {
    const data = await api.getArtifacts(taskId)
    if (!data.ok) throw new Error(data.detail || 'Failed to load artifacts')
    const existing = (data.artifacts || []).filter((a: Artifact) => a.exists)
    if (existing.length === 0) {
      artifactsAreaVisible.value = false
      return
    }
    artifactsAreaVisible.value = true
    isRunning.value = data.task_status === 'running'

    const groups: Record<string, Artifact[]> = {}
    existing.forEach((a: Artifact) => {
      if (!groups[a.step_key]) groups[a.step_key] = []
      groups[a.step_key].push(a)
    })
    artifactGroups.value = Object.entries(groups).map(([stepKey, items]) => ({ stepKey, items }))
  } catch (e) {
    console.error('loadArtifacts error:', e)
    artifactsAreaVisible.value = false
  }
}

function artifactLabel(art: Artifact): string {
  let label = t(art.label_key) || art.label_key
  if (art.scope_index !== null && art.scope_index !== undefined) {
    label = label.replace('{index}', String(art.scope_index + 1))
  }
  return label
}

function artifactIcon(art: Artifact): string {
  const icons: Record<string, string> = { text: '📄', image: '🖼️', video: '🎬', audio: '🔊', json: '📋', subtitle: '💬' }
  return icons[art.category] || '📄'
}

function artifactFileUrl(art: Artifact): string {
  return api.getArtifactFileUrl(appState.currentArtifactsTaskId!, art.artifact_id)
}

function formatSize(size: number): string {
  return size > 1048576 ? (size / 1048576).toFixed(1) + ' MB' : (size / 1024).toFixed(0) + ' KB'
}

async function toggleArtifactPreview(art: Artifact, el: HTMLElement) {
  const fileUrl = artifactFileUrl(art)
  if (el.dataset.expanded === '1') {
    el.dataset.expanded = '0'
    el.textContent = t('clickToPreview')
    return
  }
  el.dataset.expanded = '1'
  if (previewCache[fileUrl]) {
    el.textContent = previewCache[fileUrl]
    return
  }
  el.textContent = t('loading') + '...'
  try {
    const resp = await fetch(fileUrl)
    let text = await resp.text()
    if (text.length > 2000) text = text.substring(0, 2000) + '\n...'
    previewCache[fileUrl] = text
    el.textContent = text
  } catch (e: any) {
    el.textContent = 'Error: ' + e.message
  }
}

const imageModalUrl = ref('')

function openImageModal(url: string) {
  imageModalUrl.value = url
}

function closeImageModal() {
  imageModalUrl.value = ''
}

async function confirmDeleteArtifact(art: Artifact) {
  const taskId = appState.currentArtifactsTaskId
  if (!taskId) return
  let preview
  try {
    preview = await api.getArtifactCascadePreview(taskId, art.artifact_id)
    if (!preview.ok) throw new Error(preview.detail)
  } catch (e: any) {
    showToast(t('artifactDeleteFailed') + ': ' + e.message, 4500)
    return
  }
  const fileList = (preview.files_to_delete || []).map((f: string) => '  • ' + f).join('\n')
  const stepList = (preview.steps_to_reset || []).map((s: string) => '  • ' + s).join('\n')
  const msg =
    t('deleteArtifactConfirm') + '\n\n' + t('willDelete') + ':\n' + fileList + '\n\n' + t('willResetSteps') + ':\n' + stepList
  if (!(await confirmAsync(msg))) return
  await deleteArtifact(taskId, art.artifact_id)
}

async function deleteArtifact(taskId: string, artifactId: string) {
  try {
    const data = await api.deleteArtifact(taskId, artifactId)
    if (!data.ok) throw new Error(data.detail || 'Delete failed')
    Object.keys(previewCache).forEach((k) => delete previewCache[k])
    try {
      const taskData = await api.getTask(taskId)
      if (taskData.task_type) {
        loadArtifacts()
      }
    } catch {
      /* ignore */
    }
  } catch (e: any) {
    showToast(t('artifactDeleteFailed') + ': ' + e.message, 4500)
  }
}

export function useArtifacts() {
  return {
    artifactsAreaVisible,
    artifactGroups,
    isRunning,
    imageModalUrl,
    stepLabelMap,
    loadArtifacts,
    scheduleArtifactRefresh,
    artifactLabel,
    artifactIcon,
    artifactFileUrl,
    formatSize,
    toggleArtifactPreview,
    openImageModal,
    closeImageModal,
    confirmDeleteArtifact,
  }
}
