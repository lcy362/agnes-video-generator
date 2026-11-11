# 多参考图能力扩展 PRD（v8.1 计划代号）

> 状态：🟢 已实施（P0-a ~ P2-b 全部落地；实施口径与偏差见 §十三）
> 关联：`docs/dev/agnes_video_upstream_behavior.md` §9.5（官方参考图上限）、`docs/plans/v8.0/simple_video_PRD.md`（简单视频已落地部分）
> 版本说明：`8.1` 为**计划代号**，非已发版本号；`APP_VERSION` 与 tag 由用户按 `docs/dev/release_process.md` 触发
> 范围：创意长视频、稿件长视频、诗词视频、数字人口播、简单图片（简单视频已支持，本期仅补齐一致性）

---

## 一、背景

### 1.1 上游能力（已实测）

`mode=reference` 的 `images[]` 数组：Flash ≤5 张 / 2.5 ≤8 张，提示词可用 `<Picture N>` 指代。
图片侧 `POST /v1/images/generations` 的 `extra_body.image` 也是数组。

### 1.2 本项目现状（六种类型横向对照）

| 类型 | 数据结构 | 后端落盘 | API 传参 | 前端 UI | 实际能力 |
|---|---|---|---|---|---|
| 简单视频 | `reference_images: List[str]` | ✅ `{task_id}_ref{i}` | ✅ 全量 | ✅ 多选/删除/计数 | **≤5/≤8 张** |
| 创意长视频 | `reference_image: str`（角色）+ `scene_reference_images: List[str]`（每场景 1 张）+ `end_frame_images` | ✅ `{task_id}_ref` / `_scene_{i}` | ⚠️ 硬编码 1~2 张（三策略） | ⚠️ 每场景单文件 input | **每场景 1 张** |
| 稿件长视频 | `reference_images: Dict[str, List[str]]` | ✅ `{task_id}_ref{i}` + map | ✅ 全量直传 | ❌ 无任何 UI | **后端已就绪，前端不可用** |
| 诗词视频 | 无 | ❌ | ❌ | ❌ | **无参考图** |
| 数字人口播 | `anchor_reference_image: str` | ❌ 无落盘代码 | ⚠️ 仅 i2i 锚点图 1 张 | ⚠️ 单文件 input | **契约不一致（见 §4.4）** |
| 简单图片 | `reference_image: UploadFile` | ✅ `img_ref_{uuid}` | ✅ 数组（仅 1 张） | ⚠️ 单文件 input | **1 张** |

### 1.3 三个平台级缺口

1. **上限双源**：`core/config.py:1442/1466`（`max_ref_images`）与 `core/api/agnes_video.py:1525`（硬编码 `5 if flash else 8`）各写一份，改一处即静默截断。
2. **超限三套行为**：路由 422 / 前端静默丢弃（`SimpleForm.vue:202-205`）/ API 层静默截断（`agnes_video.py:1531`）。
3. **`SceneTask` 缺 `ref_images`**：`core/pipelines/multi_scene.py:492-494` 的 `_get_scene_ref_images` 钩子恒返回 `[]`，是「死钩子」——这是所有多场景类型无法多图的**共同根因**。

---

## 二、目标与非目标

### 目标

1. **一个抽象**：所有类型统一为「人物板、风格板、衔接静帧、本段内容图」四类槽位，合并规则唯一（§3.6）。
2. **多图可用**：creative / manuscript / poetry / anchor / simple_image 都能从 UI 上传多张并真正送到上游。
3. **不打扰**：不传图的用户行为零变化（默认无图、无暂停、无额外步骤）。
4. **单一来源**：上限只由 `core/config.py` 决定；超限行为统一为「前端预拦截 + 后端 422」，API 层仅作兜底并留日志。

### 非目标

- 不做参考视频 `videos[]`（2.5 支持但本期不暴露）。
- 不做本地音频文件上传（参考音频仍只接受公开 http(s) URL）。
- 不做「AI 自动理解图片并分配场景」。
- 不改动简单视频已落地的交互（仅复用其校验与上限来源）。
- 不重写 `MultiScenePipeline` 模板方法，不改检查点枚举体系。

---

## 三、核心设计

### 3.1 三档槽位模型

新增 `core/pipelines/ref_slots.py`（无状态纯函数模块）：

