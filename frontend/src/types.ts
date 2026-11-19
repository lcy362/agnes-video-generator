// 与后端 models/task.py 对齐的类型定义（仅前端需要的字段）

export type TaskType = 'simple' | 'creative' | 'manuscript' | 'anchor' | 'poetry' | 'image'

export interface TaskState {
  task_id: string
  task_type?: TaskType
  status?: string
  dir_name?: string
  current_step?: string
  current_status?: string
  current_progress?: number
  current_message?: string
  // v7.0：结构化消息——后端下发 i18n key + 插值参数，前端用 22 语言文案渲染；
  // 未命中 key（旧后端 / 未覆盖）时回退 current_message。
  current_message_key?: string
  current_message_params?: Record<string, string | number>
  final_video_file?: string
  idea?: string
  prompt?: string
  manuscript_text?: string
  script_text?: string
  scene_count?: number
  paragraph_count?: number
  paragraphs?: unknown[]
  creative_name?: string
  // v6.1：后台是否有活跃 pipeline（服务重启后遗留的 pending/queued 任务为 false）
  active?: boolean
  // GA 埋点：error_collector 内存聚合的上游接口报错（按状态码计数，轮询增量上报）
  upstream_errors?: UpstreamError[]
  // v7.7：快速重试模式状态（连续 2 次 503 后 available=true，用户开启后 enabled=true）
  fast_retry?: FastRetryState
  // v8.3：长任务模式状态（忙轨次数封顶 → 累计等待时长封顶）
  long_task?: LongTaskState
  [key: string]: any
}

// v8.3 长任务模式（后端 models/task.py::LongTaskConfig 对齐）
export interface LongTaskState {
  enabled?: boolean
  timeout_minutes?: number
  waited_s?: number
  started_at?: string
  finished_reason?: '' | 'expired' | 'success' | 'non_retryable' | 'disabled' | string
  last_reason?: string
}

// v7.7 快速重试模式（后端 models/task.py::FastRetryConfig 对齐）
export interface FastRetryState {
  available?: boolean
  enabled?: boolean
  per_minute?: number
  minutes?: number
  consecutive_busy?: number
  attempts?: number
  started_at?: string
  finished_reason?: '' | 'success' | 'expired' | 'disabled' | string
  // v8.0：本次是否由「设置页自动快速重试」触发 / 用户本轮是否手动关过
  auto?: boolean
  auto_off?: boolean
  // v8.4：两轮之间的常规节奏间隔 X（分钟）、接力等待状态、已接力轮次
  interval_minutes?: number
  chain_pending?: boolean
  rounds?: number
}

// v8.0：快速重试全局设置（设置页 → /api/config.fast_retry）
export interface FastRetrySettings {
  auto: boolean
  per_minute: number
  minutes: number
  /** v8.4：两轮快速重试之间的常规节奏间隔（分钟） */
  interval_minutes?: number
}

export interface UpstreamError {
  status_code: number
  model_type: string
  api_method: string
  count: number
  first_ts: string
  last_ts: string
}

export interface TaskListItem {
  task_id: string
  /** 仅 simple 任务下发：t2v / i2v / ti2vid / keyframes，用于成功归因 */
  mode?: string
  task_type?: TaskType
  status?: string
  creative_name?: string
  idea?: string
  prompt?: string
  manuscript_text?: string
  script_text?: string
  scene_count?: number
  paragraph_count?: number
  dir_name?: string
  // v6.0 手动模式
  current_mode?: 'auto' | 'manual'
  current_checkpoint?: string
  awaiting_user?: boolean
}

export interface StepDef {
  key: string
  labelKey: string
}

export interface Voice {
  id: string
  name: string
  local_name?: string
  region?: string
  region_code?: string
  gender?: 'male' | 'female'
  lang?: string
  style_tags?: string[]
  preview_text?: string
}

export interface VoiceGroup {
  code: string
  label: string
  count: number
  voices: Voice[]
}

export interface VoiceCatalog {
  languages: VoiceGroup[]
  compat_hint?: Record<string, string[]>
}

export interface Artifact {
  artifact_id: string
  category: 'text' | 'image' | 'video' | 'audio' | 'json' | 'subtitle'
  label_key: string
  step_key: string
  scope_index?: number | null
  size: number
  exists: boolean
  deletable: boolean
}

export interface Workspace {
  path: string
  name?: string
  is_default?: boolean
}

// ── 风格预设库（P0-1）──
export interface Preset {
  id: string
  category?: string
  prompt: string
  name?: string
  created_at?: string
  kind?: 'system' | 'user'
}

// ── 产物画廊（P1，纯只读）──
export interface GalleryItem {
  task_id: string
  dir_name: string
  task_type: TaskType
  status: string
  kind: 'video' | 'image'
  description?: string
  title?: string
  media_url?: string
  thumb_url?: string | null
}
