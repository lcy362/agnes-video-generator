<script setup lang="ts">
import { ref, computed } from 'vue'
import { t, tf, currentLang as lang } from '@/i18n'
import { appState } from '@/store'
import * as api from '@/api'
import { useTasks } from '@/composables/useTasks'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import { copyText } from '@/utils/clipboard'
import ExperimentalBadge from './shared/ExperimentalBadge.vue'
import RefImagesInput from './shared/RefImagesInput.vue'
import { JIMENG_FAQ_PATH, JIMENG_GUIDE_PATH, siteUrl } from '@/utils/siteLinks'

const props = defineProps<{ taskId: string; checkpoint: string }>()

const { switchMode, loadTaskList } = useTasks()
const { startPolling, setRunning, setProgressMessageHtml } = useProgress()
const { showToast } = useToast()

// 四卡片选择：AI 帮我改 / 我自己改 / 外部 Agent 改 / 在线编辑 +（v7.6）外部工具协作
const activeCard = ref<'ai' | 'self' | 'agent' | 'edit' | 'collab'>('ai')

// 官网"其他免费 AI 工具"页面（官网提供 zh / en 多语言路径，其余语言回退 en）
const moreToolsHref = computed(() => {
  const l = lang.value === 'zh' ? 'zh' : 'en'
  return `https://video.lichuanyang.top/${l}/guides/free-ai-tools`
})
const aiRequest = ref('')
const aiLoading = ref(false)
const aiResult = ref<any>(null)
const checkpointData = ref<any>(null)
const loadingData = ref(false)

// ── v8.1：references 检查点「逐段补图」 ──
const sceneRefs = computed<any[]>(() =>
  props.checkpoint === 'references' ? checkpointData.value?.scenes || [] : [],
)
const sceneRefEdits = ref<Record<number, File[]>>({})
const sceneRefSaving = ref<number | null>(null)
// 保守额度：先给人物板 + 风格板预留 2 张，剩余才是本段内容图
const sceneRefMax = computed(() => {
  const limit = Number(appState.videoCapabilities?.[appState.models.video]?.max_ref_images ?? 5)
  return Math.max(1, limit - 2)
})

async function saveSceneRefs(index: number) {
  const files = sceneRefEdits.value[index] || []
  if (!files.length) return
  sceneRefSaving.value = index
  try {
    const d = await api.setSceneRefs(props.taskId, index, files)
    if (d.ok) {
      const item = sceneRefs.value.find((x: any) => x.index === index)
      if (item) {
        item.ref_count = (d.ref_images || []).length
        item.ref_files = (d.ref_images || []).map((p: string) => p.split('/').pop())
      }
      delete sceneRefEdits.value[index]
      showToast(t('cpDone'))
    } else {
      if (d.detail) showToast(String(d.detail))
    }
  } catch (e: any) {
    if (e?.detail || e?.message) showToast(String(e.detail || e.message))
  } finally {
    sceneRefSaving.value = null
  }
}

const impactData = ref<any>(null)
const impactLoading = ref(false)
const confirming = ref(false)

const checkpointLabel = computed(() => {
  const map: Record<string, string> = {
    image_analysis: 'cpImageAnalysis', story: 'cpStory', script: 'cpScript',
    character_ref: 'cpCharacterRef', end_frame_prompts: 'cpEndFramePrompts',
    end_frame_gen: 'cpEndFrameGen',
    scenes: 'cpScenes', references: 'cpReferences', videos: 'cpVideos',
    audio: 'cpAudio', subtitle: 'cpSubtitle', final: 'cpFinal',
  }
  return t(map[props.checkpoint] || props.checkpoint)
})

// 拉取检查点产物元数据（驱动 AI 修改目标与"自己改"路径清单）
async function loadCheckpoint() {
  loadingData.value = true
  try {
    const d = await api.getCheckpoint(props.taskId, props.checkpoint)
    if (d.ok) {
      checkpointData.value = d
      // v7.6 外部素材模式：videos 检查点以「即梦协作」为主，默认选中该卡片
      if (d.external_hint && props.checkpoint === 'videos') activeCard.value = 'collab'
    }
  } catch {
    /* ignore */
  } finally {
    loadingData.value = false
  }
}
loadCheckpoint()

