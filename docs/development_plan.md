# Agnes Video Generator v2.0 — 完整开发计划（已归档）

> **状态**：📦 **已归档** — v2.0 开发已全部完成
> **当前阶段**：🟢 维护模式，参见 `AGENTS.md` 和 `docs/regression_test_plan.md`
> **最后更新**：2026-06-14
> **说明**：本文档保留作为开发过程的历史参考，不再作为活跃执行文档。

---

## 0. 分批执行流程（CRITICAL）

### 核心原则

```
❌ 禁止：一次性实现全部 T01-T05 → 最后才测试
✅ 必须：实现一批 → 验证一批 → 确认一批 → 下一批
✅ 必须：每批完成后 bash start.sh 可正常启动，且该批次涉及的主流程可用
```

### 增量可运行原则（CRITICAL）

每一批次交付的不仅是"编译通过"的代码，而是**可通过 `bash start.sh` 正常启动服务、且已有功能的主流程不被破坏**的可运行状态。具体要求：

| 批次 | start.sh 启动 | 主流程验证范围 |
|------|--------------|---------------|
| Batch A | 必须成功启动 | 现有创意长视频页面可加载、任务列表/详情 API 正常 |
| Batch B | 必须成功启动 | 现有创意长视频创建 API 可用（POST /api/tasks 返回 200），新旧 import 路径均可用 |
| Batch C | 必须成功启动 | 三种任务类型创建 API 均可用、三 Tab 前端可交互、WebSocket 进度推送正常 |

如果某批次实现后 `start.sh` 无法启动，则该批次**未通过**，必须修复后才能进入 QA 验证。

### 三批执行总览

```
                        ┌── 主理人向用户确认 ──┐
                        ↓                       │
Batch A (T01)  →  QA验证A  →  ✅用户确认  →  Batch B (T02+T03)
    基础设施                              │
                                         ↓
                                    QA验证B  →  ✅用户确认  →  Batch C (T04+T05)
                                                                      │
                                                                      ↓
                                                                 QA验证C  →  ✅交付
```

### 0.1 主理人收到"继续2.0版本开发"时的标准操作

```
[ ] 1. 确认团队已存在（software-agnes-refactor），若不存在则 TeamCreate
[ ] 2. 阅读 docs/system_design.md 确认当前批次任务规格
[ ] 3. 阅读 AGENTS.md 确认代码规范
[ ] 4. 启动 software-engineer，仅下发**当前批次**的任务（从 Batch A 开始）
[ ] 5. 工程师完成当前批次后 → 核对 AGENTS.md 全局一致性审查清单
[ ] 6. 工程师自行运行 bash start.sh 确认服务可启动（启动失败 → 立即修复）
[ ] 7. 工程师验证当前批次涉及的主流程可用（详见该批次验证清单）
[ ] 8. 启动 software-qa-engineer 验证当前批次
[ ] 9. QA 通过 → 向用户汇报当前批次结果，**等待用户确认后**进入下一批
[ ] 10. QA 不通过 → 反馈工程师修复 → 重新验证（最多 2 轮）
```

### 0.2 工程师启动提示词模板（每批独立）

> 以下是 Agnes Video Generator v2.0 **第 X 批（Batch X）** 实现任务。
>
> 请先阅读以下文件了解完整上下文：
> - `docs/development_plan.md` — 开发计划总览（重点看当前批次的任务清单）
> - `docs/system_design.md` — 架构设计（重点看当前批次相关章节）
> - `AGENTS.md` — 代码规范、日志前缀、共享知识
>
> **当前批次任务**：[列出本批次的文件清单和设计要求]
>
> **重要提醒**：
> - 只实现当前批次的任务，不要跨批次实现
> - 完成后自行运行可离线验证的检查（Python 语法、导入测试）
> - 完成后执行全局一致性审查（仅审查本批次涉及的条目）
> - **完成后必须运行 `bash start.sh` 确认服务正常启动**（启动失败则本批次未通过）
> - **完成后必须验证当前批次涉及的主流程可用**（详见验证清单末尾的 start.sh + 主流程项）
> - 如果新代码导致已有功能报错，必须添加向后兼容别名或修复，确保旧流程不受影响

