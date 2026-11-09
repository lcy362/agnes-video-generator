import type { TaskType, StepDef } from './types'

// Step definitions per task type（与旧 index.html 的 STEPS 一致）
export const STEPS: Record<string, StepDef[]> = {
  simple: [
    { key: 'submit', labelKey: 'sStepSubmit' },
    { key: 'video_gen', labelKey: 'sStepVideoGen' },
  ],
  // 简单图片：后端一次同步调用，没有流水线环节。
  // 此前缺 image 分支 → getStepsForType 回退创意 12 步，图片任务详情页
  // 会显示「场景配置/故事/剧本/拼接」等完全不相干的环节。
  image: [
    { key: 'submit', labelKey: 'sStepSubmit' },
    { key: 'image_gen', labelKey: 'sStepImageGen' },
  ],
  creative: [
    { key: 'init', labelKey: 'cStepInit' },
    { key: 'scene_config', labelKey: 'cStepSceneConfig' },
    { key: 'image_analysis', labelKey: 'cStepImageAnalysis' },
    { key: 'story', labelKey: 'cStepStory' },
    { key: 'character_ref', labelKey: 'cStepCharacterRef' },
    { key: 'script', labelKey: 'cStepScript' },
    { key: 'end_frame_prompts', labelKey: 'cStepEndFramePrompts' },
    { key: 'end_frame_gen', labelKey: 'cStepEndFrameGen' },
    { key: 'video_gen', labelKey: 'cStepVideoGen' },
    { key: 'audio', labelKey: 'cStepAudio' },
    { key: 'subtitle', labelKey: 'cStepSubtitle' },
    { key: 'concatenate', labelKey: 'cStepConcat' },
  ],
  manuscript: [
    { key: 'split_text', labelKey: 'mStepSplit' },
    { key: 'scene_prompts', labelKey: 'mStepScenePrompts' },
    { key: 'video_gen', labelKey: 'mStepVideoGen' },
    { key: 'audio', labelKey: 'mStepAudio' },
    { key: 'subtitle', labelKey: 'mStepSubtitle' },
    { key: 'concatenate', labelKey: 'mStepConcat' },
  ],
  anchor: [
    { key: 'generate_anchor', labelKey: 'aStepGenerateAnchor' },
    { key: 'split_text', labelKey: 'aStepSplit' },
    { key: 'clip_prompts', labelKey: 'aStepClipPrompts' },
    { key: 'clip_gen', labelKey: 'aStepClipGen' },
    { key: 'audio', labelKey: 'aStepAudio' },
    { key: 'subtitle', labelKey: 'aStepSubtitle' },
    { key: 'concatenate', labelKey: 'aStepConcat' },
  ],
  poetry: [
    { key: 'build_scenes', labelKey: 'pStepBuildScenes' },
    { key: 'video_generation', labelKey: 'pStepVideoGen' },
    { key: 'audio', labelKey: 'pStepAudio' },
    { key: 'subtitle', labelKey: 'pStepSubtitle' },
    { key: 'concatenation', labelKey: 'pStepConcat' },
  ],
}

// step key -> state field 映射（与旧 isStepDoneInState 一致）
export const STEP_FIELD_MAP: Record<string, Record<string, string>> = {
  creative: {
    scene_config: 'step_scene_config',
    image_analysis: 'step_image_analysis',
    story: 'step_story',
    character_ref: 'step_character_ref',
    script: 'step_script',
    end_frame_prompts: 'step_end_frame_prompts',
    end_frame_gen: 'step_end_frame_generation',
    video_gen: 'step_video_generation',
    audio: 'step_audio',
    subtitle: 'step_subtitle',
    concatenate: 'step_concatenation',
  },
  manuscript: {
    split_text: 'step_split',
    scene_prompts: 'step_scene_prompts',
    video_gen: 'step_video_generation',
    audio: 'step_audio',
    subtitle: 'step_subtitle',
    concatenate: 'step_concatenation',
  },
  anchor: {
    generate_anchor: 'step_generate_anchor',
    split_text: 'step_split',
    clip_prompts: 'step_clip_prompts',
    clip_gen: 'step_clip_generation',
    audio: 'step_audio',
    subtitle: 'step_subtitle',
    concatenate: 'step_concatenation',
  },
  poetry: {
    build_scenes: 'step_build_scenes',
    video_generation: 'step_video_generation',
    audio: 'step_audio',
    subtitle: 'step_subtitle',
    concatenation: 'step_concatenation',
  },
}

export function getStepsForType(taskType?: TaskType | string): StepDef[] {
  return STEPS[taskType as string] || STEPS.creative
}

export function isStepDoneInState(state: any, stepKey: string, taskType?: string): boolean {
  const map = STEP_FIELD_MAP[taskType as string] || STEP_FIELD_MAP.creative
  const field = map[stepKey]
  return field ? state[field] === 'completed' : false
}