// ── v7.6 外部素材模式：外部工具协作卡片（external_hint 非空时展示）──
const collabHint = computed(() => checkpointData.value?.external_hint || null)
const collabProvider = computed<any>(() => collabHint.value?.provider || {})
const collabProviderName = computed(() => collabProvider.value.name || '')
// v7.6：外部素材模式下 videos 检查点以「即梦协作」为主，隐藏其余操作方式卡片
const collabPrimary = computed(() => !!collabHint.value && props.checkpoint === 'videos')
// 协作卡内提示词标题（如「给 Jimeng (Dreamina) 的视频生成提示词」）
const collabPromptLabel = computed(() =>
  tf('checkpoint.collab.prompt_label', { name: collabProviderName.value }))
// v7.6 即梦协作仍在试验阶段：气泡 + 官网说明/常见问题链接（路径由工具注册表下发，
// 语言前缀按当前 UI 语言拼接，见 utils/siteLinks.ts）
const collabExperimental = computed(() => !!collabProvider.value.experimental)
const collabGuideHref = computed(() => siteUrl(collabProvider.value.guide_path || JIMENG_GUIDE_PATH))
const collabFaqHref = computed(() => siteUrl(collabProvider.value.faq_path || JIMENG_FAQ_PATH))
// 可批量导入的检查点：参考图 → image，视频片段 → video
const importKind = computed(() => (props.checkpoint === 'references' ? 'image' : props.checkpoint === 'videos' ? 'video' : ''))
const canImport = computed(() => !!importKind.value && !!collabHint.value)
const copyingPrompt = ref(false)
const importing = ref(false)
const importResults = ref<any[]>([])

async function copyCollabPrompt() {
  const ok = await copyText(collabHint.value?.prompt || '')
  if (!ok) return
  copyingPrompt.value = true
  setTimeout(() => (copyingPrompt.value = false), 1500)
}

// 批量导入外部产物 → 归一化 + 探针回显 → 刷新检查点详情
async function onImportFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return
  importing.value = true
  try {
    const d = await api.importArtifacts(props.taskId, files, importKind.value)
    if (!d.ok) throw new Error((d as any).detail || t('failContinue'))
    importResults.value = d.results || []
    await loadCheckpoint()
    showToast(t('checkpoint.import.done'))
  } catch (err: any) {
    showToast(err?.message || t('failContinue'), 4500)
  } finally {
    importing.value = false
    input.value = ''
  }
}

// ── 通道 1：AI 帮我改（文本 / 图片产物；视频/音频不支持）──
const aiSupportedCategories = ['text', 'json', 'subtitle']
const aiImageExts = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp']
function isAiModifiable(a: any): boolean {
  const cat = String(a.category || '')
  const rel = String(a.file_relpath || a.path || '')
  const ext = rel.slice(rel.lastIndexOf('.')).toLowerCase()
  return (
    a.editable !== false && a.deletable !== false && a.exists !== false &&
    (aiSupportedCategories.includes(cat) || cat === 'image' || aiImageExts.includes(ext))
  )
}
const aiModifiableArts = computed(() =>
  (checkpointData.value?.artifacts || []).filter((a: any) => isAiModifiable(a)),
)

async function runAiModify() {
  const req = aiRequest.value.trim()
  if (!req) return
  const target = aiModifiableArts.value[0]
  if (!target) {
    showToast(t('noEditableArtifact'), 3500)
    return
  }
  aiLoading.value = true
  aiResult.value = null
  try {
    const d = await api.aiModify(props.taskId, props.checkpoint, target.artifact_id, req)
    if (!d.ok) throw new Error(d.detail || t('aiModifyFailed'))
    const isImage = d.category === 'image'
    // 原内容（文本取其内容做 diff；图片直接引文件 URL 预览）
    let originText = ''
    const originUrl = api.getArtifactFileUrl(props.taskId, target.artifact_id)
    if (!isImage) {
      try {
        const r = await fetch(originUrl)
        if (r.ok) originText = await r.text()
      } catch {
        /* 原内容拉取失败则留空 */
      }
    }
    aiResult.value = {
      target: target.artifact_id,
      category: d.category,
      isImage,
      new_content: d.new_content as string,
      diff_summary: d.diff_summary as string,
      originText,
      originUrl,
    }
    // 影响预计算（修改前提示）
    impactData.value = await api.getImpact(props.taskId, props.checkpoint, [target.artifact_id])
  } catch (e: any) {
    showToast(e.message || t('aiModifyFailed'), 4500)
  } finally {
    aiLoading.value = false
  }
}