---

## 1. 交付目标

## 1. 交付目标

| 目标 | 描述 |
|------|------|
| 🎬 简单视频 | 暴露 Agnes Video API 全部参数为结构化 UI 选项（模式/时长/分辨率/seed/negative_prompt/参考图），不依赖单一 prompt |
| 🎥 创意长视频 | 现有 7 步流程 + edge_tts 旁白 + 字幕叠加，保持断点续传 |
| 📝 稿件长视频 | 长文本 → 时间估算拆段（5-12s，不拆句子）→ AI scene_prompt → 视频 → TTS+字幕 → 拼接 |
| 🎵 音频字幕 | edge_tts 免费 TTS + SRT 字幕生成 + moviepy 叠加 |
| 🏗️ 架构分层 | `core/api/` / `core/compositor/` / `core/audio/` / `core/pipelines/` 四层 |

---

## 2. 核心决策

| # | 决策点 | 方案 |
|---|--------|------|
| D1 | 稿件拆段 | 按朗读时间估算（4字/秒），5-12 秒/段，**不拆开完整句子** |
| D2 | 稿件场景 prompt | AI 生成英文 prompt，**原文直接作旁白+字幕** |
| D3 | TTS 默认语音 | `zh-CN-XiaoxiaoNeural`，4 个中文角色可选 |
| D4 | 字幕样式 | P1：字体/字号/颜色/位置/描边色+宽/背景色 |
| D5 | 简单视频 prompt | 结构化暴露 Agnes API 全部 8 个参数，**不做 AI 增强** |
| D6 | 旧任务兼容 | `TaskManager.load()` 自动识别无 `task_type` 的旧数据为 CREATIVE |
| D7 | 默认分辨率 | 768×1152（竖屏），3 种预设可选 |
| D8 | 视频 padding | ≤ 1 秒，最后一帧 freeze |
| D9 | 多语言 | 保持 7 语言（zh/en/ru/ja/ko/ms/id），补全新文案 |

---

## 3. 技术栈

| 组件 | 选型 | 变更 |
|------|------|------|
| 后端 | Python FastAPI + WebSocket | 保持 |
| 数据模型 | Pydantic v2 | 泛化 |
| 视频处理 | moviepy + ffmpeg | 保持 |
| TTS | **edge_tts >= 6.1.0** | **新增** |
| 字幕 | **srt >= 3.5.0** | **新增** |
| 前端 | 原生 HTML/CSS/JS + Tailwind CDN | 重写 |
| LLM | Agnes Chat API（requests 同步） | 保持 |

---

## 4. 架构

```
core/
├── api/                    [新增] 通用 API 调用层
│   ├── agnes_image.py       (从 image_generator.py 迁移)
│   ├── agnes_video.py       (从 video_generator.py 迁移)
│   └── agnes_chat.py        (从 screenwriter.py 提取)
│
├── compositor/             [新增] 通用视频拼接层
│   ├── concatenator.py      (纯拼接 + 带音频拼接)
│   └── processor.py         (缩放/帧提取/静音)
│
├── audio/                  [新增] 通用音频字幕层
│   ├── tts.py               (EdgeTTSEngine + SilentTTSEngine)
│   └── subtitle.py          (cues→SRT + moviepy叠加)
│
├── pipelines/              [新增] 业务流水线层
│   ├── base.py              (共享进度/断点/shutdown)
│   ├── simple_video.py      (类型1)
│   ├── creative_video.py    (类型2，含音频字幕)
│   └── manuscript_video.py  (类型3，含时间拆段)
│
├── screenwriter.py          [保持+小改] 编剧Agent
├── config.py                [修改] 音频/字幕默认配置
└── task_manager.py          [修改] 泛化多任务类型
```

---

## 5. 分批任务

### 批次依赖图

```
Batch A (T01) ──→ Batch B (T02+T03) ──→ Batch C (T04+T05)
    ↑                   ↑                    ↑
 验证后确认           验证后确认            验证后确认
```