```python
@dataclass(frozen=True)
class RefSlot:
    kind: str                 # character | style | continuity | user_scene
    images: list[str]
    visible: bool = True      # True 才会出现在 <Picture N> 编号里

# 优先级：数值越小越靠前，越不容易被截断。顺序即 §3.6 的角色顺序。
SLOT_PRIORITY = {
    "character": 0,
    "style": 1,
    "continuity": 2,
    "user_scene": 3,
}

def merge_ref_images(slots: list[RefSlot], limit: int) -> tuple[list[str], list[str]]:
    """按优先级拼接 → 去重 → 截断。

    Returns:
        (payload_images, dropped)  dropped 为被截断的槽位描述，供日志与进度提示。
    """
```

规则（**唯一出处**，所有子类与 API 层共用）：

1. **排序**：按 `SLOT_PRIORITY` 升序；同优先级保持传入顺序。
2. **去重**：`http(s)`/`data:` 按字符串比较；本地路径按 `os.path.realpath` 比较。
3. **截断**：取前 `limit` 张，超出部分记录 `dropped`。
4. **编号稳定性**：同一角色的图在所有段里序号不变。多段模式的序号按 §3.6 的角色顺序，不按「用户图一律排前」。简单视频没有系统板，仍按用户上传顺序编号。

### 3.2 数据模型变更

`models/task.py`：

```python
class BaseTaskState(BaseModel):
    ...
    # v8.1：人物板 / 风格板。用户上传则直接写入，否则由流水线生成；空列表表示该任务没有这块板
    character_plate: List[str] = Field(default_factory=list)
    style_plate: List[str] = Field(default_factory=list)

class SceneTask(BaseModel):
    ...
    # v8.1：逐场景多参考图（顺序即 <Picture N>），由各流水线填充
    ref_images: List[str] = Field(default_factory=list)

class CreativeVideoTask(BaseModel):
    ...
    # v8.1：逐场景多图（key = 场景 index 字符串）；旧 scene_reference_images 只读兼容
    scene_reference_images_map: Dict[str, List[str]] = Field(default_factory=dict)

class AnchorVideoTask(BaseModel):
    ...
    # v8.1：第 1 张 = 数字人形象，其余 = 服饰/场景辅助参考
    anchor_reference_images: List[str] = Field(default_factory=list)

class SimpleImageTask(BaseModel):  # 若存在；否则在请求模型上加
    ...
    reference_images: List[str] = Field(default_factory=list)
```

所有新字段带默认值，旧 `task.json` 反序列化自动补齐（与 v8.0 simple 的做法一致）。

### 3.3 模板层一次性打通

改 `core/pipelines/multi_scene.py` 的钩子（**不改模板方法顺序**）：

```python
def _get_scene_ref_images(self, scene, index) -> List[str]:
    # 路径 R。路径 K 不走这里，视频请求只有首尾帧。
    slots = [
        RefSlot("character", list(self._state.character_plate or [])),
        RefSlot("style", list(self._state.style_plate or [])),
        RefSlot("user_scene", list(getattr(scene, "ref_images", []) or [])),
    ]
    images, dropped = merge_ref_images(slots, get_max_ref_images(self.video_api.model))
    if dropped:
        logger.warning("[MultiScene] Scene %d ref images truncated: %s", index, dropped)
    return images
```

效果：

- **poetry / manuscript** 未覆写视频提交时走路径 R，两块板在 `_build_reference_images` 里准备好即可。
- **creative** 覆写了视频提交，三条策略按 §4.1 分别走路径 K 或 R。
- **anchor** 只有一段，不使用这两块板（见 §4.4）。

### 3.4 上限单一来源

`core/config.py` 新增：

```python
def get_max_ref_images(model: str, media: str = "video") -> int:
    """参考图张数上限的唯一出处（前端经 /api/models 拿同一份值）。"""
    if media == "image":
        return int(get_settings().agnes_image_max_ref_images)  # 新增设置，默认 5
    return int(VIDEO_MODEL_CAPABILITIES.get(model, {}).get("max_ref_images") or 5)
```

同步改造：

| 位置 | 改动 |
|---|---|
| `core/api/agnes_video.py:1525` | 硬编码 → `get_max_ref_images(self.model)` |
| `web/routes/task_creation_routes.py:373` | 保持读 caps，但改为调该函数（避免两处逻辑） |
| `core/api/agnes_image.py` | 新增 `max_ref_images` 截断 + warning（当前无上限） |
| `GET /api/models` | 视频/图片分组都下发 `max_ref_images`（图片侧新增） |

### 3.5 超限行为统一

| 层 | 行为 |
|---|---|
| 前端 | 选满即禁用新增。多段模式显示「人物 / 风格已占用，本段还可 n 张」，分母是扣过系统板之后的余量 |
| 路由 | 超限 → `422 validation.too_many_ref_images`（已有多语言文案） |
| API 层 | 兜底 `merge_ref_images` 截断 + `logger.warning`（不再静默） |

