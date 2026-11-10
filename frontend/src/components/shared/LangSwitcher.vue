<script setup lang="ts">
/**
 * 语言切换器（参考官网 video.lichuanyang.top 的 nav lang switcher）
 * 触发区：地球图标 + 当前语言旗帜 + 下拉箭头
 * 展开区：按地区分组的多列面板，当前语言以 accent 勾选高亮
 * 交互：点击外部 / Esc 关闭，RTL 语言下自动镜像对齐
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { LANGS, t, useI18n } from '@/i18n'

const { currentLang, switchLang } = useI18n()

// compact：用于进度页等紧凑头部（字号/内边距更小）
const props = withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const triggerClass = computed(() =>
  props.compact
    ? 'btn btn-quiet h-8 shrink-0 gap-1 px-1.5 text-[11.5px]'
    : 'btn btn-quiet h-8 shrink-0 gap-1.5 px-2 text-[11.5px]',
)

// 语言名映射（label 形如 "🇨🇳 中文"）+ 地区分组（与官网 langGroups 一致）
const labelOf: Record<string, string> = Object.fromEntries(LANGS.map((l) => [l.code, l.label]))
const groups: { id: string; items: string[] }[] = [
  { id: 'langGroupEastAsia', items: ['zh', 'ja', 'ko'] },
  { id: 'langGroupSoutheastAsia', items: ['ms', 'id', 'vi', 'th', 'tl'] },
  { id: 'langGroupSouthAsia', items: ['hi', 'bn', 'ur'] },
  { id: 'langGroupMiddleEast', items: ['tr', 'ar', 'fa'] },
  { id: 'langGroupEurope', items: ['en', 'de', 'fr', 'nl', 'es', 'pt', 'it', 'ru'] },
]

// 触发按钮只显示旗帜
const currentFlag = computed(() => (labelOf[currentLang.value] || '🌐').split(' ')[0])

function pick(code: string) {
  switchLang(code)
  open.value = false
}

function onDocPointerDown(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', onDocPointerDown)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocPointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="shrink-0"
      :class="[triggerClass, open ? 'bg-paper-2 text-ink' : '']"
      aria-haspopup="true"
      :aria-expanded="open"
      :aria-label="t('langSwitch')"
      :title="t('langSwitch')"
      @click="open = !open"
    >
      <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke-width="1.8"></circle>
        <path stroke-linecap="round" stroke-width="1.8" d="M3 12h18M12 3c2.5 2.5 2.5 15 0 18M12 3c-2.5 2.5-2.5 15 0 18"></path>
      </svg>
      <span aria-hidden="true">{{ currentFlag }}</span>
      <svg
        class="w-3 h-3 shrink-0 transition-transform"
        :class="{ 'rotate-180': open }"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
      </svg>
    </button>

    <div v-if="open" class="lang-menu">
      <div v-for="g in groups" :key="g.id" class="lang-group">
        <p class="lang-group-title">{{ t(g.id) }}</p>
        <button
          v-for="code in g.items"
          :key="code"
          type="button"
          class="lang-item"
          :class="{ 'is-active': code === currentLang }"
          :aria-current="code === currentLang ? 'true' : undefined"
          :lang="code"
          :title="labelOf[code]"
          @click="pick(code)"
        >
          <span class="lang-name">{{ labelOf[code] }}</span>
          <span v-if="code === currentLang" class="lang-check" aria-hidden="true">✓</span>
        </button>
      </div>
    </div>
  </div>
</template>
