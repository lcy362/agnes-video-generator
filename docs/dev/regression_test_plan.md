# Agnes Video Generator v2.0 — 大版本回归测试计划

> 用户触发词：**"执行大版本回归"**
> 主理人自动加载本文档，按以下流程逐项执行并输出报告。

---

## 一、回归范围总览

| 任务类型 | 测试场景数 | 涉及核心模块 |
|----------|-----------|-------------|
| 简单视频 (Type 1) | 4 | `simple_video.py`, `agnes_video.py`, `task_manager.py`, `task_creation_routes.py` |
| 创意视频 (Type 2) | 5 | `creative_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `tashkeel.py` |
| 稿件视频 (Type 3) | 5 | `manuscript_video.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py`, `preview_routes.py` |
| 数字人口播 (Type 4) | 2 | `anchor_video.py`, `agnes_image.py`, `agnes_video.py`, `screenwriter.py`, `tts.py`, `subtitle.py`, `concatenator.py` |
| **总计** | **15**（S1/C1-C5/M1-M5/A1-A2/P1/I1） | |

---

## 二、测试场景矩阵

### 2.1 简单视频 (SimpleVideoPipeline)

v8.0 起覆盖一键路径与官方 2.5 三种模式：

| ID | 场景 | mode | 素材 | 覆盖要点 |
|----|------|------|------|---------|
| S1 | 一键预设（无特殊需求） | 不传（默认 t2v） | 无 | 只传 `prompt`：免费 flash / 5s / **16:9** / 720P；产物方向正确；`task.json` 预设与 `SIMPLE_DEFAULT_PRESET` 一致 |
| S2 | 多图参考 | i2v | 2–5 张参考图 | `reference(images)` 组装、逐张上传、上限拦截 |
| S3 | 原生首尾帧 | keyframes | 首帧 + 尾帧 | `keyframe(first_frame/last_frame)`；不复用 `images`；缺帧前端拦截、混传 422 |
| S4 | 参考音频 | i2v | 1 张图 + 1 段音频 URL | `reference(audios)` 透传、非 http(s) 拒绝、`<Audio 1>` 占位符 |

### 2.2 创意视频 (CreativeVideoPipeline)

仅测试 keyframes 模式（three 拼接模式精简掉，只测最复杂的 keyframes）：

| ID | 场景 | chaining_mode | 参考图 | 配音 | 覆盖要点 |
|----|------|--------------|--------|------|----------|
| C1 | 带参考图+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | 参考图上传、端帧生成、keyframes 提交 |
| C2 | 参考图生成尾帧+关键帧+无配音 | keyframes | 上传参考图 | 关闭 | `generate_end_frames_from_ref`、i2i 端帧生成、keyframes |
| C3 | 带字幕+配音+关键帧 | keyframes | 无 | 开启 | TTS 旁白 + 字幕叠加 + 视频拼接 + keyframes |
| C4 | 用户上传分镜图+关键帧 | keyframes | 上传分镜图 | 关闭 | 用户分镜图覆盖 AI 分镜、关键帧 + 双图提交（3.6） |
| C5 | 阿拉伯语创意+变音符号（tashkeel） | keyframes | 无 | 开启+`audio_add_tashkeel` | 非中文 idea 语言 pinning + 显式语言指令（阿拉伯语故事/旁白）、语速公共估算（阿拉伯文 10.5 字符/秒，2026-08-31 实测校准）、tashkeel 仅送 TTS、**字幕/`narration.txt` 不含 harakat**、旁白可听时长 ≈ 视频时长 ±20%（PRD 1.2/1.2a/1.3/1.4，PR #33 吸收） |

### 2.3 稿件视频 (ManuscriptVideoPipeline)

回归稿件多段拆分场景。

| ID | 场景 | 稿件长度 | 配音 | 覆盖要点 |
|----|------|---------|------|---------|
| M1 | 多段稿件+配音 | ~130 字 / 8 句 | 开启 | split 多段合并 → 多段 prompt → 多段 video 批量 → 合并 TTS+SRT → concat overlay |
| M2 | 多段稿件+自定义字幕 | ~130 字 / 8 句 | 开启 | 自定义 stroke/position/bg 字幕样式 + 多段拆分路径 |
| M3 | 多段稿件+逐段参考图 | ~130 字 / 8 句 | 开启 | `reference_images` + `reference_images_map` 按段落 index 映射 → i2v 提交（task_state 含 `reference_images`，para_N/task.json 提交带参考图） |
| M4 | 稿件分段预览（preview-split） | 任意 | — | `POST /api/manuscript/preview-split` 返回段落/估算时长，与正式任务共用 `split_manuscript_text`；`POST /api/creative/preview-script` 白名单校验/并发 429（PRD 1.1/1.1a/1.6） |
| M5 | 稿件单段失败隔离（stability_hardening P2） | 多段稿件 | 开启 | 注入某段 LLM 失败 → 任务不 FAILED，失败段留空被跳过、其余段正常生成；**续传仅重新生成失败段**（mock 计数断言 A/C 不重复调用）；全段失败显式报错（含首段 index）；停止/暂停类异常不被当作失败段（`docs/plans/v6.0/stability_hardening_PRD.md` Phase 2） |

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
| F3 | 视频分辨率 | — | 匹配请求参数 | 自动 | **只用 ffprobe/moviepy 读产物容器（禁止用 `perf_params` 校验——它是推理内部尺寸，v2.0 请求 768x1152 时为 832x1088）**；v2.0 按绝对像素 ±15% 容差（标准档保真、非标准档被吸附，见 `pipeline_products.md` §1.6）；**2.5 系列按宽高比 ±15% 校验**（720P 比例档位输出，绝对像素与请求不同，如 `3:4` 实为 834x1112；期望比例同样经 `width_height_to_aspect_ratio` 从请求像素推导，避免 `768x1152` 这类惯例档因固有差异误判，见 4.2） |
| F4 | 音频轨道 + 语音内容 | — | 视频包含音频轨道 + 语音内容 | 自动 | `moviepy` 检测 audio stream + `whisper` ASR |
| F5 | 字幕可见性 | — | 视频画面中字幕正确显示 | 手动 | 播放查看 |
| F6 | 字幕文本匹配 | — | 字幕文本与原文一致 | 自动 | ASR 转录与原文模糊匹配（> 30%） |
| F7 | 视频总时长合理 | — | 总时长匹配期望值，±15% | 自动 | 区间校验 |

> **合成链优化专项（v6.0 优化路线图 2.1c/2.2，2026-08-30 落地）**：
> - 带字幕场景（C3/M2/P1）现优先走 ffmpeg **ASS 单链**（`_ffmpeg_mux_aligned` + `subtitles` 滤镜，句级样式灰度），`AGNES_SUBTITLE_ASS=0` 或 ffmpeg 无 libass 时自动回退 moviepy（词级动效保真路径）。
> - poetry（P1）首次全量合成时走 `concat_scenes_single_pass`（场景视频 `-c copy` 拼接 + 音频 adelay/amix 合并 + 总字幕偏移，一次编码），失败自动回退逐场景合成（续传仍复用已合成场景）。
> - 上述场景产物验证（F1-F7、R7-R10）不变：音画字幕对齐、字幕文本匹配均需与旧路径一致，回退开关 `AGNES_SUBTITLE_ASS=0` 可随时切回旧路径做对照。

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
6. **默认视频模型 = `agnes-video-2.5-flash`（v6.2.1）**：`regression_runner.py` / `scene_runner.py` 提交任务前自动将全局视频模型设为 2.5-flash（比例档位输出），可用环境变量 `AGNES_REGRESSION_VIDEO_MODEL` 覆盖为其他 2.5 系列模型（如付费的 `agnes-video-2.5`）；v2.0 渠道已于 2026-10-14 下线（见 `agnes_video_upstream_behavior.md` §4.0.2），不再作为回归选项。

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
| 创意 (C1-C5) | 3-3-3-3-3 |
| 稿件 (M1-M4) | 4-4-4-4 |
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

  S3 [关键帧 keyframes · v8.0 前编号为 S1] — ✅ 最终产物全部通过（历史记录）
  S1/S2/S4 [一键预设 / 多图参考 / 参考音频] — ⬜ v8.0 新增，待执行

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
| S1 | `/api/tasks/simple` | 只传 prompt（一键预设） | 30m |
| S2 | `/api/tasks/simple` | mode=i2v, 2–5 张 reference_images | 30m |
| S3 | `/api/tasks/simple` | mode=keyframes, first_frame+last_frame | 30m |
| S4 | `/api/tasks/simple` | mode=i2v, reference_images+reference_audio_urls | 30m |
| C1 | `/api/tasks/creative` | chaining_mode=keyframes, ref | 120m |
| C2 | `/api/tasks/creative` | keyframes+end_frame_from_ref | 120m |
| C3 | `/api/tasks/creative` | keyframes, audio+subtitle | 120m |
| C4 | `/api/tasks/creative` | keyframes + scene_reference_images | 120m |
| C5 | `/api/tasks/creative` | 阿拉伯语 idea + audio_add_tashkeel + 字幕 | 120m |

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
| M3 | `/api/tasks/manuscript` | reference_images + reference_images_map | 60m |
| M4 | `/api/manuscript/preview-split` 等 | preview 端点（不创建任务） | 10m |
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

## 十一、v7.0 上游可靠性加固回归（增量）

> 新增于 v7.0（`docs/plans/v7.0/upstream_error_handling_plan.md` U1–U8）。
> 不进入 S1/A1–A2 权重计算，作为专项验证；事实依据见
> `docs/dev/agnes_video_upstream_behavior.md`。

### 11.1 单测（自动，`tests/test_upstream_error_handling.py`）

| ID | 条目 | 验证要点 |
|----|------|---------|
| N1 | U1 队列满独立轨道 | mock 连续 5 次 `503 video_queue_full` 后成功 → 调用次数（6）可超过 `max_retries=3`；进度回调载荷含 `attempt` 递增、`status=503`、`code=video_queue_full` 与原始 `message` |
| N2 | U1 队列预算到期 | 预算置 0 → `RuntimeError` 文案含 "queue"，不再是笼统 server error |
| N3 | U1 普通 5xx 不扩容 | 非队列类 5xx 仍只 `max_retries` 次；`error_message` 透出 body `message`，`extra.upstream_code` 有值 |
| N4 | U1 `fail_to_fetch_task` | 与 `video_queue_full` 同轨，第 2 次尝试成功 |
| N5 | U2 错误提取 | `_upstream_error` 覆盖响应体 / 轮询 `error` 对象 / 脏 JSON；轮询 failed 文案含上游原文 + `code=500`；`is_remote_video_failure` 语义保持 |
| N6 | U2 无 dict 字面量 | `collect_error` 的 `error_message` 不含 `{`，且含可读 message |
| N7 | U3 躺倒签名 | `_needs_portrait_rotation_fix(1280,720,720,1280)=True`；方向一致 / 尺寸缺失 / 非法值均为 False |
| N8 | U3 默认关闭 | 开关关闭或 `perf_params` 缺尺寸时不触发 `ffprobe`/`ffmpeg`；开启 + 2.5 系列时 `fix_rotation=True`，v2.0 不受影响 |
| N9 | U5 进度不可信 | `progress` 恒 0（`internal_progress=100`）时仍正常完成并产出 URL |

### 11.2 手动/实测场景

| ID | 场景 | 验证要点 |
|----|------|---------|
| V1 | 队列饱和实测 | 2.5-flash 在饱和时段提交 → 进度面板出现「Agnes 视频队列已满（HTTP 503 · video_queue_full），正在排队重试（第 N 次 / 已等 X 分钟）。建议错峰重试或稍后再试。」（en 同理点名 Agnes）；日志 `Queue full on ... queue retry #N`；不消耗普通 5xx 配额；预算耗尽时失败文案含 Agnes + 原始报错 + 错峰建议 |
| V2 | 错误透出实测 | 构造上游 `status=failed` → 失败面板展示含 `code=` 的上游原文；`error_logs/*.json` 的 `error_message` 为可读文本 |
| V3 | 竖屏方向实测 | 2.5-flash + 9:16 单场景任务：UI 提示可见；`AGNES_FIX_V25_PORTRAIT_ROTATION=1` 时日志出现 `[UpstreamRotate]` 且成片方向正确（`ffprobe` 容器与画面方向一致）；默认关闭时行为与升级前完全一致 |
| V4 | 未适配模型提示 | 构造上游有、本地能力表无的视频模型 → 下拉项带 `⚠` + 未适配提示；不再静默按 v2.0 像素协议提交 |
| V5 | 版本可见性 | 页脚显示 `版本 vX.Y.Z`；`GET /api/models` 返回 `app_version` |

### 11.3 文档一致性

| ID | 检查点 |
|----|-------|
| D1 | F3 校验口径含「禁止用 `perf_params` 校验产物分辨率」 |
| D2 | `pipeline_products.md` §1.6/§1.7 与实测行为一致（标准档保真 / 非标准档吸附 / 9:16 躺倒） |
| D3 | `faq.md` 含「0% 长时间等待」「15 分钟硬闸」「竖屏躺倒」「demo 与自托管能力对照」四条 |

---

## 十二、ffmpeg/ffprobe 调用收口回归（增量，Issue #78）

> 新增于 2026-09-29（`core/compositor/ffmpeg_tool.py` 的
> `resolve_cmd_binary` / `probe_duration` / `has_audio_stream` / `probe_video_dimensions`）。
> 背景：7 处调用绕过 `resolve_binary()` 用裸命令名，无系统 ffmpeg 时抛
> `[WinError 2]`（崩溃）或静默降级 0.0/None/False（连 ffmpeg 兜底探测也拿不到）。
> 单测：`tests/test_ffmpeg_tool.py`。

### 12.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| F1 | `resolve_cmd_binary` 透传 | 首元素非 ffmpeg 系（如 `python`）原样返回；空列表原样返回；不修改入参列表 |
| F2 | `resolve_cmd_binary` 替换 | 裸 `ffmpeg` / 带路径的 `ffmpeg.exe` → 解析后绝对路径，其余参数顺序不变 |
| F3 | `resolve_cmd_binary` 失败 | 解析不到可执行文件 → `RuntimeError`，文案为 i18n `error.ffmpeg_missing`（中/英均含 ffmpeg 字样），不再是裸 `[WinError 2]` |
| F4 | `probe_duration` 三级兜底 | ffprobe 可用取 stdout；ffprobe 为 None 时从 `ffmpeg -i` stderr 的 `Duration:` 行解析（Docker 场景）；两者皆无 → 返回 default；文件不存在 → default |
| F5 | `has_audio_stream` 兜底 | ffprobe 可用取 stdout；ffprobe 为 None 时匹配 `ffmpeg -i` stderr 的 `Stream #...: Audio:`；两者皆无 → False |
| F6 | `probe_video_dimensions` 兜底 | ffprobe JSON 取宽高；ffprobe 为 None 时正则解析 stderr 的 `768x1152`；两者皆无 → `(None, None)` |
| F7 | `SilentTTSEngine` 崩溃点 | 无 ffmpeg → `RuntimeError`（i18n 文案，含安装指引）；有 ffmpeg → 子进程首元素为解析后的绝对路径，产出文件非空、cues 为 None |

### 12.2 行为回归（自动，含在既有场景内）

| ID | 场景 | 验证要点 |
|----|------|---------|
| F8 | 既有 mock 回归全绿 | `./scripts/run_mock_regression.sh` 28 项通过（TTS 静音时间轴、尾帧提取/归一化、水印、拼接均走新路径） |
| F9 | 全量单测 | `.venv/bin/python -m pytest tests/ -q` 无新增失败 |

### 12.3 手工实测（无系统 ffmpeg 环境）

| ID | 场景 | 验证要点 |
|----|------|---------|
| F10 | Windows 无 ffmpeg + 关旁白 | 失败信息为「未找到可用的 ffmpeg 可执行文件…」中/英双语，而非 `[WinError 2]` |
| F11 | Docker（仅 imageio-ffmpeg 内置，无 ffprobe） | 时长/音频流/尺寸探测仍返回真实值（走 ffmpeg stderr 兜底），配音时长校验与数字人拼接不再恒定失败 |

---

## 十三、v7.6 外部素材模式回归（增量）

> 新增于 v7.6（`docs/plans/v7.6/external_asset_mode_PRD.md` + `docs/plans/v7.6/system_design.md`）。
> 外部素材模式 = 手动模式的增强版：在检查点暂停后，用外部工具（即梦 / Dreamina）生成
> 分镜视频/图片，把 mp4/png 批量导回本项目，由本项目负责归一化、拼接与字幕对齐。
> 不进入 S1/A1–A2 权重计算，作为专项验证；单测见 `tests/test_external_assets.py`。
>
> **ID 说明**：本专项端到端场景命名 `X1`；§3.3 服务端点表中的 `E1` 为 `GET /`，
> 与外部素材场景互不冲突（设计文档早期曾拟用 `E1`，此处改用 `X1`）。

### 13.1 端到端场景（自动）

| ID | 类型 | 场景 | 验证要点 |
|----|------|------|---------|
| X1 | 外部素材·创意 | 即梦回填视频 + 字幕 + 保留音轨（`execution_mode=external`、`audio_source=video`） | 创建改走 `execution_mode=external`、`provider=jimeng`、`audio_source=video` 且 `audio_config.enabled=False`；`audio` 检查点自动通过（不暂停）；`videos` 检查点 `external_hint` 非空；把即梦导出的 mp4 经 `POST .../artifacts/import` 回填 → `scene_{i}/video.mp4`（归一化到任务分辨率/帧率/编码并回显探针）；合成走 `concat_videos_keep_audio`（保留原音轨 + 烧字幕），**不**注入静音轨；字幕时间轴按各场景真实时长（`ffprobe`）估时 |

### 13.2 端点验证补充（自动）

| 端点 | 验证内容 | 期望结果 |
|------|---------|---------|
| `GET /api/providers` | 返回注册表（首期仅 `jimeng`），**不含**提示词模板字段 | 200，`providers:[{id,name,icon,capabilities,notes}]` |
| `POST /api/tasks/{id}/artifacts/import` | `kind` 非 `image`/`video` → 422；`scene_map` 非 JSON dict → 422；无文件 → 400；运行中 → 409；task 不存在 → 404 | 按上述返回 |
| `POST /api/tasks/{id}/artifacts/import` | 视频回填：`files[]` 文件名带序号 → `scene_{N-1}/video.mp4`；无序号 → 按上传顺序；`scene_map` 显式指定优先 | 200，`results[].probe` 含 duration/width/height/fps/has_audio/vcodec |
| `POST /api/tasks/{id}/artifacts/import` | creative + `kind=image` → 同时登记 `scene_reference_images[pos]`（使该场景以导入图为参考） | 200，`task_state.json` 的 `scene_reference_images` 有值 |
| `GET /api/tasks/{id}/artifacts/probe?relpath=...` | 单文件探针回显；`relpath` 路径穿越（如 `../task_state.json`）→ 404 | 200 / 404 |

### 13.3 单测（自动，`tests/test_external_assets.py`）

| ID | 条目 | 验证要点 |
|----|------|---------|
| X2 | 注册表 | `list_providers()` 仅 `jimeng`；`get_provider(""/"bogus")` 回退 `jimeng`；`has_capability` 四项能力为真；`checkpoint_prompts` 覆盖 scenes/references/videos/subtitle；`render_prompt` 填充 `<任务目录>` 且未定义检查点返回空串；`provider_public` 默认不含 `checkpoint_prompts` |
| X3 | 导入映射 | `_resolve_scene_target`：文件名数字 `N` → `scene_{N-1}`（仅当 `1 ≤ N ≤ 场景数`；越界如年份/时间戳 `20261015.mp4` → 回退上传顺序，不再落到 `scene_2025/`）；无数字（去扩展名）→ 按上传顺序；`scene_map` 显式优先；manuscript → `para_` 前缀；image → `ref.png`；anchor → `clip/clip.mp4` / `anchor.png` |
| X4 | 归一化 + 探针 | `normalize_external_video` 输出目标分辨率（768×1152）、h264、含 fps；无音轨片段不补静音；`probe_media` 文件缺失时 `duration=0.0`/`has_audio=False`；`normalize_external_image` 输出目标尺寸 PNG |
| X5 | keep-audio 判定 | `BasePipeline._keeps_video_audio`：`external` + `audio_source=video` → True；`project` / `manual` → False；无 `_state` 替身不抛异常 |

### 13.4 自动模式回归不变

`execution_mode` 缺省 `auto`、`audio_source` 缺省 `project` 时，行为与 v7.5 完全一致；
`_build_manual_config("auto", ...)` 早返回 `ManualConfig()`，旧兼容端点（`/api/tasks` 别名）
不受新增 `Form` 字段影响。

---

## 十四、v7.7 快速重试模式回归（增量）

> 新增于 v7.7（`docs/plans/v7.7/fast_retry_PRD.md`）。
> 连续 2 次忙信号（503 / 队列满）后进度页出现开关；用户可开「每分钟 x 次、持续 y 分钟」
> 快速连打，提交成功 / 到期 / 手动关闭即回常规忙轨。单测见 `tests/test_fast_retry.py`。
>
> **ID 说明**：本专项用 `QR*` 命名，避开既有的 F（产物校验 / 问题反馈）与 X（外部素材）系列。

### 14.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| QR1 | 状态机 | 连续 2 次忙信号 → `fast_retry.available=True`、落盘一次并推送 `progress.video.fast_retry.available`；开启后返回 `60/x`；超过 `minutes` → `enabled=False` + `finished_reason=expired`；提交成功 → `available=False` + `success`；未开启时成功不额外推消息 |
| QR2 | 节奏隔离 | 快速模式只首跳 `acquire` 视频提交桶（之后跳过）、`sleep` 按 `60/x`、hook 收到的 `busy_attempt` 恒为 0（不消耗 15 次额度）；到期后重新取桶并恢复递增 |
| QR3 | 零回归 | `fast_retry_hook is None` 时每跳都取桶、退避序列与引入前一致；钩子抛异常退化为常规忙轨且提交不失败 |
| QR4 | 端点 | `POST /api/tasks/{id}/fast-retry`：available 时开启 200（回传 `started_at`）；未 available 400；x/y 越界 422；关闭置 `finished_reason=disabled` |
| QR5 | 兼容 | 旧 `task_state.json`（无 `fast_retry`）加载后取默认值；真实 `TaskManager` 落盘新字段可回读 |
| QR7 | 计数 / 逐跳日志 | `payload.probe` → `fast_retry.attempts`，每跳更新、0.8s 节流落盘，到期与成功保留终值；前端 `available`/`enabled` 期间 1s 轮询实时刷新；`GET /api/tasks/{id}` 返回 `Cache-Control: no-store`；快速模式每跳都有 `[FastRetry] probe #N → POST`（含 payload）与 `← HTTP`（含 body），成功那跳同样有响应日志 |

### 14.2 端到端场景（人工，需真实 503 时段）

| ID | 场景 | 验证要点 |
|----|------|---------|
| QR6 | 真实队列饱和 | `agnes-video-2.5-flash` 连续 503 → 进度页在 2 次忙信号后出现开关；开启（如 30 次/分钟 × 3 分钟）后日志出现 `[FastRetry] ... fast retry probe #N` 且间隔 ≈2s；3 分钟后自动恢复 `busy retry #N/15`；期间提交成功 → 面板收起并提示 success |

### 14.3 隔离性回归

| 项 | 期望 |
|----|------|
| 未触发 503 的任务 | 状态里 `fast_retry` 全默认，进度页不出现面板 |
| 图片 / Chat / 上传忙轨 | 完全不受影响（首期不覆盖） |
| 令牌桶配置 | `AGNES_VIDEO_RATE_LIMIT` / `AGNES_RATE_LIMIT` 语义不变 |

---

## 十五、v7.8 轮询健壮性回归（增量）

> 新增于 v7.8（`docs/plans/v7.8/polling_resilience_PRD.md`）。
> 触发：服务重启后 resume，任务级 Key 绑定丢失 → 404 被当成入库延迟无限轮询。
> 单测见 `tests/test_poll_key_binding.py`；本专项用 `PB*` 命名，避开 F/X/QR 系列。

### 15.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| PB1 | Key 指纹落盘 | 提交成功写 `video_key_hints`，值为 `sha256(Key)[:16]`，状态文件不含 Key 明文；重复绑定不重复落盘 |
| PB2 | resume 反查 | 按指纹在当前 Key 池找回提交 Key（Key 顺序变化也能命中）；Key 被删时返回 None 并交给 404 探测 |
| PB3 | 404 分流 | 首轮查不到（错 Key）→ 探测到归属 Key → 固定切换域名与 URL → 立刻重查 → 拿到 `completed`（v7.9 起每个 Key 按「老端点 + REST 端点」逐个试，调用次数不固定，断言取「首个 k1、末次 k2」而非固定序列） |
| PB4 | U9 语义保护 | 全部 Key（两种端点）均查不到时不切换、不报错，打「均查不到 / 入库延迟」日志并继续等；已有绑定时不做探测 |
| PB5 | 进度透传 | `poll_progress_hook` 每轮被调用，流水线按「状态变化或 ≥25s」节流推送 `progress.video.polling` |
| PB6 | 零回归 | 三个钩子默认 `None`，`retry_policy` / 令牌桶 / 忙轨判定均未改动 |

### 15.2 端到端（人工，需多 Key + 一次真实提交）

| ID | 场景 | 验证要点 |
|----|------|---------|
| PB7 | 提交后重启服务再 resume | 新任务状态含 Key 指纹 → 日志 `[KeyBind] restored submit key`，**首轮即 200**（不触发 404 探测）；旧任务（无指纹）走探测兜底；两种路径都应恢复轮询直至 `completed` 并完成水印 |
| PB8 | 恢复已完成的上游任务 | 不重新提交、不消耗渲染配额；下载视频 → 水印 → `status=completed` / `final_video_file` 有效（`probe_duration` 可读） |

---

## 十六、v7.9 轮询查询端点双轨回归（增量）

> 新增于 v7.9（`docs/dev/agnes_video_upstream_behavior.md` §9）。
> 触发：国内站（`api.agnes-ai.cn`）提交的任务，轮询走 `/agnesapi?video_id=` 一律 404
> → 被 U9 当成「入库延迟」白等到 1800s 超时，成品其实早已生成。
> 单测见 `tests/test_poll_endpoints.py`；本专项用 `PE*` 命名。

### 16.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| PE1 | 端点回退 | 老端点 404 → 同轮改用 `/v1/videos/{id}` → 200 `completed`；请求序列为 legacy/rest（不 sleep、不计失败） |
| PE2 | 端点确认后不重复 | 首轮确认 REST 后，后续轮次只打 REST（不再打老端点，省配额） |
| PE3 | `task_not_exist` 语义 | `/v1/videos` 的 `400 code=task_not_exist` 等同 404，按 U9 中间态继续等，**不抛 HTTPError** |
| PE4 | 归属探测覆盖 REST | 老端点全 404 但 REST 200 时，`_probe_owner_key` 仍能找回归属 Key |
| PE5 | 成品地址取值 | `wait_for_video` 能从 `metadata.url` 取到地址（REST 端点无顶层 `url`） |

### 16.2 端到端（人工，国内站 Key + 一个已提交任务）

| ID | 场景 | 验证要点 |
|----|------|---------|
| PE6 | 国内站任务 resume | 日志出现 `查询端点确认 为 v1（https://api.agnes-ai.cn/v1/videos/...）` → `status=completed` → 下载（字节数 > 0）+ 水印 → `final_video_file` 可播放 |
| PE7 | 国际站任务零回归 | `com` 站点任务仍走 `/agnesapi`，首轮即 200，不产生多余请求 |

---

## 十七、v8.0 快速重试自动模式回归（增量）

> 新增于 v8.0（`docs/plans/v8.0/fast_retry_auto_PRD.md`）。
> 变更：设置页新增「自动快速重试」开关 + 频率；开启后任务连续 2 次忙信号**自动**
> 进入快速重试（不再需要用户点进度页开关）；任务页新增「以后自动」勾选，把一次性
> 操作固化为全局设置；手动关闭只在本轮生效（`auto_off`）。
> 单测见 `tests/test_fast_retry.py`（`TestFastRetryRemember` 等）；本专项用 `FR*` 命名。

### 17.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| FR1 | 自动开启 | 全局 `auto=True` 时第 2 次忙信号直接 `enabled=True`、`auto=True`、按全局 x/y 连打并推 `progress.video.fast_retry.auto`；第 1 次忙信号仍走慢速 |
| FR2 | 手动关闭抑制 | `auto_off=True` 时不再自动开启，仅置 `available` 等用户点；关闭端点把 `auto_off` 置 True |
| FR3 | 到期冷却 | 自动模式到期：`enabled=False`、`auto=False`、`consecutive_busy=0`（需重新累计 2 次忙信号），`attempts` 保留 |
| FR4 | 全局设置读写 | `GET /api/config.fast_retry` 默认 `auto=False`；`POST /api/config/fast-retry` 越界收敛（x∈1–120、y∈1–30）、未传字段保留旧值；落盘可回读 |
| FR5 | 以后自动 | `POST /api/tasks/{id}/fast-retry?remember=true` 返回 `fast_retry_settings.auto=True` 且参数与本次一致；不带 `remember` 时全局设置不变 |
| FR6 | 零回归 | 全局 `auto=False`（默认）时行为与 v7.7 完全一致：available 落盘一次、不自动开启 |

### 17.2 端到端（人工，需真实 503 时段）

| ID | 场景 | 验证要点 |
|----|------|---------|
| FR7 | 设置页开启后跑一个任务 | 设置页 → 快速重试 → 开启自动（如 30 次/分 × 3 分钟）→ 保存；任务遇连续 2 次 503 后**无需点击**即出现 `[FastRetry] ... started automatically`，面板显示「自动」筹码与已发次数；到期回常规忙轨 |
| FR8 | 任务页「以后自动」 | 全局关闭时手动开启快速重试并勾选「以后自动」→ 刷新设置页应显示已开启且频率一致；此后新任务到条件自动连打 |
| FR9 | 手动关闭只影响本轮 | 自动模式进行中在进度页关闭 → 本轮不再自动重开；续传（新运行）后重新遵守设置 |

### 17.3 隔离性回归

| 项 | 期望 |
|----|------|
| 设置页关闭自动 | 进度页面板与 v7.7 一致（有开关、可勾「以后自动」） |
| 图片 / Chat / 上传忙轨 | 不受影响（自动模式只作用于视频提交） |
| `auto_off` 落盘 | 续传 reset 一并清零，不会跨运行残留 |

---

## 十八、v8.1 多参考图回归（增量）

> 新增于 v8.1（`docs/plans/v8.1/multi_reference_images_PRD.md`）。
> 变更：参考图上限收敛为 `core.config.get_max_ref_images`（唯一出处）；四类槽位
> （人物板 → 风格板 → 衔接静帧 → 本段内容图）统一由 `core/pipelines/ref_slots.py`
> 合并；创意 / 稿件 / 诗词 / 数字人 / 简单图片全部支持多图；新增逐场景补图端点
> `POST /api/tasks/{id}/scene-refs`。
> 单测见 `tests/test_ref_slots.py`（合并 / 上限 / 兼容 / 模板）+ `tests/test_simple_v8.py`
> 末尾两条（截断留痕、超限 422）；本专项用 `MR*` 命名。

### 18.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| MR1 | 槽位合并顺序 | `merge_ref_images` 输出 人物 → 风格 → 衔接 → 本段内容，与传入顺序无关；同优先级稳定 |
| MR2 | 去重 | URL / data URI 按字符串、本地路径按 realpath；重复图只进一次 |
| MR3 | 截断留痕 | 超限从末尾丢并返回 `dropped`；`agnes_video._apply_reference_payload` 打 warning |
| MR4 | 上限单源 | `get_max_ref_images("agnes-video-2.5-flash")==5`、`("…2.5")==8`、未知模型 5；图片侧读 `AGNES_IMAGE_MAX_REF_IMAGES` |
| MR5 | 旧任务兼容 | 缺新字段的 `task.json` 反序列化后默认空列表 / `False`；`SceneTask.ref_images` 往返 |
| MR6 | 模板拼装 | `_get_scene_ref_images` = 人物板 + 风格板 + 本段内容图，flash 截到 5 张；`_get_scene_keyframes` 默认 None |
| MR7 | 简单视频超限 | 6 张 → 422；5 张 → 200 且全量落盘 |
| MR8 | 简单图片超限 | `/api/image/generate` 6 张 → 422；多图 payload `extra_body.image` 顺序保持 |
| MR9 | 逐场景补图鉴权 | 非暂停态 409；序号越界 422；额度 = 上限 −（人物板 + 风格板 + 衔接 1 张） |
| MR10 | 零回归 | 不上传任何图时，稿件/诗词仍生成风格板、创意仍走原链路，payload 与升级前差异仅多一块风格板 |

### 18.2 端到端（人工）

| ID | 场景 | 验证要点 |
|----|------|---------|
| MR11 | 稿件路径 R | 上传 2 张人物 + 1 张风格 → `task_state.json` 的 `character_plate`/`style_plate` 落地；各段日志 `ref images` 以人物板开头 |
| MR12 | 稿件路径 K | 勾「分镜衔接」→ references 检查点等到首/尾帧静帧；视频 payload 只有 `first_frame`/`last_frame`（看 `curl.sh`） |
| MR13 | 逐段补图 | 勾「生成前暂停补图」→ 任务停在 references；检查点页逐段上传 → `POST …/scene-refs` 返回新路径，续跑后该段 `images` 带上新图 |
| MR14 | 创意关键帧 | `curl.sh` 的 payload 为 keyframe（无 `images`）；`scene_*/end_frame.png` 由多图 i2i 生成 |
| MR15 | 创意链式 | payload `images` 顺序为人物板 → 风格板 → 上一镜尾帧 → 本段内容图；独立模式无衔接静帧 |
| MR16 | 诗词 | 上传 2 张风格图 → 不另生成 `style_plate.png`；每句 `images` 以这 2 张开头；纯意象无人物板 |
| MR17 | 数字人 | 上传 2 张 → `anchor.png` 走 i2i（日志 `Generating (i2i)`），第 1 张为脸；单张仍可用 |
| MR18 | 简单图片 | 前端多选 3 张 → 任务详情 `reference_images` 三条；图生图结果以 #1 构图为主 |

### 18.3 隔离性回归

| 项 | 期望 |
|----|------|
| 旧客户端（只传 `reference_image` / `anchor_reference_image` 字符串） | 简单图片、anchor 仍可用；`anchor_reference_image` 未落盘的老行为不再复现（图挂 `anchor_reference_images`） |
| 旧 `scene_reference_images` 创意任务续传 | 首次进 `_build_reference_images` 幂等迁移到 `scene_reference_images_map`，旧字段只读 |
| 上传大小上限 | 单文件 > 10MB → 413（`AGNES_UPLOAD_MAX_MB`，0 = 关闭）；不影响既有小图 |
| 22 语言 | `python3 scripts/i18n_check.py` 无缺失；新增 9 个 key 全语言覆盖 |

---

## 十九、简单图片续传回归（增量，Issue #114）

> 修复：`POST /api/tasks/{id}/resume` 的「任务类型 → Pipeline」映射漏了
> `TaskType.IMAGE`，图片任务续传兜到 `CreativeVideoPipeline`，在
> `_execute_step("step_build_scenes")` 处抛
> `ValueError: "SimpleImageTask" object has no field "step_build_scenes"`。
> 新增 `core/pipelines/simple_image.py::SimpleImagePipeline`（按 `task_state.json`
> 落盘参数重跑一次图片生成），映射见 `web/deps.py::create_pipeline_for_type`；
> prompt 拼接统一收敛到 `core.api.agnes_image.build_full_image_prompt`（路由与
> 流水线共用，`web.helpers._build_encrypted_image_prompt` 保留为兼容别名）。
> 单测见 `tests/test_simple_image_resume.py`（`IR*` 命名）。

### 19.1 单测（自动）

| ID | 条目 | 验证要点 |
|----|------|---------|
| IR1 | 类型映射 | `create_pipeline_for_type(TaskType.IMAGE, …)` 返回 `SimpleImagePipeline`，不再落到创意流水线（`test_web_helpers_deps.py`） |
| IR2 | 续传成功 | 失败图片任务 `run()` → `final_image.png` 落盘、`status=completed`、`final_video_file` 指向结果 |
| IR3 | 参数回放 | `prompt` / `size` / `negative_prompt` 取自 `task_state.json`；`system_prompt` 非空时按 base64 封装规则拼接 |
| IR4 | 参考图缺失 | 已清理的 `reference_images` 不提交上游（打 warning 跳过），存在的按原顺序提交 |
| IR5 | 失败落盘 | 上游异常 → `status=failed`、`current_step=generate`、`error_traceback` 非空、异常上抛（前端「重试任务」再点仍可续） |
| IR6 | 路由直连 | `POST /api/tasks/{id}/resume`（图片任务）200，`active_pipelines` 里是 `SimpleImagePipeline` |

### 19.2 端到端（人工）

| ID | 场景 | 验证要点 |
|----|------|---------|
| IR7 | 简单图片失败重试 | 断网 / 上游 500 制造失败 → 进度页点「重试任务」→ 进度消息走「正在生成图片…」→ 完成后直接展示图片，35 次重试那样的 `ValueError` 不再出现 |
| IR8 | 取消与并发 | 重试期间点「停止」→ 任务停在可续传态；同一任务重复点重试返回 400「Task is already running」 |

### 19.3 隔离性回归

| 项 | 期望 |
|----|------|
| 视频类任务 | 简单/创意/稿件/数字人/诗词的续传选型与行为不变（既有 `test_web_helpers_deps.py` 用例全绿） |
| 未知 task_type | 仍兜底创意流水线，但打 warning 便于定位（不再静默） |
| 图片创建链路 | `/api/image/generate` 行为不变（同一份 prompt 拼接实现，`tests/test_image_routes_upload.py` 全绿） |

---

*文档版本：v3.13 | 更新日期：2026-11-12 | 变更：新增简单图片续传回归（IR1–IR8，Issue #114）*
