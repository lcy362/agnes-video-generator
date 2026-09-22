<script setup lang="ts">
// 风格预设选择器（P0-1）：一键填入 / 最近置前 / tooltip 预览 / 保存当前风格 / 用户预设可删
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
onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="rootEl" class="relative">
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="glass-input rounded-lg px-3 py-2 text-sm text-ink cursor-pointer hover:border-accent/40 transition"
        @click="toggle"
      >
        {{ t('presetOpen') }} <span class="text-muted">▾</span>
      </button>
      <button
        type="button"
        class="glass-input rounded-full w-7 h-7 text-sm text-ink cursor-pointer leading-none hover:border-accent/40 transition"
        title="+"
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
      class="absolute z-20 mt-1 w-72 max-h-72 overflow-y-auto glass-card rounded-xl p-2 shadow-xl"
    >
      <template v-if="groups.length">
        <div v-for="g in groups" :key="g.category" class="mb-1">
          <div class="text-xs text-muted px-2 py-1 uppercase tracking-wide">{{ catName(g.category) }}</div>
          <button
            v-for="p in g.items"
            :key="p.id"
            type="button"
            class="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg text-sm text-left text-ink hover:bg-paper-3 transition"
            :title="p.prompt"
            @click="choose(p)"
          >
            <span class="truncate">{{ displayName(p) }}</span>
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