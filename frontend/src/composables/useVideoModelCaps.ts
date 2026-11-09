import { appState } from '@/store'
import { currentLang } from '@/i18n'

// 2.5 系列模型前缀
const V25_PREFIX = 'agnes-video-2.5'

// 画幅比例 → 720P 基准像素（用于提交 video_width/video_height）
const RATIO_TO_WH: Record<string, [number, number]> = {
  '21:9': [1680, 720],
  '16:9': [1280, 720],
  '4:3': [960, 720],
  '1:1': [720, 720],
  '3:4': [720, 960],
  '9:16': [720, 1280],
}

// 历史像素档归一化：旧「横屏」1152x768 是 3:2，会被 2.5 系列映射成 4:3 画幅，
// 已在 v7.x 统一为真正的 16:9（1280x720）。此处兼容本地草稿里的旧值。
const LEGACY_RESOLUTION_MAP: Record<string, string> = {
  '1152x768': '1280x720',
}

export function normalizeResolution(value: string): string {
  return LEGACY_RESOLUTION_MAP[value] || value
}

// 2.5 系列模式 → 后端 simple 任务模式（提交映射）
export const MODE_V25_TO_API: Record<string, string> = {
  text: 't2v',
  reference: 'i2v',
  keyframe: 'keyframes',
}

// 后端 simple 任务模式 → 2.5 系列模式（表单回显）
export const MODE_API_TO_V25: Record<string, string> = {
  t2v: 'text',
  i2v: 'reference',
  keyframes: 'keyframe',
  ti2vid: 'reference',
}

function isV25(model: string): boolean {
  return typeof model === 'string' && model.startsWith(V25_PREFIX)
}

// 取能力元数据中的双语文本（按当前语言，缺省回退 en/zh/原值）
function L(obj: { zh?: string; en?: string } | string | undefined, fallback = ''): string {
  if (!obj) return fallback
  if (typeof obj === 'string') return obj
  return obj[currentLang.value === 'zh' ? 'zh' : 'en'] || obj.en || obj.zh || fallback
}