---

### Batch A：基础设施与数据模型（T01）

| 属性 | 值 |
|------|-----|
| 批次 ID | Batch A |
| 对应任务 | T01 |
| 优先级 | P0（最优先，后续批次的基础） |
| 文件数 | 5 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `requirements.txt` | 修改 | 新增 edge_tts>=6.1.0, srt>=3.5.0 |
| `models/task.py` | 重写 | TaskType枚举、BaseTaskState、SimpleVideoTask、CreativeVideoTask、ManuscriptVideoTask、AudioConfig、SubtitleStyle、ManuscriptParagraph |
| `models/__init__.py` | 修改 | 导出所有新模型 |
| `core/config.py` | 修改 | DEFAULT_VOICE、DEFAULT_SUBTITLE_STYLE、get_default_audio_config()、get_default_subtitle_style() |
| `core/task_manager.py` | 修改 | 泛化 load/save，向后兼容（无 task_type → CREATIVE） |

**验证清单（Batch A 专属）**：

```
[ ] A1: Python 语法检查 — python -m py_compile models/task.py models/__init__.py core/config.py core/task_manager.py
[ ] A2: 导入验证 — from models.task import TaskType, SimpleVideoTask, CreativeVideoTask, ManuscriptVideoTask, AudioConfig, SubtitleStyle
[ ] A3: 序列化测试 — SimpleVideoTask(...).model_dump_json() 正常输出
[ ] A4: 旧数据兼容 — TaskManager.load(dir_with_old_format) 不抛异常，返回 CreativeVideoTask
[ ] A5: config 工厂函数 — get_default_audio_config() 返回结构完整，字段有默认值
[ ] A6: requirements.txt — pip install -r requirements.txt 成功（含 edge_tts）
[ ] A7: start.sh 启动 — bash start.sh 无报错，Uvicorn 监听 8765 端口
[ ] A8: 主流程验证 — GET / 返回现有页面(200)、GET /api/config 返回 ok:true、GET /api/tasks 返回任务列表(200)
```

**完成标准**：全部 A1-A8 通过，主理人汇总后请用户确认。

---

### Batch B：通用组件 + 业务流水线（T02+T03）

