# Agnes Video Generator v2.0 — 大版本回归测试计划

> 用户触发词：**"执行大版本回归"**
> 主理人自动加载本文档，按以下流程逐项执行并输出报告。

---

## 一、回归范围总览

| 任务类型 | 测试场景数 | 涉及核心模块 |
|----------|-----------|-------------|
| 简单视频 (Type 1) | 3 | `simple_video.py`, `agnes_video.py`, `task_manager.py` |
| 创意视频 (Type 2) | 4 | `creative_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| 稿件视频 (Type 3) | 2 | `manuscript_video.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| **总计** | **9** | |

---

## 二、测试场景矩阵

### 2.1 简单视频 (SimpleVideoPipeline)

| ID | 场景 | mode | 参考图 | 尾帧 | 覆盖要点 |
|----|------|------|--------|------|---------|
| S1 | 纯文本生成 | t2v | 无 | 无 | 基础 t2v 提交流程、轮询、下载 |
| S2 | 图生视频 | ti2vid | 上传参考图 | 无 | 图片上传、i2v 参数构建 |
| S3 | 关键帧动画 | keyframes | 上传参考图 | 上传尾帧 | 双图模式、keyframes 参数构建 |

### 2.2 创意视频 (CreativeVideoPipeline)

测试重点：**无配音场景为主**，配音字幕有一个场景验证可用即可。

| ID | 场景 | chaining_mode | 参考图 | 配音 | 覆盖要点 |
|----|------|--------------|--------|------|---------|
| C1 | 纯文字+独立+无配音 | independent | 无 | 关闭 | 纯文字输入、story→script→video→SilentTTS→concat 链路 |
| C2 | 带参考图+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | 参考图上传、端帧生成、keyframes 提交 |
| C3 | 参考图生成尾帧+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | `generate_end_frames_from_ref`、i2i 端帧生成、keyframes |
| C4 | 独立场景+配音字幕验证 | independent | 无 | 开启 | TTS+字幕全链路验证（一个场景覆盖即可） |

### 2.3 稿件视频 (ManuscriptVideoPipeline)

仅回归短文本场景，无需长文本。

| ID | 场景 | 稿件长度 | 配音 | 覆盖要点 |
|----|------|---------|------|---------|
| M1 | 短稿件+配音 | ~100 字 | 开启 | split→prompt→video→TTS→SRT→concat overlay |
| M2 | 短稿件+自定义字幕 | ~100 字 | 开启 | 自定义 stroke/position/bg 字幕样式 |

---

## 三、验证产物清单

每个测试场景执行完毕后，验证以下产物。**验证方式**列说明由谁验证（自动 = 脚本可自动判断，手动 = 需要用户人工确认）。

### 3.1 最终产物

| # | 产物 | 路径模式 | 验证内容 | 验证方式 | 判断标准 |
|---|------|---------|---------|---------|---------|
| F1 | 最终视频 | `{working_dir}/{task_dir}/final_video.mp4` | 文件存在、非空 | 自动 | `os.path.exists` 且 `os.path.getsize > 0` |
| F2 | 视频时长 | — | 时长合理（> 0） | 自动 | `ffprobe` 或 `moviepy` 读取 duration |
| F3 | 视频分辨率 | — | 匹配请求参数 | 自动 | `ffprobe` 读取宽高比 |
| F4 | 音频轨道 + 语音内容 | — | 视频包含音频轨道 + 语音内容匹配预期 | 自动 | `moviepy` 检测 audio stream + `whisper` ASR 转录文本并与原文模糊匹配 |
| F5 | 字幕可见性 | — | 视频画面中字幕正确显示 | 手动 | 播放查看字幕出现时机、内容、样式是否正确 |
| F6 | 字幕文本匹配 | — | 字幕文本与原文一致 | 自动 | `whisper` 提取音频中的语音文本，与输入原文做模糊匹配（字符重叠率 > 30%） |
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

> **音频 (F4) 和字幕文本匹配 (F6) 已由脚本自动验证**：脚本自动从 final_video.mp4 提取音频，调用 `whisper` 模型进行语音识别，转录文本与输入旁白/稿件原文做模糊匹配（字符重叠率 > 30%），同时通过 `moviepy` 检测音频流是否存在。
>
> 以下检查因 IMAX 限制无法由脚本验证，仍需用户人工完成：