export function useVideoModelCaps() {
  // 当前选中视频模型
  const currentModel = () => appState.models.video || ''

  // 某模型的能力元数据（未知模型返回空）
  const capsOf = (model: string): Record<string, any> => appState.videoCapabilities[model] || {}

  // 是否 2.5 系列
  const isV25Model = (model: string) => isV25(model)

  // v7.0 U8：该模型是否有本地能力元数据（无 = 当前版本未适配）。
  // 能力表随发版硬编码，旧版本会「模型可见但档位不能用」，必须显式提示而非
  // 静默按 v2.0 像素协议提交（详见 plans/v7.0/upstream_error_handling_plan.md §4）。
  const isAdapted = (model: string): boolean => !!capsOf(model).label

  // 价格标签（付费/免费/限时免费）
  function priceText(model: string): string {
    const c = capsOf(model)
    return c.price_text ? L(c.price_text, '') : isPaidTag(model) ? 'Paid' : ''
  }

  function isPaidTag(model: string): boolean {
    const c = capsOf(model)
    if (c && c.price) return c.price === 'paid'
    return model === 'agnes-video-2.5'
  }

  // 该模型的生成模式选项（[{id, label}]，label 已本地化）
  function modeOptions(model: string): { id: string; label: string }[] {
    const c = capsOf(model)
    if (c.modes && Array.isArray(c.modes)) {
      return c.modes.map((m: any) => ({ id: m.id, label: L(m.label, m.id) }))
    }
    // 兜底：v2.0 默认
    return [
      { id: 't2v', label: L({ zh: '文生视频', en: 'Text to video' }) },
      { id: 'i2v', label: L({ zh: '图生视频（1 张参考图）', en: 'Image to video (1 ref)' }) },
      { id: 'keyframes', label: L({ zh: '关键帧动画（首尾帧）', en: 'Keyframes (first+last)' }) },
    ]
  }

  // 时长选项（兜底与后端 VIDEO_25_DURATIONS 同源，避免未适配模型选中即 422）
  function durationOptions(model: string): number[] {
    const c = capsOf(model)
    if (c.durations && Array.isArray(c.durations)) return c.durations
    return [4, 5, 6, 8, 10, 12]
  }

  // 画幅比例选项（兜底顺序与后端 VIDEO_ASPECT_RATIOS 一致）
  function ratioOptions(model: string): string[] {
    const c = capsOf(model)
    if (c.resolution && c.resolution.ratios) return c.resolution.ratios
    return ['21:9', '16:9', '4:3', '1:1', '3:4', '9:16']
  }

  // 清晰度档位选项（v2.0 无）
  function sizeOptions(model: string): string[] {
    const c = capsOf(model)
    if (c.resolution && c.resolution.sizes) return c.resolution.sizes
    return []
  }

  // 像素分辨率选项（仅 v2.0）
  function pixelOptions(model: string): { value: string; label: string }[] {
    const c = capsOf(model)
    if (c.resolution && c.resolution.type === 'pixels' && c.resolution.options) {
      return c.resolution.options.map((o: any) => ({ value: o.value, label: L(o.label, o.value) }))
    }
    return [
      { value: '768x1152', label: L({ zh: '竖屏 768x1152', en: 'Portrait 768x1152' }) },
      { value: '1280x720', label: L({ zh: '横屏 1280x720', en: 'Landscape 1280x720' }) },
      { value: '1024x1024', label: L({ zh: '方形 1024x1024', en: 'Square 1024x1024' }) },
    ]
  }

  // 比例 → 像素（提交用）
  function ratioToWH(ratio: string, model: string): [number, number] {
    return RATIO_TO_WH[ratio] || (isV25(model) ? [1280, 720] : [768, 1152])
  }

  // 比例 → 展示文本（含实际输出像素，如 "9:16 · 720×1280"）
  function ratioWHText(ratio: string, model: string): string {
    const [w, h] = ratioToWH(ratio, model)
    return `${ratio} · ${w}×${h}`
  }

  // 支持负面提示词？
  function supportsNegative(model: string): boolean {
    const c = capsOf(model)
    return c.supports_negative !== false
  }

  // 参考图上限（None = 不限）
  function maxRefImages(model: string): number | null {
    const c = capsOf(model)
    return c.max_ref_images ?? null
  }

  // 参考音频上限（None = 不支持/不限）
  function maxRefAudios(model: string): number | null {
    const c = capsOf(model)
    return c.max_ref_audios ?? null
  }

  // 支持参考视频？
  function supportsRefVideo(model: string): boolean {
    return !!capsOf(model).supports_ref_video
  }

  // 模型能力简介（本地化描述）
  function descOf(model: string): string {
    const c = capsOf(model)
    return L(c.desc, '')
  }

  // 全部已知视频模型能力（供差异对比表）
  function allCapabilities(): { model: string; caps: Record<string, any> }[] {
    const selected = currentModel()
    const all = appState.modelListCache.video || []
    const known = all.filter((m) => capsOf(m).label)
    // 若当前模型不在列表（如未拉取成功），补一条
    const ids = known.map((k) => k)
    if (selected && !ids.includes(selected) && capsOf(selected).label) known.unshift(selected)
    return known.map((m) => ({ model: m, caps: capsOf(m) }))
  }

  return {
    currentModel,
    capsOf,
    isV25Model,
    isAdapted,
    priceText,
    isPaidTag,
    modeOptions,
    durationOptions,
    ratioOptions,
    sizeOptions,
    pixelOptions,
    ratioToWH,
    ratioWHText,
    supportsNegative,
    maxRefImages,
    maxRefAudios,
    supportsRefVideo,
    descOf,
    allCapabilities,
  }
}
