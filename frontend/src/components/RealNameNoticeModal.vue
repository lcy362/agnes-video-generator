<script setup lang="ts">
/**
 * 中国站实名认证公告弹窗（一次性）。
 *
 * 背景：Agnes 中国站要求 2026-10-26 12:00（北京时间）前完成实名认证，未完成的账号
 * 调用频率会降低；国际版不受影响。上游同时给出预期：该时点后 503 / queue is full
 * 等繁忙报错将明显改善。
 *
 * 交互：
 * - 首次进入（localStorage 无标记）自动弹出；点「我知道了」或遮罩后写入标记，不再打扰。
 * - 可访问性走 `useModalA11y`（ESC 关闭 + focus trap）；关闭即视为已读。
 * - 两个站点的控制台地址直接硬链（国内 / 国际），文案全部走 i18n（22 语言）。
 */
import { onMounted, ref } from 'vue'
import { t } from '@/i18n'
import { useModalA11y } from '@/composables/useModalA11y'
import { REAL_NAME_NOTICE_ID, dismissNotice, isNoticeDismissed } from '@/utils/notice'

/** 中国站控制台（实名认证在这里做） */
const CN_CONSOLE = 'https://platform.agnes-ai.cn'
/** 国际站控制台（不受影响，仅作对照参考） */
const GLOBAL_CONSOLE = 'https://platform.agnes-ai.com'

const visible = ref(false)
const { containerRef } = useModalA11y(visible, close)

/** 关闭并永久记为已读（一次性弹窗） */
function close() {
  visible.value = false
  dismissNotice(REAL_NAME_NOTICE_ID)
}

onMounted(() => {
  // 首次挂载后再置 true，让 useModalA11y 的 watch 正常接管焦点与 ESC
  if (!isNoticeDismissed(REAL_NAME_NOTICE_ID)) visible.value = true
})
</script>

<template>
  <teleport to="body">
    <div
      v-if="visible"
      ref="containerRef"
      class="modal-backdrop"
      role="dialog"
      aria-modal="true"
      :aria-label="t('noticeRealNameTitle')"
    >
      <div class="absolute inset-0" @click="close"></div>

      <div class="modal max-h-[85vh] w-full max-w-md overflow-y-auto p-5 sm:p-6">
        <div class="mb-4">
          <p class="eyebrow">Notice</p>
          <h3 class="mt-1.5 text-[14px] font-semibold leading-snug tracking-[-0.01em] text-ink">
            {{ t('noticeRealNameTitle') }}
          </h3>
        </div>

        <ul class="space-y-3 text-[12.5px] leading-relaxed text-ink-2">
          <li class="flex gap-2.5">
            <span class="mono shrink-0 pt-0.5 text-[9.5px] text-muted/70">01</span>
            <div class="min-w-0">
              <p>{{ t('noticeRealNameBody') }}</p>
              <a
                :href="CN_CONSOLE"
                target="_blank"
                rel="noopener"
                class="mono mt-1 inline-block break-all text-[11px] text-accent underline decoration-dotted underline-offset-2 transition-colors hover:text-ink"
              >{{ CN_CONSOLE.replace('https://', '') }} ↗</a>
            </div>
          </li>

          <li class="flex gap-2.5">
            <span class="mono shrink-0 pt-0.5 text-[9.5px] text-muted/70">02</span>
            <p class="font-medium">{{ t('noticeRealNameFreq') }}</p>
          </li>

          <li class="flex gap-2.5">
            <span class="mono shrink-0 pt-0.5 text-[9.5px] text-muted/70">03</span>
            <div class="min-w-0">
              <p>{{ t('noticeRealNameGlobal') }}</p>
              <a
                :href="GLOBAL_CONSOLE"
                target="_blank"
                rel="noopener"
                class="mono mt-1 inline-block break-all text-[11px] text-muted underline decoration-dotted underline-offset-2 transition-colors hover:text-ink-2"
              >{{ GLOBAL_CONSOLE.replace('https://', '') }} ↗</a>
            </div>
          </li>

          <li class="flex gap-2.5 rounded border border-rule bg-paper px-3 py-2">
            <span class="mono shrink-0 pt-0.5 text-[9.5px] text-muted/70">04</span>
            <p class="text-[11.5px] leading-relaxed text-muted">{{ t('noticeRealNameOutlook') }}</p>
          </li>
        </ul>

        <div class="mt-5 flex justify-end">
          <button class="btn btn-primary" @click="close">
            {{ t('noticeRealNameGotIt') }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>
