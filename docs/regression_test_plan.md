# Agnes Video Generator v2.0 — 大版本回归测试计划

> 用户触发词：**"执行大版本回归"**
> 主理人自动加载本文档，按以下流程逐项执行并输出报告。

---

## 一、回归范围总览

| 任务类型 | 测试场景数 | 涉及核心模块 |
|----------|-----------|-------------|
| 简单视频 (Type 1) | 1 | `simple_video.py`, `agnes_video.py`, `task_manager.py` |
| 创意视频 (Type 2) | 2 | `creative_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py` |
| 稿件视频 (Type 3) | 2 | `manuscript_video.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| 数字人口播 (Type 4) | 2 | `anchor_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| **总计** | **7** | |

---

## 二、测试场景矩阵

### 2.1 简单视频 (SimpleVideoPipeline)

仅测试 keyframes 模式（其他模式精简掉）：

| ID | 场景 | mode | 参考图 | 尾帧 | 覆盖要点 |
|----|------|------|--------|------|---------|
| S1 | 关键帧动画 | keyframes | 上传参考图 | 上传尾帧 | 双图模式、keyframes 参数构建 |

### 2.2 创意视频 (CreativeVideoPipeline)

仅测试 keyframes 模式（three 拼接模式精简掉，只测最复杂的 keyframes）：

| ID | 场景 | chaining_mode | 参考图 | 配音 | 覆盖要点 |
|----|------|--------------|--------|------|---------|
| C1 | 带参考图+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | 参考图上传、端帧生成、keyframes 提交 |
| C2 | 参考图生成尾帧+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | `generate_end_frames_from_ref`、i2i 端帧生成、keyframes |

### 2.3 稿件视频 (ManuscriptVideoPipeline)

回归稿件多段拆分场景。

| ID | 场景 | 稿件长度 | 配音 | 覆盖要点 |
|----|------|---------|------|---------|
| M1 | 多段稿件+配音 | ~130 字 / 8 句 | 开启 | split 多段合并 → 多段 prompt → 多段 video 批量 → 合并 TTS+SRT → concat overlay |
| M2 | 多段稿件+自定义字幕 | ~130 字 / 8 句 | 开启 | 自定义 stroke/position/bg 字幕样式 + 多段拆分路径 |

**统一稿件文本（M1/M2 共用）**：

```
清晨的小镇，一条小溪静静流过石桥。溪水清澈见底，映着蓝天白云的倒影。岸边的柳树轻轻摇摆，叶子随风飘动。阳光洒在水面上，泛起点点金光。微风吹过，带来泥土和青草的气息。远处的屋顶上升起缕缕炊烟，宁静而安详。春天来了，古镇的景色越发迷人。桃花开满了枝头，柳树抽出嫩绿的新芽。
```

### 2.4 数字人口播 (AnchorVideoPipeline)

| ID | 场景 | audio_source | 配音 | 覆盖要点 |
|----|------|-------------|------|---------|
| A1 | 数字人+后拼接音频 | post_stitch | 开启 | 主播形象生成 → 单段 i2v → 循环播放 → TTS+字幕叠加 |
| A2 | 数字人+模型音频 | model | 关闭 | 主播形象生成 → 单段 i2v（模型自带音频）→ 不做后处理 |

**统一口播稿件**：

```
大家好，欢迎收看今天的新闻联播。今天的主要内容有：科技创新取得重大突破，人工智能领域又有新进展。国内外众多专家齐聚一堂，共同探讨未来发展。感谢您的收看，我们下期节目再见。
```

---

## 三、验证产物清单

每个测试场景执行完毕后，验证以下产物。

### 3.1 最终产物