| 属性 | 值 |
|------|-----|
| 批次 ID | Batch B |
| 对应任务 | T02 + T03 |
| 优先级 | P0 |
| 依赖 | ✅ Batch A 完成并确认 |
| 文件数 | 14 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/api/__init__.py` | 新增 | 导出 AgnesImageAPI / AgnesVideoAPI / AgnesChatAPI |
| `core/api/agnes_image.py` | 迁移 | 从 core/image_generator.py，类名 ImageGeneratorAgnesAPI → AgnesImageAPI |
| `core/api/agnes_video.py` | 迁移 | 从 core/video_generator.py，类名 VideoGeneratorAgnesAPI → AgnesVideoAPI |
| `core/api/agnes_chat.py` | 提取 | 从 core/screenwriter.py 提取 _chat/_chat_json/_chat_multimodal |
| `core/audio/__init__.py` | 新增 | 导出 |
| `core/audio/tts.py` | 新增 | EdgeTTSEngine + SilentTTSEngine |
| `core/audio/subtitle.py` | 新增 | SubtitleGenerator（cues→SRT + moviepy 叠加） |
| `core/compositor/__init__.py` | 新增 | 导出 |
| `core/compositor/concatenator.py` | 新增 | VideoConcatenator（纯拼接 + concat_with_audio） |
| `core/compositor/processor.py` | 新增 | VideoProcessor（缩放/帧提取/静音） |
| `core/pipelines/__init__.py` | 新增 | BasePipeline + 导出 |
| `core/pipelines/simple_video.py` | 新增 | 简单视频流水线 |
| `core/pipelines/creative_video.py` | 新增 | 创意长视频（从 pipeline.py + 音频字幕步骤） |
| `core/pipelines/manuscript_video.py` | 新增 | 稿件长视频（含时间拆段算法） |
| `core/screenwriter.py` | 修改 | 改用 AgnesChatAPI；新增 generate_scene_prompt_for_paragraph() |
| `core/image_generator.py` | 删除或留别名 | 旧文件指向 core/api/agnes_image.py |
| `core/video_generator.py` | 删除或留别名 | 旧文件指向 core/api/agnes_video.py |
| `core/pipeline.py` | 删除或留别名 | 旧文件指向 core/pipelines/creative_video.py |

**验证清单（Batch B 专属）**：

```
[ ] B1: 导入链完整 — python -c "from core.api import AgnesImageAPI,AgnesVideoAPI,AgnesChatAPI;from core.audio import EdgeTTSEngine,SubtitleGenerator;from core.compositor import VideoConcatenator;from core.pipelines import SimpleVideoPipeline,CreativeVideoPipeline,ManuscriptVideoPipeline"
[ ] B2: Screenwriter 使用 AgnesChatAPI — grep "requests.post" core/screenwriter.py 无结果或仅旧注释
[ ] B3: 日志前缀正确 — 检查 api/ 文件用 [AgnesImage]/[AgnesVideo]/[AgnesChat]；audio/ 用 [TTS]/[Subtitle]；compositor/ 用 [Compositor]；pipelines/ 用 [Simple]/[Pipeline]/[Manuscript]
[ ] B4: SubtitleGenerator.cues_to_srt() — 输入虚拟 cues → 输出合法 SRT 格式
[ ] B5: split_manuscript() 算法 — 边界测试（空文本/单句短/单句长/多句混合）
[ ] B6: 三个 Pipeline 类结构完整 — 都有 run() 方法，签名正确
[ ] B7: 旧文件兼容 — 旧 import 路径如有保留别名，from core.image_generator import ImageGeneratorAgnesAPI 仍然可用
[ ] B8: start.sh 启动 — bash start.sh 无报错，Uvicorn 监听 8765 端口
[ ] B9: 主流程验证 — POST /api/tasks（现有创意长视频端点）发送合法参数仍返回 200，GET /api/tasks/{id} 正常返回
```

**完成标准**：全部 B1-B9 通过，主理人汇总后请用户确认。

---

### Batch C：服务端集成 + 前端（T04+T05）

| 属性 | 值 |
|------|-----|
| 批次 ID | Batch C |
| 对应任务 | T04 + T05 |
| 优先级 | P0 |
| 依赖 | ✅ Batch B 完成并确认 |
| 文件数 | 3 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `server.py` | 重写 | 三种任务路由（simple/creative/manuscript）、Pipeline 工厂、WebSocket 保持 |
| `core/__init__.py` | 修改 | 更新顶层导出 |
| `static/index.html` | 重写 | 三 Tab 架构 + 结构化表单 + i18n 7 语言补全 |

**新增 API 端点**：
- `POST /api/tasks/simple` — 创建简单视频任务
- `POST /api/tasks/creative` — 创建创意长视频任务
- `POST /api/tasks/manuscript` — 创建稿件长视频任务

**验证清单（Batch C 专属）**：

```
[ ] C1: start.sh 启动 — bash start.sh 无报错，Uvicorn 监听 8765 端口
[ ] C2: GET / → 返回 index.html，浏览器打开三 Tab 结构可见
[ ] C3: i18n — 切换 7 种语言，所有新增文案翻译不缺失
[ ] C4: POST /api/tasks/simple — curl 发送合法参数 → 返回 {"ok":true,"task_id":"..."}
[ ] C5: POST /api/tasks/creative — 同上
[ ] C6: POST /api/tasks/manuscript — 同上
[ ] C7: GET /api/tasks — 返回列表，包含三种 task_type
[ ] C8: GET /api/tasks/{id} — 返回含 task_type 字段的详情
[ ] C9: 简单视频 Tab — 切换模式时参考图/尾帧上传区正确显示/隐藏
[ ] C10: 稿件长视频 Tab — textarea + [预览拆分] 按钮存在且可交互
[ ] C11: 创意长视频 Tab — 音频配置区（旁白开关/语音角色/语速/字幕样式）可见
[ ] C12: 主流程验证 — 简单视频完整流程：创建任务 → 前端显示进度 → 任务列表可查到该任务
```

**完成标准**：全部 C1-C12 通过，主理人汇总交付。

---

## 6. 每批完成后的主理人确认模板

向用户汇报时使用以下格式：

```
## ✅ Batch X 完成

