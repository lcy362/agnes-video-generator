# 设计文档：风格预设库（P0-1）+ 产物画廊（P1）

> **来源**：调研存档 `docs/plans/optimization-research/platform_features_research.md`（R5，2026-09-20 归档）中可执行的两项：P0-1（风格/提示词预设库）+ P1（产物画廊）。
> **设计核心约束**（用户明确要求）：
> 1. 产物画廊与任务列表**并行**，优化产物浏览体验；
> 2. **不破坏任务列表的目录结构**；
> 3. **尽量少增加实体文件**；
> 4. 尽可能**以现有目录结构为基础，通过逻辑实现功能**；
> 5. **画廊仅做展示，不进行任何删除操作**；
> 6. 其余候选（对话式生成、自由画布、平台治理、P2 凭据分组）**明确不做**。
> **当前状态**：设计稿（待评审）| 配套调研 R5 已调研完成（2026-09-22）

---

## 一、背景与目标

### 1.1 现状盘点（已逐条核代码）

| 能力 | 现状 | 代码证据 |
|------|------|---------|
| 风格输入 | `style` 为自由文本输入，无任何可复用模板 | `frontend/src/components/forms/{CreativeForm,PoetryForm,ManuscriptForm,AnchorForm}.vue` |
| 硬编码中文默认值 | `CreativeForm.vue:24`、`PoetryForm.vue:25` 默认 `'电影质感写实风格'`，非中文用户被预填中文并送进 prompt | 已核对 |
| 任务目录扫描 | `TaskManager.list_tasks()` 遍历工作区 `task_state.json`，返回 task_id/dir_name/task_type/status 等轻字段 | `core/task_manager.py:196-219` |
| 结构化产物枚举 | `list_artifacts()` 按任务类型定义产物（含 `final_video`），`build_manifest()` 输出 `final_video_file`、`preview_url` | `core/artifacts.py:343` / `:967` |
| 成片路径 | 各任务 state 顶层字段 `final_video_file` 已存成片绝对路径 | `models/task.py`；图片用 `state.final_video_file = img_path`（`web/routes/image_routes.py:127`） |
| 图片伺服 | `GET /api/image/{task_id}` 直接返回图片文件 | `web/routes/image_routes.py:135` |
| 媒体访问 | 产物条目的 `preview_url = /api/tasks/{id}/artifacts/{artifact_id}/file` | `core/artifacts.py:996` |
| 产物删除 | `get_cascade_plan()` + `apply_cascade_plan()`，级联清理；任务删除端点已具备 | `core/artifacts.py` |
| 持久化目录 | `.agnes_config/` 已存在（CONFIG_DIR），`_ensure_config_dir()` 保证目录可写 | `core/config.py:15/521` |
| 前端 Tab | `switchMainTab('create'|'list'|'simple')`，三标签 | `frontend/src/App.vue:29` |

**结论**：产物画廊所需的**数据（成片路径）**、**媒体访问（现有端点）**、**目录扫描（`list_tasks`）**、**只读展示**均已具备。画廊和预设库都可"以现有目录结构为基础、通过逻辑实现功能"，几乎不新增实体文件。

---

## 二、P0-1 风格/提示词预设库

### 2.1 数据形态

**系统预设（只读）**：新建 `resource/presets/styles.json`，只存 id + category + prompt 本体；名称/分类文案走前端 i18n（避免 JSON 内联 22 语言）：

```json
[
  { "id": "cinematic_realism", "category": "realistic",
    "prompt": "cinematic lighting, shallow depth of field, 35mm film grain" },
  { "id": "ink_wash", "category": "oriental",
    "prompt": "traditional Chinese ink wash painting, rice paper texture" }
]
```

**用户自定义预设（可读写）**：持久化到 `.agnes_config/presets.json`，name 用户自填、不参与翻译，category=custom：

```json
[
  { "id": "u_1", "name": "我的冷色调", "category": "custom",
    "prompt": "cool desaturated color grading", "created_at": "2026-09-22T10:00:00" }
]
```

