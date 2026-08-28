# Agnes Video Generator v2.0 — 大版本回归测试计划

> 用户触发词：**"执行大版本回归"**
> 主理人自动加载本文档，按以下流程逐项执行并输出报告。

---

## 一、回归范围总览

| 任务类型 | 测试场景数 | 涉及核心模块 |
|----------|-----------|-------------|
| 简单视频 (Type 1) | 1 | `simple_video.py`, `agnes_video.py`, `task_manager.py` |
| 创意视频 (Type 2) | 3 | `creative_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py` |
| 稿件视频 (Type 3) | 2 | `manuscript_video.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| 数字人口播 (Type 4) | 2 | `anchor_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| **总计** | **8** | |

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
|----|------|--------------|--------|------|----------|
| C1 | 带参考图+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | 参考图上传、端帧生成、keyframes 提交 |
| C2 | 参考图生成尾帧+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | `generate_end_frames_from_ref`、i2i 端帧生成、keyframes |
| C3 | 带字幕+配音+关键帧 | keyframes | 无 | 开启 | TTS 旁白 + 字幕叠加 + 视频拼接 + keyframes |
| C4 | 用户上传分镜图+关键帧 | keyframes | 上传分镜图 | 关闭 | 用户分镜图覆盖 AI 分镜、关键帧 + 双图提交（3.6） |

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

### 2.5 诗词视频 (PoetryVideoPipeline)

| ID | 场景 | 配音 | 字幕 | 覆盖要点 |
|----|------|------|------|---------|
| P1 | 诗词朗诵+字幕 | 开启 | 开启 | LLM 拆场景 → 原诗句旁白 + 定时对齐字幕 → 逐句 t2v → 拼接 |

### 2.6 简单图片 (SimpleImagePipeline)

| ID | 场景 | 模型 | 覆盖要点 |
|----|------|------|---------|
| I1 | 文生图 | t2i | 单次 t2i 提交、结果伺服 |

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
| F3 | 视频分辨率 | — | 匹配请求参数 | 自动 | `moviepy` 读取宽高；v2.0 按绝对像素 ±15% 容差；**2.5 系列按宽高比 ±15% 校验**（720P 比例档位输出，如 768x1152 → 704x960，见 4.2） |
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
| E11 | `GET /api/config/keys` | 返回 key_count 与 source，无 Key 明文（v5.0 优化 1） | 自动 | 200，`key_count >= 0` |
| E12 | `POST /api/config/keys` | 多 Key 保存后重建 KeyRing/限速器（v5.0 优化 1） | 自动 | 200，`key_count` 等于入参数 |
| E13 | `DELETE /api/tasks/{id}` | 删除已完成任务目录；运行中任务返回 400（v5.0 优化 3） | 自动 | 200 或 400 |

---

## 三点五、v5.0 优化专项回归（随「执行优化批次」增量执行）

> 触发：完成 `docs/plans/v6.0/optimization_roadmap.md`（合并版；v5.0 旧路线图已废弃并入其中）任一优化点后，执行对应专项验证。
> 目的：以低成本（纯本地 / mock）覆盖优化引入的行为变化，不替代上方 11 场景全量回归。

