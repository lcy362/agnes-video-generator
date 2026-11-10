<script setup lang="ts">
/**
 * 「试验中」气泡（v7.6 即梦协作 / 外部素材模式）。
 *
 * 即梦（Dreamina）协作自 v7.6 起提供，检查点提示词、批量导入与字幕对齐仍可能随版本
 * 调整，因此凡出现该功能的入口（创建面板的执行模式按钮 / 工具下拉、检查点协作卡片）
 * 都挂这枚气泡，文案与说明走 i18n（`experimentalBadge` / `experimentalBadgeHint`）。
 *
 * 用法：`<ExperimentalBadge />` 或 `<ExperimentalBadge size="sm" />`。
 */
import { t } from '@/i18n'

withDefaults(defineProps<{ size?: 'xs' | 'sm' }>(), { size: 'xs' })
</script>

<template>
  <span
    class="mono inline-flex shrink-0 items-center whitespace-nowrap rounded border align-middle font-medium uppercase tracking-[0.06em]"
    :class="size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-1.5 py-0.5 text-[9px] leading-none'"
    style="
      color: var(--color-warning);
      border-color: color-mix(in oklab, var(--color-warning) 34%, transparent);
      background: color-mix(in oklab, var(--color-warning) 8%, transparent);
    "
    :title="t('experimentalBadgeHint')"
  >{{ t('experimentalBadge') }}</span>
</template>
