<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useProgress } from '@/composables/useProgress'
import { useArtifacts } from '@/composables/useArtifacts'
import { useNavigation } from '@/composables/useNavigation'
import ProgressHeader from './ProgressHeader.vue'
import StepTimeline from './StepTimeline.vue'
import ArtifactCard from './ArtifactCard.vue'
import CheckpointDetail from './CheckpointDetail.vue'
import FeedbackPanel from './FeedbackPanel.vue'
import { isDeterministicError } from '@/utils/feedback'

const {
  progressPct,
  progressMessage,
  resultVideoVisible,
  resultVideoSrc,
  steps,
  stepStates,
  taskFailed,
  failedMessage,
  awaitingCheckpoint,
  retryCount,
  connectionLost,
  retryFailedTask,
  mountProgressPage,
  unmountProgressPage,
} = useProgress()

const {
  artifactsAreaVisible,
  artifactGroups,
  imageModalUrl,
  stepLabelMap,
  closeImageModal,
} = useArtifacts()

const { goBack } = useNavigation()

// 产物流按执行顺序排列（steps 顺序优先，未知 step 保持后端相对顺序）
const orderedGroups = computed(() => {
  const order = steps.value.map((s) => s.key)
  const map: Record<string, (typeof artifactGroups.value)[0]> = {}
  artifactGroups.value.forEach((g) => {
    if (!map[g.stepKey]) map[g.stepKey] = g
  })
  const keys = Object.keys(map)
  keys.sort((a, b) => {
    const ia = order.indexOf(a)
    const ib = order.indexOf(b)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  return keys.map((k) => map[k])
})

// 折叠状态：默认只展开「最近一个环节」的产物，之前的历史环节自动折叠
// （暂停点时主体聚焦当前检查点产物；自动模式时主体聚焦最近生成环节）
const collapsed = ref<Record<string, boolean>>({})
function toggleCollapse(key: string) {
  collapsed.value[key] = !collapsed.value[key]
}

// 当前聚焦分组 = 最新产物分组（暂停点高亮 + 大图展示；自动模式为主体的最近环节）
const focusGroup = computed(() => {
  const groups = orderedGroups.value
  return groups.length ? groups[groups.length - 1].stepKey : null
})

function isCollapsed(key: string): boolean {
  if (key in collapsed.value) return collapsed.value[key]
  // 仅展开最近一个环节，之前的全部自动折叠（页面主体留给当前环节/暂停点产物）
  return key !== focusGroup.value
}

// 当前暂停点产物分组（用于高亮 + 大图展示）
const checkpointGroup = computed(() => {
  if (!awaitingCheckpoint.value) return null
  return focusGroup.value
})

// 步骤定位：点击时间线滚动到对应产物分组
function scrollToStep(stepKey: string) {
  const el = document.getElementById('artifact-group-' + stepKey)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// ── v6.1 问题反馈：失败任务重试（断点续传自愈偶发故障）──
async function onRetryTask() {
  const taskId = appState.progressTaskId
  if (taskId) await retryFailedTask(taskId)
}

// ── 任务信息展示（优化 v6.1：展示用户输入提示词与各项配置）──
const taskInfo = ref<any>(null)
const taskInfoOpen = ref(true)

// 各任务类型：输入提示词字段 → i18n label
const INPUT_FIELDS: Record<string, { field: string; label: string }[]> = {
  creative: [{ field: 'idea', label: 'tiIdea' }],
  manuscript: [{ field: 'manuscript_text', label: 'tiManuscript' }],
  anchor: [
    { field: 'script_text', label: 'tiScript' },
    { field: 'anchor_prompt', label: 'tiAnchorPrompt' },
  ],
  poetry: [{ field: 'poem_text', label: 'tiPoem' }],
  simple: [{ field: 'prompt', label: 'tiPrompt' }],
}

// 各任务类型：关键配置展示（字段 → i18n label）
const CONFIG_FIELDS: Record<string, { field: string; label: string; fmt?: (v: any) => string }[]> = {
  creative: [
    { field: 'video_width', label: 'tiWidth', fmt: (v) => String(v ?? '') },
    { field: 'video_height', label: 'tiHeight', fmt: (v) => String(v ?? '') },
    { field: 'scene_count', label: 'tiScenes', fmt: (v) => String(v ?? '') },
    { field: 'chaining_mode', label: 'tiChaining' },
    { field: 'style', label: 'tiStyle' },
  ],
  manuscript: [
    { field: 'scene_count', label: 'tiScenes', fmt: (v) => String(v ?? '') },
    { field: 'paragraph_count', label: 'tiParagraphs', fmt: (v) => String(v ?? '') },
  ],
  anchor: [
    { field: 'audio_source', label: 'tiAudioSource' },
    { field: 'video_width', label: 'tiWidth', fmt: (v) => String(v ?? '') },
    { field: 'video_height', label: 'tiHeight', fmt: (v) => String(v ?? '') },
  ],
  poetry: [
    { field: 'video_width', label: 'tiWidth', fmt: (v) => String(v ?? '') },
    { field: 'video_height', label: 'tiHeight', fmt: (v) => String(v ?? '') },
    { field: 'scene_count', label: 'tiScenes', fmt: (v) => String(v ?? '') },
    { field: 'style', label: 'tiStyle' },
  ],
  simple: [
    { field: 'mode', label: 'tiMode' },
    { field: 'duration', label: 'tiDuration', fmt: (v) => String(v ?? '') },
  ],
}

const taskInputs = computed(() => INPUT_FIELDS[appState.currentTaskType] || [])
const taskConfigs = computed(() => CONFIG_FIELDS[appState.currentTaskType] || [])

// v6.1 问题反馈：诊断报告用的关键配置字符串列表（复用 taskConfigs 展示逻辑）
const feedbackConfigs = computed(() =>
  taskConfigs.value
    .map((c) => {
      const v = c.fmt ? c.fmt(taskInfo.value?.[c.field]) : taskInfo.value?.[c.field]
      return v ? `${t(c.label)}: ${v}` : null
    })
    .filter((s): s is string => !!s),
)

// v6.1 问题反馈：错误是否为确定性故障（命中则切换引导文案 + 弱化重试按钮）
const deterministicError = computed(() => isDeterministicError(failedMessage.value))

onMounted(async () => {
  const taskId = appState.progressTaskId
  if (!taskId) return
  taskInfo.value = await mountProgressPage(taskId, appState.currentDirName)
})

onUnmounted(() => {
  unmountProgressPage()
})
</script>

<template>
  <div class="progress-page min-h-screen">
    <ProgressHeader />

    <div class="max-w-6xl mx-auto px-4 py-6 lg:flex lg:gap-6">
      <!-- 左侧：支持项目卡片（置顶，与首页一致）+ 环节状态列表（宽屏） -->
      <aside class="hidden lg:block w-[240px] shrink-0">
        <div class="sticky top-[120px]">
          <div class="sidebar-card">
            <div class="stitle">{{ t('adSupportTitle') }}</div>
            <p class="text-muted text-xs leading-relaxed mb-2">{{ t('adSupportDesc') }}</p>
            <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener">{{ t('adStar') }}</a>
            <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adStarDesc') }}</p>
            <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ t('adAdblock') }}</a>
            <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adAdblockDesc') }}</p>
            <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ t('adClick') }}</a>
            <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adClickDesc') }}</p>
            <p class="text-muted text-xs mt-2 leading-relaxed">{{ t('adThanks') }}</p>
          </div>
          <StepTimeline @locate="scrollToStep" />
        </div>
      </aside>

      <!-- 主工作台 -->
      <main class="flex-1 min-w-0">
        <!-- 移动端环节胶囊条 -->
        <div class="lg:hidden mb-4">
          <StepTimeline horizontal @locate="scrollToStep" />
        </div>

        <!-- 状态区 -->
        <div class="glass-card rounded-2xl p-5 mb-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-muted">{{ t('progress') }}</span>
            <span class="text-sm text-accent font-medium">{{ progressPct }}%</span>
          </div>
          <div class="w-full bg-paper-2/50 rounded-full h-2.5 overflow-hidden">
            <div class="bg-accent h-2.5 rounded-full transition-all duration-500" :style="{ width: progressPct + '%' }"></div>
          </div>

          <!-- 失败信息 -->
          <div v-if="taskFailed" class="mt-4 p-4 bg-red-950 border border-red-800 rounded-lg space-y-2">
            <p class="text-red-400 font-medium">{{ t('genFailed') }}</p>
            <p class="text-muted text-xs">{{ failedMessage || t('genFailedMsg') }}</p>
            <!-- v6.1 问题反馈：重试引导（偶发故障优先断点续传自愈，多次失败再上报） -->
            <div class="pt-2 border-t border-red-800/60 space-y-2">
              <!-- 引导文案：确定性故障切换为「重试可能无效」 -->
              <p class="text-xs leading-relaxed" :class="deterministicError ? 'text-amber-400' : 'text-muted'">
                {{ deterministicError ? t('fbDeterministicHint') : t('fbRetryHint') }}
              </p>
              <div class="flex items-center gap-3 flex-wrap">
                <button
                  class="text-xs px-3 py-1.5 transition rounded-lg"
                  :class="deterministicError ? 'bg-paper-2/40 border border-rule text-muted hover:text-ink-2' : 'bg-accent text-accent-ink hover:opacity-90'"
                  @click="onRetryTask"
                >
                  ↻ {{ t('fbRetryBtn') }}
                </button>
                <span v-if="retryCount > 0" class="text-xs text-muted">{{ t('fbRetriedN').replace('{n}', String(retryCount)) }}</span>
              </div>
              <!-- v6.1 问题反馈：反馈区（渐进展开 + 复制 + FAQ + GitHub Issue） -->
              <FeedbackPanel
                v-if="appState.progressTaskId"
                :task-id="appState.progressTaskId"
                :task-type="appState.currentTaskType || 'creative'"
                :mode="taskInfo?.mode"
                :failed-step="taskInfo?.current_step || ''"
                :error-message="failedMessage || ''"
                :retry-count="retryCount"
                :configs="feedbackConfigs"
                @retry="onRetryTask"
              />
            </div>
          </div>
          <!-- 进度消息（HTML 渲染，来自后端安全文案） -->
          <div v-else class="mt-4 text-sm text-muted" v-html="progressMessage"></div>

          <!-- 1.7：连接异常横幅（连续轮询失败 N 次后展示） -->
          <div v-if="connectionLost" class="mt-3 rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2 text-xs text-red-400">
            {{ t('connLost') }}
          </div>
        </div>

        <!-- 任务信息（用户输入提示词 + 各项配置，v6.1） -->
        <div v-if="taskInfo" class="glass-card rounded-2xl mb-4 overflow-hidden">
          <button class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-paper-2/30 transition" @click="taskInfoOpen = !taskInfoOpen">
            <span class="text-sm transition-transform" :class="taskInfoOpen ? 'rotate-90' : ''">▸</span>
            <span class="text-sm font-medium text-ink-2">{{ t('taskInfo') }}</span>
            <span class="ml-auto text-xs text-muted">{{ taskInfoOpen ? t('ppCollapse') : t('ppExpand') }}</span>
          </button>

          <div v-show="taskInfoOpen" class="px-4 pb-4 space-y-3">
            <!-- 输入提示词 -->
            <div v-for="f in taskInputs" :key="f.field" class="space-y-1">
              <div class="text-xs text-muted">{{ t(f.label) }}</div>
              <p class="text-sm text-ink-2 bg-paper-2/30 rounded-lg px-3 py-2 whitespace-pre-wrap break-words leading-relaxed">
                {{ taskInfo[f.field] || '—' }}
              </p>
            </div>

            <!-- 关键配置 -->
            <div v-if="taskConfigs.length" class="flex flex-wrap gap-x-6 gap-y-2 pt-1">
              <div v-for="c in taskConfigs" :key="c.field" class="flex items-center gap-1.5 text-xs">
                <span class="text-muted">{{ t(c.label) }}:</span>
                <span class="text-ink-2 font-mono">{{ c.fmt ? c.fmt(taskInfo[c.field]) : (taskInfo[c.field] || '—') }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 产物流：逐步追加（按环节分组，已完成折叠） -->
        <div v-if="artifactsAreaVisible" class="space-y-3">
          <div
            v-for="g in orderedGroups"
            :id="'artifact-group-' + g.stepKey"
            :key="g.stepKey"
            class="artifact-group glass-card rounded-2xl overflow-hidden"
            :class="g.stepKey === checkpointGroup ? 'border-amber-500/40 ring-1 ring-amber-500/20' : ''"
          >
            <button
              class="w-full flex items-center gap-3 px-4 py-3 text-left transition hover:bg-paper-2/30"
              :class="g.stepKey === checkpointGroup ? 'bg-amber-500/5' : ''"
              @click="toggleCollapse(g.stepKey)"
            >
              <span class="text-sm transition-transform" :class="isCollapsed(g.stepKey) ? '' : 'rotate-90'">▸</span>
              <span class="text-sm font-medium" :class="g.stepKey === checkpointGroup ? 'text-amber-400' : 'text-ink-2'">{{ t(stepLabelMap[g.stepKey] || g.stepKey) }}</span>
              <span v-if="g.stepKey === checkpointGroup" class="text-xs px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400 shrink-0">⏸ {{ t('awaitingUser') }}</span>
              <span class="text-xs text-muted">{{ g.items.length }} 项</span>
              <span class="ml-auto text-xs text-muted">{{ isCollapsed(g.stepKey) ? t('ppExpand') : t('ppCollapse') }}</span>
            </button>

            <div v-show="!isCollapsed(g.stepKey)" class="px-4 pb-4 space-y-2" :class="g.stepKey === checkpointGroup ? 'px-5 pb-5' : ''">
              <ArtifactCard v-for="art in g.items" :key="art.artifact_id" :art="art" :large="g.stepKey === checkpointGroup" />
            </div>
          </div>
        </div>

        <!-- 暂停审查区：紧跟最新产物（就近操作） -->
        <CheckpointDetail
          v-if="awaitingCheckpoint && appState.currentTaskId"
          :task-id="appState.currentTaskId"
          :checkpoint="awaitingCheckpoint"
        />

        <!-- 结果视频 -->
        <div v-if="resultVideoVisible" class="mt-4 p-4 glass-card rounded-2xl">
          <p class="text-green-400 text-sm font-medium mb-2">{{ t('videoComplete') }}</p>
          <video :src="resultVideoSrc" controls class="w-full rounded-lg max-h-96"></video>
          <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-xs">
            <span>🎉</span>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">{{ t('doneTipTiktok') }}</a>
            <span class="text-ink/10 select-none">·</span>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('doneTipMore') }}</a>
          </div>
        </div>

        <!-- 官网导流资源（更多资源链接，与主页一致） -->
        <div class="mt-8 border-t border-rule/30 pt-6 text-center">
          <p class="text-xs text-muted mb-3">{{ t('moreResources') }}</p>
          <div class="flex justify-center flex-wrap gap-x-5 gap-y-2 text-xs">
            <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('projectHome') }}</a>
            <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">{{ t('onlineDemo') }}</a>
            <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('usageGuide') }}</a>
            <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('promptTips') }}</a>
            <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('faqTitle') }}</a>
            <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('modelOverview') }}</a>
            <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('apiCall') }}</a>
            <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('apiDocs') }}</a>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('appScenarios') }}</a>
            <a href="https://video.lichuanyang.top/zh/guides/free-ai-tools" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('agentMoreTools') }}</a>
            <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">📖 GitHub</a>
          </div>
        </div>
      </main>
    </div>

    <!-- 图片放大弹窗 -->
    <div v-if="imageModalUrl" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 cursor-pointer" @click="closeImageModal">
      <img :src="imageModalUrl" class="max-w-[90vw] max-h-[90vh] rounded-lg" />
    </div>
  </div>
</template>
