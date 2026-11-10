<script setup lang="ts">
// 产物画廊（P1）：纯只读网格 + 类型/状态筛选；点卡片跳任务详情
// 不含任何删除 / 确认弹窗（删除管理保留在「任务列表」Tab）
import { onMounted } from 'vue'
import { t } from '@/i18n'
import { useGallery } from '@/composables/useGallery'
import { useNavigation } from '@/composables/useNavigation'

const { items, loading, filter, status, loadGallery, applyFilter, applyStatus } = useGallery()
const { goProgress } = useNavigation()

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
    <div class="mb-5 flex flex-wrap items-center gap-2">
      <p class="hint flex-1 basis-48">{{ t('galleryReadonlyHint') }}</p>
      <select
        class="field w-auto"
        :value="filter"
        @change="applyFilter(($event.target as HTMLSelectElement).value as any)"
      >
        <option value="all">{{ t('filterAll') }}</option>
        <option value="video">{{ t('filterVideo') }}</option>
        <option value="image">{{ t('filterImage') }}</option>
      </select>
      <select
        class="field w-auto"
        :value="status"
        @change="applyStatus(($event.target as HTMLSelectElement).value as any)"
      >
        <option value="all">{{ t('filterStatusAll') }}</option>
        <option value="completed">{{ t('filterStatusCompleted') }}</option>
        <option value="failed">{{ t('filterStatusFailed') }}</option>
      </select>
    </div>

    <!-- 网格 -->
    <p v-if="!loading && !items.length" class="panel px-4 py-12 text-center text-[12.5px] text-muted">
      {{ t('galleryEmpty') }}
    </p>
    <div v-if="items.length" class="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <article
        v-for="it in items"
        :key="it.task_id"
        class="group cursor-pointer overflow-hidden rounded border border-rule bg-paper-2 transition-colors hover:border-rule-2"
        @click="openItem(it.task_id, it.dir_name, it.task_type)"
      >
        <div class="relative aspect-video overflow-hidden bg-paper">
          <!-- 视频：优先用服务端惰性缩略图作封面；缺失时用原生首帧；hover 播放 -->
          <img
            v-if="it.kind === 'video' && it.thumb_url"
            :src="it.thumb_url"
            class="absolute inset-0 h-full w-full object-cover transition-opacity group-hover:opacity-0"
            loading="lazy"
            alt=""
          />
          <video
            v-if="it.kind === 'video'"
            :src="it.media_url"
            class="absolute inset-0 h-full w-full object-cover transition-opacity"
            :class="it.thumb_url ? 'opacity-0 group-hover:opacity-100' : ''"
            preload="metadata"
            muted
            playsinline
            loop
          ></video>
          <!-- 图片：直链现有端点 -->
          <img v-else-if="it.kind === 'image'" :src="it.media_url" class="absolute inset-0 h-full w-full object-cover" loading="lazy" alt="" />
          <span
            class="mono absolute start-2 top-2 rounded px-1.5 py-0.5 text-[9px] uppercase tracking-[0.1em] text-ink-2"
            style="background: color-mix(in oklab, var(--color-paper) 82%, transparent); backdrop-filter: blur(6px)"
          >
            {{ it.kind }}
          </span>
        </div>
        <div class="border-t border-rule px-3 py-2.5">
          <div class="flex items-baseline justify-between gap-2">
            <span class="truncate text-[12.5px] font-medium text-ink">{{ it.title }}</span>
            <span class="mono shrink-0 text-[9.5px] uppercase tracking-[0.08em] text-muted">
              {{ t((typeLabelKey as any)[it.task_type] || 'typeCreative') }}
            </span>
          </div>
          <p v-if="it.description" class="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-muted">{{ it.description }}</p>
        </div>
      </article>
    </div>
  </div>
</template>