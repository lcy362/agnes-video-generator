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
  [key: string]: any
}

export interface TaskListItem {
  task_id: string
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