| # | 产物 | 路径模式 | 验证内容 | 验证方式 | 判断标准 |
|---|------|---------|---------|---------|---------|
| F1 | 最终视频 | `{working_dir}/{task_dir}/final_video.mp4` | 文件存在、非空 | 自动 | `os.path.exists` 且 `os.path.getsize > 0` |
| F2 | 视频时长 | — | 时长合理（> 0） | 自动 | `ffprobe` 或 `moviepy` 读取 duration |
| F3 | 视频分辨率 | — | 匹配请求参数 | 自动 | `moviepy` 读取宽高，±15% 容差 |
| F4 | 音频轨道 + 语音内容 | — | 视频包含音频轨道 + 语音内容 | 自动 | `moviepy` 检测 audio stream + `whisper` ASR |
| F5 | 字幕可见性 | — | 视频画面中字幕正确显示 | 手动 | 播放查看 |
| F6 | 字幕文本匹配 | — | 字幕文本与原文一致 | 自动 | ASR 转录与原文模糊匹配（> 30%） |
| F7 | 视频总时长合理 | — | 总时长匹配期望值，±15% | 自动 | 区间校验 |

### 3.2 断点续传产物 (Resume Checkpoints)

| # | 产物 | 路径模式 | 验证内容 | 验证方式 | 判断标准 |
|---|------|---------|---------|---------|---------|
| R1 | task_state.json | `{task_dir}/task_state.json` | 文件有效 JSON | 自动 | `json.load` 成功 |
| R2 | task_type 字段 | task_state.json | 值正确 | 自动 | 与创建时一致 |
| R3 | 各 step 状态 | task_state.json | 已完成步骤为 `completed` | 自动 | **anchor** 根据 `audio_source` 跳过不适用步骤 |
| R4 | final_video_file | task_state.json | 路径有效 | 自动 | `os.path.exists` |
| R5 | task.json | `{task_dir}/{clip|scene_N|para_N}/task.json` | 文件存在、含 video_id | 自动 | `json.load` 含 `video_id` |
| R6 | curl.sh | `{task_dir}/{clip|scene_N|para_N}/curl.sh` | 文件存在、有效 curl | 自动 | 含查询模式 |
| R7 | 音频文件 | `{task_dir}/full_narration.mp3` 等 | 音频文件存在 | 自动 | `os.path.exists` |
| R8 | 字幕文件 | `{task_dir}/full_subtitle.srt` 等 | SRT 文件存在 | 自动 | `os.path.exists` |
| R9 | 合稿音频 | `{task_dir}/full_narration.mp3` | 文件存在、非空 | 自动 | 同 F1 |
| R10 | 合稿字幕 | `{task_dir}/full_subtitle.srt` | 文件存在、含有效 SRT | 自动 | 可解析，条目 > 0 |

### 3.3 服务端点

| # | 端点 | 验证内容 | 验证方式 | 期望结果 |
|---|------|---------|---------|---------|
| E1 | `GET /` | 返回 200，HTML 含三 Tab | 自动 | status 200 |
| E2 | `GET /api/config` | 返回 api_key | 自动 | status 200 |
| E3 | `POST /api/tasks/simple` | 参数校验 | 自动 | 200/422 |
| E4 | `POST /api/tasks/creative` | 参数校验 | 自动 | 200/422 |
| E5 | `POST /api/tasks/manuscript` | 参数校验 | 自动 | 200/422 |
| E6 | `GET /api/tasks` | 列表包含三种类型 | 自动 | 返回 tasks 数组 |
| E7 | `GET /api/tasks/{id}` | 返回 task_type | 自动 | status 200 |
| E8 | `POST /api/tasks/{id}/resume` | 续传未完成的任务 | 自动 | 200 或合理 4xx |
| E9 | `POST /api/tasks/{id}/stop` | 停止运行中的任务 | 自动 | status 200 |
| E10 | `POST /api/tasks/anchor` | 参数校验 | 自动 | 200/422 |

---

## 四、执行流程

当用户说 **"执行大版本回归"** 时执行。

### 核心规则

1. **只创建一轮任务**：严格按场景矩阵创建，不多创建。
2. **回归不改代码**：问题只记录，不修业务代码。
3. **失败记录具体原因**：含 HTTP 状态码、错误信息、超时时长。
4. **无明显原因须续传**：可恢复的失败通过 `--resume` 续传。

### 4.1 准备阶段

```
1. git status 确认工作区干净
2. 确认 test_ref.png 和 test_end.png 存在
3. bash start.sh & 启动服务
4. 确保 .working_dir/ 中无残留任务
```

