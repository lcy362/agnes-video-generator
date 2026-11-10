<script setup lang="ts">
/**
 * v6.1 问题反馈：失败面板内的反馈区闭环（PRD FR2 / FR4 / FR5 / FR6 / FR9）。
 *
 * - 渐进展开：重试计数 < RETRY_THRESHOLD 收起为低强调提示行；≥ 阈值自动展开；
 *   用户手动展开/收起状态经 fb_open_{taskId} 持久化（优先级高于自动策略）。
 * - 确定性故障：命中预筛直接自动展开 + 切换引导文案（重试按钮由父组件弱化）。
 * - 诊断信息：拼接 Markdown 报告（不含 prompt 原文），支持复制 / FAQ / GitHub Issue。
 * - 二期诊断端点：展开时拉取任务关联的模型错误详情合并进报告，失败静默降级。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import * as api from '@/api'
import { useToast } from '@/composables/useToast'
import { copyText } from '@/utils/clipboard'
import {
  RETRY_THRESHOLD,
  getFeedbackOpenOverride,
  setFeedbackOpenOverride,
  isDeterministicError,
  buildDiagnosticReport,
  buildIssueTitle,
  buildIssueUrl,
  TRACEBACK_MAX,
  FAQ_URL,
} from '@/utils/feedback'

const props = defineProps<{
  taskId: string
  taskType: string
  mode?: string
  failedStep: string
  errorMessage: string
  retryCount: number
  /** 关键配置，已格式化为「名称: 值」字符串列表 */
  configs?: string[]
}>()

// 是否命中确定性故障（父组件据此弱化重试按钮、切换引导语）
const deterministic = computed(() => isDeterministicError(props.errorMessage))

const { showToast } = useToast()

// ── 展开状态 ──
// 手动覆盖（null = 未覆盖，走自动策略）；组件卸载后回到 null，重新按自动策略判定
const open = ref(false)

function resolveOpen(): boolean {
  const override = getFeedbackOpenOverride(props.taskId)
  if (override !== null) return override
  // 自动策略：确定性故障 或 重试次数达阈值 → 自动展开
  return deterministic.value || props.retryCount >= RETRY_THRESHOLD
}

function applyOpen() {
  open.value = resolveOpen()
}

// 用户手动切换并持久化覆盖
function toggle() {
  open.value = !open.value
  setFeedbackOpenOverride(props.taskId, open.value)
}

// 任务/失败态变化时重新判定展开
watch(
  () => [props.retryCount, deterministic.value, props.taskId] as const,
  applyOpen,
)

// ── 诊断信息 ──
const appVersion = ref(appState.appVersion || '')
const report = ref('')
const reportLoading = ref(false)
const diagOpen = ref(true)

async function loadAppVersion() {
  if (appVersion.value) return
  try {
    const cfg = await api.getConfig()
    if (cfg.app_version) {
      appVersion.value = cfg.app_version
      appState.appVersion = cfg.app_version
    }
  } catch {
    /* 忽略：版本缺失时报告以「未知」兜底 */
  }
}

// 诊断报告：纯前端版 + （二期）合并后端任务诊断错误详情
async function buildReport(): Promise<string> {
  const base = buildDiagnosticReport({
    appVersion: appVersion.value,
    taskId: props.taskId,
    taskType: props.taskType,
    mode: props.mode,
    failedStep: props.failedStep,
    errorMessage: props.errorMessage,
    retryCount: props.retryCount,
    configs: props.configs || [],
  })
  // 二期：拉取任务关联的模型错误详情（静默降级，失败不影响纯前端版）
  let merged = base
  try {
    const d = await api.getTaskDiagnostics(props.taskId)
    // v6.2.2：合并完整 traceback（定位环境级异常如 [WinError 2]，诊断端点已截断）
    const summary = d && d.summary
    if (summary && summary.error_traceback) {
      merged +=
        '\n' +
        t('fbRepTraceback') +
        '\n```\n' +
        String(summary.error_traceback).slice(0, TRACEBACK_MAX) +
        '\n```\n'
    }
    const logs = d && d.error_logs
    if (Array.isArray(logs) && logs.length) {
      const unk = t('fbRepUnknown')
      const lines = logs.map((log: any, i: number) => {
        const errMsg = (log.error_message || '').slice(0, 800)
        return (
          `\n${t('fbRepErrHeading').replace('{n}', String(i + 1))}\n` +
          `- ${t('fbRepErrTime')}: ${log.timestamp || unk}\n` +
          `- ${t('fbRepErrModel')}: ${log.model_type || unk}\n` +
          `- ${t('fbRepErrApi')}: ${log.api_method || unk}\n` +
          `- ${t('fbRepErrType')}: ${log.error_type || unk}\n` +
          (log.status_code ? `- ${t('fbRepErrStatusCode')}: ${log.status_code}\n` : '') +
          (errMsg ? `- ${t('fbRepErrInfo')}: ${errMsg}\n` : '')
        )
      })
      merged += '\n' + lines.join('\n')
    }
  } catch {
    /* 端点失败/404 → 静默降级为纯前端版报告 */
  }
  return merged
}

