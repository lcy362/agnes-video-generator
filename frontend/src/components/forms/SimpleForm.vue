<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { t } from '@/i18n'
import { stripEmoji } from '@/utils/text'
import { siteUrl } from '@/utils/siteLinks'
import { appState } from '@/store'
import { useGa } from '@/composables/useGa'
import { useVideoModelCaps, MODE_API_TO_V25, MODE_V25_TO_API } from '@/composables/useVideoModelCaps'
import { useConfig } from '@/composables/useConfig'
import { useTaskSubmit } from '@/composables/useTaskSubmit'
import { useDraft } from '@/composables/useDraft'
import { useConfirm } from '@/composables/useConfirm'
import WatermarkToggle from '@/components/shared/WatermarkToggle.vue'
import RefImagesInput from '@/components/shared/RefImagesInput.vue'

const { trackEvent } = useGa()
const { saveModels, isApiKeyConfigured } = useConfig()
const { confirmAsync } = useConfirm()

// 3.1：视频/图片两个提交独立守卫
const videoSubmit = useTaskSubmit()
const imageSubmit = useTaskSubmit()

// 3.4：表单草稿（切走/刷新不丢失，提交成功清除）
const videoDraft = useDraft('simple-video')
const imageDraft = useDraft('simple-image')

// v6.2：视频模型能力（动态选项 + 差异说明）
const vmCaps = useVideoModelCaps()

// Sub-mode: video / image
const subMode = ref<'video' | 'image'>('video')

// ── v8.0：一键预设（后端 /api/models 的 simple_default 为单一事实来源）──
// 目标：只输入 prompt 就能得到一条方向正确、免费可用的视频。
// 默认 16:9 而非 9:16 —— 2.5-flash 竖屏存在画面躺倒缺陷，默认竖屏会让「一键」产物直接不可用。
const preset = computed(() => {
  const d = appState.simpleDefault || {}
  return {
    model: d.model || 'agnes-video-2.5-flash',
    duration: String(d.duration ?? 5),
    ratio: d.aspect_ratio || '16:9',
    size: d.video_size || '720P',
  }
})

// Video form
const video = reactive({
  prompt: '',
  mode: 'text', // 2.5 语义；非 2.5 模型由 watch 映射为 t2v
  duration: String(appState.simpleDefault?.duration ?? 5),
  resolution: '1280x720', // 非 2.5 模型的像素档（兼容兜底）
  ratio: appState.simpleDefault?.aspect_ratio || '16:9', // 2.5 系列：画幅比例
  size: appState.simpleDefault?.video_size || '720P',    // 2.5 系列：清晰度档位
  seed: '',
  negative: '',
  system: '',
  // v8.0：对齐官方接口的素材形态
  refImages: [] as File[],       // reference：多图（≤5/≤8）
  firstFrame: null as File | null, // keyframe：首帧
  firstName: '',
  lastFrame: null as File | null,  // keyframe：尾帧
  lastName: '',
  audioUrls: [''] as string[],     // reference：音频公开 URL（≤3）
})

// 「更多设置」展开态（默认展开，预设值一目了然）
const videoAdvancedOpen = ref(true)
// 付费档二次确认（同一模型只确认一次，切换模型后重置）
const paidConfirmed = ref(false)
// 草稿只恢复提示词，避免老草稿里的 9:16 / 非法时长污染新预设
const draftPromptRestored = ref(false)

// Image form
const image = reactive({
  prompt: '',
  size: '1024x1024',
  negative: '',
  system: '',
  // v8.1：i2i 多参考图（上游 extra_body.image 本就是数组）
  refImages: [] as File[],
  imageResultVisible: false,
  imageResultSrc: '',
})

const advancedCollapsed = reactive({ video: true, image: true })

