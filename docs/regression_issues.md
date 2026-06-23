# Agnes Video Generator v2.0 — 回归测试问题清单

| 元数据 | 值 |
|--------|-----|
| 日期 | 2026-06-23 04:12 UTC |
| 版本 | 5c8c4a4 fix: 补齐 scene_runner.py 验证逻辑至与 regression_runner.py 对等 |

## 一、场景执行问题

### A1 数字人+后拼接音频

- **状态**: failed
- **耗时**: 110.0s
- **错误信息**:
  - `status=failed: ?`
- **task_id**: `0f8e40f6967b`
- **目录**: `20260623_114250_0f8e40f6967b`

### A2 数字人+模型音频

- **状态**: completed
- **耗时**: 330.1s
- **错误信息**:
  - `F1_final_video_exists`
  - `F1_final_video_nonempty`
  - `F2_duration_gt_0`
  - `F4_has_audio_stream`
  - `F7_duration_reasonable`
  - `R3_all_completed`
  - `R5_task_json`
  - `R5_has_video_id`
  - `R6_curl_sh`
  - `R6_has_video_id_in_curl`
- **失败检查项**:
  - `F1_final_video_exists`: False
  - `F1_final_video_nonempty`: False
  - `F2_duration_gt_0`: False
  - `F4_has_audio_stream`: False
  - `F7_duration_reasonable`: False
  - `R3_all_completed`: False
  - `R5_task_json`: False
  - `R5_has_video_id`: False
  - `R6_curl_sh`: False
  - `R6_has_video_id_in_curl`: False
- **task_id**: `06a84f2ed1d4`
- **目录**: `20260623_114250_06a84f2ed1d4`

### C1 带参考图+关键帧+无配音

- **状态**: completed
- **耗时**: 30.0s
- **错误信息**:
  - `R3_all_completed`
- **失败检查项**:
  - `R3_all_completed`: False
- **task_id**: `2d6f55c21b83`
- **目录**: `20260623_114250_2d6f55c21b83`

### C2 参考图生成尾帧+关键帧+无配音

- **状态**: completed
- **耗时**: 240.1s
- **错误信息**:
  - `R3_all_completed`
- **失败检查项**:
  - `R3_all_completed`: False
- **task_id**: `045aaf81aaa4`
- **目录**: `20260623_114250_045aaf81aaa4`

### C3 带字幕+配音+关键帧

- **状态**: failed
- **耗时**: 110.0s
- **错误信息**:
  - `status=failed: ?`
- **task_id**: `084472cbfe9e`
- **目录**: `20260623_114250_084472cbfe9e`

### M1 短稿件+配音

- **状态**: failed
- **耗时**: 200.1s
- **错误信息**:
  - `status=failed: ?`
- **task_id**: `2cc9797da78d`
- **目录**: `20260623_114250_2cc9797da78d`

### M2 短稿件+自定义字幕

- **状态**: completed
- **耗时**: 510.1s
- **错误信息**:
  - `R3_all_completed`
- **失败检查项**:
  - `R3_all_completed`: False
- **task_id**: `503cad6854f2`
- **目录**: `20260623_114250_503cad6854f2`

## 二、端点验证问题

无端点问题。

## 三、需手动验证项

| 检查项 | 场景 | 操作 |
|--------|------|------|
| F5 字幕可见性 | A2 | 播放 final_video.mp4 确认字幕显示 |
| F5 字幕可见性 | C1 | 播放 final_video.mp4 确认字幕显示 |
| F5 字幕可见性 | C2 | 播放 final_video.mp4 确认字幕显示 |
| F5 字幕可见性 | M2 | 播放 final_video.mp4 确认字幕显示 |
| F5 字幕可见性 | S1 | 播放 final_video.mp4 确认字幕显示 |

## 四、问题汇总

- 场景问题数: 7
- 端点问题数: 0
- 总问题数: 7
