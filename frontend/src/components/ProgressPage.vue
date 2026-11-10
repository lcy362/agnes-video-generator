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
import FastRetryPanel from './FastRetryPanel.vue'
import { isDeterministicError, isLocalNetworkError } from '@/utils/feedback'
import { stripEmoji } from '@/utils/text'

const {
  progressPct,
  progressMessage,
  resultVideoVisible,
  resultVideoSrc,
  resultIsImage,
  steps,
  stepStates,
  taskFailed,
  failedMessage,
  retryWindowHint,
  liveFailedStep,
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
  openImageModal,
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
  // 简单图片：提示词 + 负面提示词 + 系统提示词（后两者可选，空值展示「—」）
  image: [
    { field: 'prompt', label: 'tiPrompt' },
    { field: 'negative_prompt', label: 'vmColNegative' },
    { field: 'system_prompt', label: 'systemPrompt' },
  ],
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
  // 简单图片：后端只有 size（video_width/height 只是基类默认值 1280x720，展示会误导）
  image: [{ field: 'size', label: 'imageSize' }],
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
// v6.4.8：本机网络/域名解析故障单列一类，引导是「查 DNS/代理」，不套参数类文案
const networkError = computed(() => isLocalNetworkError(failedMessage.value))
const deterministicError = computed(
  () => !networkError.value && isDeterministicError(failedMessage.value),
)
// 两类「重试大概率无效」的故障：统一弱化重试按钮
const retryIneffective = computed(() => networkError.value || deterministicError.value)

// 诊断报告的失败环节：优先后端实时环节名，回退页面挂载时的快照（issue #56/#57）
const reportFailedStep = computed(
  () => liveFailedStep.value || taskInfo.value?.current_step || '',
)

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

    <div class="mx-auto w-full max-w-content px-4 py-6 lg:px-10">
      <div class="lg:flex lg:gap-9">
        <!-- 左侧：环节时间线（宽屏）+ 支持项目 -->
        <aside class="hidden w-[220px] shrink-0 lg:block">
          <div class="sticky top-24 space-y-6">
            <StepTimeline @locate="scrollToStep" />
            <div class="sidebar-card">
              <div class="stitle">{{ t('adSupportTitle') }}</div>
              <p class="mb-2 text-[11px] leading-relaxed text-muted">{{ t('adSupportDesc') }}</p>
              <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener">{{ stripEmoji(t('adStar')) }}</a>
              <p class="-mt-0.5 mb-1 px-1 text-[10.5px] leading-relaxed text-muted">{{ t('adStarDesc') }}</p>
              <a href="https://github.com/lcy362/flint" target="_blank" rel="noopener" class="wrap">{{ stripEmoji(t('adSkewStar')) }}</a>
              <p class="-mt-0.5 mb-1 px-1 text-[10.5px] leading-relaxed text-muted">{{ t('adSkewStarDesc') }}</p>
              <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ stripEmoji(t('adAdblock')) }}</a>
              <p class="-mt-0.5 mb-1 px-1 text-[10.5px] leading-relaxed text-muted">{{ t('adAdblockDesc') }}</p>
              <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ stripEmoji(t('adClick')) }}</a>
              <p class="-mt-0.5 mb-1 px-1 text-[10.5px] leading-relaxed text-muted">{{ t('adClickDesc') }}</p>
              <p class="mt-2 text-[10.5px] leading-relaxed text-muted">{{ t('adThanks') }}</p>
            </div>
          </div>
        </aside>

        <!-- 主工作台 -->
        <main class="min-w-0 flex-1">
          <!-- 移动端环节条 -->
          <div class="mb-4 lg:hidden">
            <StepTimeline horizontal @locate="scrollToStep" />
          </div>

          <!-- 状态区：控制台式（大百分比 + 发丝进度条） -->
          <section class="panel mb-4">
            <div class="panel-body">
              <div class="flex items-start justify-between gap-4">
                <div>
                  <p class="eyebrow">{{ t('progress') }}</p>
                  <p class="metric mt-2.5 text-[44px] text-ink">
                    {{ progressPct }}<span class="ms-0.5 text-[15px] tracking-normal text-muted">%</span>
                  </p>
                </div>
                <span
                  class="chip"
                  :class="taskFailed ? 'chip-danger' : resultVideoVisible ? 'chip-success' : 'chip-warning'"
                >
                  {{ taskFailed ? t('statusFailed') : resultVideoVisible ? t('statusCompleted') : t('statusRunning') }}
                </span>
              </div>

              <div class="meter mt-4">
                <div class="meter-fill" :style="{ width: progressPct + '%' }"></div>
              </div>

              <!-- 失败信息 -->
              <div v-if="taskFailed" class="mt-5 border-t border-rule pt-4">
                <p class="flex items-center gap-2 text-[12.5px] font-medium text-danger">
                  <span class="h-1.5 w-1.5 rounded-full" style="background: var(--color-danger)"></span>
                  {{ t('genFailed') }}
                </p>
                <p class="mt-2 text-[11.5px] leading-relaxed text-muted">{{ failedMessage || t('genFailedMsg') }}</p>
                <!-- v7.3：队列满/上游 503 时的错峰重试建议（按浏览者所在时区换算，不同时区看到各自本地时间） -->
                <p v-if="retryWindowHint" class="mt-2 text-[11.5px] leading-relaxed text-accent">{{ retryWindowHint }}</p>
                <!-- v6.1 问题反馈：重试引导（偶发故障优先断点续传自愈，多次失败再上报） -->
                <div class="mt-3 border-t border-rule pt-3">
                  <!-- 引导文案：网络/域名类 → 自查环境；确定性故障 → 建议直接反馈；其余 → 断点续传自愈 -->
                  <p class="text-[11.5px] leading-relaxed" :class="retryIneffective ? 'text-warning' : 'text-muted'">
                    {{ networkError ? t('fbNetworkHint') : deterministicError ? t('fbDeterministicHint') : t('fbRetryHint') }}
                  </p>
                  <div class="mt-2.5 flex flex-wrap items-center gap-3">
                    <button
                      class="btn btn-sm"
                      :class="retryIneffective ? 'btn-ghost' : 'btn-primary'"
                      @click="onRetryTask"
                    >
                      ↻ {{ t('fbRetryBtn') }}
                    </button>
                    <span v-if="retryCount > 0" class="mono text-[10.5px] text-muted">{{ t('fbRetriedN').replace('{n}', String(retryCount)) }}</span>
                  </div>
                  <!-- v6.1 问题反馈：反馈区（渐进展开 + 复制 + FAQ + GitHub Issue） -->
                  <FeedbackPanel
                    v-if="appState.progressTaskId"
                    class="mt-3"
                    :task-id="appState.progressTaskId"
                    :task-type="appState.currentTaskType || 'creative'"
                    :mode="taskInfo?.mode"
                    :failed-step="reportFailedStep"
                    :error-message="failedMessage || ''"
                    :retry-count="retryCount"
                    :configs="feedbackConfigs"
                    @retry="onRetryTask"
                  />
                </div>
              </div>
              <!-- 进度消息（HTML 渲染，来自后端安全文案） -->
              <div v-else class="mt-3 text-[12.5px] leading-relaxed text-ink-2" v-html="progressMessage"></div>

              <!-- v7.7 快速重试：连续 2 次 503 后出现开关（提交成功/到期自动消失或收起） -->
              <FastRetryPanel v-if="!taskFailed" />

              <!-- 1.7：连接异常横幅（连续轮询失败 N 次后展示） -->
              <div
                v-if="connectionLost"
                class="mt-3 flex items-start gap-2 rounded border px-3 py-2 text-[11.5px] leading-relaxed text-danger"
                style="border-color: color-mix(in oklab, var(--color-danger) 30%, transparent); background: color-mix(in oklab, var(--color-danger) 8%, transparent)"
              >
                {{ t('connLost') }}
              </div>
            </div>
          </section>

          <!-- 任务信息（用户输入提示词 + 各项配置，v6.1） -->
          <section v-if="taskInfo" class="panel mb-4">
            <button
              class="panel-head collapse-header w-full text-start"
              :title="taskInfoOpen ? t('ppCollapse') : t('ppExpand')"
              :aria-label="taskInfoOpen ? t('ppCollapse') : t('ppExpand')"
              :aria-expanded="taskInfoOpen"
              @click="taskInfoOpen = !taskInfoOpen"
            >
              <span class="panel-title">{{ t('taskInfo') }}</span>
              <span class="mono text-[11px] text-muted" aria-hidden="true">{{ taskInfoOpen ? '−' : '+' }}</span>
            </button>

            <div v-show="taskInfoOpen" class="panel-body space-y-3">
              <!-- 输入提示词 -->
              <div v-for="f in taskInputs" :key="f.field">
                <p class="label">{{ t(f.label) }}</p>
                <p class="whitespace-pre-wrap break-words rounded border border-rule bg-paper px-3 py-2 text-[12px] leading-relaxed text-ink-2">
                  {{ taskInfo[f.field] || '—' }}
                </p>
              </div>

              <!-- 关键配置 -->
              <div v-if="taskConfigs.length" class="flex flex-wrap gap-x-5 gap-y-1.5 border-t border-rule pt-3">
                <div v-for="c in taskConfigs" :key="c.field" class="flex items-baseline gap-1.5 text-[11px]">
                  <span class="text-muted">{{ t(c.label) }}</span>
                  <span class="mono text-ink-2">{{ c.fmt ? c.fmt(taskInfo[c.field]) : (taskInfo[c.field] || '—') }}</span>
                </div>
              </div>
            </div>
          </section>

          <!-- 产物流：逐步追加（按环节分组，已完成折叠） -->
          <div v-if="artifactsAreaVisible" class="space-y-3">
            <section
              v-for="g in orderedGroups"
              :id="'artifact-group-' + g.stepKey"
              :key="g.stepKey"
              class="artifact-group panel"
              :class="g.stepKey === checkpointGroup ? 'border-accent/50' : ''"
            >
              <button
                class="panel-head collapse-header w-full text-start"
                :title="isCollapsed(g.stepKey) ? t('ppExpand') : t('ppCollapse')"
                :aria-label="isCollapsed(g.stepKey) ? t('ppExpand') : t('ppCollapse')"
                :aria-expanded="!isCollapsed(g.stepKey)"
                @click="toggleCollapse(g.stepKey)"
              >
                <span class="flex min-w-0 items-center gap-2">
                  <span
                    class="h-1.5 w-1.5 shrink-0 rounded-full"
                    :style="{ background: g.stepKey === checkpointGroup ? 'var(--color-accent)' : 'var(--color-success)' }"
                  ></span>
                  <span class="truncate text-[12.5px] font-medium" :class="g.stepKey === checkpointGroup ? 'text-accent' : 'text-ink-2'">
                    {{ t(stepLabelMap[g.stepKey] || g.stepKey) }}
                  </span>
                  <span v-if="g.stepKey === checkpointGroup" class="chip chip-accent shrink-0">{{ t('awaitingUser') }}</span>
                  <span class="mono shrink-0 text-[10px] text-muted">{{ g.items.length }}</span>
                </span>
                <span class="mono shrink-0 text-[11px] text-muted" aria-hidden="true">{{ isCollapsed(g.stepKey) ? '+' : '−' }}</span>
              </button>

              <div v-show="!isCollapsed(g.stepKey)" class="panel-body space-y-2">
                <ArtifactCard v-for="art in g.items" :key="art.artifact_id" :art="art" :large="g.stepKey === checkpointGroup" />
              </div>
            </section>
          </div>

          <!-- 暂停审查区：紧跟最新产物（就近操作） -->
          <CheckpointDetail
            v-if="awaitingCheckpoint && appState.currentTaskId"
            :task-id="appState.currentTaskId"
            :checkpoint="awaitingCheckpoint"
          />

          <!-- 结果：视频任务出 <video>，图片任务（simple_image）出 <img> -->
          <section v-if="resultVideoVisible" class="panel mt-4">
            <header class="panel-head">
              <p class="panel-title">
                <span class="h-1.5 w-1.5 rounded-full" style="background: var(--color-success)"></span>
                {{ resultIsImage ? t('imgComplete') : t('videoComplete') }}
              </p>
            </header>
            <div class="panel-body">
              <img
                v-if="resultIsImage"
                :src="resultVideoSrc"
                class="max-h-[70vh] w-full cursor-zoom-in rounded-lg object-contain"
                @click="openImageModal(resultVideoSrc)"
              />
              <video v-else :src="resultVideoSrc" controls class="w-full rounded-lg max-h-96"></video>
              <div v-if="!resultIsImage" class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px]">
                <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-accent transition-colors hover:text-ink">{{ t('doneTipTiktok') }}</a>
                <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('doneTipMore') }}</a>
              </div>
            </div>
          </section>

          <!-- 官网导流资源（更多资源链接，与主页一致） -->
          <footer class="mt-10 border-t border-rule/60 pt-6">
            <p class="eyebrow mb-3">{{ t('moreResources') }}</p>
            <div class="flex flex-wrap gap-x-5 gap-y-2 text-[11.5px]">
              <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('projectHome') }}</a>
              <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-accent transition-colors hover:text-ink">{{ t('onlineDemo') }}</a>
              <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('usageGuide') }}</a>
              <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('promptTips') }}</a>
              <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('faqTitle') }}</a>
              <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('modelOverview') }}</a>
              <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('apiCall') }}</a>
              <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('apiDocs') }}</a>
              <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('appScenarios') }}</a>
              <a href="https://video.lichuanyang.top/zh/guides/free-ai-tools" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('agentMoreTools') }}</a>
              <a href="https://github.com/lcy362/flint" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">{{ t('flintLinkLabel') }}</a>
              <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="text-muted transition-colors hover:text-ink-2">GitHub</a>
            </div>
          </footer>
        </main>
      </div>
    </div>

    <!-- 图片放大弹窗 -->
    <div v-if="imageModalUrl" class="modal-backdrop cursor-pointer" @click="closeImageModal">
      <img :src="imageModalUrl" class="max-h-[90vh] max-w-[90vw] rounded-lg" />
    </div>
  </div>
</template>
