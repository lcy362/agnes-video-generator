# 开发计划：创意视频 i2i 尾帧一致性优化

> **目标**：优化创意视频（CreativeVideoPipeline）的 i2i 尾帧生成路径，提升跨场景人物一致性与视觉连贯性。
> **范围**：仅创意视频 i2i 尾帧模式 + 图片模型统一升级。**不动**稿件流水线、简单视频、前端 UI。
> **依据**：官方文档 [agnes-image-21-flash](https://agnes-ai.com/doc/agnes-image-21-flash)（已核实）。
> **状态**：📋 待开发 | **创建日期**：2026-06-18

---

## 一、背景与依据

### 1.1 官方文档核实结论

抓取官方文档 `agnes-image-21-flash` 确认以下关键事实（**与项目内置 skill 文档矛盾，以官方为准**）：

| 事实 | 官方依据 |
|------|---------|
| `agnes-image-2.1-flash` **同时支持 t2i 与 i2i** | "supporting both text-to-image and image-to-image workflows" |
| i2i 模型名与 t2i **相同**，均为 `agnes-image-2.1-flash` | "Use the following model name for both text-to-image and image-to-image workflows" |
| i2i 参考图用 **`image` 数组** 形式（`extra_body.image=[url]`） | 文档全部 3 个 i2i curl 示例均为数组 |
| i2i 具备 **Composition Preservation**（构图保持） | "Preserve the original composition when editing or transforming input images" |
| i2i **不需要** `tags:["img2img"]` | 文档明确说明 |
| 2.1 专门优化**高信息密度图像** | 适合复杂尾帧场景 |

> ⚠️ **更正记录**：项目内置 `agnes-image-gen` skill 文档（`SKILL.md:39-40`）称 "2.1 仅 t2i、2.0 才是 i2i"，该说法**过时/错误**。当前代码 `core/api/agnes_image.py:37-40` 基于该错误说法做了 t2i/i2i 分模型，本轮一并修正。

### 1.2 当前实现的 i2i 尾帧数据流

```
角色参考图 (character_reference.png)
  ├─ Step 2 _step_character_reference (creative_video.py:207)
  │    └─ t2i 生成，来自 extract_character_description（中立站姿全身/四分之三）
  │       或用户上传 reference_image
  │
  └─ Step 3.6 _step_pregenerate_end_frames (creative_video.py:383)
       └─ generate_end_frames_from_ref=True 分支 (creative_video.py:471)
            └─ image_generator.generate_single_image(
                  prompt=end_frame_prompt,                    # 含角色外观硬块
                  reference_image_paths=[character_ref_path], # ← 唯一参考图
                  size=f"{vw}x{vh}",
               )
  ↓
  Step 4 _generate_keyframe_scenes (creative_video.py:863)
  └─ [本场景首帧, 本场景尾帧] → submit_video (keyframes 模式)
     其中"本场景首帧" = 上一场景尾帧（链式衔接，creative_video.py:967）
```

### 1.3 当前实现的问题清单

| # | 问题 | 位置 | 严重度 |
|---|------|------|--------|
| ① | i2i 用 `agnes-image-2.0-flash` 而非官方推荐的 2.1 | `agnes_image.py:40` | 🔴 P0 |
| ② | i2i 单图传字符串而非数组，与官方示例不一致 | `agnes_image.py:81-82` | 🔴 P0 |
| ③ | 角色参考图进 i2i 前未规范化尺寸，横构图→竖屏会拉伸变形 | `creative_video.py:471-475` | 🔴 P0 |
| ④ | 尾帧 prompt 角色外观靠 LLM "软约束"输出，不保证逐字 | `screenwriter.py:282-289` | 🔴 P0 |
| ⑤ | 角色外观文本仅内存传递，断点续传后丢失 | `creative_video.py:358-360` | 🟠 P1 |
| ⑥ | 每场景尾帧只引用角色图，场景间无视觉记忆（环境/风格跳脱） | `creative_video.py:471-475` | 🟠 P1 |
| ⑦ | keyframes 兜底分支用纯 t2i（`creative_video.py:948-951`），未升级模型/未引用角色图 | `creative_video.py:948-951` | 🟡 P1 |

### 1.4 关于 seed 的说明（不做）

经论证：`seed` 只对**完全相同 prompt + 相同参数**的复现有效，对**跨场景不同 prompt** 的锁脸基本无效（人脸身份由 prompt/参考图的 cross-attention 决定，非初始噪声）。本轮**不引入 seed 锁脸**。真正的人物一致性抓手是**参考图（i2i/keyframes）+ prompt 中的角色外观硬约束**。

### 1.5 关于 i2i 失败降级的说明（不做）

按决策要求，i2i 失败**不降级**为 t2i。3 次重试失败后保持现有 `raise` 行为（`creative_video.py:489-490`），让流水线明确报错而非静默产出角色不一致的尾帧。

---

## 二、改动方案

### 改动 1：图片 API 模型统一为 2.1 + 参数规范化（P0）

**文件**：`core/api/agnes_image.py`

**改动点**：
- 删除 `self.i2i_model = "agnes-image-2.0-flash"`（`:40`），t2i 与 i2i 统一用 `self.model = "agnes-image-2.1-flash"`。
- 删除 `generate_single_image` 中按 `use_i2i` 切换模型的逻辑（`:69-70`）。
- i2i 参考图**统一用数组**形式：`extra_body["image"] = resolved`（始终 list，单图也传 `[url]`），与官方文档示例一致（`:81-84`）。
- 保留 `response_format: "url"`、`n:1` 不变。

**回退能力**：在 `__init__` 增加可选参数 `i2i_model: str = "agnes-image-2.1-flash"`，允许通过环境变量回退到 2.0（若实测 2.1 i2i 质量不佳）。默认 2.1。

**兼容性**：`reference_image_paths=[]` 时仍走纯 t2i，行为不变。

### 改动 2：i2i 调用前规范化角色参考图尺寸（P0）

**文件**：`core/pipelines/creative_video.py`

**评估结论**：走 **ffmpeg 预处理**而非依赖 i2i 模型自适应。理由：
- i2i 的"构图保持"是双刃剑：用户上传横构图参考图要生成竖屏尾帧时，"保持原图构图"会硬塞横构图进竖屏，角色被压扁/裁切。我们要的是"角色身份保持 + 构图适配竖屏"，二者部分冲突。
- ffmpeg pad 是确定性的：保证输入严格等于目标尺寸，黑边填充，构图不被模型二次扭曲。i2i 模型只专注身份保持。

**改动点**：
- 新增辅助方法 `_normalize_image_to_size(src_path, vw, vh) -> str`，用 `scale=vw:vh:force_original_aspect_ratio=decrease,pad=vw:vh:(ow-iw)/2:(oh-ih)/2` 滤镜（复用 `creative_video.py:441` 现有滤镜），输出到 `working_dir/character_ref_normalized.png`。
- 在 i2i 尾帧调用（`:471-475`）前，先对 `character_ref_path` 规范化，传 normalized 路径。
- 用户上传参考图（`_step_character_reference` `:227-236` 分支）也走规范化。
- 缓存：normalized 图按 `{character_ref_path 的 mtime}+{vw}x{vh}` 命名，避免重复生成。

### 改动 3：优化 prompt 结构（P0）

**文件**：`core/screenwriter.py`、`core/pipelines/creative_video.py`

**改动点**：
- `extract_character_description`（`screenwriter.py:209-250`）：保持中立站姿全身/四分之三视角，**补充"清晰正面面部、无遮挡、光照均匀"**要求，使其成为更强的 i2i 身份锚点。
- `generate_end_frame_prompts`（`screenwriter.py:278-332`）：尾帧 prompt 采用 i2i 友好结构，明确分离：
  - **[PRESERVE]**：角色外观逐字块（hair/face/clothing/shoes），"keep the same person, same face, same clothing, do NOT alter identity"
  - **[CHANGE]**：场景末帧的环境/姿势/光影/构图/情绪
- i2i 调用时，prompt 由"角色外观硬块 + 场景尾帧描述"**程序化拼合**（见改动 4），而非完全依赖 LLM 输出。

### 改动 4：角色外观文本持久化 + 程序化拼入（P1）

**文件**：`models/task.py`、`core/pipelines/creative_video.py`

**改动点**：
- `CreativeVideoTask`（`models/task.py:166` 附近）新增字段 `character_appearance: str = ""`。
- `creative_video.py:358-360`（`get_character_appearance` 调用处）把结果写入 task state（`task_manager.update_state(character_appearance=...)`）。
- i2i 尾帧调用前（`creative_video.py:462-466` 取 prompt 处），程序化把 `self._state.character_appearance` 作为 `[PRESERVE]` 段拼到 `end_frame_prompt` 前：
  ```
  [PRESERVE — keep exactly]
  {character_appearance}
  Keep the same person, same face, same clothing. Do NOT alter identity.

  [CHANGE — end frame of this scene]
  {end_frame_prompt}
  ```
- 断点续传兼容：`character_appearance` 有默认空串，Pydantic v2 自动处理旧数据。

### 改动 5：i2i 尾帧多图引导实现场景间视觉链（P1）

**文件**：`core/pipelines/creative_video.py`

**改动点**：
- `_step_pregenerate_end_frames` i2i 调用（`:471-475`）的 `reference_image_paths`，从 `[character_ref_normalized]` 改为：
  - 第一个场景：`[character_ref_normalized]`
  - 后续场景：`[character_ref_normalized, prev_scene_end_frame]`
- 利用 2.1 多图 i2i：角色图锁人脸 + 上一场景尾帧锁环境/风格/镜头延续。
- `prev_scene_end_frame` 取自已生成的 `pregenerated[scene_idx-1]`，需保证按序生成（`_step_pregenerate_end_frames` 循环天然按序，`prev` 在循环内可维护）。
- **回退保护**：多图 i2i 若实测报错或无改善，保留单图分支（`[character_ref_normalized]`）作为可配置项。

### 改动 6：keyframes 兜底分支同步升级（P1）

**文件**：`core/pipelines/creative_video.py:948-951`

**改动点**：
- `_generate_keyframe_scenes` 中尾帧缺失的兜底生成（当前纯 t2i），改为与 Step 3.6 一致策略：
  - 默认走 i2i（引用规范化角色图 + 改动 4 的拼合 prompt）
  - 模型随改动 1 统一为 2.1
- 保证两条尾帧生成路径（Step 3.6 预生成 / Step 4 兜底）行为一致。

---

## 三、不做的事（明确边界）

- ❌ 不引入 seed 锁脸（已论证无效）。
- ❌ i2i 失败**不降级**为 t2i（按决策保持 raise）。
- ❌ 不动稿件流水线 `manuscript_video.py`。
- ❌ 不动简单视频 `simple_video.py`。
- ❌ 不动前端 UI（所有改动用默认行为，无需新增开关）。

---

## 四、实施顺序与验证

### 4.1 实施顺序（按依赖关系）

| 阶段 | 改动 | 依赖 |
|------|------|------|
| 1 | 改动 1（agnes_image.py 模型统一 + 数组化） | 无 |
| 2 | 改动 2（尺寸规范化辅助方法） | 改动 1 |
| 3 | 改动 4（task 字段 + 持久化 + 程序化拼 prompt） | 无 |
| 4 | 改动 3（prompt 结构优化） | 改动 4（复用 character_appearance） |
| 5 | 改动 5（多图 i2i 视觉链） | 改动 1/2/4 |
| 6 | 改动 6（兜底分支同步） | 改动 1/2/3/4 |

### 4.2 验证清单（按 AGENTS.md §0.4）

**第一层：静态分析**
```bash
.venv/bin/python -m py_compile core/api/agnes_image.py
.venv/bin/python -m py_compile core/pipelines/creative_video.py
.venv/bin/python -m py_compile core/screenwriter.py
.venv/bin/python -m py_compile models/task.py
.venv/bin/python -c "from core.api.agnes_image import AgnesImageAPI; print('OK')"
```

**第二层：单元验证**
- i2i payload 构造：模型 = `agnes-image-2.1-flash`、`extra_body.image` 为 list（单图也 `[url]`）。
- `_normalize_image_to_size` 滤镜调用（mock ffmpeg 验证命令构造）。
- `character_appearance` 字段持久化与断点续传读取（无该字段的旧 task state 能正常加载）。
- prompt 程序化拼合：`[PRESERVE] + [CHANGE]` 结构正确。

**第三层：端点验证**
```bash
# 创意任务走 i2i 尾帧路径
curl -X POST http://localhost:8765/api/tasks/creative \
  -H "Content-Type: application/json" \
  -d '{"idea":"太空探险","chaining_mode":"keyframes","generate_end_frames_from_ref":true}'
```
肉眼确认：① 模型切换无报错；② 角色图规范化后 i2i 输出无拉伸；③ 跨场景人物一致性。

### 4.3 实测对照（可选，建议）

改动 5（多图 i2i）有不确定性，建议实测对照：
- 同一 story，分别用单图 `[角色图]` vs 多图 `[角色图, 上一尾帧]` 各生成一组尾帧，肉眼对比场景连贯度。
- 若多图无改善或报错，回退单图。

---

## 五、开发待办批次清单

> **执行规则**：每次执行一小批次（一个批次 = 下表中的一行），完成后停下汇报，**经用户确认后再继续下一批次**。
> 状态标记：`⬜ 待办` / `🔄 进行中` / `✅ 完成` / `⏸ 已暂停`

### 批次 1 — 图片 API 模型统一（改动 1，P0）

- [x] **状态**：✅ 完成（2026-06-18）
- [ ] **文件**：`core/api/agnes_image.py`
- [ ] **内容**：
  - t2i / i2i 统一模型 `agnes-image-2.1-flash`，删除 `self.i2i_model = "2.0-flash"` 与切换逻辑
  - i2i 参考图统一用数组形式（`extra_body.image` 始终 list，单图传 `[url]`）
  - `__init__` 增加可配置 `i2i_model`（环境变量回退用，默认 2.1）
- [ ] **验证**：py_compile + import OK + i2i payload 单测（模型名、image 数组化）
- [ ] **风险**：2.1 i2i 质量未实测 → 保留环境变量回退

### 批次 2 — 角色参考图尺寸规范化（改动 2，P0）

- [ ] **状态**：⬜ 待办
- [ ] **依赖**：批次 1 完成
- [ ] **文件**：`core/pipelines/creative_video.py`
- [ ] **内容**：
  - 新增 `_normalize_image_to_size(src, vw, vh) -> str`，用 scale+pad 滤镜（复用 `:441` 现有滤镜）
  - i2i 尾帧调用前（`:471-475`）对 `character_ref_path` 规范化
  - 用户上传参考图（`_step_character_reference` `:227-236`）同样规范化
  - normalized 图缓存（按 mtime + 尺寸命名）
- [ ] **验证**：py_compile + 滤镜命令构造单测（mock ffmpeg）

### 批次 3 — 角色外观持久化 + 程序化拼入（改动 4，P1）

- [ ] **状态**：⬜ 待办
- [ ] **依赖**：无（可与批次 2 并行，但建议批次 2 先行）
- [ ] **文件**：`models/task.py`、`core/pipelines/creative_video.py`
- [ ] **内容**：
  - `CreativeVideoTask` 新增字段 `character_appearance: str = ""`
  - `creative_video.py:358-360` 落盘到 task state（`update_state`）
  - i2i 尾帧调用前程序化拼 prompt：`[PRESERVE] 角色外观 + [CHANGE] 尾帧描述`
- [ ] **验证**：py_compile + 旧 task state 兼容性（无字段可加载）+ prompt 拼合单测

### 批次 4 — Prompt 结构优化（改动 3，P0）

- [ ] **状态**：⬜ 待办
- [ ] **依赖**：批次 3 完成（复用 character_appearance）
- [ ] **文件**：`core/screenwriter.py`
- [ ] **内容**：
  - `extract_character_description`：补充"清晰正面面部、无遮挡、光照均匀"
  - `generate_end_frame_prompts`：`[PRESERVE]`/`[CHANGE]` 分离结构
- [ ] **验证**：py_compile + prompt 结构单测

### 批次 5 — i2i 尾帧多图引导（改动 5，P1）

- [ ] **状态**：⬜ 待办
- [ ] **依赖**：批次 1/2/4 完成
- [ ] **文件**：`core/pipelines/creative_video.py`
- [ ] **内容**：
  - i2i 调用 `reference_image_paths` 改为 `[角色图规范化, 上一场景尾帧]`（首场景仅 `[角色图]`）
  - 按序维护 `prev_scene_end_frame`
  - 保留单图回退分支（可配置）
- [ ] **验证**：py_compile + 端点验证 + **实测对照**（单图 vs 多图肉眼对比连贯度）
- [ ] **风险**：多图支持不确定 → 实测后定默认值

### 批次 6 — keyframes 兜底分支同步（改动 6，P1）

- [ ] **状态**：⬜ 待办
- [ ] **依赖**：批次 1/2/3/4 完成
- [ ] **文件**：`core/pipelines/creative_video.py:948-951`
- [ ] **内容**：
  - 兜底尾帧生成从纯 t2i 改为与 Step 3.6 一致（i2i + 规范化角色图 + 拼合 prompt）
  - 保证两条尾帧路径行为一致
- [ ] **验证**：py_compile + 端点验证（keyframes 模式走通兜底分支）

### 批次汇总

| 批次 | 改动 | 优先级 | 依赖 | 状态 |
|------|------|--------|------|------|
| 1 | 图片 API 模型统一 + 数组化 | P0 | 无 | ✅ |
| 2 | 角色图尺寸规范化 | P0 | 1 | ⬜ |
| 3 | 角色外观持久化 + 程序化拼 prompt | P1 | 无 | ⬜ |
| 4 | Prompt 结构优化 | P0 | 3 | ⬜ |
| 5 | i2i 尾帧多图引导 | P1 | 1/2/4 | ⬜ |
| 6 | keyframes 兜底分支同步 | P1 | 1/2/3/4 | ⬜ |

**进度**：1 / 6 批次完成

---

## 六、风险与回退

| 风险 | 应对 |
|------|------|
| 2.1 的 i2i 实际质量不如 2.0 | 改动 1 保留 `i2i_model` 可配置项（环境变量），可快速回退 2.0 |
| 多图 i2i（改动 5）Agnes 支持有限 | 保留单图回退分支，实测后定默认值 |
| 角色 appearance 字段破坏旧 task state | Pydantic v2 默认空串，向后兼容；`TaskManager.load()` 已有多态兼容机制 |
| ffmpeg 规范化在大尺寸图上耗时 | normalized 图缓存，单角色图只生成一次 |

---

## 七、涉及文件清单

| 文件 | 改动类型 |
|------|---------|
| `core/api/agnes_image.py` | 修改（改动 1） |
| `core/pipelines/creative_video.py` | 修改（改动 2/4/5/6） |
| `core/screenwriter.py` | 修改（改动 3） |
| `models/task.py` | 修改（改动 4，新增字段） |
| `docs/i2i_endframe_optimization_plan.md` | 新增（本文档） |

---

## 八、与决策记录的对应（AGENTS.md §十）

新增决策建议（待评审写入 AGENTS.md）：

| ID | 决策 | 详情 |
|----|------|------|
| D12 | 图片模型统一 | t2i 与 i2i 均用 `agnes-image-2.1-flash`（官方确认同时支持） |
| D13 | i2i 参考图规范化尺寸 | ffmpeg pad 到 vw×vh，避免构图拉伸；i2i 专注身份保持 |
| D14 | 角色外观持久化 | `character_appearance` 存入 task state，支持断点续传一致性 |
| D15 | i2i 尾帧多图引导 | `[角色图, 上一场景尾帧]` 实现场景间视觉链（可回退单图） |

---

*文档版本：v1.1 | 创建日期：2026-06-18 | 状态：📋 待开发（批次化执行，每批次经用户确认后继续）| 进度：0/6 批次*
