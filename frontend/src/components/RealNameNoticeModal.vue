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
      class="fixed inset-0 z-[70] flex items-center justify-center px-4"
      role="dialog"
      aria-modal="true"
      :aria-label="t('noticeRealNameTitle')"
    >
      <div class="absolute inset-0 bg-black/50 animate-fade-in" @click="close"></div>

      <div class="relative bg-paper rounded-2xl p-5 sm:p-6 max-w-md w-full shadow-2xl border border-rule max-h-[85vh] overflow-y-auto">
        <div class="flex items-start gap-2.5">
          <span class="text-lg leading-none pt-0.5" aria-hidden="true">📢</span>
          <h3 class="text-base font-semibold text-ink leading-snug">{{ t('noticeRealNameTitle') }}</h3>
        </div>

        <ul class="mt-4 space-y-3 text-sm text-ink-2 leading-relaxed">
          <li class="flex gap-2">
            <span class="shrink-0 pt-0.5" aria-hidden="true">🇨🇳</span>
            <div class="min-w-0">
              <p>{{ t('noticeRealNameBody') }}</p>
              <a
                :href="CN_CONSOLE"
                target="_blank"
                rel="noopener"
                class="inline-block mt-1 text-accent hover:text-ink transition-colors break-all underline underline-offset-2"
              >{{ CN_CONSOLE.replace('https://', '') }} ↗</a>
            </div>
          </li>

          <li class="flex gap-2">
            <span class="shrink-0 pt-0.5" aria-hidden="true">⚠️</span>
            <p class="font-medium text-ink-2">{{ t('noticeRealNameFreq') }}</p>
          </li>

          <li class="flex gap-2">
            <span class="shrink-0 pt-0.5" aria-hidden="true">🌍</span>
            <div class="min-w-0">
              <p>{{ t('noticeRealNameGlobal') }}</p>
              <a
                :href="GLOBAL_CONSOLE"
                target="_blank"
                rel="noopener"
                class="inline-block mt-1 text-muted hover:text-ink-2 transition-colors break-all underline underline-offset-2"
              >{{ GLOBAL_CONSOLE.replace('https://', '') }} ↗</a>
            </div>
          </li>

          <li class="flex gap-2 rounded-xl bg-paper-2/60 border border-rule/60 px-3 py-2">
            <span class="shrink-0 pt-0.5" aria-hidden="true">📉</span>
            <p class="text-xs leading-relaxed text-ink-2">{{ t('noticeRealNameOutlook') }}</p>
          </li>
        </ul>

        <div class="flex justify-end mt-5">
          <button
            class="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-accent-ink hover:opacity-90 transition"
            @click="close"
          >
            {{ t('noticeRealNameGotIt') }}
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>