function dataUrlToFile(dataUrl: string, name: string): Promise<File> {
  return fetch(dataUrl)
    .then((r) => r.blob())
    .then((b) => new File([b], name))
}

// 应用 AI 修改并继续：文本/图片 → 覆盖落盘（upload）→ approve 重置下游 + 恢复执行
async function applyAiAndContinue() {
  const res = aiResult.value
  if (!res?.target) return
  confirming.value = true
  try {
    if (res.new_content) {
      const file = res.isImage
        ? await dataUrlToFile(res.new_content as string, res.target + '.png')
        : new File([res.new_content as string], res.target + '.txt', { type: 'text/plain;charset=utf-8' })
      const up = await api.uploadArtifact(props.taskId, res.target, file)
      if (!up.ok) throw new Error(up.detail || t('artifactSaveFailed'))
    }
    await doApprove([res.target])
  } catch (e: any) {
    showToast(e.message || t('failContinue'), 4500)
  } finally {
    confirming.value = false
  }
}

// ── 影响预计算 ──
async function previewImpact(modifiedIds: string[]) {
  impactLoading.value = true
  try {
    impactData.value = await api.getImpact(props.taskId, props.checkpoint, modifiedIds)
  } finally {
    impactLoading.value = false
  }
}

// ── 确认并继续（approve）──
async function doApprove(modifiedIds: string[], paramUpdates: Record<string, any> = {}) {
  confirming.value = true
  try {
    const d = await api.approveCheckpoint(props.taskId, props.checkpoint, modifiedIds, paramUpdates, true)
    if (!d.ok) throw new Error(d.detail || t('failContinue'))
    await continueAfterConfirm()
  } catch (e: any) {
    showToast(e.message || t('failContinue'), 4500)
  } finally {
    confirming.value = false
  }
}

// 统一恢复执行：清除暂停 UI（setRunning 内部处理）+ 立即展示恢复中消息 + 启动轮询
async function continueAfterConfirm() {
  setRunning(props.taskId)
  setProgressMessageHtml(`<span class="text-accent animate-pulse">${t('resuming')}</span>`)
  await startPolling(props.taskId)
  loadTaskList()
}

// ── 统一继续按钮：无论是否修改，走同一 approve 逻辑。
//   根据当前通道自动收集修改产物：
//     - 通道 1（AI 修改）→ 若已生成结果则先落盘再审批；未生成则直接确认
//     - 通道 4（在线编辑已保存）→ 携带已保存的产物
//     - 其余 → 无修改，直接确认继续
async function continueTask() {
  if (activeCard.value === 'ai') {
    if (aiResult.value?.target) {
      await applyAiAndContinue()
      return
    }
    await doApprove([])
    return
  }
  let modified: string[] = []
  if (activeCard.value === 'edit') {
    modified = Object.keys(savedMap.value).filter((id) => savedMap.value[id])
  }
  await doApprove(modified)
}

// ── 切回自动并继续 ──
async function switchToAutoAndRun() {
  const d = await switchMode(props.taskId, 'auto')
  // 后端切换即继续（resume），前端同步恢复轮询与状态展示
  if (d?.ok) {
    await continueAfterConfirm()
  }
}

// ── 重新生成当前检查点 ──
async function regen() {
  confirming.value = true
  try {
    const d = await api.regenCheckpoint(props.taskId, props.checkpoint)
    if (!d.ok) throw new Error(d.detail || t('failRegen'))
    await continueAfterConfirm()
  } catch (e: any) {
    showToast(e.message || t('failRegen'), 4500)
  } finally {
    confirming.value = false
  }
}

// ── 通道 4：在线编辑（弹窗内修改文本产物 + 与原内容对比）──
const editModalOpen = ref(false)
const editArts = ref<any[]>([])
const editLoading = ref(false)
const origins = ref<Record<string, string>>({})
const edits = ref<Record<string, string>>({})
const savedMap = ref<Record<string, boolean>>({})
const compareMap = ref<Record<string, boolean>>({})
const savingId = ref('')

