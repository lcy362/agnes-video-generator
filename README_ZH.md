# 🎬 Agnes Video Generator — 完全免费的 AI 视频生成工具

[![English](https://img.shields.io/badge/EN-English-blue)](/README.md)

> **完全免费的 AI 视频生成器** — 无需订阅、无需信用卡、无用量限制。基于 Agnes AI 免费模型，输入文字创意，一键生成带旁白配音和字幕的多场景 AI 视频。支持 text-to-video、image-to-video、keyframes 视频生成。

本项目基于 [ViMax](https://github.com/HKUDS/ViMax) 和 [vimax-agnes](https://github.com/easyeye163/vimax-agnes) 改造而来，将命令行 AI 视频生成工具升级为带 Web UI 的一站式免费视频创作平台。

## 🎥 Demo

> 暗黑童话 —《青蛙王子》，5 个场景，keyframes 串联，TTS 旁白配音 + 自动字幕，全自动生成。

[![青蛙王子 — 演示视频](https://img.shields.io/badge/▶%20观看演示-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/L4F6KdGnD6U/)

<sub>点击在抖音观看</sub>

## 为什么选择 Agnes Video Generator？

市面上的 AI 视频工具几乎都要按秒收费。Agnes Video Generator 完全不同 — **从头到尾完全免费**，无论是文本生成、图片合成还是视频渲染，都不花一分钱。你只需要一个免费的 [Agnes AI](https://platform.agnes-ai.com) API Key，就能零成本生成无限量的 AI 视频。

非常适合内容创作者、教育工作者、营销人员和技术开发者，放心大胆地尝试 AI 视频创作，再也不用担心账单。

## ✨ 特性

### 🆓 零成本 AI 视频生成

所有核心 AI 模型**全部免费** — 没有试用期、没有水印、没有 token 限制：

| 能力 | 模型 | 费用 |
|------|------|------|
| 文本 / 脚本生成 | `agnes-2.0-flash` | 免费 |
| 图片生成 | `agnes-image-2.1-flash` | 免费 |
| 视频生成 | `agnes-video-v2.0` | 免费 |
| 语音旁白（TTS） | Edge TTS（微软） | 免费 |

### 🎬 三种视频创作模式

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **简单视频** | 单条 prompt → 单个 AI 视频。完整暴露所有参数（生成模式、时长、分辨率、seed、负向提示词） | 快速生成单段 AI 视频 |
| **创意长视频** | AI 全流程：创意 → 故事 → 脚本 → 角色参考图 → 多场景视频 → 旁白配音 → 字幕叠加 → 拼接成片 | 故事短片、创意视频 |
| **稿件长视频** | 粘贴长文/稿件 → 自动拆段 → 逐段 AI 视频 → 统一 TTS 旁白 + 字幕叠加 → 最终视频 | 解说视频、课程内容、Vlog |

### 🎙️ AI 旁白配音与字幕

- **免费 TTS 旁白**：基于微软 Edge TTS，提供 4 种中文语音角色（温柔女声、沉稳男声、活泼女声、年轻男声），语速可调（-30% ~ +30%）
- **自动字幕生成**：基于词级时间戳的细粒度 SRT 分割，每 2-3 秒一条字幕，音画完美同步
- **多行字幕自动换行**：长字幕文本自动拆分为两行显示，智能在标点处断行，避免溢出屏幕
- **字幕样式全自定义**：字体、颜色、字号、位置（顶部/底部）、描边、半透明背景

### 🌐 多语言 Web UI

一键启动后在浏览器中完成所有操作，支持 **7 种语言**：中文、English、Русский、日本語、한국어、Melayu、Indonesia。

### 🎨 高级创意控制

- **自定义参考图** — 上传角色参考图，所有场景保持角色外观一致性
- **自定义尾帧** — 为每个场景指定尾帧图片，精确控制 AI 视频画面
- **图生图尾帧** — 基于参考图用 img2img 自动生成场景尾帧
- **三种视频串联模式** — `keyframes`（推荐）/ `ti2vid`（过渡帧）/ `none`（独立场景）
- **多种分辨率** — 竖屏 9:16（768×1152）、横屏 16:9（1152×768）、方形 1:1（1024×1024）
- **灵活时长** — 每场景 5s / 10s / 15s / 18s / 20s

### 🔧 生产级特性

- **断点续传** — 任务中断后自动从断点恢复，不重复调用 API
- **任务管理** — 在 Web UI 中创建、查看、续传和停止任务
- **实时进度** — WebSocket 推送每步 AI 视频生成进度到前端
- **页面配置 API Key** — 无需手动编辑配置文件，直接在浏览器中设置
- **AI Agent 友好** — 专为 AI 编程助手设计，可轻松完成部署和配置

## 🚀 快速开始

### 环境要求

- Python 3.10+
- ffmpeg（视频拼接和音频处理用）

### 方式 A：手动部署

**第一步 — 克隆 & 启动**

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

脚本会自动创建虚拟环境、安装依赖，并在浏览器中打开 `http://localhost:8765`。也可以手动启动：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

**第二步 — 配置 API Key**

前往 [Agnes AI](https://platform.agnes-ai.com) 获取免费 API Key，然后二选一：

```bash
# 方式 1：环境变量
export AGNES_API_KEY="your-api-key"

# 方式 2：通过 API 设置（等同于在 Web UI 中填写）
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}'
```

**第三步 — 创建第一个视频**

打开 `http://localhost:8765`，选择视频模式（简单 / 创意 / 稿件），输入创意描述，点击"开始生成视频"。

### 方式 B：AI Agent 辅助部署

本项目专为 AI 编程助手（Claude、Cursor、QoderWork 等）友好设计。先由你下载代码并准备好 API Key：

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
```

然后告诉你的 Agent：

> "阅读这个项目的 AGENTS.md，安装依赖，配置 API Key `<your-key>`，然后启动服务。"

Agent 会读取 `AGENTS.md`（一份完整的部署指引），自动完成：环境检查（Python 3.10+、ffmpeg）、`pip install`、服务启动和 API Key 写入。启动后还可以让 Agent 验证部署：

> "跑一下部署验证检查。"

Agent 会按 `AGENTS.md` 中的四层验证清单（连通性 → 静态分析 → 端点测试 → 字幕功能）逐项执行并汇报结果。

## 📖 使用说明

### 1. 配置 API Key

在页面顶部输入免费的 [Agnes AI](https://platform.agnes-ai.com) API Key 并保存。也可通过环境变量设置：

```bash
export AGNES_API_KEY="your-api-key"
```

### 2. 选择视频模式

#### 简单视频

快速生成单段 AI 视频，完整参数控制：

| 字段 | 说明 |
|------|------|
| Prompt | 用自然语言描述 AI 视频场景 |
| 生成模式 | 文生视频 / 图生视频 / 文+图 / 关键帧 |
| 分辨率 | 竖屏 9:16 / 横屏 16:9 / 方形 1:1 |
| 时长 | 5s / 10s / 15s / 18s / 20s |
| 参考图 | 可选上传，用于图生视频模式 |
| 尾帧图 | 可选上传，用于关键帧模式 |

#### 创意长视频

AI 驱动的多场景故事视频：

| 字段 | 说明 | 必填 |
|------|------|------|
| 创意描述 | 描述你的 AI 视频创意 | 是 |
| 用户要求 | 场景数、时长等约束 | - |
| 视觉风格 | 电影质感写实、动漫、赛博朋克等 | - |
| 串联模式 | keyframes（推荐）/ ti2vid / none | - |
| 旁白配音 | 启用/禁用 TTS，选择语音角色和语速 | - |
| 字幕样式 | 字体、颜色、字号、位置、描边、背景 | - |
| 参考图 | 可选角色参考图，保持角色一致性 | - |
| 尾帧 | 自定义或自动生成每场景尾帧 | - |

#### 稿件长视频

长文本转旁白视频：

| 字段 | 说明 | 必填 |
|------|------|------|
| 稿件文本 | 粘贴完整文章、脚本或旁白文本 | 是 |
| 分辨率 | 竖屏 / 横屏 / 方形 | - |
| 旁白配音 | 语音角色和语速 | - |
| 字幕样式 | 完整的字幕自定义选项 | - |

> **提示**：每段视频的时长由程序根据文本长度自动计算（约 4 字/秒，每段 5–12 秒），无需手动设置。

### 3. 点击"开始生成视频"

进度面板会实时显示每步生成状态。创意长视频流程：初始化 → 图片分析 → 故事生成 → 角色参考图 → 脚本编写 → 旁白生成 → 尾帧 Prompt → 尾帧生成 → 视频生成 → 音频字幕 → 拼接。

### 4. 断点续传与任务管理

如果服务中断，重新启动后在"任务列表"中找到未完成的任务，点击"续传"即可从断点恢复。运行中的任务也可以随时停止，稍后续传。

## 🏗️ 项目结构

```
agnes-video-generator/
├── start.sh                          # 一键启动脚本
├── requirements.txt                  # Python 依赖
├── server.py                         # FastAPI 主服务 (REST + WebSocket)
├── static/
│   └── index.html                    # 前端 SPA — 三种任务 Tab，7 种语言 (Tailwind CSS)
├── core/
│   ├── config.py                     # API Key、字体解析、默认配置
│   ├── screenwriter.py               # 编剧 Agent (LLM 驱动的故事/脚本/旁白生成)
│   ├── task_manager.py               # 任务状态持久化 & 断点续传
│   ├── api/
│   │   ├── agnes_chat.py             # LLM Chat API (agnes-2.0-flash)
│   │   ├── agnes_image.py            # 图片生成 API (agnes-image-2.1-flash)
│   │   └── agnes_video.py            # 视频生成 API (agnes-video-v2.0)
│   ├── audio/
│   │   ├── tts.py                    # Edge TTS 引擎 + 静音降级引擎
│   │   └── subtitle.py               # SRT 生成（词级细粒度）+ 字幕叠加
│   ├── compositor/
│   │   ├── concatenator.py           # 视频拼接 + 音频/字幕叠加
│   │   └── processor.py              # 视频缩放、帧提取、定格、静音生成
│   └── pipelines/
│       ├── simple_video.py           # 流水线：简单视频
│       ├── creative_video.py         # 流水线：创意长视频（10 步）
│       └── manuscript_video.py       # 流水线：稿件长视频（5 步）
├── models/
│   └── task.py                       # 数据模型（3 种任务类型、配置、请求）
├── resource/
│   └── fonts/                        # 内置 CJK 字体（字幕渲染用）
├── utils/
│   ├── image.py                      # 图片下载 / base64 转换
│   └── video.py                      # 视频下载
├── scripts/
│   └── regression_runner.py          # 9 场景回归测试套件
└── docs/
    ├── system_design.md              # 架构设计文档
    ├── regression_test_plan.md       # 回归测试计划
    └── *.mermaid                     # UML 图
```

## 🔧 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python FastAPI | 异步 + WebSocket |
| 前端 | HTML/CSS/JS + Tailwind CSS CDN | 零构建步骤，单文件 SPA |
| LLM | Agnes Chat (`agnes-2.0-flash`) | 免费 — 故事、脚本、旁白生成 |
| 图片 AI | `agnes-image-2.1-flash` (t2i) / `agnes-image-2.0-flash` (i2i) | 免费 — 参考图、尾帧生成 |
| 视频 AI | `agnes-video-v2.0` | 免费 — 文生视频、图生视频、关键帧 |
| TTS | Edge TTS（微软） | 免费 — 4 种中文语音，无需 API Key |
| 字幕 | moviepy + srt | 词级细粒度 SRT，多行自动换行 |
| 视频处理 | moviepy + ffmpeg | 拼接、字幕叠加、音频混合 |

## 🎬 三种 AI 视频串联模式

| 模式 | 原理 | 适用场景 |
|------|------|---------|
| **keyframes** | 每场景指定首帧+末帧，服务端自动插值过渡 | 追求平滑过渡（推荐） |
| **ti2vid** | 上一场景末帧 → img2img 过渡图 → 下一场景首帧 | 需要场景间视觉连续性 |
| **none** | 所有场景共用同一参考图，互不依赖 | 快速出片，场景独立 |

## 📋 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web UI 页面 |
| GET | `/api/config` | 获取 API Key（脱敏） |
| POST | `/api/config` | 保存 API Key |
| GET | `/api/voices` | 列出可用 TTS 语音角色 |
| POST | `/api/tasks/simple` | 创建简单视频任务 |
| POST | `/api/tasks/creative` | 创建创意长视频任务 |
| POST | `/api/tasks/manuscript` | 创建稿件长视频任务 |
| GET | `/api/tasks` | 列出所有任务（含类型标识） |
| GET | `/api/tasks/{id}` | 查询任务详情 |
| POST | `/api/tasks/{id}/resume` | 续传中断任务 |
| POST | `/api/tasks/{id}/stop` | 停止运行中的任务 |
| GET | `/api/video/{id}` | 下载/播放最终视频 |
| WS | `/ws/{id}` | WebSocket 实时进度 |

## ⚠️ 使用须知

本项目目前处于早期阶段，corner case 可能未完全处理。建议先走主流程：

1. 在页面上填写创意描述，提交 AI 视频任务
2. 观察**控制台日志**（启动 `server.py` 的终端），耐心等待
3. 关键操作均有日志输出，便于排查问题

### 已知限制

- 网络不稳定时可能出现部分步骤重试失败
- 大尺寸 AI 视频（>20s）生成时间较长，建议耐心等待
- 自定义尾帧数量与场景数不匹配时行为未定义
- 并发创建多个 AI 视频任务可能导致资源竞争

### 日志说明

所有重要操作都会在服务端控制台输出日志：

| 前缀 | 模块 |
|------|------|
| `[Startup]` | 服务启动，残留任务重置 |
| `[WS]` | WebSocket 连接/断开 |
| `[Resume]` / `[Stop]` | 任务续传/停止 |
| `[Pipeline]` / `[Simple]` / `[Manuscript]` | 流水线步骤执行 |
| `[TTS]` / `[Subtitle]` | 音频和字幕生成 |
| `[Compositor]` | 视频拼接和处理 |
| `[AgnesImage]` / `[AgnesVideo]` / `[AgnesChat]` | AI API 调用 |
| `[TaskManager]` | 任务状态持久化 |

### 输出物路径

所有 AI 视频任务产物存放在 `.working_dir/{时间戳}_{task_id}/` 目录下：

```
.working_dir/{时间戳}_{task_id}/
├── task_state.json              # 任务状态（断点续传依赖此文件）
├── final_video.mp4              # 最终视频（含旁白 + 字幕）
├── story.txt                    # AI 生成的故事（创意模式）
├── script.json                  # 场景脚本（JSON 格式）
├── narration.mp3                # 合并的 TTS 旁白音频
├── narration.srt                # 合并的字幕文件
├── scene_0/
│   ├── video.mp4                # 场景 0 AI 视频
│   ├── end_frame.png            # 场景 0 尾帧
│   └── task.json                # 视频生成任务 ID
├── scene_1/
│   └── ...
└── scene_2/
    └── ...
```

## 🙏 致谢

本项目基于以下开源项目改造：

- [ViMax](https://github.com/HKUDS/ViMax) — 香港大学数据科学实验室的 AI 视频生成框架
- [vimax-agnes](https://github.com/easyeye163/vimax-agnes) — 基于 ViMax 的 Agnes AI 适配实现

特别感谢 [Agnes AI](https://platform.agnes-ai.com) 提供**完全免费**、高质量的 AI 模型 API（文本生成、图片生成、视频生成），让这个项目得以零成本运行。

## 反馈与贡献

欢迎通过 [GitHub Issues](../../issues) 提交问题反馈或功能建议。

## 📄 License

MIT

---

**关键词**：免费AI视频生成器, AI视频生成工具, 文字转视频AI, 免费AI视频制作, AI视频创作, 开源视频生成器, Agnes AI, 文生视频, 图生视频, 关键帧视频, AI旁白配音, 自动字幕, 多场景视频, 零成本AI视频, 无需订阅的AI视频工具