// 3.4 / v8.0：视频草稿只恢复提示词——设置项一律以预设为准，
// 避免旧草稿把 9:16、旧时长档或跨模型的非法 mode 带回，造成「一键」产物方向错误或 422。
;(() => {
  const vd = videoDraft.load()
  if (vd && typeof vd.prompt === 'string' && vd.prompt) {
    video.prompt = vd.prompt
    draftPromptRestored.value = true
  }
  const id = imageDraft.load()
  if (id) {
    if (typeof id.prompt === 'string') image.prompt = id.prompt
    if (typeof id.size === 'string') image.size = id.size
    if (typeof id.negative === 'string') image.negative = id.negative
    if (typeof id.system === 'string') image.system = id.system
  }
})()
videoDraft.autoSave(video, (v) => ({ prompt: v.prompt }))
imageDraft.autoSave(image, (v) => ({
  prompt: v.prompt, size: v.size, negative: v.negative, system: v.system,
}))

// ── 按所选视频模型动态派生选项 ──
const currentVideoModel = computed(() => appState.models.video || '')
const isV25 = computed(() => vmCaps.isV25Model(currentVideoModel.value))
const isPaidModel = computed(() => vmCaps.isPaidTag(currentVideoModel.value))
const modeOptions = computed(() => vmCaps.modeOptions(currentVideoModel.value))
const durationOptions = computed(() => vmCaps.durationOptions(currentVideoModel.value))
const ratioOptions = computed(() => vmCaps.ratioOptions(currentVideoModel.value))
const sizeOptions = computed(() => vmCaps.sizeOptions(currentVideoModel.value))
const pixelOptions = computed(() => vmCaps.pixelOptions(currentVideoModel.value))
const maxRefImages = computed(() => vmCaps.maxRefImages(currentVideoModel.value) ?? 5)
// v8.1：图片参考图上限（后端 AGNES_IMAGE_MAX_REF_IMAGES 下发，默认 5）
const maxImageRefImages = computed(() => Number(appState.imageCapabilities?.max_ref_images ?? 5))
const maxRefAudios = computed(() => vmCaps.maxRefAudios(currentVideoModel.value) ?? 3)

// 免费档排前面、付费档靠后：降低免费用户误选付费档的概率（仍保留显式标注与二次确认）
const videoModelOptions = computed(() => {
  const list = [...(appState.modelListCache.video || [])]
  // 模型列表尚未加载时至少让当前模型可选，避免下拉为空
  if (!list.length && currentVideoModel.value) list.push(currentVideoModel.value)
  return list.sort((a, b) => Number(vmCaps.isPaidTag(a)) - Number(vmCaps.isPaidTag(b)))
})

// 素材区显隐（按模型 + 模式语义统一）
const needsRefImages = computed(() => (isV25.value ? video.mode === 'reference' : video.mode !== 't2v'))
const needsFrames = computed(() => (isV25.value ? video.mode === 'keyframe' : video.mode === 'keyframes'))

// 画幅方向标记（横屏 / 竖屏 / 方形），避免用户只看比例数字选错方向
function ratioOrientation(ratio: string): string {
  const [w, h] = ratio.split(':').map(Number)
  if (w === h) return t('ratioSquare')
  return w > h ? t('ratioLandscape') : t('ratioPortrait')
}

// 比例下拉标签：`16:9（横屏）· 1280×720`
function ratioOptionLabel(ratio: string): string {
  const [w, h] = vmCaps.ratioToWH(ratio, currentVideoModel.value)
  return `${ratio}（${ratioOrientation(ratio)}）· ${w}×${h}`
}

// 预设摘要（主区一行展示当前生效的关键选项）
const modeLabel = computed(() => modeOptions.value.find((o) => o.id === video.mode)?.label || '')
const presetSummary = computed(() => {
  const parts: string[] = [
    vmCaps.capsOf(currentVideoModel.value).label || currentVideoModel.value,
    modeLabel.value,
    `${video.duration}s`,
    isV25.value ? `${video.ratio}（${ratioOrientation(video.ratio)}）` : video.resolution,
  ]
  if (isV25.value && sizeOptions.value.length > 1) parts.push(video.size)
  parts.push(isPaidModel.value ? t('simplePaidBadge') : t('simpleFreeBadge'))
  return parts.filter(Boolean).join(' · ')
})

