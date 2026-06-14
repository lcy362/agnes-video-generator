# Agnes Video Generator v2.0 — 大版本回归测试计划

> 用户触发词：**"执行大版本回归"**
> 主理人自动加载本文档，按以下流程逐项执行并输出报告。

---

## 一、回归范围总览

| 任务类型 | 测试场景数 | 涉及核心模块 |
|----------|-----------|-------------|
| 简单视频 (Type 1) | 3 | `simple_video.py`, `agnes_video.py`, `task_manager.py` |
| 创意视频 (Type 2) | 4 | `creative_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| 稿件视频 (Type 3) | 3 | `manuscript_video.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| **总计** | **10** | |

---

## 二、测试场景矩阵

### 2.1 简单视频 (SimpleVideoPipeline)

| ID | 场景 | mode | 参考图 | 尾帧 | 覆盖要点 |
|----|------|------|--------|------|---------|
| S1 | 纯文本生成 | t2v | 无 | 无 | 基础 t2v 提交流程、轮询、下载 |
| S2 | 图生视频 | ti2vid | 上传参考图 | 无 | 图片上传、i2v 参数构建 |
| S3 | 关键帧动画 | keyframes | 上传参考图 | 上传尾帧 | 双图模式、keyframes 参数构建 |

### 2.2 创意视频 (CreativeVideoPipeline)

| ID | 场景 | chaining_mode | 参考图 | 配音 | 覆盖要点 |
|----|------|--------------|--------|------|---------|
| C1 | 独立场景+配音 | independent | 无 | 开启 | story→script→video→tts→subtitle→concat 全链路 |
| C2 | 关键帧链式+配音 | keyframes | 上传参考图 | 开启 | 端帧生成、keyframes 提交、TTS+字幕 |
| C3 | 独立场景+静音 | independent | 无 | 关闭 | SilentTTSEngine、无配音流程 |
| C4 | 自定义尾帧+配音 | keyframes | 上传参考图 | 开启 | 自定义尾帧跳过生成、i2i 端帧 |

### 2.3 稿件视频 (ManuscriptVideoPipeline)

| ID | 场景 | 稿件长度 | 配音 | 覆盖要点 |
|----|------|---------|------|---------|
| M1 | 短稿件+配音 | 100-200 字 | 开启 | split→prompt→video→单条 TTS→单条 SRT→concat overlay |
| M2 | 长稿件+静音 | 500+ 字 | 关闭 | split 多段、静音时间轴、无 TTS 流程 |
| M3 | 短稿件+配音+字幕样式 | 100-200 字 | 开启 | 自定义 stroke/bg/position 字幕样式 |

---

## 三、验证产物清单

每个测试场景执行完毕后，验证以下产物。**验证方式**列说明由谁验证（自动 = 脚本可自动判断，手动 = 需要用户人工确认）。

### 3.1 最终产物

| # | 产物 | 路径模式 | 验证内容 | 验证方式 | 判断标准 |
|---|------|---------|---------|---------|---------|
| F1 | 最终视频 | `{working_dir}/{task_dir}/final_video.mp4` | 文件存在、非空 | 自动 | `os.path.exists` 且 `os.path.getsize > 0` |
| F2 | 视频时长 | — | 时长合理（> 0） | 自动 | `ffprobe` 或 `moviepy` 读取 duration |
| F3 | 视频分辨率 | — | 匹配请求参数 | 自动 | `ffprobe` 读取宽高比 |
| F4 | 音频轨道 | — | 视频包含音频 | 手动 | 播放听是否有旁白/静音；或 `ffprobe` 查看 audio stream 是否存在 |
| F5 | 字幕可见性 | — | 视频画面中字幕正确显示 | 手动 | 播放查看字幕出现时机、内容、样式是否正确 |
| F6 | 字幕文本匹配 | — | 字幕文本与原文一致 | 手动 | 比对字幕内容和输入文本 |
| F7 | 视频总时长合理 | — | 总时长 ≈ max(各段视频和, 总音频时长+1s) | 自动 | 用 `ffprobe` 获取 duration，脚本校验 |

### 3.2 断点续传产物 (Resume Checkpoints)