> 复用 `CONFIG_DIR` 与原子写法（参考 `core/config.py:538` `save_config`），**不引入数据库、不新增实体体系**。

### 2.2 后端改动

| 文件 | 改动 | 作用 |
|------|------|------|
| `resource/presets/styles.json` | 新增，首批 10-15 条 | 提供开箱即用的风格模板 |
| `core/presets.py`（新建，纯函数） | 读系统预设（`resource/presets/`）+ 读写用户预设（`.agnes_config/presets.json`）；返回按 category 分组的结构 | 单一数据源 |
| `web/routes/preset_routes.py`（新建） | `GET /api/presets`（系统+用户合并、分组）+ `POST /api/presets`（存用户预设）+ `DELETE /api/presets/{id}` | 前端增删查 |
| `server.py` | 注册路由 | 暴露接口 |

> 应用预设只做"把 `payload.prompt` 填入请求参数"，**不引入新的生成链路**——与调研文档 §2.1 一致。

### 2.3 前端改动（核心：优化用户填入体验）

预设库的目标不是简单罗列模板，而是**让"填风格"这一步尽量省事、可复用、少打字**：

| 交互点 | 改法 | 作用 |
|--------|------|------|
| style 输入框旁 | **点击预设即一键填入** `style` 输入框（可继续手动微调），而非仅"查看" | 少打字，选完即生效 |
| 预设下拉 | 按 category 分组，组内显示简化名称 + 悬停 tooltip 展开完整 prompt | 快速定位，不打断输入 |
| 常用置顶 | 最近使用的预设自动置前（本地记录） | 高频风格秒选 |
| "保存当前值为预设" | 把当前输入框内容存成自定义预设，命名后可复用 | 把手写成果沉淀为模板 |
| 用户预设管理 | 自定义预设可重命名 / 删除；系统预设只读 | 可控、可维护 |

**文件级改动**：

| 文件 | 改动 |
|------|------|
| `i18n/langs/*.json`（22 个） | 新增预设分类名 key + 每条系统预设的名称 key |
| 新增 `usePresets.ts` | 拉取/保存/删除/本地最近使用（复用 `frontend/src/api/index.ts` 的 `request()`） |
| `CreativeForm.vue` / `PoetryForm.vue` / `ManuscriptForm.vue` | style 输入框旁加"选择预设"下拉（按 category 分组、tooltip 预览、最近置前）+ 一键填入 + "保存当前值为预设" + 用户预设可删 |

> **体验底线**：预设可一键填入选中的 style 输入框，用户既能零成本套用、也能选后继续手改——两种路径都少打字、不打断思考，且对"不填"保持完全向下兼容。

### 2.4 顺带修复（P0-1 核心价值之一）

| 文件 | 改动 |
|------|------|
| `CreativeForm.vue:24` | `style: '电影质感写实风格'` → `style: ''` |
| `PoetryForm.vue:25` | 同上 → `''` |

> 修改后表单不再预填中文；空值成为合法选择，与后端 `style: str = Form("")` 默认一致，行为与现状（不填时）完全兼容。

### 2.5 验收标准

1. creative / manuscript / poetry 三处均可选预设；不选或清空时行为与现状完全一致。
2. 非中文界面下 `style` 不再预填中文。
3. `i18n_check.py`（缺失即返回码 2）+ `vue-tsc --noEmit` + `vite build` 通过。

---

## 三、产物画廊（P1）— 核心设计

### 3.1 设计原则（对应核心约束）

1. **与任务列表并行**：新增"画廊"Tab，与现有"列表"Tab `v-show` 并行；不改动 `TaskListPanel.vue`。
2. **不破坏任务目录结构**：画廊**只读**任务目录，不向任何任务目录写入文件。
3. **尽量少增加实体文件**：**不生成独立缩略图文件**。缩略图/封面用现有媒体端点 + 浏览器原生能力实现（见 3.4）。
4. **以现有目录结构为基础、通过逻辑实现**：数据完全由 `list_tasks()`（目录扫描）+ `final_video_file`（成片路径）逻辑聚合而来，不新增清单/索引实体。

