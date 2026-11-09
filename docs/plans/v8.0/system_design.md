# v8.0 简单视频优化 · 增量系统设计

> 状态：🟢 已实施
> 关联 PRD：`docs/plans/v8.0/simple_video_PRD.md`
> 接口契约：Agnes 官方 2.5 文档 + `docs/dev/agnes_video_upstream_behavior.md`

## 一、默认预设（单一事实来源）

`core/config.py::SIMPLE_DEFAULT_PRESET`：

| 项 | 值 | 依据 |
|---|---|---|
| `model` | `agnes-video-2.5-flash` | 免费（限时） |
| `mode` | `t2v` | 后端语义；前端 2.5 语义为 `text` |
| `duration` | `5` | 官方默认 `"5"` |
| `aspect_ratio` | `16:9` | 官方默认；规避 2.5-flash 9:16 躺倒 |
| `video_width/height` | `1280 / 720` | 由比例推导，仅用于生成 `aspect_ratio` |
| `video_size` | `720P` | Flash 唯一合法档 |

下发路径：`GET /api/models` → `simple_default`（缓存命中/未命中两个分支都返回）。
前端 `appState.simpleDefault`；后端 `POST /api/tasks/simple` 的 `Form(...)` 默认值直接引用该字典。

## 二、接口契约变化（向后兼容）

### 2.1 `POST /api/tasks/simple` 新增可选参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `reference_images` | `List[UploadFile]` | 多图参考（替代单图 `reference_image`） |
| `first_frame_image` | `UploadFile` | keyframe 首帧 |
| `last_frame_image` | `UploadFile` | keyframe 尾帧 |
| `reference_audio_urls` | `str`（换行/逗号分隔） | 参考音频公开 URL，≤3 |
| `video_size` | `str` | 归一到 `720P/1080P/1K/2K` |

旧参数 `reference_image` / `end_frame_image` 保留，并回填到新字段：
- `reference_image` → `reference_images[0]`（若未传多图）
- `end_frame_image` → 旧 keyframes 任务的尾帧

### 2.2 任务状态新增字段（全部带默认值）

`models/task.py::SimpleVideoTask`：
```python
reference_images: List[str] = []
first_frame_image: str = ""
last_frame_image: str = ""
reference_audio_urls: List[str] = []
```
历史 `task.json` 缺这些字段时由 Pydantic 默认值补齐，`parse_task_state` 无需迁移。

### 2.3 校验规则

| 场景 | 行为 |
|---|---|
| `duration` 不在 `4/5/6/8/10/12` | 422（既有） |
| `video_size` 非法 | 归一为 `720P`（不 422） |
| 参考图超上限 | 422 |
| 参考音频超 3 段 / 非 http(s) | 422 |
| `keyframes` + `reference_images/audios` | 422（官方模式互斥） |
| `i2v` 缺图 | 后端放行（兼容旧调用），前端拦截 |

## 三、模式映射与互斥

| 前端（2.5 语义） | 后端 `mode` | 素材 |
|---|---|---|
| `text` | `t2v` | 无 |
| `reference` | `i2v`（或 `ti2vid`） | `reference_images`、`reference_audio_urls` |
| `keyframe` | `keyframes` | `first_frame_image` / `last_frame_image` |

`core/api/agnes_video.py::_submit_video_v25` 按「keyframe > reference > text」组装 payload：

- keyframe：`mode=keyframe` + `first_frame` / `last_frame`，不带 `images/audios`
- reference：`mode=reference` + `images`（Flash ≤5 / 2.5 ≤8）+ `audios`（≤3）
- text：仅公共参数

回退开关：`AGNES_KEYFRAME_NATIVE=0` 时首尾帧合并进 `images`，走旧 reference 降级。

## 四、前端结构

`frontend/src/components/forms/SimpleForm.vue`：

- 主区：提示词 → 预设摘要（模型 · 模式 · 时长 · 画幅 · 免费/付费）→「修改设置 / 恢复默认」→ 生成按钮
- 更多设置：模型（免费优先 + 标签 + 付费警示）、模式/时长/画幅/清晰度、素材区、高级参数
- 素材区按模式切换：`reference` → 多图 + 音频 URL；`keyframe` → 首帧/尾帧
- 草稿：视频只恢复 prompt；设置项以预设为准
- 付费确认：`useConfirm().confirmAsync`，同一模型确认一次，切换模型重置

`frontend/src/store.ts`：
- `currentTaskType` 初始值 `localStorage('wb_task_type') || 'simple'`
- `rememberTaskType()` 在 CreatePanel 切换时写入
- 新增 `simpleDefault`

`frontend/src/composables/useVideoModelCaps.ts`：
- 兜底时长改为 `[4,5,6,8,10,12]`，兜底比例与后端一致
- 新增 `maxRefAudios`

## 五、能力元数据修正（`core/config.py`）

| 项 | 修正前 | 修正后 |
|---|---|---|
| 2.5 `sizes` | `720P/960P/2K` | `720P/1080P/1K/2K` |
| 2.5 `max_ref_images` | 5 | 8 |
| 2.5 `max_ref_audios` | — | 3 |
| Flash `max_ref_audios` | — | 3 |
| Flash keyframe 标签 | 「自动降级图片参考」 | 「首尾帧控制」 |
| 价格文案 | `960P $0.04/s` | `1080P/1K $0.04/s` |

## 六、测试

- `tests/test_simple_v8.py`：预设、size 归一、历史任务兼容、payload 组装、路由一键路径、
  多图/首尾帧/音频、互斥与上限校验。
- 回归矩阵：`docs/dev/regression_test_plan.md` 场景 S1–S4。