| 验证项 | 用户操作步骤 | 预期结果 |
|--------|------------|---------|
| 字幕可见性 (F5) | 播放时观察画面底部/顶部是否有字幕出现 | 字幕在对应时间出现，样式（字体/颜色/描边/背景）与配置一致 |
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
   │ F4 音频轨道+语音内容  │ ✅      │ ✅      │ ✅      │
   │ F7 时长合理           │ ✅      │ ✅      │ ✅      │
  │ R1 task_state.json   │ ✅      │ ✅      │ ✅      │
  │ R5 task.json         │ ✅      │ ✅      │ ✅      │
  │ R6 curl.sh           │ ✅      │ ✅      │ ✅      │

────────────────────────────────────────────────
二、创意视频 (Creative)
────────────────────────────────────────────────

  C1 [纯文字+独立+无配音]           — ✅ 最终产物全部通过
  C2 [带参考图+关键帧+无配音]       — ✅ 最终产物全部通过
  C3 [参考图生成尾帧+关键帧+无配音] — ✅ 最终产物全部通过
  C4 [独立场景+配音字幕验证]         — ✅ 最终产物全部通过

  │ 检查项               │ C1      │ C2      │ C3      │ C4      │
  │──────────────────────│────────│────────│────────│────────│
  │ F1 最终视频存在       │ ✅      │ ✅      │ ✅      │ ✅      │
  │ F2 视频时长 > 0      │ {n}s    │ {n}s    │ {n}s    │ {n}s    │
   │ F4 音频轨道+语音内容  │ N/A¹    │ N/A¹    │ N/A¹    │ ✅      │
   │ F6 字幕文本匹配       │ N/A¹    │ N/A¹    │ N/A¹    │ ✅      │
   │ F7 总时长合理         │ ✅      │ ✅      │ ✅      │ ✅      │
   │ R3 step_* 状态       │ ✅      │ ✅      │ ✅      │ ✅      │
   │ R5 scene_N/task.json │ ✅      │ ✅      │ ✅      │ ✅      │
   │ R7 scene_N/narration │ N/A¹    │ N/A¹    │ N/A¹    │ ✅      │
   │ R8 scene_N/subtitle  │ N/A¹    │ N/A¹    │ N/A¹    │ ✅      │

   ¹ C1-C3 无配音，音频/字幕相关检查标记为 N/A。F5 字幕可见性仍为手动验证项。

────────────────────────────────────────────────
三、稿件视频 (Manuscript)
────────────────────────────────────────────────

  M1 [短稿件+配音]     — ✅ 最终产物全部通过
  M2 [短稿件+自定义字幕] — ✅ 最终产物全部通过

  │ 检查项                      │ M1      │ M2      │
  │────────────────────────────│────────│────────│
  │ F1 最终视频存在              │ ✅      │ ✅      │
  │ F2 视频时长 > 0             │ {n}s    │ {n}s    │
   │ F4 音频轨道+语音内容         │ ✅      │ ✅      │
   │ F6 字幕文本匹配              │ ✅      │ ✅      │
   │ F7 总时长合理                │ ✅      │ ✅      │
   │ R9 full_narration.mp3       │ ✅      │ ✅      │
   │ R10 full_subtitle.srt       │ ✅      │ ✅      │
   │ R5 para_N/task.json         │ ✅      │ ✅      │
   │ R6 para_N/curl.sh           │ ✅      │ ✅      │

────────────────────────────────────────────────
四、需用户手动验证部分
────────────────────────────────────────────────

   > 音频正确性 (F4) 和字幕文本匹配 (F6) 已由脚本通过 whisper ASR 自动验证。
   > 以下为仍需人工确认的项：

   1. 字幕可见性 (F5)
      - 播放 {task_dir}/final_video.mp4，观察画面中字幕的出现时机、位置和样式
      - 预期: C4/M1/M2 字幕内容、位置、字体/颜色/描边/背景与配置一致

   2. 断点续传
      - 手动停止服务 → 重启 → 在任务列表点击"续传"
      - 预期: 任务从断点继续，完成后 final_video.mp4 正常

────────────────────────────────────────────────
五、汇总
────────────────────────────────────────────────

   自动验证通过: {n}/{m}
   需手动验证:    1 项（F5 字幕可见性，因 IMAX 视觉限制无法自动判断）
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
| 稿件 (M1-M2) | 4 | 段落×Chat + 段落×Image + 轮询 |

