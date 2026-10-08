<script setup lang="ts">
// 风格预设选择器（P0-1）：下拉选择一键填入 / 高亮当前 / 最近置前 / tooltip 预览 / 保存当前风格 / 用户预设可删
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { t } from '@/i18n'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { usePresets } from '@/composables/usePresets'
import type { Preset } from '@/types'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const { showToast } = useToast()
const { confirmAsync } = useConfirm()
const {
  system, user, loadPresets, savePreset, removePreset, recents, markRecent,
} = usePresets()

const open = ref(false)
const saving = ref(false)
const newName = ref('')

interface Grouped {
  category: string
  items: Preset[]
}

const groups = computed<Grouped[]>(() => {
  const recent = recents()
  const byCat: Record<string, Preset[]> = {}
  for (const p of system.value) {
    const cat = p.category || 'other'
    ;(byCat[cat] = byCat[cat] || []).push({ ...p, kind: 'system', category: cat })
  }
  // 用户自定义预设归入 custom 分组
  byCat['custom'] = user.value.map((p) => ({ ...p, category: 'custom', kind: 'user' }))
  // 最近使用置前（组内排序）
  for (const items of Object.values(byCat)) {
    items.sort((a, b) => {
      const ai = recent.indexOf(a.id)
      const bi = recent.indexOf(b.id)
      const ar = ai === -1 ? Number.MAX_SAFE_INTEGER : ai
      const br = bi === -1 ? Number.MAX_SAFE_INTEGER : bi
      return ar - br
    })
  }
  // 用户自定义预设置于最前，其余按分类出现顺序
  const entries = Object.entries(byCat)
  entries.sort(([ca], [cb]) => {
    if (ca === 'custom') return -1
    if (cb === 'custom') return 1
    return 0
  })
  return entries.map(([category, items]) => ({ category, items }))
})

function catName(cat: string): string {
  if (cat === 'custom') return t('presetCat_custom')
  return t('presetCat_' + cat) || cat
}

function displayName(p: Preset): string {
  // 用户预设用自填名称；系统预设名称走 i18n（key = presetName_{id}）
  if (p.kind === 'user') return p.name || t('presetNameUntitled')
  return t('presetName_' + p.id) || p.id || ''
}

// 当前风格命中的预设：用于在触发按钮上显示名称、并在面板里打勾高亮。
const activePreset = computed<Preset | null>(() => {
  const v = (props.modelValue || '').trim()
  if (!v) return null
  return [...system.value, ...user.value].find((p) => (p.prompt || '').trim() === v) || null
})
const activeName = computed(() => (activePreset.value ? displayName(activePreset.value) : ''))

function toggle() {
  open.value = !open.value
  if (open.value && system.value.length === 0 && user.value.length === 0) loadPresets()
}

function choose(p: Preset) {
  if (!p.prompt) return
  emit('update:modelValue', p.prompt)
  markRecent(p.id)
  open.value = false
}

async function submitSave() {
  const prompt = (props.modelValue || '').trim()
  if (!prompt) {
    showToast(t('presetSaveFailed'), 3000)
    return
  }
  try {
    await savePreset(newName.value || t('presetNameUntitled'), prompt)
    showToast(t('presetSaved'), 2500, 'success')
    newName.value = ''
    saving.value = false
  } catch (e: any) {
    showToast(t('presetSaveFailed') + ': ' + e.message, 4000)
  }
}

async function remove(p: Preset) {
  if (!(await confirmAsync(t('presetDeleteConfirm')))) return
  try {
    await removePreset(p.id)
    showToast(t('presetDeleted'), 2500, 'success')
  } catch (e: any) {
    showToast(t('presetDeleteFailed') + ': ' + e.message, 4000)
  }
}

