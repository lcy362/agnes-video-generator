import { ref } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useToast } from './useToast'
import { useGa } from './useGa'
import { useNavigation } from './useNavigation'
import * as api from '@/api'

export interface TaskSubmitOptions {
  taskType: string
  /** 构造 FormData；校验失败时 throw Error(msg) 中断（消息以 toast 提示） */
  buildForm: () => FormData
  /** 埋点 task_type（默认取 taskType） */
  eventTaskType?: string
  extraEvent?: Record<string, any>
  /** 成功 toast 文案（默认 t('submitted')） */
  successMessage?: string
  /** 成功后自定义处理（默认：跳转进度页 + submitted toast） */
  onSubmit?: (d: any) => void
  /** 成功后钩子（默认跳转/toast 之后调用，用于清理草稿等） */
  onSuccess?: (d: any) => void
}

const SUBMIT_APIS: Record<string, (fd: FormData) => Promise<any>> = {
  simple: (fd) => api.submitSimple(fd),
  simple_image: (fd) => api.submitImage(fd),
  creative: (fd) => api.submitCreative(fd),
  manuscript: (fd) => api.submitManuscript(fd),
  anchor: (fd) => api.submitAnchor(fd),
  poetry: (fd) => api.submitPoetry(fd),
}

/**
 * 3.1：任务提交统一执行器。
 * 收敛各表单重复的「校验 → 提交 → 埋点 → 跳转/失败提示 → 恢复按钮」样板。
 * 每次调用返回独立 submitting（SimpleForm 视频/图片双提交互不干扰）。
 */
export function useTaskSubmit() {
  const submitting = ref(false)
  const { showToast } = useToast()
  const { trackEvent } = useGa()
  const { goProgress } = useNavigation()

  async function runSubmit(opts: TaskSubmitOptions): Promise<any> {
    if (submitting.value) return null
    const apiFn = SUBMIT_APIS[opts.taskType]
    if (!apiFn) {
      showToast(`unknown task type: ${opts.taskType}`, 3500)
      return null
    }
    let form: FormData
    try {
      form = opts.buildForm()
    } catch (e: any) {
      showToast(e?.message || t('failCreate'), 3500)
      return null
    }
    submitting.value = true
    try {
      const d = await apiFn(form)
      if (!d.ok) throw new Error(d.detail || t('failCreate'))
      trackEvent('create_task', {
        task_type: opts.eventTaskType || opts.taskType,
        ...opts.extraEvent,
      })
      if (opts.onSubmit) {
        opts.onSubmit(d)
      } else {
        appState.currentTaskType = opts.taskType
        appState.currentDirName = d.dir_name
        goProgress(d.task_id, 'create')
      }
      showToast(opts.successMessage || t('submitted'), 5000, 'success')
      opts.onSuccess?.(d)
      return d
    } catch (e: any) {
      trackEvent('create_task_failed', {
        task_type: opts.eventTaskType || opts.taskType,
        error: (e.message || '').slice(0, 120),
      })
      showToast(t('failCreate') + ': ' + e.message, 4500)
      return null
    } finally {
      submitting.value = false
    }
  }

  return { submitting, runSubmit }
}

/** 3.1：收集 SubtitleConfig + 音色的公共音频/字幕字段到 FormData。 */
export function collectAudioSubtitleFields(
  fd: FormData,
  sc: any,
  voiceSelections: Record<string, string>,
  taskKey: string,
  lang = 'zh',
) {
  if (!sc) return
  fd.append('audio_enabled', String(sc.audioEnabled))
  fd.append('audio_voice', voiceSelections[taskKey])
  fd.append('audio_lang', lang)
  fd.append('audio_rate', sc.rate)
  fd.append('subtitle_enabled', String(sc.subtitleEnabled))
  fd.append('subtitle_style_mode', sc.styleMode)
  fd.append('subtitle_style_hints', sc.style.hints)
  fd.append('subtitle_font', sc.style.font)
  fd.append('subtitle_color', sc.style.color)
  fd.append('subtitle_fontsize', String(sc.style.fontsize))
  fd.append('subtitle_position', sc.style.position)
  fd.append('subtitle_stroke_color', sc.style.stroke_color)
  fd.append('subtitle_stroke_width', String(sc.style.stroke_width))
  fd.append('subtitle_bg_color', sc.style.bg_color)
}