- **总权重上限 = 10**（Agnes API 上限 20 次/分钟，留 50% 余量）
- 例：可同时运行 2 个创意(权重 7) + 3 个简单(权重 3) = 10 ✅
- 例：或 1 个稿件(权重 4) + 1 个创意(权重 4) + 2 个简单(权重 2) = 10 ✅

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
    "total": 9, "completed": 3, "failed": 0, "running": 1
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
4. JSON 原始记录写入 docs/regression_report.json
5. MD 可读报告写入 docs/regression_report.md
```

### 注意事项

- **手动验证项**（字幕可见性 F5）因 IMAX 视觉限制无法由脚本自动判断，需用户按报告中的文件路径播放确认字幕正确显示。音频正确性 (F4) 和字幕文本匹配 (F6) 已由脚本通过 whisper ASR 自动验证
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

如果 `.working_dir` 中没有合适素材，可以自行准备任意图片文件（PNG/JPG 均可），
或使用以下命令自动生成测试素材：

```bash
# 自动生成测试用的参考图和尾帧图（使用 Python 纯色填充）
python -c "
from PIL import Image
for name, color in [('test_ref.png', (100,150,200)), ('test_end.png', (200,150,100))]:
    img = Image.new('RGB', (768, 1152), color)
    img.save(name)
    print(f'{name} created')
"
```

---

## 八、工具依赖与问题排查

回归脚本依赖以下外部工具，如果不可用会影响对应的验证项：

### 8.1 依赖工具清单

| 工具 | 用途 | 影响的验证项 | 缺失时的行为 |
|------|------|-------------|-------------|
| `ffmpeg` | 音频提取、视频元数据 | F4 (ASR), F2/F3 (时长/分辨率) | 自动跳过 ASR 验证；moviepy 可替代元数据读取 |
| `moviepy` | 视频元数据读取 | F2/F3/F4/F7 | 相关检查标记为 `skip` |
| `whisper` (openai-whisper) | 语音识别 (ASR) | F4 (语音内容), F6 (字幕文本匹配) | 相关检查标记为 `skip` |
| `requests` | HTTP API 调用 | 全部场景 | 脚本无法运行（应已包含在 requirements.txt） |
| `PIL/Pillow` | 测试素材自动生成 | 仅素材准备阶段 | 需手动准备 test_ref.png/test_end.png |

### 8.2 Whisper 安装与问题排查

Whisper 用于自动验证音频轨道中的语音内容是否与输入原文匹配。如果 whisper 不可用：

#### macOS 安装

```bash
# 在项目 venv 中安装
.venv/bin/pip install openai-whisper

# 如果安装失败，可能需要先安装 ffmpeg
brew install ffmpeg

# 验证安装
.venv/bin/python -c "import whisper; print(whisper.load_model('tiny'))"
```

#### 常见问题

**Q: `whisper` 模型加载 OOM (内存不足)？**
- 脚本默认使用 `tiny` 模型（~75MB），内存需求低
- 如果仍 OOM，可修改 `scripts/regression_runner.py` 中 `_get_whisper_model()` 的模型名
- 或者跳过 ASR 验证：whisper 不可用时自动标记为 `skip`，不影响其他检查

**Q: `librosa` 或 `numba` 依赖冲突？**
- openai-whisper 依赖可能与其他包冲突，建议在独立 venv 中安装

**Q: 中文识别效果差？**
- tiny 模型对中文的识别精度有限，模糊匹配阈值（字符重叠率 > 30%）已考虑此限制
- 如需更高精度，可升级为 `base` 或 `small` 模型

**Q: 如何跳过 ASR 验证？**
- 不安装 whisper 即可 — 脚本自动检测并跳过，不影响其他检查

### 8.3 FFmpeg 安装

```bash
# macOS
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt install ffmpeg

# 验证
ffmpeg -version
```

### 8.4 执行前健康检查

建议在首次执行回归前运行以下命令确认环境就绪：

```bash
# 检查 Python 依赖
.venv/bin/python -c "
deps = ['fastapi', 'moviepy', 'edge_tts', 'srt', 'requests', 'pydantic']
for d in deps:
    try:
        __import__(d.replace('-','_'))
        print(f'  [OK] {d}')
    except ImportError:
        print(f'  [MISS] {d}')