### 3.6 多段连贯：三件事分两个通道

人物、风格、段间衔接不能塞进同一次视频请求。`keyframe` 与 `reference` 互斥：带了首尾帧就不能再带 `images[]`。上一镜的成片是完整构图，和人物定妆、风格板放在同一次 `images[]` 里会互相抢画面，人物更容易漂。

因此多参考图用在**画静帧**（图片接口 `extra_body.image` 本来就是数组），视频请求只提交画好的那一张或两张。

**两块全程复用的板**（每个任务各生成一次，用户上传则直接采用、不再另画一张）：

| 板 | 张数 | 何时跳过 |
|---|---|---|
| 人物板 | 生成 1 张；用户上传则用用户的，最多 2 张（脸 + 服装） | 文案没有反复出现的人物，不发明一张脸 |
| 风格板 | 生成 1 张；用户上传则用用户的，最多 2 张 | 用户已上传风格图 |

风格板的提示词只描述介质、调色、光线，不写人物、不写具体情节，避免和人物板抢身份。用户上传的图按表单分组进入对应的板，不另做「全局图」再往尾部追加。

**两条路径**（一张视频请求只走一条）：

| 路径 | 视频请求 | 多参考图用在哪 | 保住什么 | 是否串行 |
|---|---|---|---|---|
| K 静帧锁定 | 原生 `first_frame` + `last_frame`，不带 `images[]` | 画本段首帧、尾帧的图生图 | 人物 + 风格 + 剪接 | 静帧按段串起来；各段视频仍可一起提交 |
| R 参考图锁定 | `images[]`，不带首尾帧 | 视频请求本身 | 人物 + 风格 | 全并行 |

路径 K 的图生图顺序（超出图片侧上限时从末尾丢）：

1. 人物板
2. 风格板
3. 上一镜的尾帧静帧（仅首帧、且不是第一段）。用的是上一镜**生成好的尾帧静帧**，不是等成片抽出的真实尾帧，这样下一段不必等上一段视频出片
4. 用户为本段上传的内容图

尾帧的图生图换成「人物板 + 风格板 + 本段首帧 + 本段内容图」，不再带上一镜，否则这一段的画面不会往前走。图生图提示词写明角色：第 1 张锁身份，第 2 张只取风格、不复制构图，第 3 张接空间，其后是本段内容。

路径 R 的 `images[]` 顺序：人物板、风格板、本段内容图。不放入上一镜。

创意现有的「链式」是路径 R 再加一张衔接静帧，视频侧顺序为人物、风格、衔接静帧、本段内容图。衔接静帧由「人物板 + 风格板 + 上一镜尾帧」图生图得到，再进视频请求。它的剪接弱于路径 K，只留给已经选择链式的任务。

截断时从末尾丢：先丢多出来的本段内容图，再丢衔接静帧，再丢多出来的风格图，人物板留到最后一张。进度里写明丢掉的是哪一张。

额度（系统板先占，剩下给本段内容图）：

| 调用 | 上限 | 系统占用 | 用户还能传 |
|---|---|---|---|
| 视频 Flash，路径 R | 5 | 人物 1 + 风格 1 | 3 |
| 视频 2.5，路径 R | 8 | 人物 1 + 风格 1 | 6 |
| 视频 Flash，创意链式 | 5 | 人物 1 + 风格 1 + 衔接 1 | 2 |
| 视频 2.5，创意链式 | 8 | 同上 3 张 | 5 |
| 图生图，路径 K | 默认 5 | 人物 1 + 风格 1 + 上一镜 1 | 2 |

用户把某一板传到 2 张时，系统占用按实际张数算，本段内容图相应减少。界面按这个余量显示 `n / 剩余`，不把模型上限整段交给用户再在提交时静默截掉系统板。没有人物板时，风格板单独占 1 张。

---

## 四、分模式方案

### 4.1 创意长视频（creative）

**现状**：`steps_video.py` 三策略硬编码 1~2 张；`_user_scene_ref` 每场景只取 1 张。

**改造**：

1. **数据迁移（幂等）**：`_build_reference_images`（`creative/pipeline.py:218`）阶段执行一次
   `scene_reference_images_map.update({str(i): [p] for i, p in enumerate(scene_reference_images) if p})`，
   之后只读 map；旧字段保留不再写。续传任务重入不会重复迁移（map 已存在则跳过）。
