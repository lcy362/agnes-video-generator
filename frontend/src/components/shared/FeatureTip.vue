/**
 * 功能引导气泡（v8.5）。
 *
 * 首次进入带重试开关的面板时，用一张分步卡片解释「快速重试」与「长任务模式」：
 * 两者都在上游排队时才有意义，但触发时机不同（遇到队列满 / 提交后即可开），
 * 新手很容易看成一回事，所以第一次出现时按两步讲清。
 *
 * 约定：
 * - 只负责展示与步骤推进，不决定「弹不弹」；是否弹由父组件按 localStorage 判定；
 * - 文案全部由父组件传入（已 i18n 化），组件内不写死文案；
 * - 点击埋点走 `data-track` 全局委托（v8.2 契约），不手动调 trackEvent。
 *
 * 用法：`<FeatureTip :open="tipOpen" :steps="tipSteps" @close="closeTip" />`
 */

<script setup lang="ts">

import { computed, ref, watch } from 'vue'
import { t } from '@/i18n'

const props = defineProps<{
  open: boolean
  steps: { title: string; body: string }[]
}>()

const emit = defineEmits<{ (e: 'close', reason: 'done' | 'skip' | 'dismiss'): void }>()

const index = ref(0)
const isLast = computed(() => index.value >= props.steps.length - 1)
const current = computed(() => props.steps[index.value] || { title: '', body: '' })

// 每次重新打开都从第一步开始（关闭后再次触发时不会停在上次的末步）
watch(
  () => props.open,
  (v) => {
    if (v) index.value = 0
  },
)

function next() {
  if (!isLast.value) {
    index.value += 1
    return
  }
  emit('close', 'done')
}

function skip() {
  emit('close', 'skip')
}

function dismiss() {
  emit('close', 'dismiss')
}
</script>

<template>
  <div
    v-if="open && steps.length"
    class="relative mt-4 overflow-hidden rounded-xl border px-4 py-3"
    style="
      border-color: color-mix(in oklab, var(--color-accent) 32%, transparent);
      background: color-mix(in oklab, var(--color-accent) 7%, transparent);
    "
    role="dialog"
    data-track="feature_tip"
    :data-track-params="JSON.stringify({ tip: 'retry_modes', step: index + 1 })"
  >
    <!-- 指向下方开关区域的小三角 -->
    <span
      aria-hidden="true"
      class="absolute -bottom-[7px] left-6 h-3 w-3 rotate-45 border-b border-e"
      style="
        border-color: color-mix(in oklab, var(--color-accent) 32%, transparent);
        background: color-mix(in oklab, var(--color-accent) 7%, transparent);
      "
    ></span>

    <div class="flex items-start justify-between gap-3">
      <p class="flex min-w-0 items-center gap-2 text-[12px] font-medium text-ink">
        <span class="mono shrink-0 rounded border border-rule-2 px-1.5 py-0.5 text-[9.5px] text-muted">
          {{ index + 1 }}/{{ steps.length }}
        </span>
        <span class="truncate">{{ current.title }}</span>
      </p>
      <button
        class="shrink-0 text-[12px] leading-none text-muted transition-colors hover:text-ink"
        :aria-label="t('featureTip.skip')"
        data-track="feature_tip_dismiss"
        @click="dismiss"
      >
        ✕
      </button>
    </div>

    <p class="mt-1.5 text-[11.5px] leading-relaxed text-ink-2">{{ current.body }}</p>

    <div class="mt-3 flex items-center gap-2">
      <button
        class="btn btn-primary btn-sm"
        data-track="feature_tip_next"
        :data-track-params="JSON.stringify({ tip: 'retry_modes', step: index + 1 })"
        @click="next"
      >
        {{ isLast ? t('featureTip.gotit') : t('featureTip.next') }}
      </button>
      <button
        v-if="!isLast"
        class="btn btn-quiet btn-xs"
        data-track="feature_tip_skip"
        @click="skip"
      >
        {{ t('featureTip.skip') }}
      </button>
    </div>
  </div>
</template>