// 检查点内可编辑的文本类产物（manifest 条目：editable + exists + category；兼容 deletable）
const editableTextArts = computed(() =>
  (checkpointData.value?.artifacts || []).filter(
    (a: any) => a.editable !== false && a.deletable !== false && a.exists && ['text', 'json', 'subtitle'].includes(a.category),
  ),
)

async function openEditModal() {
  const arts = editableTextArts.value
  if (!arts.length) {
    showToast(t('noEditableText'), 3500)
    return
  }
  editModalOpen.value = true
  editLoading.value = true
  editArts.value = []
  origins.value = {}
  edits.value = {}
  savedMap.value = {}
  compareMap.value = {}
  try {
    for (const a of arts) {
      const resp = await fetch(api.getArtifactFileUrl(props.taskId, a.artifact_id))
      const text = await resp.text()
      origins.value[a.artifact_id] = text
      edits.value[a.artifact_id] = text
    }
    editArts.value = arts
  } catch (e: any) {
    showToast(e.message || t('loadFailed'), 4500)
  } finally {
    editLoading.value = false
  }
}

function closeEditModal() {
  editModalOpen.value = false
}

function toggleCompare(id: string) {
  compareMap.value[id] = !compareMap.value[id]
}

// 保存单个产物：调用 upload 接口覆盖回填（记录 modified_artifacts + 刷新清单）
async function saveArtifact(id: string) {
  if (savingId.value) return
  savingId.value = id
  try {
    const file = new File([edits.value[id] || ''], id + '.txt', { type: 'text/plain' })
    const d = await api.uploadArtifact(props.taskId, id, file)
    if (!d.ok) throw new Error(d.detail || t('artifactSaveFailed'))
    savedMap.value[id] = true
    origins.value[id] = edits.value[id]
    showToast(t('artifactSaved'))
  } catch (e: any) {
    showToast(t('artifactSaveFailed') + (e.message ? ': ' + e.message : ''), 3500)
  } finally {
    savingId.value = ''
  }
}

// 弹窗内产物 label（manifest 条目字段为 name_key；兼容 label_key）
function artLabel(a: any): string {
  const key = a.name_key || a.label_key
  let label = t(key) || key || a.artifact_id
  if (a.scope_index !== null && a.scope_index !== undefined) {
    label = label.replace('{index}', String(a.scope_index + 1))
  }
  return label
}
</script>