2. **三策略按 §3.6 走，不再二选一**：

| 策略 | 路径 | 视频请求 | 图生图吃进的参考图 |
|---|---|---|---|
| keyframes（默认） | K | 原生 `first_frame` / `last_frame`。现有实现把这两张放进 `reference_image_paths`，会走 reference 模式，必须改成 `first_frame=` / `last_frame=` | 首帧：人物板 + 风格板 + 上一镜尾帧静帧 + 本段内容图。尾帧：人物板 + 风格板 + 本段首帧 + 本段内容图。用户已上传该段首帧或尾帧时，该张以用户图为准，不再图生图 |
| ti2vid（链式） | R + 1 张衔接静帧 | `images[]` = 人物板、风格板、衔接静帧、本段内容图 | 衔接静帧的参考图改为人物板 + 风格板 + 上一镜尾帧（现在只有上一镜尾帧一张） |
| independent | R | `images[]` = 人物板、风格板、本段内容图。不注入上一镜 | 无 |

人物板沿用现有 `character_reference.png`（用户上传的角色图优先，不再另画）。风格板为新产物 `style_plate.png`，从任务 `style` 生成；用户上传了风格图则跳过。

3. **上限**：本段内容图的余量 = 模型上限 − 人物板张数 − 风格板张数；链式再减 1 张衔接静帧。前端按余量显示。
4. **前端**（`CreativeForm.vue`）：
   - `sceneRefs: File[][]`（按场景数组），每场景 `<input multiple>` + 缩略图 + 删除
   - 提交契约：`scene_reference_images_map`（JSON `[[0, 3], [1], ...]`）+ 顺序 append 文件，与稿件现有 `reference_images_map` 同形
   - keyframes 模式下上传框文案改为「用于生成首帧的参考图（≤N 张）」

**风险**：creative 是续传最复杂的类型，迁移必须幂等 + 旧字段只读；改动面集中在 `steps_video.py` 三处 + 表单。

### 4.2 稿件长视频（manuscript）

**现状**：后端 `reference_images: Dict[str, List[str]]` 已支持单段多图（`manuscript_video.py:429-436`），前端零 UI，且提交前用户不知道段数（段数由后端按字数估算）。

**方案：路径 R 为默认，路径 K 为开关**

稿件段落经常换话题，默认不把上一段画面接进下一段。人物和风格用路径 R 锁，各段仍并行提交。

1. 拆段之后、提交视频之前，生成两块板：文案里有反复出现的人物才画人物板（否则跳过，不发明一张脸）；风格板按正文语气画 1 张。用户若在表单上传了「人物参考」（≤2）或「风格参考」（≤2），对应的板直接用用户的图。
2. 每段视频 `images[]` = 人物板、风格板、该段内容图。内容图来自提交时的 `reference_images`，或来自检查点补图。
3. 表单增加开关「分镜衔接」，默认关。打开后这一任务改走路径 K：每段先按 §3.6 画首帧和尾帧，视频只提交这两张静帧。代价是静帧按段串行，视频提交仍可批量。

不再使用单独的「全局参考图」桶。用户上传的图必须归入人物、风格或本段内容，避免和系统板叠成两套脸或两种风格。

L2 实现：

- `_get_pausable_steps`（`manuscript_video.py:225-231`）判定条件由「`reference_images` 非空」改为 `state.pause_for_scene_refs`（新字段，默认 `False`）
- 新端点 `POST /api/tasks/{task_id}/scene-refs`（multipart：`scene_index: int`，`reference_images: List[UploadFile]`）：
  - 落盘 `{task_id}_sref_{scene}_{seq}{ext}`（复用 `_save_upload_file`）
  - 写入 `scenes[i].ref_images`（覆盖语义）+ `update_state`
  - 逐段张数 ≤ 扣过人物板、风格板之后的余量，超限 422
  - **仅在任务处于该检查点暂停时允许调用**，否则 409（避免运行中改参数）
- 前端检查点面板（复用 v7.6 外部素材的检查点 UI 骨架）：每段展示文案前 40 字 + 多图上传 + 「跳过本段」；底部「继续生成」调既有 resume

### 4.3 诗词视频（poetry）

**现状**：`_build_reference_images` 空实现，`_get_pausable_steps` 显式 discard `step_reference_images`，未覆写 `_generate_videos`。

**改造：默认路径 R，只锁风格；人物和衔接按需打开**

