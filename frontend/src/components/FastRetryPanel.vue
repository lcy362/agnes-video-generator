<script setup lang="ts">
/**
 * v7.7 快速重试模式面板。
 *
 * 出现条件：后端连续检测到 2 次视频队列繁忙（503 `video_queue_full`）后，
 * 任务状态里 `fast_retry.available = true`。用户开启后按「每分钟 x 次、
 * 持续 y 分钟」连打；提交成功或到期后后端自动恢复正常重试节奏。
 *
 * 单位说明：界面、状态行与后端进度消息统一用「次/分钟」，与后端
 * `per_minute` 契约一致，不再做 ×60 换算。
 *
 * 与既有逻辑的关系：本面板只是把用户的意愿写进任务状态，实际节奏由
 * `core/api/agnes_video.py` 的提交循环读取；未开启时行为与升级前一致。
 *
 * v8.0：新增「以后自动开启」勾选——勾上后本次参数同时写入设置页的全局设置
 * （`auto=True`），此后所有任务到条件都会自动快速重试；若设置页已经开启自动，
 * 这里只提示、不再询问，避免出现两份互相矛盾的开关。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t, tf } from '@/i18n'
import { appState } from '@/store'
import { useProgress } from '@/composables/useProgress'

const { fastRetry, setFastRetryMode, longTask, setLongTaskMode } = useProgress()

// 界面单位：次/分钟（与后端 per_minute 一致，区间 1–120）
const perMinute = ref(30)
const minutes = ref(3)
// v8.4：两轮快速重试之间的常规节奏间隔 X（分钟，默认 5）
const intervalMinute = ref(5)
const submitting = ref(false)
// v8.0：「以后自动」——勾选后本次参数写入设置页的全局设置，此后到条件自动开启
const remember = ref(false)
// 设置页已开启自动模式时，这里不再询问「以后自动」（已经是自动）
const autoGlobal = computed(() => !!appState.fastRetrySettings.auto)
// 剩余时间用本地时钟每秒重算（后端只给 started_at + minutes，不额外轮询）
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const cfg = computed(() => fastRetry.value)
const enabled = computed(() => !!cfg.value?.enabled)
const visible = computed(() => !!cfg.value && (enabled.value || !!cfg.value.available))

// 后端下发的生效值回填输入框：仅首次同步，避免轮询刷新覆盖用户正在编辑的输入
let paramsSynced = false
watch(
  cfg,
  (v) => {
    if (!v) return
    if (!paramsSynced && v.per_minute) {
      perMinute.value = v.per_minute
      paramsSynced = true
    }
    if (v?.minutes) minutes.value = v.minutes
    if (v?.interval_minutes) intervalMinute.value = v.interval_minutes
  },
  { immediate: true },
)

// 生效频率（次/分钟），用于状态行展示
const activePerMinute = computed(() => cfg.value?.per_minute || 30)

const remainingText = computed(() => {
  const c = cfg.value
  if (!c?.enabled || !c.started_at) return ''
  const started = new Date(c.started_at).getTime()
  if (!Number.isFinite(started)) return ''
  const left = Math.max(0, started + (c.minutes || 0) * 60000 - now.value)
  const m = Math.floor(left / 60000)
  const s = Math.floor((left % 60000) / 1000)
  return `${m}:${String(s).padStart(2, '0')}`
})

const hint = computed(() => {
  const c = cfg.value
  if (!c) return ''
  if (c.enabled) return tf('fastRetry.remaining', { x: activePerMinute.value, t: remainingText.value })
  if (c.finished_reason === 'expired') {
    // v8.4：到期后进入接力等待，X 分钟后自动再开一轮
    if (c.chain_pending) return tf('fastRetry.chainHint', { i: c.interval_minutes || 5 })
    return t('fastRetry.expiredHint')
  }
  return t('fastRetry.desc')
})

async function toggle() {
  if (submitting.value) return
  submitting.value = true
  try {
    // 次/分钟直接透传（夹在 1–120，与后端 clamp 区间一致；空输入回落 1）
    const v = Number(perMinute.value)
    const rate = Number.isFinite(v) && v > 0 ? v : 1
    const perMinuteValue = Math.max(1, Math.min(120, Math.round(rate)))
    const iv = Number(intervalMinute.value)
    const intervalValue = Number.isFinite(iv) && iv > 0
      ? Math.max(1, Math.min(60, Math.round(iv)))
      : 5
    await setFastRetryMode(
      !enabled.value,
      perMinuteValue,
      minutes.value,
      !enabled.value && remember.value && !autoGlobal.value,
      intervalValue,
    )
  } finally {
    submitting.value = false
  }
}

// ── v8.3 长任务模式 ────────────────────────────────────────────────
// 与快速重试的分工：快速重试改「节奏」，本模式改「总预算」（累计忙轨等待时长）。
// 只在视频类任务显示（图片任务没有视频提交忙轨，开了也没有意义）。
const VIDEO_TASK_TYPES = ['simple', 'creative', 'manuscript', 'anchor', 'poetry']
const ltCfg = computed(() => longTask.value)
const ltVisible = computed(
  () => VIDEO_TASK_TYPES.includes(String(appState.currentTaskType || '')) && !!ltCfg.value,
)
const ltEnabled = computed(() => !!ltCfg.value?.enabled)
// 默认 1 小时；后端 clamp 区间 5–480 分钟
const ltTimeout = ref(60)
const ltSubmitting = ref(false)

// 后端下发的配置回填（只在首次同步，避免轮询覆盖用户正在编辑的输入）
let ltSynced = false
watch(
  ltCfg,
  (v) => {
    if (!v || ltSynced) return
    if (v.timeout_minutes) ltTimeout.value = v.timeout_minutes
    ltSynced = true
  },
  { immediate: true },
)

function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}

const ltWaitedText = computed(() => fmtDuration(Number(ltCfg.value?.waited_s || 0)))
const ltRemainingText = computed(() => {
  const budget = Math.max(1, Number(ltCfg.value?.timeout_minutes || 60)) * 60
  return fmtDuration(budget - Number(ltCfg.value?.waited_s || 0))
})

const ltHint = computed(() => {
  const c = ltCfg.value
  if (!c) return ''
  if (c.enabled)
    return tf('longTask.active', {
      y: c.timeout_minutes || 60,
      waited: ltWaitedText.value,
      left: ltRemainingText.value,
    })
  if (c.finished_reason === 'expired') return tf('longTask.expired', { y: c.timeout_minutes || 60 })
  if (c.finished_reason === 'non_retryable')
    return tf('longTask.nonRetryable', { reason: c.last_reason || '-' })
  if (c.finished_reason === 'disabled') return t('longTask.disabled')
  return t('longTask.desc')
})

// 进度页只负责「开启本次任务」；关闭统一走设置页（避免误关后长任务白等）
async function enableLongTask() {
  if (ltSubmitting.value || ltEnabled.value) return
  ltSubmitting.value = true
  try {
    const v = Number(ltTimeout.value)
    const timeout = Number.isFinite(v) && v > 0 ? Math.round(v) : 60
    await setLongTaskMode(true, Math.max(5, Math.min(480, timeout)))
  } finally {
    ltSubmitting.value = false
  }
}
</script>

<template>
  <div
    v-if="visible"
    class="mt-4 border-t border-rule pt-4"
  >
    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <p class="flex items-center gap-2 text-[12px] font-medium text-ink-2">
          <span class="h-1.5 w-1.5 rounded-full" style="background: var(--color-accent)"></span>
          {{ t('fastRetry.title') }}
        </p>
        <p class="mt-1 text-[11px] leading-relaxed text-muted">{{ hint }}</p>
      </div>
      <button
        role="switch"
        :aria-checked="enabled"
        :aria-label="t('fastRetry.title')"
        :disabled="submitting"
        class="relative mt-0.5 h-[18px] w-8 shrink-0 rounded-full border transition-colors disabled:opacity-50"
        :class="enabled ? 'border-accent bg-accent/25' : 'border-rule-2 bg-paper-3'"
        data-track="fast_retry_toggle"
        :data-track-params="JSON.stringify({ to: enabled ? 'off' : 'on' })"
        @click="toggle"
      >
        <span
          class="absolute top-[2px] h-3 w-3 rounded-full transition-all"
          :class="enabled ? 'bg-accent' : 'bg-muted'"
          :style="{ insetInlineStart: enabled ? '16px' : '2px' }"
        ></span>
      </button>
    </div>

    <div v-if="!enabled" class="mt-3 flex flex-wrap items-end gap-3">
      <label>
        <span class="label">{{ t('fastRetry.perMinute') }}</span>
        <input
          v-model.number="perMinute"
          type="number"
          min="1"
          max="120"
          step="1"
          class="field w-20"
        />
      </label>
      <label>
        <span class="label">{{ t('fastRetry.minutes') }}</span>
        <input
          v-model.number="minutes"
          type="number"
          min="1"
          max="30"
          class="field w-20"
        />
      </label>
      <!-- v8.4：两轮之间的常规节奏间隔 X（到期后回到常规重试 X 分钟，再自动开下一轮） -->
      <label>
        <span class="label">{{ t('fastRetry.interval') }}</span>
        <input
          v-model.number="intervalMinute"
          type="number"
          min="1"
          max="60"
          step="1"
          class="field w-20"
        />
      </label>
      <button
        class="btn btn-primary btn-sm"
        :disabled="submitting"
        data-track="fast_retry_start"
        @click="toggle"
      >
        {{ t('fastRetry.start') }}
      </button>
    </div>

    <!-- v8.0：一次性执行 vs 永久自动（设置页已开启自动时不再显示该选项） -->
    <template v-if="!enabled">
      <div v-if="!autoGlobal" class="mt-2 flex items-start justify-between gap-3">
        <span class="min-w-0">
          <span class="block text-[11.5px] font-medium text-ink-2">{{ t('fastRetry.rememberLabel') }}</span>
          <span class="mt-0.5 block text-[11px] leading-relaxed text-muted">{{ t('fastRetry.rememberHint') }}</span>
        </span>
        <button
          type="button"
          role="switch"
          :aria-checked="remember"
          :aria-label="t('fastRetry.rememberLabel')"
          class="relative mt-0.5 h-[18px] w-8 shrink-0 rounded-full border transition-colors"
          :class="remember ? 'border-accent bg-accent/25' : 'border-rule-2 bg-paper-3'"
          data-track="fast_retry_remember"
          :data-track-params="JSON.stringify({ to: remember ? 'off' : 'on' })"
          @click="remember = !remember"
        >
          <span
            class="absolute top-[2px] h-3 w-3 rounded-full transition-all"
            :class="remember ? 'bg-accent' : 'bg-muted'"
            :style="{ insetInlineStart: remember ? '16px' : '2px' }"
          ></span>
        </button>
      </div>
      <p v-else class="hint mt-1">{{ t('fastRetry.autoGlobalOn') }}</p>
    </template>

    <div v-else class="mt-3 flex flex-wrap items-center gap-2">
      <!-- 已打次数：后端 attempts 每 1 秒最多落盘一次，快速模式下随 1s 轮询刷新 -->
      <span class="chip chip-accent">
        {{ tf('fastRetry.attempts', { n: cfg?.attempts || 0 }) }}
      </span>
      <span v-if="cfg?.auto" class="chip">{{ t('fastRetry.autoBadge') }}</span>
      <button
        class="btn btn-ghost btn-sm"
        :disabled="submitting"
        data-track="fast_retry_stop"
        @click="toggle"
      >
        {{ t('fastRetry.stop') }}
      </button>
    </div>
  </div>

  <!-- v8.3 长任务模式：保持现有重试频率，只把总预算延长到设定时长 -->
  <div v-if="ltVisible" class="mt-4 border-t border-rule pt-4">
    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <p class="flex items-center gap-2 text-[12px] font-medium text-ink-2">
          <span class="h-1.5 w-1.5 rounded-full" style="background: var(--color-accent)"></span>
          {{ t('longTask.title') }}
        </p>
        <p class="mt-1 text-[11px] leading-relaxed text-muted">{{ ltHint }}</p>
      </div>
      <button
        role="switch"
        :aria-checked="ltEnabled"
        :aria-label="t('longTask.title')"
        :disabled="ltSubmitting"
        class="relative mt-0.5 h-[18px] w-8 shrink-0 rounded-full border transition-colors disabled:opacity-50"
        :class="ltEnabled ? 'border-accent bg-accent/25' : 'border-rule-2 bg-paper-3'"
        data-track="long_task_toggle"
        :data-track-params="JSON.stringify({ to: ltEnabled ? 'off' : 'on' })"
        @click="enableLongTask"
      >
        <span
          class="absolute top-[2px] h-3 w-3 rounded-full transition-all"
          :class="ltEnabled ? 'bg-accent' : 'bg-muted'"
          :style="{ insetInlineStart: ltEnabled ? '16px' : '2px' }"
        ></span>
      </button>
    </div>

    <div v-if="!ltEnabled" class="mt-3 flex flex-wrap items-end gap-3">
      <label>
        <span class="label">{{ t('longTask.timeout') }}</span>
        <input
          v-model.number="ltTimeout"
          type="number"
          min="5"
          max="480"
          step="5"
          class="field w-20"
        />
      </label>
      <button
        class="btn btn-primary btn-sm"
        :disabled="ltSubmitting"
        data-track="long_task_start"
        @click="enableLongTask"
      >
        {{ t('longTask.start') }}
      </button>
    </div>

    <div v-else class="mt-3 flex flex-wrap items-center gap-2">
      <span class="chip chip-accent">
        {{ tf('longTask.waited', { t: ltWaitedText, left: ltRemainingText }) }}
      </span>
    </div>
  </div>
</template>