| # | 产物 | 路径模式 | 验证内容 | 验证方式 | 判断标准 |
|---|------|---------|---------|---------|---------|
| R1 | task_state.json | `{task_dir}/task_state.json` | 文件有效 JSON、包含所有必要字段 | 自动 | `json.load` 成功，字段完整 |
| R2 | task_type 字段 | task_state.json | 值正确（simple/creative/manuscript） | 自动 | 与创建时一致 |
| R3 | 各 step 状态 | task_state.json | 已完成步骤为 `completed` | 自动 | step_xxx 字段值 |
| R4 | final_video_file | task_state.json | 路径有效 | 自动 | `os.path.exists(路径)` |
| R5 | task.json (video_id) | `{task_dir}/task.json` (简易) 或 `{scene_dir}/task.json` (创意/稿件) | 文件存在、包含 video_id | 自动 | `json.load` 含 `video_id` 键 |
| R6 | curl.sh | `{task_dir}/curl.sh` 或 `{scene/para_dir}/curl.sh` | 文件存在、包含有效 curl 命令 | 自动 | 文件存在，内容含 `agnesapi?video_id=` |
| R7 | 段落/场景级音频 | `para_{n}/narration.mp3` 等 | 音频文件存在（稿件/创意） | 自动 | `os.path.exists` |
| R8 | 段落/场景级字幕 | `{para_dir}/narration.srt` 或 `{scene_dir}/subtitle.srt` | 字幕文件存在 | 自动 | `os.path.exists` |
| R9 | 合稿音频 (稿件) | `{task_dir}/full_narration.mp3` | 文件存在、非空 | 自动 | 同 F1 |
| R10 | 合稿字幕 (稿件) | `{task_dir}/full_subtitle.srt` | 文件存在、包含有效 SRT 条目 | 自动 | 可解析，条目 > 0 |

### 3.3 服务端点

| # | 端点 | 验证内容 | 验证方式 | 期望结果 |
|---|------|---------|---------|---------|
| E1 | `GET /` | 返回 200，HTML 含三 Tab | 自动 | status 200 |
| E2 | `GET /api/config` | 返回 api_key | 自动 | status 200 |
| E3 | `POST /api/tasks/simple` | 参数校验 | 自动 | 合法参数返回 200/422 |
| E4 | `POST /api/tasks/creative` | 参数校验 | 自动 | 合法参数返回 200/422 |
| E5 | `POST /api/tasks/manuscript` | 参数校验 | 自动 | 合法参数返回 200/422 |
| E6 | `GET /api/tasks` | 列表包含三种类型 | 自动 | 返回 tasks 数组 |
| E7 | `GET /api/tasks/{id}` | 返回 task_type | 自动 | status 200 |
| E8 | `POST /api/tasks/{id}/resume` | 续传未完成的任务 | 自动 | status 200 或合理 4xx |
| E9 | `POST /api/tasks/{id}/stop` | 停止运行中的任务 | 自动 | status 200 |

---

## 四、验证方式说明

### 4.1 自动验证（主理人执行）

以下检查由主理人通过脚本自动完成，在报告中输出 `✅ PASS` 或 `❌ FAIL`：

```python
# 自动验证脚本伪代码：
def auto_check(task_dir):
    checks = {}
    # F1: 最终视频
    video = os.path.join(task_dir, "final_video.mp4")
    checks["final_video_exists"] = os.path.exists(video)
    checks["final_video_nonempty"] = os.path.getsize(video) > 0 if checks["final_video_exists"] else False

    # F2: 视频时长
    from moviepy import VideoFileClip
    clip = VideoFileClip(video)
    checks["video_duration"] = clip.duration > 0

    # F7: 视频分辨率
    checks["video_width"] = clip.w  # 记录值供报告
    checks["video_height"] = clip.h

    # R1-R10: 检查点产物
    task_state = os.path.join(task_dir, "task_state.json")
    checks["task_state_exists"] = os.path.exists(task_state)
    ...

    return checks
```

### 4.2 手动验证（用户确认）

以下检查需要用户人工完成，主理人在报告中**明确列出验证步骤和预期结果**：

| 验证项 | 用户操作步骤 | 预期结果 |
|--------|------------|---------|
| 音频轨道 (F4) | 播放 final_video.mp4，注意听是否有旁白/背景音 | 配音开启：有 TTS 朗读声；配音关闭：无声音或静音 |
| 字幕可见性 (F5) | 播放时观察画面底部/顶部是否有字幕出现 | 字幕在对应时间出现，样式（字体/颜色/描边/背景）与配置一致 |
| 字幕文本匹配 (F6) | 对比字幕文字与输入的稿件/旁白文本 | 字幕内容无误，未出现乱码或错别字 |
| 断点续传 (手动) | 1. 停止服务 (`Ctrl+C`) \n2. 重启 `bash start.sh` \n3. 在任务列表点击"续传" | 任务从断点继续，成功生成最终视频 |
| WebSocket 进度 | 打开浏览器 DevTools → Network → WS，观察消息 | 各 step 有 progress 消息推送 |