1. 每首诗生成 1 张风格板（或采用用户上传的风格参考，≤2）。这是诗词连贯性的主体，每句视频都带上。
2. 人物板仅在分镜里有反复出现的人物时生成；纯意象、无人入画时不生成。
3. 每句视频走路径 R：`images[]` = 人物板（若有）、风格板、该句内容图。句与句并行。
4. 开关「句间衔接」默认关。叙事诗需要镜头连续时打开，改走路径 K。
5. 用户自定义分镜（`poetry_video.py:123-132`）句数已知，内容图在表单按句上传。LLM 分镜路径复用 §4.2 的检查点补图。
6. `_build_reference_images` 登记风格板、人物板和逐句内容图。

### 4.4 数字人口播（anchor）

**前置 Bug（P0 必修，与多图无关但阻塞一切）**：
`web/routes/task_creation_routes.py:987` 声明 `anchor_reference_image: str = Form("")`，而 `AnchorForm.vue:53` 以 **File** append 同名 key，且全仓无落盘代码 → 该参考图**当前完全无效**（`anchor_video.py:126` 的 `os.path.exists` 永不成立，静默退化为 t2i）。

**改造**：

1. 路由改 `anchor_reference_images: List[UploadFile] = File([])`，落盘 `{task_id}_aref{idx}`，写入 `anchor_reference_images: List[str]`；旧 `anchor_reference_image`（str）保留为「首图」兼容读路径。
2. `anchor_video.py:126-148`：i2i 生成锚点图时传全部参考图（`merge_ref_images` 上限按图片模型），第 1 张为主形象。
3. 视频阶段（`anchor_video.py:213-246`）仍只用锚点图 —— anchor 只有 1 段 5s 循环，多图作用于锚点图生成。
4. 前端 `AnchorForm.vue`：单文件 input 改多选 + 序号 + 删除，文案说明「第 1 张为数字人形象」。

**优先级 P2**：anchor 产物只有 1 段循环视频，多图收益有限；但 P0 的契约修复应单独提前修。

### 4.5 简单图片（simple_image / i2i）

**现状**：`agnes_image.py:143-153` 已支持 `extra_body.image` 数组；路由与前端只传 1 张。

**改造**：

1. `web/routes/image_routes.py:43` `reference_image: UploadFile` → `reference_images: List[UploadFile] = File([])`，保留旧单数字段兼容（有旧字段无新字段时回填为单元素）
2. 落盘 `img_ref_{uuid8}_{idx}{ext}`
3. 前端 `SimpleForm.vue:624-634` 图生图上传改 multiple + `n / max` + 删除
4. 上限：`get_max_ref_images(image_model, media="image")`，默认 5（官方未明确，保守值；可经 `AGNES_IMAGE_MAX_REF_IMAGES` 调整）

---

## 五、接口契约汇总

| 端点 | 变更 | 兼容 |
|---|---|---|
| `POST /api/tasks/creative` | 新增 `scene_reference_images_map: str(JSON)` | 旧 `scene_reference_images` 仍接收并按序迁移 |
| `POST /api/tasks/manuscript` | 新增 `character_images`、`style_images`（各 ≤2）、`link_shots: bool`（默认 false）、`pause_for_scene_refs: bool` | `reference_images_map` 契约不变 |
| `POST /api/tasks/poetry` | 新增 `character_images`、`style_images`（各 ≤2）、`link_shots: bool`（默认 false） | 不上传时仍会生成风格板 |
| `POST /api/tasks/anchor` | `anchor_reference_image: str` → `anchor_reference_images: List[UploadFile]` | 旧字段仍可作为「首图」传入 |
| `POST /api/tasks/simple_image` | 新增 `reference_images: List[UploadFile]` | `reference_image` 单数仍可用 |
| `POST /api/tasks/{id}/scene-refs` | **新增**：逐场景补图（仅暂停态可用） | — |
| `POST /api/tasks/simple` | 无变更 | 仅上限来源切到 `get_max_ref_images` |
| `GET /api/models` | 图片分组新增 `max_ref_images` | 纯新增字段 |

错误码：

- 超限 `422 validation.too_many_ref_images`（复用现有 22 语言文案）
- 非图片扩展名 `400`（现有 `_ALLOWED_UPLOAD_EXTS`）
- 任务不在暂停态调 `scene-refs` → `409`

---

## 六、前端交互规范

1. **统一上传组件**：抽 `RefImagesInput.vue`（接收 `v-model: File[]`、`max`、`label`），替代 SimpleForm/CreativeForm/AnchorForm/ManuscriptForm 各自的实现。
   - 缩略图 + 序号徽标 `#1 #2`（= `<Picture N>`）
   - 逐张删除、拖拽排序（排序决定编号，本期至少支持上下移动）
   - 选满禁用 + `n / max`