**批次**：Batch X — [批次名称]
**任务**：Txx — [任务描述]
**文件**：N 个文件已创建/修改

**验证结果**：
| 检查项 | 状态 |
|--------|------|
| X1: ... | ✓ |
| X2: ... | ✓ |
| ... | ... |
| start.sh 启动 | ✓ / ✗ |
| 主流程验证 | ✓ / ✗（说明具体验证了哪些流程） |

**IS_PASS**：YES / NO（附问题列表）

**下一步**：Batch Y — [下一批名称]，预计 N 个文件

是否继续下一批？
```

---

## 6. 文件统计

| 类别 | 数量 |
|------|------|
| 净新增文件 | 14 |
| 重写文件 | 4 (models/task.py, server.py, core/config.py, index.html) |
| 修改文件 | 4 (requirements.txt, core/task_manager.py, core/screenwriter.py, models/__init__.py) |
| 已迁移旧文件 | 3 (image_generator.py, video_generator.py, pipeline.py → 保留别名或删除) |
| 保持不变 | 7 (utils/×3, start.sh, core/__init__.py, .gitignore, LICENSE) |

---

## 7. 稿件拆段算法

```
split_manuscript(text) → List[ManuscriptParagraph]:
  1. 预处理：按换行符 → 按句号/问号/感叹号 → 候选句子列表
  2. 对每个候选句子：est_duration = len(text) / 4.0 （中文 4 字/秒）
  3. 贪心合并：累积时长 ≤ 12s，≥ 5s
     - 短句（< 5s）合并到前一段
     - 长句（> 12s）接受，不拆
  4. 如果合并后总时长 < 5s：向前合并（最后一段外）
  5. 返回段落列表，每段含 index / text / est_duration
```

---

## 8. 简单视频 UI — Agnes API 参数映射

| UI 控件 | API 参数 | 说明 |
|---------|---------|------|
| 生成模式（下拉） | mode / image | t2v / i2v(ti2vid) / keyframes |
| Prompt（文本框） | prompt | 直接透传 |
| 参考图（上传） | image | i2v/keyframes 模式显示 |
| 尾帧图（上传） | extra_body.image[1] | 仅 keyframes 显示 |
| 时长（下拉） | num_frames + frame_rate | 5/10/15/18/20s |
| 分辨率（下拉） | width + height | 竖屏 768×1152 / 横屏 1152×768 / 方形 1024×1024 |
| Seed（数字，可选） | seed | 折叠区域 |
| Negative Prompt（文本，可选） | negative_prompt | 折叠区域 |

---

## 9. 启动命令

```bash
cd /Users/lcy/video/agnes-video-generator
source .venv/bin/activate
pip install -r requirements.txt   # 首次需安装 edge_tts, srt
python server.py
# 访问 http://localhost:8765
```

---

## 10. 阶段状态（历史记录）

| 阶段 | 状态 | 批次 | 完成日期 |
|------|------|------|---------|
| PRD（产品需求） | ✅ 完成 | — | 2025-06-14 |
| 系统设计 + 任务分解 | ✅ 完成 | — | 2025-06-14 |
| 开发计划文档 | ✅ 完成 | — | 2025-06-14 |
| **Batch A：基础设施** | ✅ **完成** | T01（5 文件） | 2026-06-14 |
| **Batch B：通用组件+流水线** | ✅ **完成** | T02+T03（14 文件） | 2026-06-14 |
| **Batch C：服务端+前端** | ✅ **完成** | T04+T05（3 文件） | 2026-06-14 |
| QA 最终验收 | ✅ **通过** | — | 2026-06-14 |

---

*文档版本：v3.3 | 状态：📦 已归档 | v2.0 开发全部完成*