// 模型切换 → 修正表单值（选项集变化时避免非法值/422）
// immediate：首次挂载时模型可能已加载完成，必须立刻把 'text' 与 2.5 选项对齐。
watch(
  currentVideoModel,
  () => {
    paidConfirmed.value = false
    const ms = modeOptions.value
    if (ms.length && !ms.some((x) => x.id === video.mode)) {
      // 语义映射优先（t2v→text / i2v→reference / keyframes→keyframe），避免误落到其它模式
      const mapped = MODE_API_TO_V25[video.mode]
      video.mode = ms.some((x) => x.id === mapped) ? mapped : ms[0].id
    }
    const ds = durationOptions.value
    if (ds.length && !ds.includes(Number(video.duration))) {
      video.duration = String(ds[0])
    }
    if (isV25.value) {
      // 2.5 系列：比例/清晰度对齐能力；非法值回落预设（默认 16:9）
      if (ratioOptions.value.length && !ratioOptions.value.includes(video.ratio)) {
        video.ratio = preset.value.ratio
      }
      if (sizeOptions.value.length && !sizeOptions.value.includes(video.size)) {
        video.size = sizeOptions.value[0]
      }
    }
  },
  { immediate: true },
)

function toggleCollapse(key: 'video' | 'image') {
  advancedCollapsed[key] = !advancedCollapsed[key]
}

// ── v8.0：视频素材（多图 / 首尾帧 / 音频 URL）──
// v8.1：多图交互收敛到共享组件 RefImagesInput（缩略图 / #N / 排序 / 选满禁用）
function onFirstFrameChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  video.firstFrame = file
  video.firstName = file ? file.name : ''
}

function onLastFrameChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0] || null
  video.lastFrame = file
  video.lastName = file ? file.name : ''
}

function addAudioUrl() {
  if (video.audioUrls.length < maxRefAudios.value) video.audioUrls.push('')
}

function removeAudioUrl(index: number) {
  video.audioUrls.splice(index, 1)
  if (!video.audioUrls.length) video.audioUrls.push('')
}

/** 恢复到官方推荐预设（免费档 / 5s / 16:9 / 720P / 文生视频）。 */
function resetPreset() {
  video.mode = isV25.value ? 'text' : 't2v'
  video.duration = preset.value.duration
  video.ratio = preset.value.ratio
  video.size = preset.value.size
  video.seed = ''
  video.negative = ''
  video.system = ''
  video.refImages = []
  video.firstFrame = null
  video.firstName = ''
  video.lastFrame = null
  video.lastName = ''
  video.audioUrls = ['']
  draftPromptRestored.value = false
  paidConfirmed.value = false
  // 付费档 → 回到免费预设模型
  if (vmCaps.isPaidTag(currentVideoModel.value) && preset.value.model) {
    appState.models.video = preset.value.model
    void saveModels()
  }
}

function parseResolution(val: string) {
  const [w, h] = val.split('x').map(Number)
  return { width: w, height: h }
}

// 模型选择即保存（与 ConfigPanel 联动同一全局状态）
async function onVideoModelChange(e: Event) {
  const model = (e.target as HTMLSelectElement).value
  if (!model) return
  appState.models.video = model
  trackEvent('config_action', { action: 'select_video_model', video_model: model })
  await saveModels()
}