2. **模式互斥提示**：keyframes 模式下不展示「参考图」，改为「首帧参考图」文案（creative）。
3. **编号提示**：多图时在提示词输入框下方显示「图片按 #1、#2 顺序对应提示词中的 `<Picture 1>`、`<Picture 2>`」。
4. **不传图零打扰**：所有新上传区默认折叠在「高级设置」内（creative/manuscript/poetry/anchor）。
5. **22 语言**：新增文案键统一走 i18n，翻译缺失 CI 会拦。

---

## 七、分阶段实施

| 阶段 | 内容 | 依赖 | 预估改动面 |
|---|---|---|---|
| **P0-a 平台修漏** | 上限单源 `get_max_ref_images`；API 层截断加 warning；前端超限提示 | 无 | `config.py`、`agnes_video.py`、`agnes_image.py`、`task_creation_routes.py` |
| **P0-b 模板打通** | `SceneTask.ref_images` + `character_plate` / `style_plate` + `ref_slots.py` + 路径 R 的 `_get_scene_ref_images` | P0-a | `models/task.py`、`multi_scene.py`、新增 `ref_slots.py` |
| **P0-c 稿件多图** | 全局图 + 逐段补图端点 + 检查点 UI | P0-b | `manuscript_video.py`、`task_creation_routes.py`、`ManuscriptForm.vue`、检查点面板 |
| **P0-d 简单图片多图** | 路由 `List[UploadFile]` + 前端多选 | P0-a | `image_routes.py`、`SimpleForm.vue` |
| **P1-a 创意多图** | `scene_reference_images_map` 迁移 + 三策略 merge + 前端每场景多图 | P0-b | `steps_video.py`、`creative/pipeline.py`、`CreativeForm.vue` |
| **P1-b 诗词多图** | 全局风格图 + 逐句（检查点） | P0-b、P0-c 的端点 | `poetry_video.py`、`PoetryForm.vue` |
| **P2-a anchor 契约修复** | `str` → `List[UploadFile]` + 落盘 + 单图可用 | 无（可提前独立修） | `task_creation_routes.py`、`anchor_video.py`、`AnchorForm.vue` |
| **P2-b anchor 多图** | 锚点图 i2i 多图 | P2-a | `anchor_video.py`、`AnchorForm.vue` |

建议合并节奏：P0-a + P0-b 一个 PR（平台底座），P0-c/P0-d 各自独立 PR，P1 按类型单独 PR，P2-a 若确认为线上 bug 可插队先修。

---

## 八、兼容性与迁移

1. **旧任务反序列化**：所有新字段带默认值；`parse_task_state` 无需特判。
2. **creative 迁移**：`scene_reference_images` → map 的迁移幂等（map 非空即跳过），旧字段只读保留，便于回滚。
3. **anchor 迁移**：旧 `anchor_reference_image` 字符串若存在且 `anchor_reference_images` 为空 → 视为首图（`anchor_video.py` 内读取时合并）。
4. **续传**：`scene.ref_images` 落盘在 `task.json`，续传直接复用；已存在 `video.mp4` 的场景跳过（现有逻辑不变）。
5. **上传目录**：新增前缀 `_sref_` / `_aref_` / `img_ref_{uuid}_{i}`，与现有命名不冲突。
6. **磁盘治理（顺带补强）**：
   - 用户上传参考图登记为 artifacts 中间产物（当前完全未登记），参与级联删除
   - `_save_upload_file` 增加单文件大小上限（建议 10MB，可配 `AGNES_UPLOAD_MAX_MB`）
   - `sweep_stale_tasks` 覆盖 `uploads/` 中孤立文件（当前明确跳过）

---

## 九、验收标准

### 功能

1. 稿件默认（路径 R）：有人物的文案生成人物板 + 风格板 → 每段 `images` 以这两块板开头，其后才是该段内容图。无人称的文案不生成人物板。
2. 稿件打开「分镜衔接」：视频 payload 只有 `first_frame` / `last_frame`，没有 `images`。第 2 段首帧的图生图参考图含人物板、风格板、第 1 段尾帧静帧。
3. 创意关键帧：视频 payload 为原生 keyframe，不含 `images`。首帧图生图参考图顺序为人物板、风格板、上一镜尾帧静帧、本段内容图。
4. 创意链式：视频 `images` 顺序为人物板、风格板、衔接静帧、本段内容图。独立模式不含衔接静帧。
5. 诗词：上传 2 张风格图 → 不另生成风格板，每句 `images` 都以这 2 张开头。无人入画时没有人物板。
6. anchor：上传参考图后 `anchor.png` 由 i2i 生成（此前恒为 t2i，属修复）。多张时第 1 张为脸，其后为服装和背景。
7. 简单图片：上传 3 张 → 上游 payload `extra_body.image` 长度 3。
8. Flash 传 6 张视频参考图 → 路由 422；2.5 传 9 张 → 422；`AGNES_IMAGE_MAX_REF_IMAGES=2` 时图片传 3 张 → 422。
9. 用户不上传、且不打开衔接开关：稿件和诗词仍并行提交；每段 `images` 只有系统板。创意关键帧的视频请求只有首尾帧。

