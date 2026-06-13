# 🎬 Agnes Video Generator — ✨ 完全免费的 AI 视频生成工具

[![English](https://img.shields.io/badge/EN-English-blue)](/README.md)

> 🆓 完全免费的 AI 视频生成工具。基于 Agnes AI 免费模型，输入文字创意，自动生成多场景 AI 视频。支持 text-to-video、image-to-video、keyframes 视频生成。

本项目基于 [ViMax](https://github.com/HKUDS/ViMax) 和 [vimax-agnes](https://github.com/easyeye163/vimax-agnes) 改造而来，将命令行 AI 视频生成工具升级为带 Web UI 的一站式视频生成器。

## 🎥 Demo

> 暗黑童话 —《青蛙王子》，5 个场景，keyframes 串联，全自动生成。

[![青蛙王子 — 演示视频](https://img.shields.io/badge/▶%20观看演示-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/L4F6KdGnD6U/)

<sub>点击在抖音观看</sub>

## ✨ 特性

- **🌐 Web UI** — 一键启动后在浏览器中完成所有操作，无需命令行
- **🎥 AI 全流程自动化** — 创意 → 故事 → 角色参考图 → 脚本 → 逐场景 AI 视频 → 拼接成片
- **🖼️ 自定义参考图** — 上传角色参考图，所有场景保持角色一致性
- **🎯 自定义尾帧** — 为每个场景指定尾帧图片，精确控制 AI 视频画面
- **🔄 图生图尾帧** — 基于参考图用 img2img 自动生成场景尾帧
- **🔗 三种视频串联模式** — `keyframes`（推荐）/ `ti2vid`（过渡帧）/ `none`（独立场景）
- **💾 断点续传** — AI 视频任务中断后重启自动从断点恢复，不重复上传、不重复生成
- **🔑 页面配置 API Key** — 无需手动编辑配置文件
- **📡 实时进度** — WebSocket 推送每步 AI 视频生成进度到前端

## 🚀 快速开始

### 环境要求

- Python 3.10+
- ffmpeg（AI 视频拼接用）

### 一键启动

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

浏览器会自动打开 `http://localhost:8765`。

### 手动启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

然后访问 `http://localhost:8765`。

## 📖 使用说明

### 1. 配置 API Key

在页面顶部输入 [Agnes AI](https://platform.agnes-ai.com) 的 API Key 并保存。

也可通过环境变量设置：

```bash
export AGNES_API_KEY="your-api-key"
```

### 2. 创建 AI 视频任务

填写以下信息：

| 字段 | 说明 | 必填 |
|------|------|------|
| 创意描述 | 用自然语言描述你的 AI 视频创意 | ✅ |
| 用户要求 | 场景数、时长等约束（如"3个场景，每个场景10秒，电影质感"） | - |
| 视觉风格 | 电影质感写实风格、动漫风格、赛博朋克等 | - |
| 串联模式 | keyframes（推荐）/ ti2vid / none | - |
| 视频尺寸 | 默认 768×1152 竖屏 | - |
| 每场景时长 | 5s / 6s / 7s / 8s / 9s / 10s | - |

### 3. 可选：参考图 & 尾帧

- **参考图**：上传一张角色图片作为视觉锚点，不传则自动从故事中生成
- **自定义尾帧**：为每个场景指定尾帧图片
- **基于参考图生成尾帧**：启用后用 i2i 基于参考图自动生成每场景尾帧

### 4. 点击"开始生成视频"

右侧面板会实时显示 AI 视频生成进度：初始化 → 图片分析 → 故事生成 → 角色参考图 → 脚本编写 → 尾帧生成 → 视频生成 → 拼接。

### 5. 断点续传

如果服务中断，重新启动后在"任务列表"中找到未完成的任务，点击"续传"即可从断点恢复。

## 🏗️ 项目结构

```
agnes-video-generator/
├── start.sh                    # 一键启动脚本
├── requirements.txt            # Python 依赖
├── server.py                   # FastAPI 主服务 (REST + WebSocket)
├── static/
│   └── index.html              # 前端 SPA (Tailwind CSS)
├── core/
│   ├── config.py               # API Key 持久化
│   ├── screenwriter.py         # 编剧 Agent (LLM 调用)
│   ├── image_generator.py      # AI 图片生成 (t2i / i2i)
│   ├── video_generator.py      # AI 视频生成 (t2v / ti2vid / keyframes)
│   ├── pipeline.py             # AI 视频生成编排流水线
│   └── task_manager.py         # 任务管理 & 断点续传
├── models/
│   └── task.py                 # 数据模型
└── utils/
    ├── image.py                # 图片下载 / base64 转换
    └── video.py                # 视频下载
```

## 🔧 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python FastAPI | 异步 + WebSocket |
| 前端 | HTML/CSS/JS + Tailwind CSS CDN | 零构建步骤 |
| AI 模型 | Agnes AI API | agnes-2.0-flash / agnes-image-2.1-flash / agnes-video-v2.0（全部免费）|
| 视频拼接 | moviepy | 与原项目一致 |

## 🎬 三种 AI 视频串联模式

| 模式 | 原理 | 适用场景 |
|------|------|---------|
| **keyframes** | 每场景指定首帧+末帧，服务端自动插值过渡 | 追求平滑过渡（推荐） |
| **ti2vid** | 上一场景末帧 → img2img 过渡图 → 下一场景首帧 | 需要场景间视觉连续性 |
| **none** | 所有场景共用同一参考图，互不依赖 | 快速出片，场景独立 |

## 📋 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取 API Key（脱敏） |
| POST | `/api/config` | 保存 API Key |
| POST | `/api/tasks` | 创建 AI 视频生成任务 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{id}` | 查询任务详情 |
| POST | `/api/tasks/{id}/resume` | 续传中断任务 |
| POST | `/api/tasks/{id}/stop` | 中断运行中的任务（可续传） |
| WS | `/ws/{id}` | WebSocket 实时进度 |

## ⚠️ 使用须知

本项目目前处于早期阶段，corner case 问题可能较多。建议先走主流程：

1. 在页面上填写创意描述，提交 AI 视频任务
2. 观察**控制台日志**（启动 `server.py` 的终端），耐心等待
3. 关键操作均有日志输出，便于排查问题

### 已知限制

- 网络不稳定时可能出现部分步骤重试失败
- 大尺寸 AI 视频（>20s）生成时间较长，建议耐心等待
- 自定义尾帧数量与场景数不匹配时行为未定义
- 并发创建多个 AI 视频任务可能导致资源竞争

### 日志说明

所有重要操作都会在服务端控制台输出日志，包括：

- `[Startup]` — 启动时重置残留 running 任务
- `[WS]` — WebSocket 客户端连接/断开
- `[Resume]` — 续传任务开始，打印各步骤当前状态
- `[Stop]` — 用户主动中断任务
- `[Pipeline]` — 每个步骤的执行状态（SKIP 跳过 / RUNNING 执行）
- `[TaskManager]` — 任务状态加载
- `[EndFrame]` — 尾帧生成重试信息
- `[Pipeline] Shutdown` — 任务中断
- `[Pipeline] Completed / failed` — 任务完成或失败

### 输出物路径

所有 AI 视频任务产物存放在 `.working_dir/{task_id}/` 目录下：

```
.working_dir/{task_id}/
├── task_state.json              # 任务状态（断点续传依赖此文件）
├── final_video.mp4              # 最终拼接完成的 AI 视频
├── story.txt                    # AI 生成的故事文本
├── script.json                  # 场景脚本（JSON 格式）
├── image_analysis.txt           # 图片分析结果
├── character_reference.png      # AI 生成的角色参考图
├── character_ref_prompt.txt     # 角色参考图生成 prompt
├── end_frame_prompts.json       # 尾帧提示词（keyframes 模式）
├── scene_0/
│   ├── video.mp4                # 场景 0 AI 视频
│   ├── end_frame.png            # 场景 0 尾帧
│   ├── task.json                # 视频任务 ID
│   └── curl.sh                  # 查询视频状态的 curl 命令
├── scene_1/
│   └── ...
└── scene_2/
    └── ...
```

## 🙏 致谢

本项目基于以下开源项目改造：

- [ViMax](https://github.com/HKUDS/ViMax) — 香港大学数据科学实验室的 AI 视频生成框架
- [vimax-agnes](https://github.com/easyeye163/vimax-agnes) — 基于 ViMax 的 Agnes AI 适配实现

感谢原作者的杰出工作！

同时，特别感谢 [Agnes AI](https://platform.agnes-ai.com) 提供免费、高质量的 AI 模型 API（文本生成、图片生成、视频生成），让这个项目得以零成本运行。

## 反馈与贡献

项目目前处于早期阶段，欢迎通过 [GitHub Issues](../../issues) 提交问题反馈或功能建议。

## 📄 License

MIT