### 3.2 数据来源（纯逻辑，零新增实体）

画廊数据由后端一个**逻辑聚合端点**产出，遍历工作区任务目录：

```python
# 伪代码（实现于 gallery_routes.py）
GET /api/gallery?filter=all|video|image&status=all|completed|failed
```

对每个任务（复用 `TaskManager.list_tasks()` 的目录扫描），取：
- `task_id` / `dir_name` / `task_type` / `status`
- 描述字段：`creative_name` / `idea` / `prompt` / `manuscript_text`（列表摘要）
- **成片/产物路径**：`final_video_file`（视频/图片任务均存于此顶层字段）
- **媒体 URL**（由路径推导，不存新文件）：
  - 图片任务（`task_type == image`）→ `GET /api/image/{task_id}`（已有）
  - 其它任务 → 复用产物 `preview_url`：`/api/tasks/{id}/artifacts/{task_type}:final_video/file`（`build_manifest` 已生成同样 URL，画廊复用其拼接逻辑）

> **关键**：`final_video_file` 是扁平顶层字段（不是只存在于 `manifest.json` 的缓存），因此画廊**不需要读 manifest/checkpoint 实体文件**，只需 `list_tasks` 的轻扫描 + 取单个字段即可。图片任务同样把路径存进 `final_video_file`（`image_routes.py:127`），画廊无需单独分支处理文件定位。

### 3.3 缩略图策略（满足"少生成实体"）

**默认方案：不落盘缩略图，零实体文件。**
- **图片条目**：`<img :src="mediaUrl">` 直链现有图片端点，浏览器原生缩放。
- **视频条目**：`<video :src="mediaUrl" preload="metadata">`，利用浏览器原生加载首帧作为封面，hover / click 直接播放音频预览。

**可选增强（默认不做）**：当画廊条目数较大、网格加载慢时，可对成片抽单帧生成缓存缩略图。实现上
- 缩略图放**独立缓存目录**（`.agnes_config/gallery_cache/{dir_name}.jpg`，**不在任务目录内，不破坏任务目录结构**）；
- 惰性生成：首次访问画廊时对未缓存的成片用 ffmpeg 抽单帧，缓存后复用；
- 该缓存目录属可重建 Cache，`sweep` 可纳入清理，非任务产物。
- 因为「不重编码整片」抽单帧成本低，且带缓存，故该增强不违反"少实体"约束。

> 结论：首版**默认纯逻辑、无缩略图实体**；缓存缩略图作为独立可选项，不阻塞画廊主体交付。

### 3.4 交互形态

- **筛选**：类型（全部 / 视频 / 图片）× 状态（全部 / 已完成 / 失败）——纯前端过滤已返回数据。
- **网格卡片**：封面（缩略图/首帧）+ 类型气泡 + 描述 + 状态色标；点卡片用现有 `viewTask(task_id)` 进入详情。
- **只读展示**：画廊**仅做展示，不含任何删除/批量操作**。删除等管理操作保留在任务列表"列表"Tab（现有 `DELETE /api/tasks/{id}` 链路，画廊不触碰）。

### 3.5 后端改动清单

| 文件 | 改动 | 作用 | 新增实体 |
|------|------|------|---------|
| `web/routes/gallery_routes.py`（新建） | `GET /api/gallery`：`list_tasks()` 扫描 + 取 `final_video_file` + 推导 media url + 支持 filter/status（纯只读，不暴露任何删除） | 画廊数据聚合 | **0** |
| `server.py` | 注册路由 | 暴露接口 | 0 |
| （可选）`core/gallery_cache.py` + 缩略图端点 | 惰性抽帧缓存 | 大网格优化 | 缩略图进 `.agnes_config/gallery_cache/`，任务目录**零写入** |

> 除可选缓存目录外，**主体实现 0 新增实体文件**，完全逻辑聚合现有数据，**且只读、不产生任何删除副作用**。

### 3.6 前端改动清单