---

## 五、报告模板

回归测试完成后，按以下格式输出报告：

```
═══════════════════════════════════════════════════
  Agnes Video Generator v2.0 — 大版本回归测试报告
  日期: {date}
  版本: {git_commit_hash}
═══════════════════════════════════════════════════

【服务启动】 ✅ bash start.sh 正常启动，监听 0.0.0.0:8765
【服务端点】 ✅ E1-E9 全部通过（详见下文）

────────────────────────────────────────────────
一、简单视频 (Simple)
────────────────────────────────────────────────

  S1 [纯文本 t2v]       — ✅ 最终产物全部通过
  S2 [图生视频 ti2vid]  — ✅ 最终产物全部通过
  S3 [关键帧 keyframes] — ✅ 最终产物全部通过

  │ 检查项               │ S1      │ S2      │ S3      │
  │──────────────────────│────────│────────│────────│
  │ F1 最终视频存在       │ ✅      │ ✅      │ ✅      │
  │ F2 视频时长 > 0      │ {n}s    │ {n}s    │ {n}s    │
  │ F3 分辨率匹配         │ ✅      │ ✅      │ ✅      │
  │ F4 音频轨道存在       │ ⚠️ 手动  │ ⚠️ 手动  │ ⚠️ 手动  │
  │ F7 时长合理           │ ✅      │ ✅      │ ✅      │
  │ R1 task_state.json   │ ✅      │ ✅      │ ✅      │
  │ R5 task.json         │ ✅      │ ✅      │ ✅      │
  │ R6 curl.sh           │ ✅      │ ✅      │ ✅      │

────────────────────────────────────────────────
二、创意视频 (Creative)
────────────────────────────────────────────────

  C1 [独立场景+配音]     — ✅ 最终产物全部通过
  C2 [关键帧链式+配音]   — ✅ 最终产物全部通过
  C3 [独立场景+静音]     — ✅ 最终产物全部通过
  C4 [自定义尾帧+配音]   — ✅ 最终产物全部通过

  │ 检查项               │ C1      │ C2      │ C3      │ C4      │
  │──────────────────────│────────│────────│────────│────────│
  │ F1 最终视频存在       │ ✅      │ ✅      │ ✅      │ ✅      │
  │ F2 视频时长 > 0      │ {n}s    │ {n}s    │ {n}s    │ {n}s    │
  │ F4 音频轨道存在       │ ⚠️ 手动  │ ⚠️ 手动  │ ⚠️ 手动  │ ⚠️ 手动  │
  │ F5 字幕可见性         │ ⚠️ 手动  │ ⚠️ 手动  │ N/A     │ ⚠️ 手动  │
  │ F7 总时长合理         │ ✅      │ ✅      │ ✅      │ ✅      │
  │ R3 step_* 状态       │ ✅      │ ✅      │ ✅      │ ✅      │
  │ R5 scene_N/task.json │ ✅      │ ✅      │ ✅      │ ✅      │
  │ R7 scene_N/narration │ ✅      │ ✅      │ ✅      │ ✅      │
  │ R8 scene_N/subtitle  │ ✅      │ N/A*    │ N/A     │ ✅      │

  *注: C2 keyframes 模式字幕待确认实际文件路径

────────────────────────────────────────────────
三、稿件视频 (Manuscript)
────────────────────────────────────────────────

  M1 [短稿件+配音]        — ✅ 最终产物全部通过
  M2 [长稿件+静音]        — ✅ 最终产物全部通过
  M3 [短稿件+自定义字幕]  — ✅ 最终产物全部通过

  │ 检查项                      │ M1      │ M2      │ M3      │
  │────────────────────────────│────────│────────│────────│
  │ F1 最终视频存在              │ ✅      │ ✅      │ ✅      │
  │ F2 视频时长 > 0             │ {n}s    │ {n}s    │ {n}s    │
  │ F4 音频轨道存在              │ ⚠️ 手动  │ ⚠️ 手动  │ ⚠️ 手动  │
  │ F5 字幕可见性                │ ⚠️ 手动  │ N/A     │ ⚠️ 手动  │
  │ F6 字幕文本匹配              │ ⚠️ 手动  │ N/A     │ ⚠️ 手动  │
  │ F7 总时长合理                │ ✅      │ ✅      │ ✅      │
  │ R9 full_narration.mp3       │ ✅      │ ✅      │ ✅      │
  │ R10 full_subtitle.srt       │ ✅      │ N/A     │ ✅      │
  │ R5 para_N/task.json         │ ✅      │ ✅      │ ✅      │
  │ R6 para_N/curl.sh           │ ✅      │ ✅      │ ✅      │

────────────────────────────────────────────────
四、需用户手动验证部分
────────────────────────────────────────────────

  1. 音频/旁白正确性
     - 播放 {task_dir}/final_video.mp4，确认旁白/静音符合配置
     - 预期: C1/C2/C4/M1/M3 应有 TTS 中文朗读
     - 预期: C3/M2 应无声或静音

  2. 字幕正确性
     - 播放时观察字幕内容、样式、出现时机
     - 预期: 字幕文本与输入一致，样式（描边/背景/位置）符合配置

  3. 断点续传
     - 手动停止服务 → 重启 → 在任务列表点击"续传"
     - 预期: 任务从断点继续，完成后 final_video.mp4 正常

────────────────────────────────────────────────
五、汇总
────────────────────────────────────────────────

  自动验证通过: {n}/{m}
  需手动验证:    {n} 项
  遗留问题:      {issues or 无}

═══════════════════════════════════════════════════
```