| ID | 优化点 | 验证内容 | 验证方式 | 判断标准 |
|----|--------|---------|---------|---------|
| V1 | 1 多 Key 轮询 | `get_api_keys()` 返回多 Key（env+config 合并、去重）；KeyRing round-robin 轮转；429 换 Key 立即重试 | 自动（py 单测 / mock 429） | 日志出现 `[KeyRotation] HTTP 429, 换 Key 立即重试`；单 Key 时走退避 |
| V2 | 1 限流整合 | 共享桶 `20×N×0.8`/分、视频提交桶 `1×N`/分；`_submit_with_retry` 走独立桶 | 自动 | `stats.effective_rate_per_min` 随 Key 数缩放 |
| V3 | 1 配置 API | `GET/POST /api/config/keys` 返回数量/来源，不泄露明文；保存后即时重建 | 自动（端点） | E11/E12 通过 |
| V4 | 2 图片归一化 | 参考图归一化尺寸/压缩体积；URL/data 透传；Pillow 缺失降级 | 自动（py 单测） | `[ImageNormalizer]` 日志；透传/降级不抛异常 |
| V5 | 3 删除任务 | DELETE 已完成任务删除目录、运行中任务 400 | 自动（端点） | E13 通过 |
| V6 | 4 json_repair | 含尾随逗号/缺冒号 JSON 被修复；未装库时原路径不变 | 自动（py 单测） | 返回 dict；`[AgnesChat] JSON repaired` 日志 |
| V7 | 5 用户场景参考图 | creative 场景上传参考图后该场景跳过 AI 分镜图、视频用用户图 | 回归（C 类新增 C4） | C4 场景日志显示使用用户图；未传场景行为不变 |
| V8 | 6 start.bat | Windows 下脚本语法/流程 | 手动 | 见 roadmap §6.5 |

> C4（创意+用户场景参考图）建议纳入下次全量回归场景矩阵（keyframes + 第 1 个场景上传参考图 + 无配音）。

---

## 四、执行流程

当用户说 **"执行大版本回归"** 时执行。

### 核心规则

1. **只创建一轮任务**：严格按场景矩阵创建，不多创建。
2. **回归不改代码**：问题只记录，不修业务代码。
3. **失败记录具体原因**：含 HTTP 状态码、错误信息、超时时长。
4. **无明显原因须续传**：可恢复的失败通过 `--resume` 续传。
5. **测试专用空间隔离**：回归测试使用固定独立的工作目录，与用户日常任务完全隔离（见 4.0）。
6. **默认视频模型 = `agnes-video-2.5-flash`（v6.2.1）**：`regression_runner.py` / `scene_runner.py` 提交任务前自动将全局视频模型设为 2.5-flash（比例档位输出），可用环境变量 `AGNES_REGRESSION_VIDEO_MODEL` 覆盖为其他模型（如 `agnes-video-v2.0`）；若切换 v2.0，F3 自动回到像素校验。

### 4.0 测试专用工作目录（回归空间）

回归测试**必须**使用固定的测试专用工作目录，避免污染用户日常任务数据。

| 项 | 值 |
|----|------|
| 目录路径 | `{PROJECT_ROOT}/.regression_workspace/` |
| 环境变量 | `AGNES_REGRESSION_WORKING_DIR` |
| 优先级 | 服务端 `get_working_dir()` 检测到该环境变量时，**最高优先级**，覆盖界面配置的 active workspace |
| 隔离性 | 回归产物（任务目录、uploads、manifest）全部写入此空间，与用户 `.working_dir/` 或自定义工作目录互不干扰 |
| 界面表现 | 回归模式下 `/api/config` 返回 `working_dir_source: "regression"`，前端工作目录卡片显示锁定提示，禁用增删改 |

**自动注入**：`regression_runner.py --auto-start` 启动服务时自动设置该环境变量；若手动启动服务用于回归，需显式设置：

```bash
export AGNES_REGRESSION_WORKING_DIR="{PROJECT_ROOT}/.regression_workspace"
bash start.sh
```

### 4.1 准备阶段

```
1. git status 确认工作区干净
2. 确认 test_ref.png 和 test_end.png 存在
3. 启动服务（回归专用空间，由 regression_runner.py --auto-start 自动注入环境变量）
4. 确保 .regression_workspace/ 中无残留任务（可用 --cleanup 清理）
```

### 4.2 执行方式

使用 `scripts/regression_runner.py` 自动完成全部场景并发执行。

> **v6.2.1 起**：脚本在服务就绪后自动调用 `/api/config/models` 将视频模型设为默认 `agnes-video-2.5-flash`（`ensure_regression_video_model()`），无需手动切换；如需回归其他视频模型，设置 `AGNES_REGRESSION_VIDEO_MODEL` 环境变量即可。