async function submitSimple() {
  // 付费档二次确认：避免免费用户误选后直接产生费用
  if (isPaidModel.value && !paidConfirmed.value) {
    const ok = await confirmAsync(t('simplePaidConfirm'))
    if (!ok) {
      videoAdvancedOpen.value = true // 引导用户改回免费档
      return
    }
    paidConfirmed.value = true
  }

  await videoSubmit.runSubmit({
    taskType: 'simple',
    buildForm: () => {
      const prompt = video.prompt.trim()
      if (!prompt) throw new Error(t('enterPrompt'))

      // 模式 ↔ 素材一致性（前端先拦，后端同口径校验）
      const audioUrls = video.audioUrls.map((u) => u.trim()).filter(Boolean)
      if (needsRefImages.value && !video.refImages.length && !audioUrls.length) {
        throw new Error(t('simpleModeNeedsRef'))
      }
      if (needsFrames.value && !video.firstFrame && !video.lastFrame) {
        throw new Error(t('simpleModeNeedsFrame'))
      }
      if (audioUrls.some((u) => !/^https?:\/\//i.test(u))) {
        throw new Error(t('simpleAudioUrlInvalid'))
      }

      const form = new FormData()
      form.append('prompt', prompt)
      // 2.5 系列模式映射：text→t2v / reference→i2v / keyframe→keyframes
      form.append('mode', isV25.value ? MODE_V25_TO_API[video.mode] || 't2v' : video.mode)
      form.append('duration', video.duration)
      if (isV25.value) {
        // 2.5 系列：比例 → 基准像素 + 清晰度档位
        const [w, h] = vmCaps.ratioToWH(video.ratio, currentVideoModel.value)
        form.append('video_width', String(w))
        form.append('video_height', String(h))
        form.append('video_size', video.size)
      } else {
        const res = parseResolution(video.resolution)
        form.append('video_width', String(res.width))
        form.append('video_height', String(res.height))
      }
      if (video.seed) form.append('seed', video.seed)
      // 2.5 系列不支持负面提示词，不提交
      if (!isV25.value && video.negative) form.append('negative_prompt', video.negative)
      if (video.system.trim()) form.append('system_prompt', video.system.trim())

      // v8.0：reference 多图 + 音频；keyframe 原生首尾帧（两者互斥）
      if (needsRefImages.value) {
        video.refImages.forEach((f) => form.append('reference_images', f))
        if (audioUrls.length) form.append('reference_audio_urls', audioUrls.join('\n'))
      }
      if (needsFrames.value) {
        if (video.firstFrame) form.append('first_frame_image', video.firstFrame)
        if (video.lastFrame) form.append('last_frame_image', video.lastFrame)
      }
      return form
    },
    extraEvent: {
      mode: video.mode,
      duration: video.duration,
      resolution: isV25.value ? video.ratio + '/' + video.size : video.resolution,
      video_model: currentVideoModel.value,
      paid_model: isPaidModel.value,
      ref_images: video.refImages.length,
      ref_audios: video.audioUrls.filter((u) => u.trim()).length,
    },
    onSuccess: () => {
      videoDraft.clear()
      draftPromptRestored.value = false
    },
  })
}

async function submitImage() {
  await imageSubmit.runSubmit({
    taskType: 'simple_image',
    eventTaskType: 'image',
    buildForm: () => {
      const prompt = image.prompt.trim()
      if (!prompt) throw new Error(t('enterImagePrompt'))
      const form = new FormData()
      form.append('prompt', prompt)
      form.append('size', image.size)
      if (image.negative) form.append('negative_prompt', image.negative)
      if (image.system.trim()) form.append('system_prompt', image.system.trim())
      // v8.1：多参考图（旧单数字段仍被后端接受，新前端统一走数组）
      image.refImages.forEach((f) => form.append('reference_images', f))
      return form
    },
    extraEvent: { size: image.size },
    successMessage: t('imgComplete'),
    onSubmit: (d) => {
      image.imageResultSrc = '/api/image/' + d.task_id
      image.imageResultVisible = true
    },
    onSuccess: () => imageDraft.clear(),
  })
}
</script>

<template>
  <div>
    <!-- 子模式 + 示例入口（同一行工具栏，避免散落的裸链接） -->
    <div class="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
      <span class="label mb-0 shrink-0">{{ t('subModeLabel') }}</span>
      <div class="seg">
        <button type="button" class="seg-item" :class="subMode === 'video' ? 'is-active' : ''" @click="subMode = 'video'">
          {{ stripEmoji(t('subModeVideo')) }}
        </button>
        <button type="button" class="seg-item" :class="subMode === 'image' ? 'is-active' : ''" @click="subMode = 'image'">
          {{ stripEmoji(t('subModeImage')) }}
        </button>
      </div>
      <!-- v8.0：模式示例统一指到官网新版示例页（/showcase，带 UI 语言前缀） -->
      <a
        :href="siteUrl('/showcase')"
        target="_blank"
        rel="noopener"
        class="ms-auto text-[11.5px] text-muted transition-colors hover:text-accent"
      >{{ stripEmoji(t('exampleLinkSimple')) }}</a>
    </div>

    <!-- Video sub-form -->
    <div v-if="subMode === 'video'">
      <section class="panel mb-4">
        <header class="panel-head">
          <h2 class="panel-title">{{ t('simpleSettings') }}</h2>
          <!-- 付费/免费档一眼可辨 -->
          <span class="chip" :class="isPaidModel ? 'chip-warning' : 'chip-success'">
            {{ isPaidModel ? t('simplePaidBadge') : t('simpleFreeBadge') }}
          </span>
        </header>

        <div class="panel-body">
          <!-- 主区只留提示词：输入后点一次即可生成 -->
          <div class="mb-4">
            <label class="label">{{ t('promptLabel') }} <span class="text-danger">*</span></label>
            <textarea v-model="video.prompt" rows="4" :placeholder="t('promptPlaceholder')" class="field"></textarea>
            <p v-if="draftPromptRestored" class="hint mt-1.5">{{ t('simpleDraftRestored') }}</p>
          </div>

          <!-- 预设摘要 + 修改/恢复默认 -->
          <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11.5px] text-muted">
            <span>{{ t('simplePresetLabel') }}: <span class="text-ink-2">{{ presetSummary }}</span></span>
            <button type="button" class="text-accent transition-colors hover:text-ink" @click="videoAdvancedOpen = !videoAdvancedOpen">
              {{ videoAdvancedOpen ? t('simpleHideSettings') : t('simpleCustomize') }}
            </button>
            <button type="button" class="text-muted transition-colors hover:text-ink-2" @click="resetPreset">
              {{ t('simpleResetPreset') }}
            </button>
          </div>

          <p v-if="!isApiKeyConfigured()" class="mt-3 flex items-start gap-2 text-[11.5px] text-warning">
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full" style="background: var(--color-warning)"></span>
            {{ t('simpleKeyMissing') }}
          </p>

          <!-- 更多设置 -->
          <div v-show="videoAdvancedOpen" class="mt-5 space-y-4 border-t border-rule/60 pt-5">
          <!-- 模型选择：免费档排前，付费档显式标注 -->
          <div class="subpanel">
            <label class="label">{{ t('vmModelSelect') }}</label>
            <select :value="currentVideoModel" class="field" @change="onVideoModelChange">
              <option v-for="m in videoModelOptions" :key="m" :value="m">
                {{ m }} · {{ vmCaps.isPaidTag(m) ? t('simplePaidBadge') : t('simpleFreeBadge') }}{{ vmCaps.isAdapted(m) ? '' : ' ⚠' }}
              </option>
            </select>
            <!-- 付费档醒目提示：不要让免费用户误选 -->
            <p v-if="isPaidModel" class="mt-2 text-[11.5px] font-medium text-warning">{{ t('simplePaidNotice') }}</p>
            <p v-if="!vmCaps.isAdapted(currentVideoModel)" class="mt-2 text-[11.5px] text-warning">{{ t('vmUnadaptedHint') }}</p>
            <p class="hint mt-2">{{ vmCaps.descOf(currentVideoModel) }}</p>
            <p v-if="vmCaps.priceText(currentVideoModel)" class="mt-1 text-[11.5px]" :class="isPaidModel ? 'text-warning' : 'text-success'">
              {{ vmCaps.priceText(currentVideoModel) }}
            </p>
          </div>

          <!-- 模式 / 时长 / 画幅 -->
          <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div>
              <label class="label">{{ t('genMode') }}</label>
              <select v-model="video.mode" class="field">
                <option v-for="opt in modeOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
              </select>
            </div>
            <div>
              <label class="label">{{ t('duration') }}</label>
              <select v-model="video.duration" class="field">
                <option v-for="d in durationOptions" :key="d" :value="String(d)">{{ d }}s</option>
              </select>
            </div>
            <!-- 分辨率：2.5 系列 比例 + 清晰度；旧模型像素档 -->
            <div v-if="!isV25">
              <label class="label">{{ t('resolution') }}</label>
              <select v-model="video.resolution" class="field">
                <option v-for="opt in pixelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>
            <template v-else>
              <div>
                <label class="label">{{ t('vmRatioLabel') }} <span class="opacity-70">({{ t('vmRatioHint') }})</span></label>
                <select v-model="video.ratio" class="field">
                  <option v-for="r in ratioOptions" :key="r" :value="r">{{ ratioOptionLabel(r) }}</option>
                </select>
              </div>
              <div v-if="sizeOptions.length > 1">
                <label class="label">{{ t('vmSizeLabel') }}</label>
                <select v-model="video.size" class="field">
                  <option v-for="s in sizeOptions" :key="s" :value="s">{{ s }}</option>
                </select>
              </div>
            </template>
          </div>

          <!-- 2.5 系列竖屏（9:16）上游画面旋转缺陷提示 -->
          <p v-if="isV25 && video.ratio === '9:16'" class="text-[11.5px] text-warning">{{ t('vmPortraitRotateHint') }}</p>

          <!-- reference：多图 + 参考音频 -->
          <div v-if="needsRefImages" class="subpanel space-y-4">
            <RefImagesInput
              v-model="video.refImages"
              :max="maxRefImages"
              :label="`${t('simpleRefImagesLabel')} (≤ ${maxRefImages})`"
              :hint="t('simpleRefImagesHint')"
            />

            <div>
              <label class="label">{{ t('simpleRefAudiosLabel') }} <span class="opacity-70">(≤ {{ maxRefAudios }})</span></label>
              <div class="space-y-2">
                <div v-for="(_, i) in video.audioUrls" :key="i" class="flex items-center gap-2">
                  <input v-model="video.audioUrls[i]" type="url" placeholder="https://..." class="field flex-1" />
                  <button type="button" class="btn btn-quiet btn-sm text-danger" @click="removeAudioUrl(i)">✕</button>
                </div>
              </div>
              <button v-if="video.audioUrls.length < maxRefAudios" type="button" class="btn btn-quiet btn-xs mt-2 text-accent" @click="addAudioUrl">
                + {{ t('simpleAddAudio') }}
              </button>
              <p class="hint mt-1.5">{{ t('simpleRefAudioHint') }}</p>
            </div>
          </div>

          <!-- keyframe：原生首尾帧 -->
          <div v-if="needsFrames" class="subpanel space-y-3">
            <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label class="label">{{ t('simpleFirstFrame') }}</label>
                <div class="flex items-center gap-3">
                  <label class="btn btn-ghost shrink-0">
                    <span>{{ t('chooseImage') }}</span>
                    <input type="file" accept="image/*" class="hidden" @change="onFirstFrameChange" />
                  </label>
                  <span class="truncate text-[11.5px] text-muted">{{ video.firstName || t('notSelected') }}</span>
                </div>
              </div>
              <div>
                <label class="label">{{ t('simpleLastFrame') }}</label>
                <div class="flex items-center gap-3">
                  <label class="btn btn-ghost shrink-0">
                    <span>{{ t('chooseImage') }}</span>
                    <input type="file" accept="image/*" class="hidden" @change="onLastFrameChange" />
                  </label>
                  <span class="truncate text-[11.5px] text-muted">{{ video.lastName || t('notSelected') }}</span>
                </div>
              </div>
            </div>
            <p class="hint">{{ t('simpleFrameHint') }}</p>
          </div>

          <!-- 高级参数 -->
          <div class="border-t border-rule/60 pt-4">
            <button type="button" class="collapse-header flex w-full items-center justify-between" @click="toggleCollapse('video')">
              <span class="label mb-0">{{ t('advancedSettings') }}</span>
              <span class="mono text-[11px] text-muted">{{ advancedCollapsed.video ? '+' : '−' }}</span>
            </button>
            <div v-show="!advancedCollapsed.video" class="mt-4 space-y-4">
              <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label class="label">Seed <span class="opacity-70">({{ t('optional') }})</span></label>
                  <input v-model="video.seed" type="number" :placeholder="t('seedPlaceholder')" class="field" />
                </div>
                <div v-if="vmCaps.supportsNegative(currentVideoModel)">
                  <label class="label">Negative Prompt <span class="opacity-70">({{ t('optional') }})</span></label>
                  <input v-model="video.negative" :placeholder="t('negativePlaceholder')" class="field" />
                </div>
                <div v-else class="md:col-span-2">
                  <label class="label">Negative Prompt</label>
                  <input disabled :placeholder="t('vmNegativeDisabledPlaceholder')" class="field" />
                </div>
              </div>
              <div>
                <label class="label">{{ t('systemPrompt') }} <span class="opacity-70">({{ t('optional') }})</span></label>
                <textarea v-model="video.system" rows="2" :placeholder="t('systemPromptPlaceholder')" class="field"></textarea>
              </div>
            </div>
          </div>
        </div>
        </div>
      </section>

      <WatermarkToggle />

      <button
        class="btn btn-primary btn-block"
        :disabled="videoSubmit.submitting.value || !video.prompt.trim()"
        @click="submitSimple"
      >
        {{ videoSubmit.submitting.value ? t('submitting') : t('startGenerate') }}
      </button>
      <p class="hint mt-2 text-center">{{ t('simpleWaitHint') }}</p>
    </div>

    <!-- Image sub-form -->
    <div v-else>
      <section class="panel mb-4">
        <header class="panel-head">
          <h2 class="panel-title">{{ t('imageSettings') }}</h2>
        </header>

        <div class="panel-body space-y-4">
          <div>
            <label class="label">{{ t('imagePrompt') }} <span class="text-danger">*</span></label>
            <textarea v-model="image.prompt" rows="3" :placeholder="t('imagePromptPlaceholder')" class="field"></textarea>
          </div>

          <div>
            <label class="label">{{ t('imageSize') }}</label>
            <select v-model="image.size" class="field">
              <option value="1024x1024">{{ t('resSquare') }} (1024x1024)</option>
              <option value="768x1152">{{ t('resPortrait') }} (768x1152)</option>
              <option value="1280x720">{{ t('resLandscape') }} (1280x720)</option>
              <option value="768x1344">{{ t('resPortraitHD') }} (HD)</option>
              <option value="1344x768">{{ t('resLandscapeHD') }} (HD)</option>
              <option value="1024x1792">{{ t('resPortraitTall') }}</option>
              <option value="1792x1024">{{ t('resLandscapeWide') }}</option>
            </select>
          </div>

          <RefImagesInput
            v-model="image.refImages"
            :max="maxImageRefImages"
            :label="t('refImageSimple')"
            :hint="t('refImageHint')"
          />

          <div class="border-t border-rule/60 pt-4">
            <button type="button" class="collapse-header flex w-full items-center justify-between" @click="toggleCollapse('image')">
              <span class="label mb-0">{{ t('advancedSettings') }}</span>
              <span class="mono text-[11px] text-muted">{{ advancedCollapsed.image ? '+' : '−' }}</span>
            </button>
            <div v-show="!advancedCollapsed.image" class="mt-4 space-y-4">
              <div>
                <label class="label">Negative Prompt <span class="opacity-70">({{ t('optional') }})</span></label>
                <input v-model="image.negative" :placeholder="t('negativePlaceholder')" class="field" />
              </div>
              <div>
                <label class="label">{{ t('systemPrompt') }} <span class="opacity-70">({{ t('optional') }})</span></label>
                <textarea v-model="image.system" rows="2" :placeholder="t('systemPromptPlaceholder')" class="field"></textarea>
              </div>
            </div>
          </div>
        </div>
      </section>

      <button
        class="btn btn-primary btn-block"
        :disabled="imageSubmit.submitting.value"
        @click="submitImage"
      >
        {{ imageSubmit.submitting.value ? t('submitting') : t('imgGenerate') }}
      </button>

      <div v-if="image.imageResultVisible" class="panel mt-4">
        <div class="panel-body">
          <p class="mb-2 flex items-center gap-2 text-[12.5px] font-medium text-success">
            <span class="h-1.5 w-1.5 rounded-full" style="background: var(--color-success)"></span>
            {{ t('imgComplete') }}
          </p>
          <img :src="image.imageResultSrc" class="w-full rounded-lg max-h-96 object-contain" />
        </div>
      </div>
    </div>
  </div>
</template>