<template>
  <div class="mt-4 rounded border border-accent/40 bg-paper-2 p-4">
    <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
      <h3 class="flex items-center gap-2 text-[12.5px] font-semibold text-accent">
        <span class="h-1.5 w-1.5 rounded-full" style="background: var(--color-accent)"></span>
        {{ t('awaitingUser') }} · {{ t('checkpointTitle') }}: {{ checkpointLabel }}
      </h3>
      <div class="flex gap-1.5">
        <button class="btn btn-ghost btn-sm" @click="regen" :disabled="confirming">
          {{ t('regenCurrent') }}
        </button>
        <button class="btn btn-ghost btn-sm" @click="switchToAutoAndRun">
          {{ t('switchToAuto') }}
        </button>
      </div>
    </div>

    <p class="hint mb-3">{{ t('awaitingUserTip') }}</p>

    <!-- 统一继续按钮：无论是否修改，均走同一 approve 逻辑（自动收集当前通道的修改产物） -->
    <div class="mb-4 flex flex-wrap items-center justify-center gap-3">
      <button
        class="btn btn-primary px-6"
        :disabled="confirming"
        @click="continueTask"
      >
        {{ confirming ? t('submitting') : t('continueConfirm') }}
      </button>
      <span class="hint">{{ t('continueNoChangeHint') }}</span>
    </div>

    <!-- v8.1：逐段补图（仅 references 检查点；拆段后、提交视频前） -->
    <div v-if="sceneRefs.length && !collabPrimary" class="mb-4 rounded border border-rule bg-paper p-3">
      <div class="mb-1 text-sm font-medium text-ink-2">{{ t('sceneReferenceImages') }}</div>
      <p class="hint mb-3">{{ t('sceneRefDesc') }}</p>
      <div class="space-y-3">
        <div v-for="s in sceneRefs" :key="s.index" class="rounded border border-rule/60 p-2">
          <div class="mb-1 flex items-center justify-between gap-2">
            <div class="flex min-w-0 items-center gap-2">
              <span class="mono text-[11px] text-muted">#{{ s.index + 1 }}</span>
              <span class="truncate text-[11.5px] text-ink-2">{{ s.text }}</span>
            </div>
            <span class="mono shrink-0 text-[10.5px] text-muted">{{ s.ref_count }} / {{ sceneRefMax }}</span>
          </div>
          <RefImagesInput
            :model-value="sceneRefEdits[s.index] || []"
            :max="sceneRefMax"
            @update:model-value="(v: File[]) => (sceneRefEdits[s.index] = v)"
          />
          <div v-if="(sceneRefEdits[s.index] || []).length" class="mt-2">
            <button
              class="btn btn-ghost btn-sm"
              :disabled="sceneRefSaving === s.index"
              @click="saveSceneRefs(s.index)"
            >
              {{ sceneRefSaving === s.index ? t('submitting') : t('save') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 卡片：AI / 自己 / Agent / 在线编辑 +（v7.6）外部工具协作。
         外部素材模式的 videos 检查点仅保留「协作」卡片（其余方式无实际产物可改）。 -->
    <div class="grid grid-cols-1 gap-3 mb-4" :class="collabPrimary ? 'md:grid-cols-1' : (collabHint ? 'md:grid-cols-5' : 'md:grid-cols-4')">
      <button v-if="!collabPrimary && aiModifiableArts.length" class="rounded border p-3 text-left transition" :class="activeCard === 'ai' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'" @click="activeCard = 'ai'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleAi') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleAiDesc') }}</div>
      </button>
      <button v-if="!collabPrimary" class="rounded border p-3 text-left transition" :class="activeCard === 'self' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'" @click="activeCard = 'self'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleSelf') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleSelfDesc') }}</div>
      </button>
      <div v-if="!collabPrimary" class="p-3 rounded-xl border transition flex flex-col" :class="activeCard === 'agent' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'">
        <button class="text-left" @click="activeCard = 'agent'">
          <div class="text-sm font-medium text-ink-2">{{ t('handleAgent') }}</div>
          <div class="text-xs text-muted mt-0.5">{{ t('handleAgentDesc') }}</div>
        </button>
        <a :href="moreToolsHref" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-[10px] text-accent hover:text-ink transition-colors mt-1.5">{{ t('agentMoreTools') }}</a>
        <a href="https://github.com/lcy362/flint" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-[10px] text-accent hover:text-ink transition-colors mt-1.5">{{ t('handleAgentFlint') }}</a>
      </div>
      <button v-if="!collabPrimary" class="rounded border p-3 text-left transition"
        :class="editableTextArts.length
          ? (activeCard === 'edit' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2')
          : 'border-rule/40 bg-paper-2/20 opacity-45 cursor-not-allowed'"
        :disabled="!editableTextArts.length"
        @click="activeCard = 'edit'">
        <div class="text-sm font-medium" :class="editableTextArts.length ? 'text-ink-2' : 'text-muted'">{{ t('handleEdit') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleEditDesc') }}</div>
        <div v-if="!editableTextArts.length" class="text-[10px] text-muted mt-1">{{ t('editTextOnly') }}</div>
      </button>
      <!-- v7.6 外部素材模式：外部工具协作（仅 external_hint 非空时展示） -->
      <button v-if="collabHint" class="rounded border p-3 text-left transition" :class="activeCard === 'collab' ? 'border-accent/40 bg-accent/10' : 'border-rule bg-paper hover:border-rule-2'" @click="activeCard = 'collab'">
        <div class="flex flex-wrap items-center gap-1.5 text-sm font-medium text-ink-2">
          <span>{{ collabProvider.icon }} {{ t('checkpoint.collab.title').replace('{name}', collabProvider.name || '') }}</span>
          <ExperimentalBadge v-if="collabExperimental" />
        </div>
        <div class="text-xs text-muted mt-0.5">{{ collabProvider.name }}</div>
      </button>
    </div>

    <!-- 通道 1 面板 -->
    <div v-if="activeCard === 'ai' && aiModifiableArts.length" class="space-y-3">
      <div>
        <label class="label">{{ t('aiModifyRequest') }}</label>
        <textarea v-model="aiRequest" rows="2" class="field" :placeholder="t('aiModifyRequestPlaceholder')"></textarea>
      </div>
      <button class="btn btn-primary btn-sm" :disabled="aiLoading" @click="runAiModify">
        {{ aiLoading ? t('aiModifyApplying') : t('aiModifyStart') }}
      </button>
      <!-- 影响预计算展示（修改前提示） -->
      <div v-if="impactData" class="p-3 rounded-lg bg-paper/50 border border-rule/60 space-y-1.5">
        <p class="text-xs font-medium text-red-400">{{ t('impactTitle') }}: {{ (impactData.affected || []).length }}</p>
        <ul class="text-xs text-muted space-y-0.5 max-h-24 overflow-auto">
          <li v-for="a in impactData.affected || []" :key="a">• {{ a }}</li>
        </ul>
        <p v-if="impactData.retained?.length" class="text-xs text-emerald-400">{{ t('impactRetained') }}: {{ (impactData.retained || []).length }}</p>
      </div>
      <!-- AI 修改结果预览 -->
      <div v-if="aiResult" class="p-3 rounded-lg bg-paper/50 border border-rule/60 space-y-2">
        <div class="flex items-center justify-between">
          <p class="text-xs font-medium text-emerald-400">{{ t('aiModifyResult') }}</p>
          <p v-if="aiResult.diff_summary" class="text-xs text-muted break-all">{{ aiResult.diff_summary }}</p>
        </div>
        <div v-if="!aiResult.isImage" class="space-y-2">
          <div>
            <label class="label">{{ t('originalContent') }}</label>
            <pre class="text-xs bg-paper-2 rounded px-2 py-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-all text-ink-2">{{ aiResult.originText }}</pre>
          </div>
          <div>
            <label class="label">{{ t('aiModifyRequest') }}</label>
            <textarea v-model="aiResult.new_content" rows="5" class="field" :placeholder="t('editPlaceholder')"></textarea>
          </div>
        </div>
        <div v-else class="grid grid-cols-2 gap-2">
          <img :src="aiResult.originUrl" class="rounded-lg border border-rule/60 max-h-40 object-contain w-full" :alt="t('originalContent')" />
          <img :src="aiResult.new_content" class="rounded-lg border border-emerald-400/40 max-h-40 object-contain w-full" :alt="t('aiModifyResult')" />
        </div>
        <button class="w-full btn btn-primary btn-sm" :disabled="confirming" @click="applyAiAndContinue">
          {{ confirming ? t('aiModifyApplying') : t('applyAndContinue') }}
        </button>
      </div>
    </div>

    <!-- 通道 2 面板 -->
    <div v-else-if="activeCard === 'self'" class="space-y-3">
      <div v-for="art in checkpointData?.artifacts || []" :key="art.artifact_id" class="text-xs">
        <span class="text-muted">{{ art.label_key || art.artifact_id }}:</span>
        <code class="block text-ink-2 bg-paper-2 px-2 py-1 rounded mt-0.5 break-all cursor-pointer hover:border-accent/40 border border-transparent"
          :title="t('copy')"
          @click="copyText(art.abs_path || art.path || '')"
        >{{ art.abs_path || art.path || '' }}</code>
      </div>
      <p class="text-xs text-muted">{{ t('selfEditAffected') }}: {{ t('selfEditAffectedHint') }}</p>
    </div>

    <!-- 通道 3 面板 -->
    <div v-else-if="activeCard === 'agent'" class="space-y-3">
      <p class="text-xs text-muted">{{ t('agentCommand') }}:</p>
      <code class="block text-xs bg-black/40 text-green-300 px-3 py-2 rounded-lg mb-2 break-all whitespace-pre">{{ t('agentCommandLines').replace('{dir}', checkpointData?.working_dir || '') }}</code>
      <p class="text-xs text-muted">{{ t('agentPrompt') }}:</p>
      <textarea rows="3" class="w-full glass-input rounded-lg px-3 py-2 text-sm text-ink font-mono text-xs resize-y" :value="t('agentPromptTemplate').replace('{dir}', checkpointData?.working_dir || '')" readonly></textarea>
    </div>

    <!-- v7.6 通道：外部工具协作 -->
    <div v-else-if="activeCard === 'collab' && collabHint" class="space-y-3">
      <div>
        <div class="flex flex-wrap items-center justify-between gap-2 mb-1">
          <label class="flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <span>{{ collabPromptLabel }}</span>
            <ExperimentalBadge v-if="collabExperimental" />
          </label>
          <div class="flex flex-wrap items-center gap-2 shrink-0">
            <!-- 官网新增的即梦说明与常见问题（含 503 处理），语言前缀随 UI 语言切换 -->
            <a :href="collabGuideHref" target="_blank" rel="noopener"
               class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 glass-input rounded-lg transition hover:border-accent/40">
              {{ t('experimentalGuideLink') }}
            </a>
            <a :href="collabFaqHref" target="_blank" rel="noopener"
               class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 glass-input rounded-lg transition hover:border-accent/40">
              {{ t('experimentalFaqLink') }}
            </a>
            <a v-if="collabProvider.url" :href="collabProvider.url" target="_blank" rel="noopener"
               class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 glass-input rounded-lg transition hover:border-accent/40">
              {{ tf('checkpoint.collab.open_tool', { name: collabProviderName }) }}
            </a>
          </div>
        </div>
        <textarea rows="8" readonly class="w-full glass-input rounded-lg px-3 py-2 text-xs text-ink font-mono resize-y" :value="collabHint.prompt"></textarea>
        <button class="mt-2 text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition" @click="copyCollabPrompt">
          {{ copyingPrompt ? t('checkpoint.collab.copied') : t('checkpoint.collab.copy_prompt') }}
        </button>
      </div>
      <div v-if="collabHint.fill_guide" class="rounded-lg bg-paper/50 border border-rule/60 p-3 space-y-1">
        <p class="text-xs font-medium text-ink-2">{{ t('checkpoint.collab.guide_label') }}</p>
        <p class="text-xs text-muted whitespace-pre-wrap">{{ collabHint.fill_guide }}</p>
      </div>
      <p v-if="collabHint.notes" class="text-xs text-muted whitespace-pre-wrap">{{ collabHint.notes }}</p>

      <!-- 批量导入（仅 references / videos 检查点） -->
      <div v-if="canImport" class="pt-2 border-t border-rule/40 space-y-2">
        <div class="flex flex-wrap items-center gap-3">
          <label class="cursor-pointer px-4 py-2 glass-input rounded-lg text-xs transition inline-block hover:border-blue-500/30">
            <span>{{ importing ? t('submitting') : t('checkpoint.import.select') }}</span>
            <input type="file" multiple :accept="importKind === 'image' ? 'image/*' : 'video/*'" class="hidden" @change="onImportFiles" />
          </label>
          <span class="text-xs text-muted">{{ t('checkpoint.import.title') }} · {{ t('checkpoint.import.kind') }}: {{ importKind }}</span>
        </div>
        <div v-if="importResults.length" class="overflow-auto rounded-lg border border-rule/40">
          <table class="w-full text-xs">
            <thead class="text-muted bg-paper-2/40">
              <tr>
                <th class="text-left px-2 py-1 font-medium"></th>
                <th class="text-left px-2 py-1 font-medium">{{ t('checkpoint.probe.duration') }}</th>
                <th class="text-left px-2 py-1 font-medium">{{ t('checkpoint.probe.resolution') }}</th>
                <th class="text-left px-2 py-1 font-medium">{{ t('checkpoint.probe.fps') }}</th>
                <th class="text-left px-2 py-1 font-medium">{{ t('checkpoint.probe.audio') }}</th>
                <th class="text-left px-2 py-1 font-medium">{{ t('checkpoint.probe.codec') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in importResults" :key="i" class="border-t border-rule/30 text-ink-2">
                <td class="px-2 py-1 break-all">
                  {{ r.file }}
                  <span v-if="r.scene" class="text-[10px] text-muted"> → {{ r.scene }}</span>
                </td>
                <td class="px-2 py-1">{{ r.probe?.duration != null ? r.probe.duration + 's' : '—' }}</td>
                <td class="px-2 py-1">{{ r.probe?.width != null ? r.probe.width + '×' + r.probe.height : '—' }}</td>
                <td class="px-2 py-1">{{ r.probe?.fps != null ? r.probe.fps : '—' }}</td>
                <td class="px-2 py-1">{{ r.probe?.has_audio ? '✓' : '✗' }}</td>
                <td class="px-2 py-1 break-all">{{ r.probe?.vcodec || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 通道 4 面板：在线编辑（默认/回退） -->
    <div v-else class="space-y-3">
      <p class="text-xs text-muted">{{ t('handleEditDesc') }}</p>
      <div v-if="editableTextArts.length" class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span v-for="a in editableTextArts" :key="a.artifact_id" class="text-ink-2">
          {{ artLabel(a) }}
        </span>
      </div>
      <p v-else class="text-xs text-amber-400">{{ t('noEditableText') }}</p>
      <button class="text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition disabled:opacity-40 disabled:cursor-not-allowed" :disabled="!editableTextArts.length" @click="openEditModal">
        {{ t('editOpen') }}
      </button>
    </div>
  </div>

  <!-- 在线编辑弹窗 -->
  <div v-if="editModalOpen" class="modal-backdrop" @click.self="closeEditModal">
    <div class="modal flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden">
      <div class="flex items-center justify-between gap-3 border-b border-rule px-5 py-3">
        <h3 class="text-[13px] font-semibold tracking-[-0.01em] text-ink">{{ t('editModalTitle') }} · {{ checkpointLabel }}</h3>
        <button class="btn btn-ghost btn-sm" @click="closeEditModal">{{ t('close') }}</button>
      </div>

      <div class="flex-1 space-y-4 overflow-auto p-5">
        <div v-if="editLoading" class="text-sm text-muted text-center py-10">{{ t('loading') }}...</div>

        <div v-for="a in editArts" :key="a.artifact_id" class="rounded-xl border border-rule/60 p-4 space-y-3">
          <!-- 标题 + 保存状态 -->
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-ink-2">{{ artLabel(a) }}</span>
            <span v-if="savedMap[a.artifact_id]" class="text-xs px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400">✓ {{ t('artifactSaved') }}</span>
            <span class="ml-auto text-[10px] text-muted font-mono truncate">{{ a.abs_path || a.path || '' }}</span>
          </div>

          <!-- 原内容（可折叠） -->
          <div class="rounded-lg bg-paper/50 border border-rule/40 overflow-hidden">
            <button class="w-full flex items-center gap-2 px-3 py-2 text-left text-xs text-muted hover:bg-paper-2/30 transition" @click="toggleCompare(a.artifact_id)">
              <span class="transition-transform" :class="compareMap[a.artifact_id] ? 'rotate-90' : ''">▸</span>
              <span>{{ t('originalContent') }}</span>
              <span v-if="compareMap[a.artifact_id]" class="ml-auto text-[10px] text-accent">⇄ {{ t('compare') }}</span>
            </button>
            <pre v-show="compareMap[a.artifact_id]" class="text-xs text-muted max-h-48 overflow-auto px-3 pb-3 whitespace-pre-wrap break-words">{{ origins[a.artifact_id] || '' }}</pre>
          </div>

          <!-- 编辑区 -->
          <textarea
            v-model="edits[a.artifact_id]"
            rows="6"
            class="w-full text-xs text-ink-2 bg-paper/70 p-2 rounded-lg border border-accent/40 font-mono resize-y whitespace-pre-wrap leading-relaxed focus:border-accent/70 focus:outline-none"
            :placeholder="t('editPlaceholder')"
          ></textarea>

          <!-- 操作行 -->
          <div class="flex items-center gap-2">
            <button
              class="text-xs px-3 py-1.5 bg-accent text-accent-ink rounded-lg transition disabled:opacity-50"
              :disabled="!!savingId"
              @click="saveArtifact(a.artifact_id)"
            >{{ savingId === a.artifact_id ? t('submitting') : t('editSave') }}</button>
            <button
              class="text-xs px-3 py-1.5 border border-rule text-ink-2 rounded-lg transition hover:border-accent/40"
              :class="compareMap[a.artifact_id] ? 'border-accent/50 text-accent' : ''"
              @click="toggleCompare(a.artifact_id)"
            >{{ t('compare') }}</button>
            <span class="text-[10px] text-muted">{{ t('editArtifactHint') }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