也可以使用 `scripts/scene_runner.py` 单独执行某个场景，避免主 agent 内大量轮询造成上下文爆炸：

```bash
# 列出所有可用场景
python scripts/scene_runner.py --list

# 执行单个场景（返回 JSON 结果到 stdout，日志输出到 stderr）
python scripts/scene_runner.py --scenario C3

# 执行端点验证
python scripts/scene_runner.py --endpoints

# 仅验证已有产物
python scripts/scene_runner.py --scenario C3 --validate-only --dir <dir_name>

# 续传已有任务
python scripts/scene_runner.py --scenario C3 --resume --task-id <task_id>
```

`scene_runner.py` 的输出格式：
- **stdout**: JSON 结果（包含 status, checks, errors, task_id, dir_name 等）
- **stderr**: 执行日志
- **退出码**: 0=成功, 1=失败, 2=超时, 3=参数错误

验证项覆盖与 `regression_runner.py` 完全一致（F1-F7 最终产物、R1-R6 断点续传、R7-R10 音频/字幕），主 agent 可直接使用 JSON 结果无需重新验证。ASR 语音识别（F4_has_speech / F6_text_match）仅在 `regression_runner.py` 中执行（需 whisper），`scene_runner.py` 标记为 `"skip"`。

#### 并行度控制

| 场景类型 | 权重 |
|---------|------|
| 简单 (S1) | 1 |
| 创意 (C1-C4) | 3-3-3-3 |
| 稿件 (M1-M2) | 4-4 |
| 数字人 (A1-A2) | 2-2 |
| 诗词 (P1) | 2 |
| 简单图片 (I1) | 1 |

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

测试过程中 `docs/dev/regression_report.json` 即时更新，完成后生成两个文档：

| 文档 | 路径 | 内容 |
|------|------|------|
| 测试报告 | `docs/dev/regression_report.md` | 全部场景的执行结果、检查项、端点验证 |
| 问题清单 | `docs/dev/regression_issues.md` | 仅包含失败/异常/需关注的项目 |

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

  C1 [带参考图+关键帧]         — ✅
  C2 [参考图生成尾帧+关键帧]   — ✅
  C3 [带字幕+配音+关键帧]      — ✅

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

测试素材从 `.regression_workspace/`（回归专用空间）中已完成任务获取，或使用自动生成脚本：

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
| C3 | `/api/tasks/creative` | keyframes, audio+subtitle | 120m |

---

## 九、v6.0 手动模式回归（增量）

> 新增于 v6.0（实施路线图 P4）。手动模式场景**不进入** S1/A1-A2 权重计算，
> 作为 v6.0 专项在 CI 或本地手动执行，验证手动模式核心链路与自动模式回归不冲突。

### 9.1 手动模式场景矩阵（3 场景）

| ID | 类型 | 场景 | 验证要点 |
|----|------|------|---------|
| M1 | 手动·创建暂停 | creative + `execution_mode=manual` + 暂停点 `scenes` | 任务创建后流水线在 `scenes` 检查点暂停：状态 `PENDING` + `current_checkpoint=scenes` + `awaiting_user` 徽标 |
| M2 | 手动·确认继续 | 对暂停中的任务 `POST .../checkpoints/scenes/approve` | 恢复执行、`approved_checkpoints` 记录 `scenes`、`current_checkpoint` 清空、流水线继续到下一检查点或完成 |
| M3 | 手动·运行时切换 | 自动任务运行中 `POST /api/tasks/{id}/mode` `mode=manual` | 任务挂起为 `PENDING` + `current_checkpoint` 非空；再 `mode=auto` 立即 resume 继续跑完（**切换即继续**） |

> 校验方式：与 8 场景相同，`POST` 后轮询任务状态断言关键字段；产物校验复用 F1-F7。

### 9.2 端点验证补充

