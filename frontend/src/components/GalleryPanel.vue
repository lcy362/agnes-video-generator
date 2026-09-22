<script setup lang="ts">
// 产物画廊（P1）：纯只读网格 + 类型/状态筛选；点卡片跳任务详情
// 不含任何删除 / 确认弹窗（删除管理保留在「任务列表」Tab）
import { onMounted } from 'vue'
import { t } from '@/i18n'
import { useGallery } from '@/composables/useGallery'
import { useNavigation } from '@/composables/useNavigation'

const { items, loading, filter, status, loadGallery, applyFilter, applyStatus } = useGallery()
const { goProgress } = useNavigation()

const statusColors: Record<string, string> = {
  completed: 'text-emerald-400',
  failed: 'text-red-400',
  running: 'text-yellow-400',
  pending: 'text-muted',
  queued: 'text-accent',
}
const typeLabelKey: Record<string, string> = {
  simple: 'typeSimple',
  creative: 'typeCreative',
  manuscript: 'typeManuscript',
  anchor: 'typeAnchor',
  poetry: 'typePoetry',
  image: 'typeImage',
}

function openItem(id: string, dir: string, type: string) {
  goProgress(id, 'gallery')
}

onMounted(() => {
  loadGallery()
})
</script>

<template>
  <div>
    <!-- 筛选栏 -->
    <div class="flex flex-wrap items-center gap-2 mb-4">
      <span class="text-xs text-muted">{{ t('galleryReadonlyHint') }}</span>
      <span class="flex-1"></span>
      <select
        class="glass-input rounded-lg px-3 py-2 text-sm text-ink cursor-pointer"
        :value="filter"
        @change="applyFilter(($event.target as HTMLSelectElement).value as any)"
      >
        <option value="all">{{ t('filterAll') }}</option>
        <option value="video">{{ t('filterVideo') }}</option>
        <option value="image">{{ t('filterImage') }}</option>
      </select>
      <select
        class="glass-input rounded-lg px-3 py-2 text-sm text-ink cursor-pointer"
        :value="status"
        @change="applyStatus(($event.target as HTMLSelectElement).value as any)"
      >
        <option value="all">{{ t('filterStatusAll') }}</option>
        <option value="completed">{{ t('filterStatusCompleted') }}</option>
        <option value="failed">{{ t('filterStatusFailed') }}</option>
      </select>
    </div>

    <!-- 网格 -->
    <p v-if="!loading && !items.length" class="text-muted text-sm">{{ t('galleryEmpty') }}</p>
    <div v-if="items.length" class="grid grid-cols-2 sm:grid-cols-3 gap-4">
      <article
        v-for="it in items"
        :key="it.task_id"
        class="glass-card rounded-xl overflow-hidden cursor-pointer group transition hover:border-accent/40"
        @click="openItem(it.task_id, it.dir_name, it.task_type)"
      >
        <div class="relative aspect-video bg-paper-2 overflow-hidden">
          <!-- 视频：优先用服务端惰性缩略图作封面；缺失时用原生首帧；hover 播放 -->
          <img
            v-if="it.kind === 'video' && it.thumb_url"
            :src="it.thumb_url"
            class="absolute inset-0 w-full h-full object-cover transition group-hover:opacity-0"
            loading="lazy"
            alt=""
          />
          <video
            v-if="it.kind === 'video'"
            :src="it.media_url"
            class="absolute inset-0 w-full h-full object-cover transition"
            :class="it.thumb_url ? 'opacity-0 group-hover:opacity-100' : ''"
            preload="metadata"
            muted
            playsinline
            loop
          ></video>
          <!-- 图片：直链现有端点 -->
          <img v-else-if="it.kind === 'image'" :src="it.media_url" class="absolute inset-0 w-full h-full object-cover" loading="lazy" alt="" />
          <span class="absolute top-2 left-2 px-2 py-0.5 rounded text-[10px] uppercase bg-ink/70 text-ink-2">
            {{ it.kind }}
          </span>
        </div>
        <div class="p-3">
          <div class="flex items-center justify-between gap-2 mb-1">
            <span class="text-sm font-medium text-ink truncate">{{ it.title }}</span>
            <span class="text-xs" :class="statusColors[it.status] || 'text-muted'">
              {{ t((typeLabelKey as any)[it.task_type] || 'typeCreative') }}
            </span>
          </div>
          <p v-if="it.description" class="text-xs text-muted line-clamp-2 leading-relaxed">{{ it.description }}</p>
        </div>
      </article>
    </div>
  </div>
</template>