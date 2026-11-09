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
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t, tf } from '@/i18n'
import { useProgress } from '@/composables/useProgress'

const { fastRetry, setFastRetryMode } = useProgress()

// 界面单位：次/分钟（与后端 per_minute 一致，区间 1–120）
const perMinute = ref(30)
const minutes = ref(3)
const submitting = ref(false)
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
  if (c.finished_reason === 'expired') return t('fastRetry.expiredHint')
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
    await setFastRetryMode(!enabled.value, perMinuteValue, minutes.value)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div
    v-if="visible"
    class="mt-3 rounded-lg border border-accent/30 bg-accent/5 px-3 py-3 space-y-2"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-sm font-medium text-ink-2">{{ t('fastRetry.title') }}</p>
        <p class="mt-1 text-xs text-muted leading-relaxed">{{ hint }}</p>
      </div>
      <button
        role="switch"
        :aria-checked="enabled"
        :aria-label="t('fastRetry.title')"
        :disabled="submitting"
        class="relative shrink-0 h-5 w-10 mt-0.5 rounded-full transition-colors disabled:opacity-50"
        :class="enabled ? 'bg-accent' : 'bg-paper-2/60 border border-rule'"
        @click="toggle"
      >
        <span
          class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
          :class="enabled ? 'left-5' : 'left-0.5'"
        ></span>
      </button>
    </div>

    <div v-if="!enabled" class="flex flex-wrap items-end gap-3 pt-1">
      <label class="text-xs text-muted">
        <span class="block mb-1">{{ t('fastRetry.perMinute') }}</span>
        <input
          v-model.number="perMinute"
          type="number"
          min="1"
          max="120"
          step="1"
          class="w-20 glass-input rounded-lg px-2 py-1.5 text-sm"
        />
      </label>
      <label class="text-xs text-muted">
        <span class="block mb-1">{{ t('fastRetry.minutes') }}</span>
        <input
          v-model.number="minutes"
          type="number"
          min="1"
          max="30"
          class="w-20 glass-input rounded-lg px-2 py-1.5 text-sm"
        />
      </label>
      <button
        class="text-xs px-3 py-1.5 rounded-lg bg-accent text-accent-ink hover:opacity-90 transition disabled:opacity-50"
        :disabled="submitting"
        @click="toggle"
      >
        {{ t('fastRetry.start') }}
      </button>
    </div>

    <div v-else class="flex flex-wrap items-center gap-2 text-xs">
      <!-- 已打次数：后端 attempts 每 1 秒最多落盘一次，快速模式下随 1s 轮询刷新 -->
      <span
        class="px-2 py-1 rounded-lg bg-paper-2/40 border border-rule text-ink-2 font-medium tabular-nums"
      >
        {{ tf('fastRetry.attempts', { n: cfg?.attempts || 0 }) }}
      </span>
      <button
        class="px-3 py-1.5 rounded-lg bg-paper-2/40 border border-rule text-muted hover:text-ink-2 transition disabled:opacity-50"
        :disabled="submitting"
        @click="toggle"
      >
        {{ t('fastRetry.stop') }}
      </button>
    </div>
  </div>
</template>