"

# 检查外部工具
for cmd in ffmpeg; do
    if command -v $cmd &>/dev/null; then
        echo "  [OK] $cmd"
    else
        echo "  [MISS] $cmd"
    fi
done

# 检查 whisper (可选)
.venv/bin/python -c "import whisper; print('  [OK] whisper')" 2>/dev/null || echo "  [SKIP] whisper (ASR 验证将跳过)"

# 检查测试素材
for f in test_ref.png test_end.png; do
    if [ -f "$f" ]; then echo "  [OK] $f"; else echo "  [MISS] $f (需要运行素材生成脚本)"; fi
done
```

---

## 九、回归流程自迭代机制

回归流程本身也是一个需要持续优化的"活文档"。每次执行回归时，应当：

### 9.1 执行时的问题记录

在执行回归测试过程中，如果遇到以下类型的问题，**不要绕过，应当记录并修复**：

| 问题类型 | 示例 | 处理方式 |
|---------|------|---------|
| 工具缺失/版本不兼容 | whisper 未安装、ffmpeg 版本过低 | 尝试安装/升级，如不可行则更新文档说明 |
| 验证误报 | 某检查项被判失败，但实际功能正常 | 分析根因，修复验证逻辑（本次执行中修复） |
| 验证漏报 | 某功能有 bug 但未被检查覆盖 | 添加新的检查项到验证清单 |
| 脚本自身 bug | 并发执行时偶发崩溃、报告写入不完整 | 修复脚本，测试后合并 |
| 文档与代码不一致 | 文档描述的场景参数与实际提交的不符 | 更新场景定义或文档 |
| 超时不合理 | 某类任务实际耗时远超 timeout 设定 | 调整超时值 |

### 9.2 迭代流程

```
执行回归
    │
    ├── 工具问题? → 尝试修复 → 如不可行，记录到文档
    │
    ├── 验证误报? → 分析根因 → 修复验证逻辑 → 重新运行
    │
    ├── 验证漏报? → 添加检查项 → 更新验证清单
    │
    ├── 脚本 bug? → 修复 → 测试 → 提交
    │
    └── 完成 → 更新执行记录表
```

### 9.3 每次回归后的检查清单

- [ ] 所有验证项的结果是否与预期一致？不一致的项是否已分析原因？
- [ ] 是否有新的工具依赖需要记录？
- [ ] 场景超时设置是否合理？（实际耗时 vs 设定超时的比例是否在 30%-80% 之间？）
- [ ] 加权信号量配置是否仍合理？（可根据实际 API 调用量调整权重和上限）
- [ ] 是否有 C2/C3 类"因缺少测试素材而失败"的场景需要补充素材？
- [ ] 字幕条目数是否合理？（对于 14s 稿件视频，预期 > 4 条字幕）

### 9.4 验证逻辑修改原则

修改 `scripts/regression_runner.py` 中的验证逻辑时，遵循以下原则：

1. **只修正确认有问题的地方**：如果一个检查失败但功能实际正常 → 修验证逻辑；如果功能确实有问题 → 修业务代码
2. **区分"跳过"和"失败"**：工具不可用标记 `skip`，功能异常标记 `False`
3. **区分"N/A"和"失败"**：不适用场景标记 `N/A`，功能异常标记 `False`
4. **向后兼容**：修改验证逻辑不应导致已有的通过报告变失败
5. **记录修改原因**：每次修改后在回归计划文档的执行记录表中备注

---

## 十、附录：回归测试脚本

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
  1 × Creative (w=4) + 1 × Manuscript (w=4) + 2 × Simple (w=2) = 10 ✅
  2 × Creative (w=7) + 3 × Simple (w=3) = 10 ✅
```

---

## 十一、回归测试执行记录

每次执行回归测试后，输出两个报告文件：

| 文件 | 说明 |
|------|------|
| `docs/regression_report.json` | JSON 原始数据（机器可读，用于断点续传和 CI） |
| `docs/regression_report.md` | Markdown 可读报告（人类可读，可直接用于 PR/评审） |

常用命令：

```bash
# 查看 JSON 原始记录
cat docs/regression_report.json

# 查看 MD 可读报告
cat docs/regression_report.md

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
