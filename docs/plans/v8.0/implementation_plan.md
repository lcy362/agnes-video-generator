# v8.0 简单视频优化 · 实施记录

> 状态：🟢 P0 + P1 已实施；P2 待评估
> 关联：`simple_video_PRD.md`、`system_design.md`

## 一、阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 真一键 | 预设单一来源、默认 16:9、默认 simple + 记忆、表单分层、草稿收敛、草稿合法化、付费防护、Key 提示、文档修正 | ✅ 已完成 |
| P1 接口对齐 | 原生首尾帧、多图参考、参考音频 URL、付费档位修正（960P→1080P/1K/2K）、`<Picture N>`/`<Audio N>` 引导 | ✅ 已完成 |
| P2 体验增强 | 进度预期文案已加；Prompt 六要素模板、结果页「同参重生成」、竖屏任务级校正、轮询节奏评估 | ⬜ 待评估 |

## 二、改动文件

### 后端

| 文件 | 改动 |
|---|---|
| `core/config.py` | `SIMPLE_DEFAULT_PRESET` / `get_simple_default_preset()`、`VIDEO_25_SIZES`、`normalize_video_size()`（含 960P→1080P）、能力表修正（1080P/1K/2K、多图 8、音频 3、价格文案） |
| `models/task.py` | `SimpleVideoTask` 新增 `reference_images` / `first_frame_image` / `last_frame_image` / `reference_audio_urls`（带默认值） |
| `core/api/agnes_video.py` | `submit_video` 新增 `first_frame` / `last_frame` / `reference_audio_urls`；`_submit_video_v25` 按模式互斥组装 payload；`AGNES_KEYFRAME_NATIVE` 回退开关 |
| `core/pipelines/simple_video.py` | 素材组装：keyframe 首尾帧 / reference 多图+音频 / t2v 兼容；不再把尾帧塞进 images |
| `web/routes/task_creation_routes.py` | 新增 4 个可选参数、素材校验（上限/URL/互斥）、`video_size` 归一、落盘新字段 |
| `web/routes/config_routes.py` | `/api/models` 两个分支下发 `simple_default` |
| `core/i18n_backend.py` | 新增素材校验类错误文案（中/英） |

### 前端

| 文件 | 改动 |
|---|---|
| `store.ts` | 默认 `simple`、`rememberTaskType()`、`simpleDefault` |
| `components/CreatePanel.vue` | 切换类型写入 localStorage |
| `composables/useConfig.ts` | `loadModels` / `syncModels` 接收 `simple_default` |
| `composables/useVideoModelCaps.ts` | 兜底时长/比例修正、`maxRefAudios` |
| `components/forms/SimpleForm.vue` | 主区极简、预设摘要与恢复、更多设置、付费标注与二次确认、多图/首尾帧/音频、模式素材校验、草稿只恢复 prompt |
| `i18n/langs/*.json` | 22 语言新增 21 个 key；竖屏提示去掉已下线的 Video 2.0 |
| `static/` | 重新构建产物 |

### 文档

`docs/plans/v8.0/*`、`docs/public/api.md` / `api.zh.md`、`docs/public/usage.md` / `usage.zh.md`、
`docs/public/faq.md` / `faq.zh.md`、`docs/dev/agnes_video_upstream_behavior.md`（§9.5）、
`docs/dev/regression_test_plan.md`、`AGENTS.md`。

## 三、验证命令

```bash
# 后端静态检查 + 单测
.venv/bin/python -m py_compile core/config.py core/api/agnes_video.py \
  core/pipelines/simple_video.py models/task.py \
  web/routes/task_creation_routes.py web/routes/config_routes.py
.venv/bin/python -m pytest tests/ -q

# 前端构建（自动写入 static/）
cd frontend && npm run build

# 一键路径（服务已启动）
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=一只猫在花园里追蝴蝶"
```

## 四、遗留待办

1. **keyframe 输出尺寸复验**：用真实 Key 测 `mode=keyframe + aspect_ratio=16:9 + first/last frame`，
   确认是否仍为 704×704；结论回填 `docs/dev/agnes_video_upstream_behavior.md` §9.5.3。
   若仍固定方形，默认保持原生并在 UI 标注，或改回 `AGNES_KEYFRAME_NATIVE=0`。
2. **本地音频上传**：当前仅支持公开 URL；需确认上游是否有通用素材上传端点。
3. **参考视频 `videos[]`**：付费 2.5 已支持，本期仅能力展示，UI 未暴露。
4. **轮询节奏**：官方建议 1–2s，当前 20s 起步为规避共享令牌桶限流；
   如需优化，应在令牌桶预算内做「首分钟 5s、其后退避」评估。
5. **官网 `/api-docs` 旧协议**：独立站点维护，需单独排期更新为 2.5 协议。
