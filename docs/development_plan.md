# Agnes Video Generator 改造 — 完整开发计划

*文档版本：v2.0 | 状态：已确认，等待启动 | 日期：2025-06-14*

---

## TL;DR

从单一"创意长视频"扩展为 **三种视频任务类型**，引入 **edge_tts 免费旁白+字幕**，重构代码为 **四层通用组件架构**。涉及 **5 个有序任务、18 个源文件**。

---

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

## 5. 实现任务

### 任务依赖图

```
T01 → T02 → T03 → T04 → T05
```

### T01：基础设施与数据模型

| 属性 | 值 |
|------|-----|
| 优先级 | P0 |
| 依赖 | 无 |
| 文件数 | 5 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `requirements.txt` | 修改 | 新增 edge_tts>=6.1.0, srt>=3.5.0 |
| `models/task.py` | 重写 | TaskType枚举、BaseTaskState、SimpleVideoTask、CreativeVideoTask、ManuscriptVideoTask、AudioConfig、SubtitleStyle、ManuscriptParagraph |
| `models/__init__.py` | 修改 | 导出新模型 |
| `core/config.py` | 修改 | DEFAULT_VOICE、SUBTITLE_STYLE、get_default_audio_config() |
| `core/task_manager.py` | 修改 | 泛化 load/save，向后兼容旧数据 |

### T02：通用组件层

| 属性 | 值 |
|------|-----|
| 优先级 | P0 |
| 依赖 | T01 |
| 文件数 | 10 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/api/__init__.py` | 新增 | 导出 |
| `core/api/agnes_image.py` | 迁移+重构 | 从 image_generator.py |
| `core/api/agnes_video.py` | 迁移+重构 | 从 video_generator.py |
| `core/api/agnes_chat.py` | 提取 | Screenwriter 通用 Chat 方法 |
| `core/audio/__init__.py` | 新增 | 导出 |
| `core/audio/tts.py` | 新增 | EdgeTTSEngine + SilentTTSEngine |
| `core/audio/subtitle.py` | 新增 | SubtitleGenerator |
| `core/compositor/__init__.py` | 新增 | 导出 |
| `core/compositor/concatenator.py` | 新增 | VideoConcatenator |
| `core/compositor/processor.py` | 新增 | VideoProcessor |

### T03：业务流水线层

| 属性 | 值 |
|------|-----|
| 优先级 | P0 |
| 依赖 | T02 |
| 文件数 | 4 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/pipelines/__init__.py` | 新增 | BasePipeline + 导出 |
| `core/pipelines/simple_video.py` | 新增 | 简单视频流水线 |
| `core/pipelines/creative_video.py` | 新增 | 创意长视频（从 pipeline.py + 音频字幕） |
| `core/pipelines/manuscript_video.py` | 新增 | 稿件长视频（含时间拆段） |
| `core/screenwriter.py` | 修改 | 使用 AgnesChatAPI，新增 generate_scene_prompt_for_paragraph() |

### T04：服务端集成

| 属性 | 值 |
|------|-----|
| 优先级 | P0 |
| 依赖 | T03 |
| 文件数 | 2 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `server.py` | 重写 | 三种任务路由、Pipeline工厂、WebSocket保持 |
| `core/__init__.py` | 修改 | 更新导出 |

**新增 API**：
- `POST /api/tasks/simple`
- `POST /api/tasks/creative`
- `POST /api/tasks/manuscript`

### T05：前端重构

| 属性 | 值 |
|------|-----|
| 优先级 | P0 |
| 依赖 | T04 |
| 文件数 | 1 |

**变更清单**：

| 文件 | 操作 | 说明 |
|------|------|------|
| `static/index.html` | 重写 | 三Tab架构 + 结构化表单 + i18n 补全 |

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
pip install -r requirements.txt   # 首次需安装 edge_tts
python server.py
# 访问 http://localhost:8765
```

---

*状态：✅ 规划已完成 | ⏳ 等待用户指令开始实现*
