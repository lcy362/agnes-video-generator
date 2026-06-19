# 修复计划：大版本回归测试问题修复

> 日期：2026-06-14
> 关联：大版本回归测试报告暴露的 3 个关键问题

---

## 问题 1：CreativePipeline 旁白文本过长 → 视频时长异常

**现象**：C4（创意+配音）最终视频 262.79s，远超预期（3×5s≈15s）。

**根因**：`core/pipelines/creative_video.py` 中 `_populate_narrations()` 将 AI 生成的长篇故事按段落数均分给各场景作为旁白。TTS 朗读数百字的段落 → 音频长达数十秒 → `_synthesize_single()` 通过冻结帧将视频补齐到音频长度。

**修复**：在每个场景的旁文字符数超过 `video_duration × 4`（4字/秒朗读速度）时，按句子边界裁剪。

### 涉及代码

| 位置 | 修改 |
|------|------|
| `creative_video.py:1026-1046` `_populate_narrations()` | 增加裁剪逻辑 |

### 核心变更

```python
_CHARS_PER_SEC = 4.0

def _trim_narration(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    # 按句子边界裁剪
    trimmed = text[:max_chars]
    last_period = max(
        trimmed.rfind("。"), trimmed.rfind("！"), trimmed.rfind("？"),
        trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"),
    )
    if last_period > max_chars * 0.5:
        return text[: last_period + 1]
    return trimmed[:max_chars]
```

---

## 问题 2：ManuscriptPipeline 视频 duration 与段落实际时长不匹配

**现象**：M1/M2 所有段落视频使用固定 `video_duration=5s` 提交，但段落文本可能更长（~22字≈5.5s），导致配音与视频不匹配。

**根因**：`core/pipelines/manuscript_video.py` `_step_generate_videos()` 调用 `submit_video(duration=self._state.video_duration, ...)` 对所有段落使用同一固定值。

**修复**：使用段落实估时长 `max(ceil(len(para.text) / 4.0), 3)` 作为视频提交的 duration。

### 涉及代码

| 位置 | 修改 |
|------|------|
| `manuscript_video.py:483-488` `_step_generate_videos()` | 用段落实估时长代替 `video_duration` |

---

## 问题 3：Regression Runner 未在创建任务时即持久化 task_id

**现象**：若回归脚本在任务提交后、轮询完成前中断，`--resume` 无法找到已提交的任务 ID，需要全部重跑。

**根因**：`scripts/regression_runner.py` 中 `run_scenario()` 只在任务完成后才写入报告。

**修复**：
1. 添加 `"submitted"` 中间状态
2. `submit_task()` 成功后立即 `report.update_scenario(sc.id, "submitted", result={task_id, dir_name})`
3. `should_run()` 不过滤 `"submitted"` 和 `"running"` 状态（重启后视为待处理）
4. Resume 路径：`status="submitted"` → 尝试轮询已有 task_id；超时/失败 → 重新提交
5. 修正 E1 检查文本：`"simple-video"` → `"Agnes Video Generator"`

### 涉及代码

| 位置 | 修改 |
|------|------|
| `regression_runner.py:324-326` `should_run()` | 不过滤 `submitted`/`running` |
| `regression_runner.py:588-592` `run_scenario()` | 提交后立即持久化 |
| `regression_runner.py:699-701` 端点验证 E1 | 修正检查文本 |

---

## 验证方法

1. `bash start.sh` 正常启动
2. 运行 `python scripts/regression_runner.py --auto-start`
3. 检查 C4 时长 ≈ 15s（3×5s，不再被旁白拉长）
4. 检查 M1/M2 时长 ≥ 段落估计时长
5. 中途 `Ctrl+C` 中断后 `--resume` 续传正常
