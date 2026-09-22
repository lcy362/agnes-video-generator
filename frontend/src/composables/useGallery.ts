// 产物画廊（P1）：只读加载 + 可选轮询（复用 useTasks 的退避/visibilitychange 模式）
import { ref } from 'vue'
import * as api from '@/api'
import type { GalleryItem } from '@/types'

const items = ref<GalleryItem[]>([])
const loading = ref(false)
const filter = ref<'all' | 'video' | 'image'>('all')
const status = ref<'all' | 'completed' | 'failed'>('all')
let timer: ReturnType<typeof setInterval> | null = null
let inFlight = false

async function loadGallery() {
  if (inFlight) return
  inFlight = true
  loading.value = true
  try {
    const d = await api.getGallery({ filter: filter.value, status: status.value })
    items.value = (d && d.items) || []
  } catch {
    /* 保留旧列表，静默重试 */
  } finally {
    loading.value = false
    inFlight = false
  }
}

function applyFilter(f: typeof filter.value) {
  filter.value = f
  loadGallery()
}
function applyStatus(s: typeof status.value) {
  status.value = s
  loadGallery()
}

function startGalleryTimer() {
  if (timer) return
  timer = setInterval(loadGallery, 5000)
  document.addEventListener('visibilitychange', handleVisibility)
}
function stopGalleryTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  document.removeEventListener('visibilitychange', handleVisibility)
}
function handleVisibility() {
  if (document.hidden) {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  } else {
    loadGallery()
    startGalleryTimer()
  }
}

export function useGallery() {
  return {
    items,
    loading,
    filter,
    status,
    loadGallery,
    applyFilter,
    applyStatus,
    startGalleryTimer,
    stopGalleryTimer,
  }
}