async function refreshReport() {
  reportLoading.value = true
  try {
    report.value = await buildReport()
  } finally {
    reportLoading.value = false
  }
}

// 展开时拉取诊断并合并（二期）
async function onExpand() {
  applyOpen()
  if (open.value && !report.value) {
    reportLoading.value = true
    try {
      report.value = await buildReport()
    } finally {
      reportLoading.value = false
    }
  }
}

// ── 复制 / FAQ / GitHub Issue ──
async function onCopy() {
  const text = report.value || (await buildReport())
  const ok = await copyText(text)
  showToast(ok ? t('fbCopied') : t('fbCopyFailed'))
}

function onGithub() {
  const title = buildIssueTitle(props.taskType, props.failedStep)
  const body = report.value || buildDiagnosticReport({
    appVersion: appVersion.value,
    taskId: props.taskId,
    taskType: props.taskType,
    mode: props.mode,
    failedStep: props.failedStep,
    errorMessage: props.errorMessage,
    retryCount: props.retryCount,
    configs: props.configs || [],
  })
  const { url, truncated } = buildIssueUrl(title, body)
  if (truncated) showToast(t('fbUrlTooLong'), 4000)
  window.open(url, '_blank', 'noopener')
}

onMounted(async () => {
  await loadAppVersion()
  applyOpen()
  if (open.value) refreshReport()
})
</script>

<template>
  <div class="border-t border-rule pt-3">
    <!-- 收起态：低强调提示行（可点击展开） -->
    <button
      v-if="!open"
      type="button"
      class="inline-flex items-center gap-1.5 text-[11.5px] text-muted transition-colors hover:text-accent"
      @click="toggle"
    >
      {{ t('fbCollapsedHint') }}
    </button>

    <!-- 展开态：完整反馈区 -->
    <div v-else class="space-y-3">
      <!-- 引导语：确定性故障 / 重试次数超阈值切换 -->
      <p class="text-[11.5px] leading-relaxed" :class="deterministic ? 'text-warning' : 'text-muted'">
        {{ deterministic ? t('fbDeterministicHint') : t('fbExpandedHint').replace('{n}', String(props.retryCount)) }}
      </p>

      <!-- 诊断信息预览（可折叠） -->
      <div class="overflow-hidden rounded border border-rule">
        <button
          type="button"
          class="collapse-header flex w-full items-center gap-2 px-3 py-2 text-start transition-colors hover:bg-paper-3/50"
          @click="diagOpen = !diagOpen"
        >
          <span class="mono text-[10px] text-muted">{{ diagOpen ? '−' : '+' }}</span>
          <span class="text-[11.5px] font-medium text-ink-2">{{ t('fbDiagTitle') }}</span>
          <span v-if="reportLoading" class="ms-auto text-[11px] text-muted">…</span>
        </button>
        <div v-show="diagOpen" class="px-3 pb-3">
          <pre class="mono max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-rule bg-paper p-2 text-[10.5px] leading-relaxed text-muted">{{ report || t('fbDiagLoading') }}</pre>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn btn-ghost btn-sm" @click="onCopy">
          {{ t('fbCopy') }}
        </button>
        <a
          :href="FAQ_URL"
          target="_blank"
          rel="noopener"
          class="btn btn-ghost btn-sm"
        >
          {{ t('fbFaq') }}
        </a>
        <button type="button" class="btn btn-primary btn-sm" @click="onGithub">
          {{ t('fbGithub') }}
        </button>
        <button
          v-if="deterministic"
          type="button"
          class="btn btn-quiet btn-sm text-accent"
          @click="$emit('retry')"
        >
          ↻ {{ t('fbRetryBtn') }}
        </button>
      </div>

      <!-- 隐私提示 -->
      <p class="text-[10.5px] leading-relaxed text-muted/80">{{ t('fbPrivacyHint') }}</p>
    </div>
  </div>
</template>