### 工程

10. `merge_ref_images` 单测覆盖：优先级（人物 > 风格 > 衔接 > 本段内容）、去重（URL / 本地路径 / data URI）、截断、`dropped` 返回。
11. `tests/test_simple_v8.py` 补 `images[:max_refs]` 截断用例与 `too_many_ref_images` 422 用例（当前双缺口）。
12. mock 回归新增场景（`docs/dev/regression_test_plan.md` §十八）：
    - `MR1` 稿件路径 R（人物板 + 风格板）/ `MR2` 稿件衔接开关走路径 K / `MR3` 创意关键帧原生首尾帧 / `MR4` 诗词风格板 / `MR5` anchor 参考图生效 / `MR6` 简单图片多图 / `MR7` 超限 422 / `MR8` 不上传时仍并行且只带系统板
13. `pytest tests/ -q` 全绿；前端 build 通过；22 语言文案完整。

---

## 十、风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 上游多图互相干扰（参考图越多越乱） | 成片质量下降 | 系统板最多人物 2 + 风格 2；上一镜只出现在静帧里，不和人物板一起进视频 `images[]`。质量下降时先丢掉本段内容图，再丢掉衔接静帧 |
| creative 数据结构迁移破坏续传 | 老任务无法继续 | 幂等迁移 + 旧字段只读 + 单测覆盖「旧 task.json 载入」 |
| 稿件逐段补图让任务停住 | 用户以为卡死 | 默认关闭；勾选时表单明示「将在生成前暂停等您补图」；检查点页有「全部跳过」 |
| 多图后磁盘与内存膨胀 | 上传全量读入内存（现状无大小限制） | 加 10MB 单文件上限；参考图登记 artifacts 参与级联删除 |
| 上限改多源后仍不一致 | 静默截断复发 | `get_max_ref_images` 为唯一入口；加单测断言「API 层与 config 值一致」 |
| 图片侧上限官方未明确 | 传多张可能被上游拒 | 默认 5，可配；上游 400 时错误透出保持现有行为 |

---

## 十一、待确认（已按下列口径实施）

1. **范围**：P0-a ~ P2-b **一次做全**（用户要求「根据文档实现」，未拆 PR）。
2. **稿件逐段补图**：走「检查点暂停 + 逐段上传」（`pause_for_scene_refs` + `POST /api/tasks/{id}/scene-refs`）。
3. **anchor 契约 bug**：按线上 bug 一并修复——上传图现在真实落盘并走 i2i，旧 `str` 字段保留为首图。
4. **图片侧上限**：默认 5 张，经 `AGNES_IMAGE_MAX_REF_IMAGES` 可调。
5. **文档落位**：保留 `v8.1` 独立计划线（`8.1` 仍是计划代号，非已发版本号）。

---

## 十二、变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-11 | 初版方案：现状矩阵、三档槽位模型、`SceneTask.ref_images` 打底、五模式分阶段方案 |
| 2026-11-11 | 连贯性分配：人物板 / 风格板 / 衔接静帧分路径 K（画进首尾帧）与路径 R（视频参考图）。稿件、诗词默认路径 R，衔接为显式开关 |

---

## 十三、实施记录（2026-11-11）

### 13.1 落地内容（按阶段）