| 文件 | 改动 |
|------|------|
| `App.vue` | `switchMainTab` 增加 `'gallery'`；新增"画廊"Tab 按钮 + `<GalleryPanel v-show>` 与任务列表并行 |
| 新增 `GalleryPanel.vue` | 纯只读网格卡片 + 类型/状态筛选；点卡片跳详情。（**不含删除/确认弹窗**，不依赖 `useConfirm` 的删除路径） |
| 新增 `useGallery.ts` | `loadGallery(filter,status)` + 可选轮询（复用 `useTasks` 的退避/`visibilitychange` 模式） |
| `frontend/src/api/index.ts` | 增加 gallery **只读**调用（复用 `request()`，无任何 delete 方法） |
| `i18n/langs/*.json`（22 个） | 新增 tabGallery / filterVideo / filterImage 等 key |

> 复用现有色标逻辑（参考 `TaskListPanel.vue:27-50`）；画廊**不触碰删除链路**。

---

## 四、与任务列表的关系（不破坏，只并行）

| 维度 | 任务列表 | 产物画廊 |
|------|---------|---------|
| 触发 | `switchMainTab('list')` | `switchMainTab('gallery')`（新增，并行） |
| 数据 | `GET /api/tasks` | `GET /api/gallery`（复用扫描+成片字段） |
| 目录结构 | 不变 | **只读**，不写入任何任务目录 |
| 实体文件 | 不变 | **0 新增**（主体）；可选缓存进 `.agnes_config/` |
| 删除 | `DELETE /api/tasks/{id}` | **无**（画廊纯只读展示，不暴露删除） |
| 详情跳转 | `viewTask(task_id)` | 复用同一跳转 |

> 画廊是任务列表在"产物维度"的另一种**只读**视图，共用任务目录与详情跳转，但不触碰删除链路，零冲突。

---

## 五、回归面与风险

| 项 | 评估 |
|----|------|
| 后端回归 | 新增独立 gallery/preset 路由，不动现有任务/产物/删除链路；`list_tasks` 复用不改造；画廊端点纯只读、无副作用 |
| i18n | 永远硬前置：新增 key 需 22 语言补全（缺 en / zh 会被 `i18n_check.py` 硬阻断） |
| 前端构建 | 新增组件均走既有 `useConfirm`/`useToast`/`request()`，无新依赖 |
| 产物删除 | 画廊**不触碰删除链路**，删除风险项移除以彻底隔离 |

---

## 六、实施顺序与验收

1. **P0-1 预设库**（价值最高、含国际化缺陷修复）：后端 preset 路由 → 前端"一键填入 + 最近置前 + 保存为预设"选择器 + i18n → 修 `CreativeForm.vue:24`/`PoetryForm.vue:25` 默认值。
2. **P1 画廊 v1（纯逻辑、纯只读）**：`gallery_routes.py`（只读聚合）→ `GalleryPanel.vue` + `useGallery` → Tab 并行。**不做任何删除操作**。
3. **P1 画廊 v1.x（可选增强）**：缓存缩略图（`.agnes_config/gallery_cache/`），大网格性能优化。仍为只读，不引入删除。
4. **明确不做**：P2 凭据站点分组展示（纯展示层边际价值）、对话式生成、自由画布、平台治理类能力——与"单用户、自部署、永久免费、无登录"定位冲突或价值不足，本期不做。

**整体验收**：
- 画廊与任务列表并行可切换，不破坏现有列表与任务目录结构；
- 画廊为**纯只读展示，不含任何删除/批量操作**，不产生删除副作用；
- 画廊数据全部逻辑聚合，任务目录 `final_video_file` 语义不变、不新增任务内文件；
- `py_compile` + `i18n_check.py` + `vue-tsc --noEmit` + `vite build` 全通过；
- 涉及流水线改动跑 `./scripts/run_mock_regression.sh`。

---

*文档版本：v0.2（2026-09-22）| 状态：设计稿待评审 | 配套调研：`optimization-research/platform_features_research.md`（R5）（已调研完成 2026-09-22）*