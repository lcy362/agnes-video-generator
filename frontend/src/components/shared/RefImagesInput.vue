<script setup lang="ts">
/**
 * 多参考图上传组件（v8.1）
 *
 * 统一 SimpleForm / CreativeForm / ManuscriptForm / PoetryForm / AnchorForm 的
 * 参考图交互：多选 + 序号徽标（= 提示词里的 `<Picture N>`）+ 缩略图 + 逐张删除
 * + 上下移动（顺序即编号）+ 选满禁用 + `n / max`。
 *
 * 只用既有 i18n key（`chooseImage` / `notSelected`），避免 22 语言翻译缺失。
 */
import { computed, onBeforeUnmount, watch } from 'vue'
import { t } from '@/i18n'

const props = withDefaults(
  defineProps<{
    modelValue: File[]
    max: number
    label?: string
    hint?: string
    /** 文件选择框的附加 class（沿用旧表单的测试选择器，如 `scene-ref-file`） */
    inputClass?: string
  }>(),
  { label: '', hint: '', inputClass: '' },
)

const emit = defineEmits<{ (e: 'update:modelValue', v: File[]): void }>()

const full = computed(() => props.modelValue.length >= props.max)

// File → 预览 URL（同一文件复用同一个 blob URL，避免重复创建泄漏）
const previews = new Map<File, string>()

function urlOf(file: File): string {
  if (!previews.has(file)) {
    previews.set(file, URL.createObjectURL(file))
  }
  return previews.get(file) || ''
}

function release(file: File) {
  const url = previews.get(file)
  if (url) {
    URL.revokeObjectURL(url)
    previews.delete(file)
  }
}

// 被移除的文件（外部直接改 modelValue）也要回收
watch(
  () => props.modelValue,
  (next) => {
    const keep = new Set(next)
    for (const file of Array.from(previews.keys())) {
      if (!keep.has(file)) release(file)
    }
  },
  { deep: true },
)

onBeforeUnmount(() => {
  for (const file of Array.from(previews.keys())) release(file)
})

function onChange(e: Event) {
  const input = e.target as HTMLInputElement
  const merged = [...props.modelValue]
  for (const f of Array.from(input.files || [])) {
    if (merged.length >= props.max) break
    merged.push(f)
  }
  input.value = '' // 允许重复选择同一文件
  emit('update:modelValue', merged)
}

function removeAt(index: number) {
  const next = [...props.modelValue]
  const [removed] = next.splice(index, 1)
  if (removed) release(removed)
  emit('update:modelValue', next)
}

function move(index: number, delta: number) {
  const next = [...props.modelValue]
  const target = index + delta
  if (target < 0 || target >= next.length) return
  ;[next[index], next[target]] = [next[target], next[index]]
  emit('update:modelValue', next)
}
</script>

<template>
  <div>
    <label v-if="label" class="label">{{ label }}</label>
    <div class="flex flex-wrap items-center gap-2">
      <label class="btn btn-ghost shrink-0" :class="full ? 'pointer-events-none opacity-50' : ''">
        <span>{{ t('chooseImage') }}</span>
        <input
          type="file"
          accept="image/*"
          multiple
          class="hidden"
          :class="inputClass"
          :disabled="full"
          @change="onChange"
        />
      </label>
      <span class="mono text-[11px] text-muted">{{ modelValue.length }} / {{ max }}</span>
    </div>
    <p v-if="hint" class="hint mt-1.5">{{ hint }}</p>

    <ul v-if="modelValue.length" class="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
      <li
        v-for="(file, index) in modelValue"
        :key="index"
        class="overflow-hidden rounded border border-rule bg-paper-2"
      >
        <div class="relative">
          <img :src="urlOf(file)" :alt="`#${index + 1}`" class="h-20 w-full object-cover" />
          <span class="mono absolute start-1 top-1 rounded bg-black/60 px-1 text-[10px] leading-4 text-white">
            #{{ index + 1 }}
          </span>
        </div>
        <div class="flex items-center justify-between gap-1 px-1.5 py-1">
          <span class="truncate text-[10.5px] text-muted">{{ file.name || t('notSelected') }}</span>
          <span class="flex shrink-0 items-center">
            <button
              type="button"
              class="px-1 text-[11px] text-muted transition-colors hover:text-ink disabled:opacity-30"
              :disabled="index === 0"
              :aria-label="`#${index + 1} ↑`"
              @click="move(index, -1)"
            >↑</button>
            <button
              type="button"
              class="px-1 text-[11px] text-muted transition-colors hover:text-ink disabled:opacity-30"
              :disabled="index === modelValue.length - 1"
              :aria-label="`#${index + 1} ↓`"
              @click="move(index, 1)"
            >↓</button>
            <button
              type="button"
              class="px-1 text-[12px] text-muted transition-colors hover:text-danger"
              :aria-label="`#${index + 1} ×`"
              @click="removeAt(index)"
            >×</button>
          </span>
        </div>
      </li>
    </ul>
  </div>
</template>