| 阶段 | 落地 | 关键文件 |
|---|---|---|
| P0-a | 上限唯一出处 `get_max_ref_images`（视频取能力表 / 图片取 `AGNES_IMAGE_MAX_REF_IMAGES`）；API 层截断留 warning；`/api/models` 新增 `image_capabilities` | `core/config.py`、`core/api/agnes_video.py`、`core/api/agnes_image.py`、`web/routes/config_routes.py` |
| P0-b | 新增 `core/pipelines/ref_slots.py`（`RefSlot` / `merge_ref_images` / 额度助手）；`BaseTaskState.character_plate/style_plate`、`SceneTask.ref_images/first_frame_file`；模板 `_get_scene_ref_images` 走统一合并、新增 `_get_scene_keyframes`（路径 K）与 `_prepare_ref_plates` / `_prepare_link_shot_frames` | `core/pipelines/ref_slots.py`、`models/task.py`、`core/pipelines/multi_scene.py` |
| P0-c | 稿件人物板/风格板 + `link_shots` + `pause_for_scene_refs`；暂停时自动把 `references` 加入 `pause_points`；新增 `POST /api/tasks/{id}/scene-refs`（409/422/额度校验）；检查点接口回显逐段摘要；检查点页「逐段补图」面板 | `core/pipelines/manuscript_video.py`、`web/routes/task_creation_routes.py`、`web/routes/task_routes.py`、`web/routes/video_routes.py`、`CheckpointDetail.vue` |
| P0-d | `/api/image/generate` 改多图 + 复用统一落盘校验（扩展名白名单 / 大小上限 / 可解码）；前端多选 | `web/routes/image_routes.py`、`SimpleForm.vue` |
| P1-a | creative `scene_reference_images_map` 幂等迁移；三策略按槽位合并；关键帧改原生 `first_frame`/`last_frame`（不再塞 `images`）；风格板 + 逐场景多图 UI | `core/pipelines/creative/*`、`CreativeForm.vue` |
| P1-b | 诗词人物板/风格板 + 逐句内容图 + `link_shots` | `core/pipelines/poetry_video.py`、`PoetryForm.vue` |
| P2-a/b | anchor 多图落盘（修「上传即丢」契约 bug）+ 锚点图 i2i 多图 | `web/routes/task_creation_routes.py`、`core/pipelines/anchor_video.py`、`AnchorForm.vue` |
| 前端 | 新增共享组件 `RefImagesInput.vue`（缩略图 / `#N` 徽标 / 删除 / 上下移动 / 选满禁用）；22 语言 9 个新 key | `frontend/src/components/shared/RefImagesInput.vue`、`frontend/src/i18n/langs/*.json` |

### 13.2 与方案的偏差

1. **路径 K 的尾帧来源**：方案要求「首帧 = 本段起点、尾帧 = 本段终点」两帧都由多图 i2i 画。实际沿用上游「本段首帧 + 末帧」模型：先画首帧（人物板 + 风格板 + 上一镜尾帧 + 本段内容图），再以「本段首帧」替代「上一镜尾帧」画尾帧——避免尾帧被上一镜拽回起点。
2. **人物板生成判定**：方案写「由 LLM 从文案抽角色外观」，实现为轻量启发式（人称/职业词命中才画板）+ 命中后走 `screenwriter.get_character_appearance`，LLM 失败则用中性 prompt。宁可少画一张脸，也不把人物塞进纯意象文本。
3. **稿件人物板**：只用「用户上传」或「启发式命中后生成」两种来源，不做「同一人物跨段一致性」的聚类（方案未要求，成本不成比例）。
4. **端点名**：方案 §五 写 `POST /api/tasks/simple_image`，现网实际是 `POST /api/image/generate`，实现按现网端点扩展。
5. **磁盘治理**：单文件大小上限（`AGNES_UPLOAD_MAX_MB`，默认 10MB）已落地；「参考图登记为 artifacts / `sweep_stale_tasks` 覆盖 uploads」**未做**（现有 uploads 目录本就不参与级联删除，统一治理留给独立批次）。

### 13.3 自验结果

- `.venv/bin/python -m pytest tests/ -q` 全绿（含新增 `tests/test_ref_slots.py` 16 条、`tests/test_simple_v8.py` 2 条）。
- `cd frontend && npm run build`（含 `vue-tsc --noEmit`）通过；`npm run test` 19 条通过；`scripts/i18n_check.py` 无缺失。
- 真机联调（本机 8799 端口，真实上游）：
  - 稿件（2 人物 + 1 风格 + `link_shots` + `pause_for_scene_refs`）跑到 references 检查点暂停，`scenes[0]` 首/尾帧静帧均已生成，`curl.sh` 为 keyframe payload；
  - `POST /scene-refs` 成功写入 `scene_0`（额度 5 − 2 − 1 − 1 = 1，2 张被 422 拒绝）→ 检查点接口 `ref_count` 同步为 1；
  - 非暂停任务 409、序号越界 422、简单图片 6 张 422 均符合预期；
  - 4 个测试任务已通过 `DELETE /api/tasks/{id}` 清理。