| 端点 | 验证内容 |
|------|---------|
| `POST /api/tasks/{id}/mode` | 双向切换 + simple 类型 400 + 幂等 |
| `GET /api/tasks/{id}/checkpoints` | 返回按检查点分组的产物清单（含 `files`） |
| `GET /api/tasks/{id}/checkpoints/{name}/impact` | 预计算只算不落盘，返回 affected/retained |
| `POST /api/tasks/{id}/checkpoints/{name}/approve` | `confirmed=false` 仅返回影响清单；`confirmed=true` 落盘 + resume |
| `POST /api/tasks/{id}/checkpoints/{name}/regen` | 等价 approve 全产物 |
| `POST /api/tasks/{id}/artifacts/{id}/upload` | 回填产物 + 运行中 409 + 路径穿越 403 |

### 9.3 自动模式回归不变

11 场景（S1/C1-C4/M1-M2/A1-A2/P1/I1）回归路径与 v5.x 完全一致；
`execution_mode` 缺省 `auto` 时 `_maybe_pause` 不生效（`pause_points` 为空），行为零变化。
| M1 | `/api/tasks/manuscript` | 8句稿件, audio_enabled | 60m |
| M2 | `/api/tasks/manuscript` | 自定义字幕样式 | 60m |
| A1 | `/api/tasks/anchor` | audio_source=post_stitch | 60m |
| A2 | `/api/tasks/anchor` | audio_source=model | 60m |

---

## 十、v6.1 问题反馈模块回归（增量）

> 新增于 v6.1（实施路线图 P5）。不进入 S1/A1-A2 权重计算，作为 v6.1 专项验证
> 「失败 → 重试 → 反馈」闭环与诊断端点。与 8 场景回归路径互不冲突。

### 10.1 前端反馈闭环场景（手动）

| ID | 场景 | 验证要点 |
|----|------|---------|
| F1 | 失败重试引导 | 失败任务面板显示「重试任务」主按钮 + 偶发引导文案；点击后任务重新 running（resume），重试计数 `fb_retry_{taskId}` +1 且跨刷新保持 |
| F2 | 反馈区渐进展开 | 重试计数 < 2 时反馈区为收起提示行「多次重试仍未解决？」；≥ 2 自动展开；手动展开/收起状态经 `fb_open_{taskId}` 持久化 |
| F3 | 确定性故障预筛 | `current_message` 命中关键词（如 HTTP 400 / content policy）时直接展开反馈区 + 切换「重试可能无效」文案 + 重试按钮弱化；429/5xx/timeout 文案不命中 |
| F4 | 复制诊断信息 | 复制完整 Markdown 报告（版本/任务/环节/错误/重试次数/关键配置），弹出「已复制」toast；隐私提示不含 prompt 原文 |
| F5 | GitHub Issue 引导 | 「去 GitHub 提 Issue」打开预填 title/body 的 issues/new（labels=bug）；超长降级且不报错 |

### 10.2 诊断端点（自动）

| ID | 场景 | 验证要点 |
|----|------|---------|
| D1 | 精确匹配 | 任务运行中触发模型调用失败 → `error_logs/` 落盘含 `task_id`；`GET /api/tasks/{id}/diagnostics` 返回 `match_source=exact` 且 `error_logs` 含关联日志 |
| D2 | 无记录 | 无关联日志时返回 `match_source=none`、`error_logs=[]`（前端静默降级为纯前端版报告） |
| D3 | 敏感字段 | 响应不含 `prompt` / `response_body` / `system_prompt` / `extra`；`error_message` 截断 |

### 10.3 端点补充

| 端点 | 验证内容 |
|------|---------|
| `GET /api/config` | 返回 `app_version`（诊断信息版本字段来源） |
| `GET /api/tasks/{id}/diagnostics` | 任务存在返回摘要 + 错误列表；任务不存在 404 |

---

*文档版本：v3.3 | 更新日期：2026-08-25 | 变更：新增 v6.1 问题反馈模块回归（F1-F5 / D1-D3）与端点*