### 4.2 并发执行

使用 `scripts/regression_runner.py` 自动完成。

#### 并行度控制

| 场景类型 | 权重 |
|---------|------|
| 简单 (S1) | 1 |
| 创意 (C1-C2) | 3-3 |
| 稿件 (M1-M2) | 4-4 |
| 数字人 (A1-A2) | 2-2 |

- **总权重上限 = 10**（Agnes API 上限 20 次/分钟，留 50% 余量）

#### 执行命令

```bash
# 从头执行
python scripts/regression_runner.py --auto-start

# 断点续传
python scripts/regression_runner.py --resume --auto-start

# 快速验证
python scripts/regression_runner.py --quick
```

### 4.3 报告与续传

测试过程中 `docs/regression_report.json` 即时更新。

```bash
# 中断后恢复
python scripts/regression_runner.py --resume

# 恢复逻辑：
#   - completed/skipped → 跳过
#   - failed（可恢复）→ 重新提交
#   - failed（不可恢复）→ 跳过
#   - running/pending → 视为 pending（需重提）
```

---

## 五、报告模板

```
═══════════════════════════════════════════════════
  Agnes Video Generator v2.0 — 大版本回归测试报告
  日期: {date}
  版本: {git_commit_hash}
═══════════════════════════════════════════════════

【服务启动】 ✅
【服务端点】 ✅ E1-E10（详见下文）

────────────────────────────────────────────────
一、简单视频 (Simple)
────────────────────────────────────────────────

  S1 [关键帧 keyframes] — ✅ 最终产物全部通过

────────────────────────────────────────────────
二、创意视频 (Creative)
────────────────────────────────────────────────

  C1 [带参考图+关键帧]       — ✅
  C2 [参考图生成尾帧+关键帧] — ✅

────────────────────────────────────────────────
三、稿件视频 (Manuscript)
────────────────────────────────────────────────

  M1 [短稿件+配音]           — ✅
  M2 [短稿件+自定义字幕]     — ✅

────────────────────────────────────────────────
四、数字人口播 (Anchor)
────────────────────────────────────────────────

  A1 [数字人+后拼接音频]     — ✅
  A2 [数字人+模型音频]       — ✅

────────────────────────────────────────────────
五、端点验证 (E1-E10)
────────────────────────────────────────────────

  E1-E10: ✅ 全部通过

────────────────────────────────────────────────
六、汇总
────────────────────────────────────────────────

  自动验证通过: {n}/{m}
  需手动验证:    1 项（F5 字幕可见性）
  遗留问题:      {issues or 无}
═══════════════════════════════════════════════════
```

---

## 六、素材来源说明

测试素材从 `.working_dir/` 中已完成任务获取，或使用自动生成脚本：

```bash
python -c "
from PIL import Image
for name, color in [('test_ref.png', (100,150,200)), ('test_end.png', (200,150,100))]:
    Image.new('RGB', (768, 1152), color).save(name)
"
```

---

## 七、依赖工具

| 工具 | 用途 |
|------|------|
| `ffmpeg` | 音频提取、视频元数据 |
| `moviepy` | 视频元数据读取 |
| `whisper` | ASR 语音识别（可选） |
| `requests` | HTTP API 调用 |
| `PIL/Pillow` | 测试素材生成 |

---

## 八、附录：场景配置摘要

| ID | 端点 | 关键参数 | 超时 |
|----|------|---------|------|
| S1 | `/api/tasks/simple` | mode=keyframes, ref+end | 30m |
| C1 | `/api/tasks/creative` | chaining_mode=keyframes, ref | 120m |
| C2 | `/api/tasks/creative` | keyframes+end_frame_from_ref | 120m |
| M1 | `/api/tasks/manuscript` | 8句稿件, audio_enabled | 60m |
| M2 | `/api/tasks/manuscript` | 自定义字幕样式 | 60m |
| A1 | `/api/tasks/anchor` | audio_source=post_stitch | 60m |
| A2 | `/api/tasks/anchor` | audio_source=model | 60m |

---

*文档版本：v3.0 | 更新日期：2026-06-21*
