# 🏗️ 项目结构

```
agnes-video-generator/
├── start.sh                          # 一键启动脚本
├── requirements.txt                  # Python 依赖
├── Dockerfile                        # 多平台 Docker 镜像（Python 3.11 + imageio-ffmpeg）
├── docker-compose.yml                # Docker Compose（bind mount 持久化工作区 + 配置）
├── docker-run.sh                     # 一行 Docker 启动脚本（封装挂载参数）
├── server.py                         # FastAPI 主服务（仅 REST；进度经任务状态轮询，无 WebSocket）
├── static/
│   └── index.html                    # 前端构建产物 — 六种任务 Tab，22 种语言（Vite 构建输出）
├── frontend/                         # 前端源码（Vue 3 + Vite + TypeScript + Tailwind）
├── core/
│   ├── config.py                     # API Key、字体解析、默认配置
│   ├── screenwriter.py               # 编剧 Agent (LLM 驱动的故事/脚本/旁白生成)
│   ├── task_manager.py               # 任务状态持久化 & 断点续传
│   ├── api/
│   │   ├── agnes_chat.py             # LLM Chat API (agnes-3.0-flash)
│   │   ├── agnes_image.py            # 图片生成 API (agnes-image-2.5-flash，旧版 2.1 / 2.0-flash 可选)
│   │   ├── agnes_video.py            # 视频生成 API (agnes-video-v2.0)
│   │   └── rate_limiter.py           # 双令牌桶限速（共享桶 20 × Key 数 × 0.8 次/分 + 视频提交独立桶）
│   ├── audio/
│   │   ├── tts.py                    # Edge TTS 引擎 + 静音降级引擎
│   │   └── subtitle.py               # SRT 生成（词级细粒度）+ 字幕叠加
│   ├── compositor/
│   │   ├── concatenator.py           # 视频拼接 + 音频/字幕整体叠加
│   │   └── processor.py              # 视频缩放、帧提取、定格、静音生成
│   └── pipelines/
│       ├── multi_scene.py            # 多场景流水线模板基类（创意/稿件/数字人/诗词共用）
│       ├── simple_video.py           # 流水线：简单视频
│       ├── creative/                 # 流水线：创意长视频（编剧→分镜→视频→配音→拼接）
│       ├── manuscript_video.py       # 流水线：稿件长视频
│       ├── anchor_video.py           # 流水线：数字人口播
│       └── poetry_video.py           # 流水线：诗词视频
├── models/
│   └── task.py                       # 数据模型（6 种任务类型、配置、请求）
├── resource/
│   └── fonts/                        # 内置 CJK 字体（字幕渲染用）
├── utils/
│   ├── image.py                      # 图片下载 / base64 转换
│   └── video.py                      # 视频下载
├── scripts/
│   └── regression_runner.py          # 14 场景回归测试套件
└── docs/
    ├── plans/                         # 计划文档（分版本 + 待调研）
    ├── public/                        # 对外资料（README 引用、用户阅读）
    └── dev/                           # 架构/基础文档（内部、无需用户阅读）
```

# 🔧 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python FastAPI | 仅 REST；进度经任务状态轮询暴露（**无 WebSocket**） |
| 前端 | Vue 3 + Vite + TypeScript + Tailwind | 源码在 `frontend/`，构建产物提交到 `static/` |
| LLM | Agnes Chat (`agnes-3.0-flash`) | 免费 — 故事、脚本、旁白生成 |
| 图片 AI | `agnes-image-2.5-flash` (t2i / i2i) | 免费 — 参考图、尾帧、独立图片生成 |
| 视频 AI | `agnes-video-v2.0` | 免费 — 文生视频、图生视频、关键帧 |
| TTS | Edge TTS（微软） | 免费 — 动态音色目录，按 22 种 UI 语言分组，无需额外 API Key |
| 字幕 | moviepy + srt | 词级细粒度 SRT，多行自动换行 |
| 视频处理 | moviepy + ffmpeg | 拼接、字幕叠加、音频混合 |
