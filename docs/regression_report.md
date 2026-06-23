# Agnes Video Generator v2.0 — 大版本回归测试报告

| 元数据 | 值 |
|--------|-----|
| 日期 | 2026-06-23 04:12 UTC |
| 版本 | 5c8c4a4 fix: 补齐 scene_runner.py 验证逻辑至与 regression_runner.py 对等 |
| 报告版本 | 2.0 |
| 自动验证 | 66/109 通过 |

## 概览

| 状态 | 数量 |
|------|------|
| 总计 | 8 |
| ✅ 完成 | 5 |
| ❌ 失败 | 3 |
| ⏭️ 跳过 | 0 |
| 🔄 运行中 | 0 |
| ⏳ 待处理 | 0 |

端点验证: 10/10 ✅

---

## 简单视频 (Simple)

### S1 关键帧 keyframes — ✅ 通过 (330.5s)

| 检查项 | S1 |
|---|---|
| F1_final_video_exists | ✅ |
| F1_final_video_nonempty | ✅ |
| F2_duration_gt_0 | ✅ |
| F3_resolution_matches | ✅ |
| F4_has_audio_stream | ✅ |
| F4_has_speech | N/A |
| F6_text_match | N/A |
| F7_duration_reasonable | ✅ |
| R10_full_subtitle | N/A |
| R1_task_state_valid | ✅ |
| R2_task_type | simple |
| R2_task_type_matches | ✅ |
| R3_all_completed | ✅ |
| R3_incomplete_steps | — |
| R4_final_path_exists | ✅ |
| R5_has_video_id | ✅ |
| R5_task_json | ✅ |
| R6_curl_sh | ✅ |
| R6_dirs_checked | 1 |
| R6_dirs_with_curl | 1 |
| R6_has_video_id_in_curl | ✅ |
| R7_audio_files | N/A |
| R7_sub_dirs_exist | N/A |
| R8_subtitle_srt | N/A |
| R9_full_narration | N/A |

---

## 创意视频 (Creative)

### C1 带参考图+关键帧+无配音 — ⚠️ 通过但有失败检查 (30.0s)
### C2 参考图生成尾帧+关键帧+无配音 — ⚠️ 通过但有失败检查 (240.1s)
### C3 带字幕+配音+关键帧 — ❌ failed

| 检查项 | C1 | C2 | C3 |
|---|---|---|---|
| F1_final_video_exists | ✅ | ✅ | — |
| F1_final_video_nonempty | ✅ | ✅ | — |
| F2_duration_gt_0 | ✅ | ✅ | —s |
| F3_resolution_matches | ✅ | ✅ | — |
| F4_has_audio_stream | ✅ | ✅ | — |
| F4_has_speech | N/A | N/A | — |
| F6_text_match | N/A | N/A | — |
| F7_duration_reasonable | ✅ | ✅ | — |
| R10_full_subtitle | N/A | N/A | — |
| R1_task_state_valid | ✅ | ✅ | — |
| R2_task_type | creative | creative | — |
| R2_task_type_matches | ✅ | ✅ | — |
| R3_all_completed | ❌ | ❌ | — |
| R3_incomplete_steps | step_audio_subtitle | step_audio_subtitle | — |
| R4_final_path_exists | ✅ | ✅ | — |
| R5_has_video_id | ✅ | ✅ | — |
| R5_task_json | ✅ | ✅ | — |
| R6_curl_sh | ✅ | ✅ | — |
| R6_dirs_checked | 3 | 3 | — |
| R6_dirs_with_curl | 3 | 3 | — |
| R6_has_video_id_in_curl | ✅ | ✅ | — |
| R7_audio_files | N/A | N/A | — |
| R7_sub_dirs_exist | ✅ | ✅ | — |
| R8_subtitle_srt | N/A | N/A | — |
| R9_full_narration | N/A | N/A | — |

---

## 稿件视频 (Manuscript)

### M1 短稿件+配音 — ❌ failed
### M2 短稿件+自定义字幕 — ⚠️ 通过但有失败检查 (510.1s)

