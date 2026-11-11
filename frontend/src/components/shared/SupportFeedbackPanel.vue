<script setup lang="ts">
/**
 * 「支持作者 + 问题反馈」侧栏面板（v8.0 视觉优化）。
 *
 * 主工作台左侧导航栏（`App.vue`）与进度页侧栏（`ProgressPage.vue`）共用：
 * - 上：支持作者（Star 本项目 / Star Flint / 关 AdBlock / 点广告）
 * - 下：问题反馈（提 GitHub Issue / X 上 @Sand_Grid）
 *
 * 视觉约定（见 docs/dev/design_system.md）：链接从「裸文字」升级为描边瓷砖，
 * 每行 = 线性图标 + 主文案 + 一行说明 + 右上箭头；hover 只改描边 / 底色 / 图标色，
 * 不加阴影、位移与渐变。图标统一 24×24 stroke，文案全部走 i18n（22 语言）。
 */
import { t } from '@/i18n'
import { stripEmoji } from '@/utils/text'

interface PanelLink {
  href: string
  /** 主文案 i18n key */
  labelKey: string
  /** 一行说明 i18n key */
  descKey: string
  /** 24×24 线性图标 path（可多段） */
  paths: string[]
}

/** 右上外链箭头 */
const ARROW = ['M7 17 17 7', 'M9 7h8v8']

const SUPPORT_LINKS: PanelLink[] = [
  {
    href: 'https://github.com/lcy362/agnes-video-generator',
    labelKey: 'adStar',
    descKey: 'adStarDesc',
    paths: ['M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z'],
  },
  {
    href: 'https://github.com/lcy362/flint',
    labelKey: 'adSkewStar',
    descKey: 'adSkewStarDesc',
    paths: ['M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z'],
  },
  {
    href: 'https://video.lichuanyang.top',
    labelKey: 'adAdblock',
    descKey: 'adAdblockDesc',
    paths: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'],
  },
  {
    href: 'https://video.lichuanyang.top',
    labelKey: 'adClick',
    descKey: 'adClickDesc',
    paths: ['M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z'],
  },
]

const FEEDBACK_LINKS: PanelLink[] = [
  {
    href: 'https://github.com/lcy362/agnes-video-generator/issues/new/choose',
    labelKey: 'adGithubIssue',
    descKey: 'adGithubIssueDesc',
    // 14px 下 octocat 轮廓会糊成一团，改用「问题 / 提醒」圆标，GitHub 语义交给文案
    paths: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z', 'M12 8v5', 'M12 16.5h.01'],
  },
  {
    href: 'https://x.com/Sand_Grid',
    labelKey: 'adXFollow',
    descKey: 'adXFollowDesc',
    paths: ['M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94', 'M16 12a4 4 0 1 0-8 0 4 4 0 0 0 8 0z'],
  },
]
</script>

<template>
  <div class="sf">
    <!-- 支持作者 -->
    <section>
      <p class="sf-title">{{ stripEmoji(t('adSupportTitle')) }}</p>
      <p class="sf-sub">{{ t('adSupportDesc') }}</p>
      <div class="sf-list">
        <a
          v-for="l in SUPPORT_LINKS"
          :key="l.labelKey"
          :href="l.href"
          target="_blank"
          rel="noopener"
          class="sf-link"
        >
          <svg class="sf-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path v-for="(d, i) in l.paths" :key="i" :d="d" />
          </svg>
          <span class="sf-body">
            <span class="sf-label">{{ stripEmoji(t(l.labelKey)) }}</span>
            <span class="sf-desc">{{ t(l.descKey) }}</span>
          </span>
          <svg class="sf-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path v-for="(d, i) in ARROW" :key="i" :d="d" />
          </svg>
        </a>
      </div>
      <p class="sf-thanks">{{ t('adThanks') }}</p>
    </section>

    <!-- 问题反馈（支持作者在下方的独立分组，不抢支持项目的层级） -->
    <section class="sf-feedback">
      <p class="sf-title">{{ t('adFeedbackTitle') }}</p>
      <p class="sf-sub">{{ t('adFeedbackDesc') }}</p>
      <div class="sf-list">
        <a
          v-for="l in FEEDBACK_LINKS"
          :key="l.labelKey"
          :href="l.href"
          target="_blank"
          rel="noopener"
          class="sf-link"
        >
          <svg class="sf-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path v-for="(d, i) in l.paths" :key="i" :d="d" />
          </svg>
          <span class="sf-body">
            <span class="sf-label">{{ t(l.labelKey) }}</span>
            <span class="sf-desc">{{ t(l.descKey) }}</span>
          </span>
          <svg class="sf-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path v-for="(d, i) in ARROW" :key="i" :d="d" />
          </svg>
        </a>
      </div>
    </section>
  </div>
</template>

<style scoped>
.sf-title {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--color-muted);
}

.sf-sub {
  margin-top: 5px;
  margin-bottom: 7px;
  font-size: 10.5px;
  line-height: 1.45;
  color: color-mix(in oklab, var(--color-muted) 78%, transparent);
}

.sf-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 链接瓷砖：描边 + 图标 + 两行文案 + 外链箭头，保证在窄侧栏里也「点得着、看得见」 */
.sf-link {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 7px;
  border: 1px solid var(--color-rule);
  border-radius: var(--r-xs);
  background: color-mix(in oklab, var(--color-paper-2) 60%, transparent);
  color: var(--color-ink-2);
  text-decoration: none;
  white-space: normal;
  transition:
    color var(--dur-short) var(--ease-out),
    border-color var(--dur-short) var(--ease-out),
    background-color var(--dur-short) var(--ease-out);
}

.sf-link:hover,
.sf-link:focus-visible {
  border-color: var(--color-rule-2);
  background: var(--color-paper-3);
  color: var(--color-ink);
}

.sf-icon {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  color: var(--color-muted);
  transition: color var(--dur-short) var(--ease-out);
}

.sf-link:hover .sf-icon,
.sf-link:focus-visible .sf-icon {
  color: var(--color-accent);
}

.sf-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.sf-label {
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.sf-desc {
  font-size: 10px;
  line-height: 1.35;
  color: var(--color-muted);
  overflow-wrap: anywhere;
}

.sf-arrow {
  width: 11px;
  height: 11px;
  flex: 0 0 auto;
  color: color-mix(in oklab, var(--color-muted) 55%, transparent);
  transition: color var(--dur-short) var(--ease-out);
}

.sf-link:hover .sf-arrow,
.sf-link:focus-visible .sf-arrow {
  color: var(--color-ink-2);
}

.sf-thanks {
  margin-top: 6px;
  font-size: 10px;
  line-height: 1.45;
  color: color-mix(in oklab, var(--color-muted) 70%, transparent);
}

.sf-feedback {
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid color-mix(in oklab, var(--color-rule) 70%, transparent);
}
</style>
