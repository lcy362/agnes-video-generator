# AGENTS.md — Agnes Video Generator

## 项目概述

基于 [ViMax](https://github.com/HKUDS/ViMax) 和 [vimax-agnes](https://github.com/easyeye163/vimax-agnes) 改造而来的 Agnes AI 视频生成工具。

**核心原则：** prompt 生成等细节逻辑与 vimax-agnes 原项目严格保持一致，不随意改动。

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端框架 | **Python FastAPI** | 异步支持好, 可复用 vimax-agnes 代码, 自带 WebSocket |
| 前端 | **原生 HTML/CSS/JS + Tailwind CSS CDN** | 零构建步骤, 轻量, 一键启动 |
| 实时通信 | **WebSocket** | 推送任务进度到前端 |
| 视频拼接 | **moviepy** | 与原项目一致 |

## 目录结构

```
agnes-video-generator/
├── start.sh                    # 一键启动脚本
├── requirements.txt            # Python 依赖
├── server.py                   # FastAPI 主服务
├── static/
│   └── index.html              # 前端单页 (Tailwind CSS CDN)
├── core/
│   ├── __init__.py
│   ├── config.py               # 配置管理 (API Key 持久化)
│   ├── screenwriter.py         # 编剧 Agent (严格复用 vimax-agnes 的 prompt)
│   ├── image_generator.py      # 图片生成 API 封装
│   ├── video_generator.py      # 视频生成 API 封装
│   ├── pipeline.py             # 视频生成流水线
│   └── task_manager.py         # 任务管理与断点续传
├── models/
│   └── task.py                 # Task/Schema 数据模型
└── utils/
    ├── image.py                # 图片下载/转换
    └── video.py                # 视频下载
```

## 与原项目的关系

- `core/screenwriter.py` → 严格复用 `vimax-agnes/agents/screenwriter.py` 的 prompt 模板
- `core/image_generator.py` → 复用 `vimax-agnes/tools/image_generator_agnes_api.py` 的 API 调用逻辑
- `core/video_generator.py` → 复用 `vimax-agnes/tools/video_generator_agnes_api.py` 的 API 调用逻辑
- `core/pipeline.py` → 基于 `vimax-agnes/pipelines/idea2video_pipeline.py` 重构, 增加断点续传
- `core/task_manager.py` → **全新模块**, 定义 task 结构, 管理断点续传

## 日志规范

所有重要操作必须输出日志，使用 `logging.getLogger(__name__)` 获取 logger。日志前缀约定：

| 前缀 | 含义 | 示例 |
|------|------|------|
| `[Startup]` | 服务启动 | 重置残留 running 任务 |
| `[WS]` | WebSocket | 客户端连接/断开 |
| `[Resume]` | 续传任务 | 各步骤当前状态 |
| `[Pipeline]` | 流水线步骤 | SKIP / RUNNING / Completed / Shutdown |
| `[TaskManager]` | 任务管理 | 任务加载 |
| `[EndFrame]` | 尾帧生成 | 重试信息 |

## 输出物路径

所有任务产物存放在 `.working_dir/{task_id}/` 下：

```
.working_dir/{task_id}/
├── task_state.json          # 任务状态（断点续传核心文件）
├── final_video.mp4          # 最终拼接视频
├── story.txt                # AI 故事
├── script.json              # 场景脚本
├── image_analysis.txt       # 图片分析结果
├── character_reference.png  # 角色参考图
├── character_ref_prompt.txt # 角色参考 prompt
├── end_frame_prompts.json   # 尾帧提示词（keyframes 模式）
├── scene_0/
│   ├── video.mp4
│   ├── end_frame.png
│   ├── task.json            # 视频任务 ID
│   └── curl.sh              # 查询视频状态的 curl
└── ...
```