| 检查项 | M1 | M2 |
|---|---|---|
| F1_final_video_exists | — | ✅ |
| F1_final_video_nonempty | — | ✅ |
| F2_duration_gt_0 | —s | ✅ |
| F3_resolution_matches | — | ✅ |
| F4_has_audio_stream | — | ✅ |
| F4_has_speech | — | ✅ |
| F6_text_match | — | ✅ |
| F7_duration_reasonable | — | ✅ |
| R10_full_subtitle | — | ✅ |
| R1_task_state_valid | — | ✅ |
| R2_task_type | — | manuscript |
| R2_task_type_matches | — | ✅ |
| R3_all_completed | — | ❌ |
| R3_incomplete_steps | — | step_audio_subtitle |
| R4_final_path_exists | — | ✅ |
| R5_has_video_id | — | ✅ |
| R5_task_json | — | ✅ |
| R6_curl_sh | — | ✅ |
| R6_dirs_checked | — | 3 |
| R6_dirs_with_curl | — | 3 |
| R6_has_video_id_in_curl | — | ✅ |
| R7_audio_files | — | ✅ |
| R7_sub_dirs_exist | — | ✅ |
| R8_subtitle_srt | — | ✅ |
| R9_full_narration | — | ✅ |

---

## 数字人口播 (Anchor)

### A1 数字人+后拼接音频 — ❌ failed
### A2 数字人+模型音频 — ⚠️ 通过但有失败检查 (330.1s)

| 检查项 | A1 | A2 |
|---|---|---|
| F1_final_video_exists | — | ❌ |
| F1_final_video_nonempty | — | ❌ |
| F2_duration_gt_0 | —s | ❌ |
| F4_has_audio_stream | — | ❌ |
| F4_has_speech | — | N/A |
| F6_text_match | — | N/A |
| F7_duration_reasonable | — | ❌ |
| R10_full_subtitle | — | N/A |
| R1_task_state_valid | — | ✅ |
| R2_task_type | — | anchor |
| R2_task_type_matches | — | ✅ |
| R3_all_completed | — | ❌ |
| R3_incomplete_steps | — | step_split,step_clip_prompts,step_audio |
| R4_final_path_exists | — | ✅ |
| R5_has_video_id | — | ❌ |
| R5_task_json | — | ❌ |
| R6_curl_sh | — | ❌ |
| R6_dirs_checked | — | — |
| R6_dirs_with_curl | — | — |
| R6_has_video_id_in_curl | — | ❌ |
| R7_audio_files | — | N/A |
| R7_sub_dirs_exist | — | ✅ |
| R8_subtitle_srt | — | N/A |
| R9_full_narration | — | N/A |

---

## 端点验证 (E1-E10)

| 端点 | 状态 | 详情 |
|------|------|------|
| E1 | ✅ | 200 |
| E10 | ✅ | 200 |
| E2 | ✅ | 200 |
| E3 | ✅ | 200 |
| E4 | ✅ | 200 |
| E5 | ✅ | 200 |
| E6 | ✅ | 200 |
| E7 | ✅ | fb5ffdd78ed7 type=creative |
| E8 | ✅ | 2cc9797da78d 200 |
| E9 | ✅ | fb5ffdd78ed7 200 |

---

## 需手动验证

以下检查因 IMAX 视觉限制无法由脚本验证，需人工确认：

| 检查项 | 操作 | 预期 |
|--------|------|------|
| F5 字幕可见性 | 播放 final_video.mp4 观察画面 | 字幕内容、位置、样式与配置一致 |

> 音频正确性 (F4) 和字幕文本匹配 (F6) 已由脚本通过 whisper ASR 自动验证。

## 错误汇总

- **A1** (数字人+后拼接音频): status=failed: ?
- **A2** (数字人+模型音频): F1_final_video_exists
- **C1** (带参考图+关键帧+无配音): R3_all_completed
- **C2** (参考图生成尾帧+关键帧+无配音): R3_all_completed
- **C3** (带字幕+配音+关键帧): status=failed: ?
- **M1** (短稿件+配音): status=failed: ?
- **M2** (短稿件+自定义字幕): R3_all_completed
