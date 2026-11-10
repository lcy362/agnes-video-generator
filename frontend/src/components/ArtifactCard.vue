<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { t } from '@/i18n'
import { useArtifacts } from '@/composables/useArtifacts'
import { copyText } from '@/utils/clipboard'
import type { Artifact } from '@/types'

const props = defineProps<{ art: Artifact; large?: boolean }>()

const {
  isRunning,
  artifactLabel,
  artifactIcon,
  artifactFileUrl,
  formatSize,
  toggleArtifactPreview,
  openImageModal,
  confirmDeleteArtifact,
} = useArtifacts()

const previewExpanded = ref(false)
const previewText = ref('')
const previewLoading = ref(false)

// 文本 / JSON / 字幕类产物：默认自动展开预览
async function loadPreview() {
  previewExpanded.value = true
  previewLoading.value = true
  previewText.value = ''
  try {
    const resp = await fetch(artifactFileUrl(props.art))
    let text = await resp.text()
    if (text.length > 2000) text = text.substring(0, 2000) + '\n...'
    previewText.value = text
  } catch (err: any) {
    previewText.value = 'Error: ' + err.message
  } finally {
    previewLoading.value = false
  }
}

async function onPreviewClick(e: Event) {
  const el = e.currentTarget as HTMLElement
  if (previewExpanded.value) {
    previewExpanded.value = false
    previewText.value = ''
  } else {
    await loadPreview()
  }
  void el
}

onMounted(() => {
  const cat = props.art.category
  if (cat !== 'image' && cat !== 'video' && cat !== 'audio') {
    loadPreview()
  }
})

async function onCopyPath() {
  const p = (props.art as any).abs_path || (props.art as any).path || ''
  if (!p) return
  await copyText(p)
}
</script>

<template>
  <div class="artifact-card flex items-start gap-3 rounded border border-rule bg-paper px-3 py-2.5">
    <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center text-[12px] leading-none text-muted">{{ artifactIcon(art) }}</span>
    <div class="min-w-0 flex-1">
      <div class="mb-1 flex items-baseline gap-2">
        <span class="truncate text-[11.5px] text-ink-2">{{ artifactLabel(art) }}</span>
        <span class="mono shrink-0 text-[10px] text-muted">{{ formatSize(art.size) }}</span>
      </div>

      <!-- 图片预览 -->
      <img
        v-if="art.category === 'image'"
        :src="artifactFileUrl(art)"
        class="cursor-pointer rounded border border-rule"
        :class="large ? 'max-h-[400px] w-full' : 'max-h-36'"
        loading="lazy"
        @click="openImageModal(artifactFileUrl(art))"
      />
      <!-- 视频预览 -->
      <video
        v-else-if="art.category === 'video'"
        :src="artifactFileUrl(art)"
        controls
        playsinline
        preload="metadata"
        class="w-full rounded border border-rule bg-black"
        :style="large ? 'max-height: 460px' : 'max-height: 260px'"
      ></video>
      <!-- 音频预览 -->
      <audio v-else-if="art.category === 'audio'" :src="artifactFileUrl(art)" controls class="w-full" preload="metadata"></audio>
      <!-- 文本 / JSON 预览 -->
      <pre
        v-else
        class="cursor-pointer overflow-auto whitespace-pre-wrap rounded border border-rule bg-paper-2 p-2 text-[11px] leading-relaxed text-muted"
        :class="large ? 'max-h-64' : 'max-h-24'"
        @click="onPreviewClick"
      >{{ previewExpanded ? (previewLoading ? t('loading') + '...' : previewText) : t('clickToPreview') }}</pre>

      <!-- 路径复制 -->
      <div
        v-if="(art as any).abs_path || (art as any).path"
        class="mono mt-1.5 cursor-pointer truncate text-[10px] text-muted transition-colors hover:text-ink-2"
        :title="t('copy')"
        @click="onCopyPath"
      >{{ (art as any).abs_path || (art as any).path }}</div>
    </div>

    <!-- 删除 -->
    <button
      v-if="art.deletable && !isRunning"
      class="btn btn-quiet btn-xs shrink-0 text-danger"
      :title="t('delete')"
      @click="confirmDeleteArtifact(art)"
    >
      ✕
    </button>
  </div>
</template>
