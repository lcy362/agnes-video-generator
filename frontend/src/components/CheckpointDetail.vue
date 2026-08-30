<script setup lang="ts">
import { ref, computed } from 'vue'
import { t, currentLang as lang } from '@/i18n'
import { appState } from '@/store'
import * as api from '@/api'
import { useTasks } from '@/composables/useTasks'
import { useProgress } from '@/composables/useProgress'
import { useToast } from '@/composables/useToast'
import { copyText } from '@/utils/clipboard'

const props = defineProps<{ taskId: string; checkpoint: string }>()

const { switchMode, loadTaskList } = useTasks()
const { startPolling, setRunning, setProgressMessageHtml } = useProgress()
const { showToast } = useToast()

// 四卡片选择：AI 帮我改 / 我自己改 / 外部 Agent 改 / 在线编辑
const activeCard = ref<'ai' | 'self' | 'agent' | 'edit'>('ai')

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
    if (d.ok) checkpointData.value = d
  } catch {
    /* ignore */
  } finally {
    loadingData.value = false
  }
}
loadCheckpoint()

// ── 通道 1：AI 帮我改（P1 已实现后端；ai-modify 为 P1.5，此处先做前端调用适配）──
async function runAiModify() {
  const req = aiRequest.value.trim()
  if (!req) return
  aiLoading.value = true
  aiResult.value = null
  try {
    // 当前检查点第一个可编辑产物作为修改目标（简化：通道 1 一期由产物矩阵驱动）
    // 兼容 manifest 字段（editable）与 artifacts 接口字段（deletable）
    const arts = (checkpointData.value?.artifacts || []).filter(
      (a: any) => a.editable !== false && a.deletable !== false && a.exists !== false,
    )
    const target = arts[0]
    if (!target) throw new Error(t('noEditableArtifact'))
    // 先按 impact 预计算
    const imp = await api.getImpact(props.taskId, props.checkpoint, [target.artifact_id])
    impactData.value = imp
    aiResult.value = { target: target.artifact_id, preview: null }
  } catch (e: any) {
    showToast(e.message || t('aiModifyFailed'), 4500)
  } finally {
    aiLoading.value = false
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
//     - 通道 1（AI 修改完成）→ 携带 AI 修改目标产物
//     - 通道 4（在线编辑已保存）→ 携带已保存的产物
//     - 其余 → 无修改，直接确认继续
async function continueTask() {
  let modified: string[] = []
  if (activeCard.value === 'ai' && aiResult.value?.target) {
    modified = [aiResult.value.target]
  } else if (activeCard.value === 'edit') {
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
  <div class="mt-4 p-4 bg-paper/30 rounded-2xl border border-amber-500/30">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-amber-400">
        ⏸ {{ t('awaitingUser') }} · {{ t('checkpointTitle') }}: {{ checkpointLabel }}
      </h3>
      <div class="flex gap-2">
        <button class="text-xs px-2.5 py-1.5 bg-accent text-accent-ink rounded-lg transition" @click="regen" :disabled="confirming">
          {{ t('regenCurrent') }}
        </button>
        <button class="text-xs px-2.5 py-1.5 border border-rule text-ink-2 rounded-lg transition hover:border-accent/40" @click="switchToAutoAndRun">
          ⚡ {{ t('switchToAuto') }}
        </button>
      </div>
    </div>

    <p class="text-xs text-muted mb-3">{{ t('awaitingUserTip') }}</p>

    <!-- 统一继续按钮：无论是否修改，均走同一 approve 逻辑（自动收集当前通道的修改产物） -->
    <div class="flex items-center justify-center mb-4">
      <button
        class="text-sm px-6 py-2 bg-emerald-600 text-white rounded-lg transition hover:bg-emerald-500 disabled:opacity-50 shadow-sm"
        :disabled="confirming"
        @click="continueTask"
      >
        {{ confirming ? t('submitting') : t('continueConfirm') }}
      </button>
      <span class="text-xs text-muted ml-3">{{ t('continueNoChangeHint') }}</span>
    </div>

    <!-- 四卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
      <button class="p-3 rounded-xl border text-left transition" :class="activeCard === 'ai' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40'" @click="activeCard = 'ai'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleAi') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleAiDesc') }}</div>
      </button>
      <button class="p-3 rounded-xl border text-left transition" :class="activeCard === 'self' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40'" @click="activeCard = 'self'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleSelf') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleSelfDesc') }}</div>
      </button>
      <div class="p-3 rounded-xl border transition flex flex-col" :class="activeCard === 'agent' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40'">
        <button class="text-left" @click="activeCard = 'agent'">
          <div class="text-sm font-medium text-ink-2">{{ t('handleAgent') }}</div>
          <div class="text-xs text-muted mt-0.5">{{ t('handleAgentDesc') }}</div>
        </button>
        <a :href="moreToolsHref" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-[10px] text-accent hover:text-ink transition-colors mt-1.5">🔗 {{ t('agentMoreTools') }}</a>
      </div>
      <button class="p-3 rounded-xl border text-left transition"
        :class="editableTextArts.length
          ? (activeCard === 'edit' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40')
          : 'border-rule/40 bg-paper-2/20 opacity-45 cursor-not-allowed'"
        :disabled="!editableTextArts.length"
        @click="activeCard = 'edit'">
        <div class="text-sm font-medium" :class="editableTextArts.length ? 'text-ink-2' : 'text-muted'">{{ t('handleEdit') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleEditDesc') }}</div>
        <div v-if="!editableTextArts.length" class="text-[10px] text-muted mt-1">🚫 {{ t('editTextOnly') }}</div>
      </button>
    </div>

    <!-- 通道 1 面板 -->
    <div v-if="activeCard === 'ai'" class="space-y-3">
      <div>
        <label class="block text-xs text-muted mb-1">{{ t('aiModifyRequest') }}</label>
        <textarea v-model="aiRequest" rows="2" class="w-full glass-input rounded-lg px-3 py-2 text-sm text-ink resize-y" :placeholder="t('aiModifyRequestPlaceholder')"></textarea>
      </div>
      <button class="text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition disabled:opacity-50" :disabled="aiLoading" @click="runAiModify">
        {{ aiLoading ? t('aiModifyApplying') : t('aiModifyStart') }}
      </button>
      <!-- 影响预计算展示（修改前提示） -->
      <div v-if="impactData" class="p-3 rounded-lg bg-paper/50 border border-rule/60 space-y-1.5">
        <p class="text-xs font-medium text-red-400">{{ t('impactTitle') }}: {{ (impactData.affected || []).length }}</p>
        <ul class="text-xs text-muted space-y-0.5 max-h-24 overflow-auto">
          <li v-for="a in impactData.affected || []" :key="a">• {{ a }}</li>
        </ul>
        <p v-if="impactData.retained?.length" class="text-xs text-emerald-400">{{ t('impactRetained') }}: {{ (impactData.retained || []).length }}</p>
        <p class="text-xs text-accent mt-1">{{ t('continueToApply') }}</p>
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

    <!-- 通道 4 面板：在线编辑 -->
    <div v-else class="space-y-3">
      <p class="text-xs text-muted">{{ t('handleEditDesc') }}</p>
      <div v-if="editableTextArts.length" class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span v-for="a in editableTextArts" :key="a.artifact_id" class="text-ink-2">
          📄 {{ artLabel(a) }}
        </span>
      </div>
      <p v-else class="text-xs text-amber-400">{{ t('noEditableText') }}</p>
      <button class="text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition disabled:opacity-40 disabled:cursor-not-allowed" :disabled="!editableTextArts.length" @click="openEditModal">
        {{ t('editOpen') }}
      </button>
    </div>
  </div>

  <!-- 在线编辑弹窗 -->
  <div v-if="editModalOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70" @click.self="closeEditModal">
    <div class="w-full max-w-3xl max-h-[85vh] flex flex-col glass-card rounded-2xl overflow-hidden">
      <div class="flex items-center justify-between px-5 py-3 border-b border-rule/50 bg-paper-2/50">
        <h3 class="text-sm font-semibold text-ink-2">✏️ {{ t('editModalTitle') }} · {{ checkpointLabel }}</h3>
        <button class="text-xs px-2.5 py-1.5 border border-rule text-ink-2 rounded-lg transition hover:border-accent/40" @click="closeEditModal">{{ t('close') }}</button>
      </div>

      <div class="flex-1 overflow-auto p-5 space-y-5">
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