---

## 六、执行流程

当用户说 **"执行大版本回归"** 时，主理人执行以下操作：

### 6.1 准备阶段

```
1. git status 确认工作区干净，记录当前 commit hash
2. 确认 test_ref.png 和 test_end.png 存在（回归素材）
3. bash start.sh & 启动服务（等待 8 秒 health check）
4. 确保 .working_dir/ 中无残留的半成品任务干扰测试
```

### 6.2 并发执行（所有场景同时运行）

使用 `scripts/regression_runner.py` 自动完成创建→轮询→验证→记录全流程。

#### 并行度控制

基于 Agnes API 调用量分析，采用**加权信号量**控制并发：

| 场景类型 | 单场景权重 | 说明（每分钟 Agnes API 调用估算） |
|---------|-----------|----------------------------------|
| 简单 (S1-S3) | 1 | 1 次 submit + 轮询 ~4 次/分钟 |
| 创意 (C1-C4) | 3-4 | Chat + N×Image + N×Video + 轮询 |
| 稿件 (M1-M3) | 4-5 | 段落×Chat + 段落×Image + 轮询 |

- **总权重上限 = 10**（Agnes API 上限 20 次/分钟，留 50% 余量）
- 例：可同时运行 2 个创意(权重 8) + 2 个简单(权重 2)
- 例：或 1 个稿件(权重 5) + 1 个创意(权重 4) + 1 个简单(权重 1)

#### 执行命令

```bash
# 从头执行（默认：不自动启动服务）
python scripts/regression_runner.py

# 自动启动服务
python scripts/regression_runner.py --auto-start

# 断点续传（跳过报告中已完成的场景）
python scripts/regression_runner.py --resume --auto-start

# 快速验证：不运行新任务，只验证已有产物
python scripts/regression_runner.py --quick
```

#### 每场景执行逻辑

```
对每个 pending 场景（并发执行）：

  步骤 A — 加权信号量 acquire(weight)
    等待直到当前总权重 + 场景权重 ≤ 10

  步骤 B — 创建任务
    通过 HTTP POST 提交场景参数，记录 task_id 和 dir_name

  步骤 C — 异步轮询
    每 20 秒 GET /api/tasks/{task_id} 检查 status
    超时限制：简单 30min / 创意 120min / 稿件 60min

  步骤 D — 产物验证
    调用 validate_task() 检查 F1-F7, R1-R10
    记录每项检查结果到 report

  步骤 E — 释放信号量
    release(weight)，让下一排队场景开始

  步骤 F — 报告更新
    将结果写入 docs/regression_report.json（增量写入）
```

### 6.3 报告与续传

#### 增量报告

测试过程中，`docs/regression_report.json` 在每个场景完成后即时更新。报告结构：