function onDocClick(e: MouseEvent) {
  const el = rootEl.value
  if (el && !el.contains(e.target as Node)) open.value = false
}
const rootEl = ref<HTMLElement | null>(null)
onMounted(() => {
  document.addEventListener('click', onDocClick)
  // 挂载即加载预设，使触发按钮能立即显示当前命中的预设名称
  if (system.value.length === 0 && user.value.length === 0) loadPresets()
})
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="rootEl" class="relative">
    <div class="flex items-center gap-1.5">
      <!-- 下拉选择触发器：仿原生 select，显示当前预设或占位提示，chevron 展开时翻转 -->
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-lg glass-input px-3 py-2.5 text-sm cursor-pointer transition
               hover:border-accent/50"
        :class="open ? 'border-accent/60 ring-2 ring-accent/25' : ''"
        :title="t('presetSelectHint')"
        @click="toggle"
      >
        <span class="text-xs text-muted shrink-0">{{ t('presetTriggerLabel') }}</span>
        <span v-if="activeName" class="font-medium text-ink truncate max-w-[9rem]">{{ activeName }}</span>
        <span v-else class="text-muted truncate max-w-[9rem]">{{ t('presetPlaceholder') }}</span>
        <svg
          class="w-3.5 h-3.5 text-muted shrink-0 transition-transform duration-200"
          :class="open ? 'rotate-180' : ''"
          viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7"
          stroke-linecap="round" stroke-linejoin="round"
        ><path d="M5.5 8 10 12.5 14.5 8" /></svg>
      </button>
      <button
        type="button"
        class="glass-input rounded-lg w-8 h-9 text-base text-ink cursor-pointer leading-none shrink-0 hover:border-accent/40 transition"
        :title="t('presetSaveAs')"
        @click="saving = !saving"
      >
        +
      </button>
    </div>

    <!-- 保存当前风格为预设 -->
    <div v-if="saving" class="flex items-center gap-2 mt-2">
      <input
        v-model="newName"
        class="glass-input rounded-lg px-3 py-2 text-sm text-ink placeholder-muted flex-1"
        :placeholder="t('presetNamePlaceholder')"
        @keyup.enter="submitSave"
      />
      <button type="button" class="px-3 py-2 rounded-lg text-sm bg-accent text-accent-ink cursor-pointer" @click="submitSave">
        {{ t('presetSaveAs') }}
      </button>
      <button type="button" class="px-2 py-2 rounded-lg text-sm text-muted cursor-pointer" @click="saving = false">
        ✕
      </button>
    </div>

    <!-- 预设下拉面板 -->
    <div
      v-if="open"
      class="absolute right-0 z-20 mt-1 w-72 max-h-72 overflow-y-auto glass-card rounded-xl p-2 shadow-xl"
    >
      <template v-if="groups.length">
        <div v-for="g in groups" :key="g.category" class="mb-1">
          <div class="text-xs text-muted px-2 py-1 uppercase tracking-wide">{{ catName(g.category) }}</div>
          <button
            v-for="p in g.items"
            :key="p.id"
            type="button"
            class="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg text-sm text-left hover:bg-paper-3 transition"
            :class="activePreset && activePreset.id === p.id ? 'text-accent font-medium' : 'text-ink'"
            :title="p.prompt"
            @click="choose(p)"
          >
            <span class="flex items-center gap-1.5 truncate">
              <span
                v-if="activePreset && activePreset.id === p.id"
                class="shrink-0"
                aria-hidden="true"
              >✓</span>
              <span class="truncate">{{ displayName(p) }}</span>
            </span>
            <span
              v-if="p.kind === 'user'"
              class="text-muted hover:text-red-400 px-1 shrink-0"
              @click.stop="remove(p)"
            >✕</span>
          </button>
        </div>
        <p class="text-xs text-muted px-2 py-1">{{ t('presetSelectHint') }}</p>
      </template>
      <p v-else class="text-sm text-muted px-2 py-2">{{ t('presetNoPresets') }}</p>
    </div>
  </div>
</template>