```json
{
  "version": "2.0",
  "git_commit": "abc1234 ...",
  "scenarios": {
    "S1": {
      "status": "completed",
      "result": {
        "task_id": "...",
        "dir_name": "...",
        "duration_s": 123,
        "checks": {
          "F1_final_video_exists": true,
          "F2_duration": 5.2,
          "F4_has_audio_stream": false
        }
      },
      "errors": []
    }
  },
  "endpoints": {
    "E1": { "status": "passed", "detail": "200" }
  },
  "summary": {
    "total": 10, "completed": 3, "failed": 0, "running": 1
  }
}
```

#### 断点续传

```bash
# 中断后恢复：跳过已完成的场景，继续未完成的
python scripts/regression_runner.py --resume

# 恢复逻辑：
#   - status=completed/skipped → 跳过，不重复执行
#   - status=failed/pending    → 重新提交并运行
#   - status=running           → 视为 pending（服务器已重启，旧任务失效）
```

### 6.4 验证阶段

所有场景执行完毕后，脚本自动执行端点验证：

```
1. 运行 E1-E9 服务端点验证（并发执行 9 项检查）
2. 汇总所有场景的自动验证结果
3. 输出汇总日志（控制台）
4. 报告写入 docs/regression_report.json
```

### 注意事项

- **手动验证项**（音频正确性 F4、字幕可见性 F5、字幕文本匹配 F6）不自动检查，需用户按报告中的文件路径逐个播放确认
- **断点续传不替换已完成的场景检查**——如果某个已完成场景的产物被误删，使用 `--quick` 模式重新验证
- **Agnes API 调用上限**由加权信号量确保，但若服务器自身的重试逻辑产生额外调用，实际调用数可能略高于估算值
- 自动验证失败不阻塞其他场景（每个场景独立报告）

---

## 七、素材来源说明

测试过程中需要的参考图、尾帧图等素材，优先从 `.working_dir/` 中已有的**已完成创意视频任务**中获取：

| 素材类型 | 查找位置 | 说明 |
|---------|---------|------|
| 参考图 (reference_image) | `{task_dir}/character_reference.png` | 创意视频的角色参考图 |
| 自定义尾帧 | `{task_dir}/scene_{n}/end_frame.png` | 创意视频各场景的尾帧 |
| 参考图缓存 | `{task_dir}/*.url` | 已上传的参考图 URL 缓存 |

**查找步骤**：
1. 执行 `ls .working_dir/` 查看已有任务目录
2. 选择 status=completed 的创意视频任务
3. 检查该目录下是否有 `character_reference.png` 或 `scene_0/end_frame.png`
4. 在测试 API 调用时，将素材路径作为 `reference_image` 或 `end_frame_image` 参数传入

如果 `.working_dir` 中没有合适素材，可以自行准备任意图片文件（PNG/JPG 均可）。

---

## 八、附录：回归测试脚本

回归测试自动化脚本位于 `scripts/regression_runner.py`，包含：

- **并发执行器**：asyncio 驱动，所有场景并发运行
- **加权信号量**：基于 Agnes API 调用量的并行度控制
- **增量报告器**：JSON 报告每场景完成后即时更新
- **产物验证器**：验证 F1-F7、R1-R10 全部检查项
- **端点验证器**：E1-E9 服务端点并发验证
- **断点续传**：自动检测已有报告，跳过已完成场景

### 依赖

脚本依赖项目已有的 `requests` 库，无需额外安装。视频元数据验证（F2/F3/F7）需要 `moviepy`，如不可用则自动跳过。

### 并行度计算公式

```
AGNES_RATE_LIMIT = 20  (次/分钟，平台限制)
MAX_WEIGHT = AGNES_RATE_LIMIT / 2 = 10  (留 50% 余量)

并发场景一例:
  2 × Creative (权重 4+3=7) + 3 × Simple (权重 3) = 10 ✅
  1 × Manuscript (权重 5) + 1 × Creative (权重 4) + 1 × Simple (1) = 10 ✅
```

---

## 九、回归测试执行记录

每次执行回归测试后，JSON 报告自动保存到 `docs/regression_report.json`。主理人应执行以下命令生成人类可读报告：

```bash
# 查看 JSON 报告
cat docs/regression_report.json

# 筛选失败项
python -c "
import json
r = json.load(open('docs/regression_report.json'))
for sid, sc in r['scenarios'].items():
    if sc['status'] != 'completed':
        print(f'{sid}: {sc[\"status\"]} - {sc.get(\"errors\", [])}')
"
```

### 执行记录

| 日期 | 版本 | 自动验证 | 手动验证 | 遗留问题 | 报告文件 |
|------|------|---------|---------|---------|---------|
| <!-- 在此追加 --> | | | | | |
