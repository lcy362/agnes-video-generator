## 三项功能方案与实施计划

基于对现有代码结构的完整分析，以下是三项功能的设计方案。

---

### 一、拆分字幕和旁白配置

**现状问题：** 当前 `AudioConfig` 将 `subtitle_style` 嵌套在内部，字幕和旁白强耦合——关闭旁白就无法使用字幕，开启旁白就必定生成字幕。两者无法独立控制。

**方案概述：** 将 `SubtitleConfig` 提升为与 `AudioConfig` 平级的独立配置，各自拥有 `enabled` 开关，Pipeline 中拆分为独立步骤。

#### 1.1 数据模型变更（models/task.py）

新增 `SubtitleConfig`：

```python
class SubtitleConfig(BaseModel):
    enabled: bool = True
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)

class AudioConfig(BaseModel):
    enabled: bool = True
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    # 移除 subtitle_style 字段
```

`CreativeVideoTask` 和 `ManuscriptVideoTask` 新增独立字段：

```python
audio_config: AudioConfig = Field(default_factory=AudioConfig)
subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)
```

向后兼容：`TaskManager.load()` 反序列化时，如果旧数据有 `audio_config.subtitle_style` 但无 `subtitle_config`，自动迁移——将嵌套的 `subtitle_style` 提取为独立的 `SubtitleConfig`。

#### 1.2 Pipeline 变更

创意视频（creative_video.py）和稿件视频（manuscript_video.py）的 `_step_audio_subtitle` 拆分为两个独立步骤：

- `_step_audio`：仅负责 TTS 生成（旁白音频 + SubMaker cues），受 `audio_config.enabled` 控制
- `_step_subtitle`：仅负责 SRT 生成，受 `subtitle_config.enabled` 控制

两种情况的 SRT 来源：

- 旁白开启 + 字幕开启：从 TTS 的 SubMaker cues 生成 SRT（现有逻辑）
- 旁白关闭 + 字幕开启：需要独立的字幕文本来源——创意视频从各 scene 的旁白文本拼接，稿件视频直接用原文。此时用 `SilentTTSEngine` 生成静音音频，字幕文本单独提供给 `SubtitleGenerator`（需新增一个从纯文本生成 SRT 的方法，不依赖 SubMaker cues）
- 旁白开启 + 字幕关闭：生成音频但不生成 SRT，拼接时 `srt_path=None`
- 旁白关闭 + 字幕关闭：静音 + 无字幕

`_step_concatenate` 逻辑调整：判断条件从 `audio_config.enabled` 改为 `audio_config.enabled or subtitle_config.enabled`——只要有音频或字幕就需要走 `concat_videos_with_audio_overlay`。

#### 1.3 API 端点变更（server.py）

创意视频和稿件视频的创建端点新增参数：

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `subtitle_enabled` | `bool` | `True` | 是否启用字幕 |

`audio_enabled` 和 `subtitle_enabled` 独立控制。构建时分别创建 `AudioConfig` 和 `SubtitleConfig`。

#### 1.4 前端变更（static/index.html）

在音频配置折叠面板内，将字幕相关控件（字体、颜色、字号、位置、描边等）拆分为独立的"字幕设置"区域，增加 `subtitle_enabled` 复选框。当取消勾选"启用字幕"时，字幕设置区域灰化；取消勾选"启用旁白"时，语音角色和语速灰化。两者互不影响。

i18n 新增 key：`subtitleEnabled` / `audioEnabled` 等。

---

### 二、字幕 LLM 智能样式模式

**现状问题：** 当前所有字幕共用一个全局样式（位置、颜色、字号均固定），无法为每条字幕单独定制外观。

**方案概述：** 新增 `style_mode` 字段支持 `"fixed"`（默认）和 `"llm"` 两种模式。`"llm"` 模式下，由 LLM 为每条字幕单独决定 **位置、颜色、字号**，SRT 文件扩展携带样式信息，拼接时逐条渲染。用户可通过自然语言提示（`style_hints`）描述期望的风格，如"强调词用红色大字号，摘要用黄色，其余用白色小字放在底部"。

#### 2.1 数据模型变更（models/task.py）

```python
class SubtitleStyle(BaseModel):
    # === 固定模式下使用的全局默认值 ===
    font: str = "STHeitiMedium.ttc"
    color: str = "white"
    position: tuple = ("center", "bottom-80")
    fontsize: int = 48
    stroke_color: str = "black"
    stroke_width: int = 2
    bg_color: tuple = (0, 0, 0, 128)

    # === LLM 模式控制 ===
    style_mode: str = "fixed"      # "fixed" | "llm"
    style_hints: str = ""           # 用户对 LLM 的样式偏好描述
```

#### 2.2 SRT 侧车 JSON 格式扩展

采用 **SRT + 侧车 JSON** 双文件方案，JSON 文件名改为 `subtitle_styles.json`（原 `subtitle_positions.json`）：

```json
[
  {
    "index": 1,
    "position": ["center", "top+100"],
    "color": "#FF4444",
    "fontsize": 56
  },
  {
    "index": 2,
    "position": ["center", "bottom-120"],
    "color": "white",
    "fontsize": 42
  },
  {
    "index": 3,
    "position": ["left+40", "bottom-200"],
    "color": "#FFD700",
    "fontsize": 48
  }
]
```

字段说明：

- `position`：必填。格式同现有 `("horizontal", "vertical")`，支持 `"center"`, `"left+N"`, `"right+N"`, `"top+N"`, `"bottom-N"`
- `color`：可选。未指定时回退到 `SubtitleStyle.color` 全局值。支持颜色名和 hex
- `fontsize`：可选。未指定时回退到 `SubtitleStyle.fontsize` 全局值。范围 18-80

后续可扩展 `stroke_color`、`bg_color` 等字段，当前聚焦核心三要素。

#### 2.3 LLM 样式决策（core/screenwriter.py）

新增方法 `generate_subtitle_styles`（替代原 `generate_subtitle_positions`）：

```python
async def generate_subtitle_styles(
    srt_path: str,
    video_width: int,
    video_height: int,
    style_hints: str = "",
) -> list[dict]
```

输入：SRT 文件中的每条字幕文本 + 时间码 + 视频尺寸 + 用户样式偏好。

LLM Prompt 设计要点：

- 提供视频尺寸和可用区域（四边各留 40px 安全边距）
- 列出所有字幕条目（序号、起止时间、文本内容）
- 要求 LLM 为每条字幕决定：位置、颜色（colorname 或 #RRGGBB）、字号（像素）
- 位置格式：`["horizontal", "vertical"]`，支持 `"center"`, `"left+N"`, `"right+N"`, `"top+N"`, `"bottom-N"`
- 设计规则（写入 prompt 约束）：
  - 相邻时间段的字幕位置应有所变化，避免视觉单调
  - 语义转折或新话题的字幕可换位置、换色
  - 强调性/结论性内容用较大字号和醒目色（如红、金）
  - 颜色与视频背景保持足够对比度，确保可读性
  - 用户 `style_hints` 中的偏好作为最强约束
- JSON mode 输出，确保可解析

限速：此方法调用 Chat API，共享全局 rate_limiter。单次调用覆盖所有字幕条目。

#### 2.4 拼接层变更（core/compositor/concatenator.py）

`concat_videos_with_audio_overlay` 新增可选参数：

```python
subtitle_styles: Optional[str] = None  # styles JSON 路径（取代原 subtitle_positions）
```

`_parse_srt_to_clips` 修改：当 `subtitle_styles` 存在时，逐条读取 JSON，以全局 `SubtitleStyle` 为底，用 JSON 中的字段覆盖 `position`、`color`、`fontsize`，每条字幕独立创建 TextClip。未在 JSON 中出现的字段沿用全局值。

#### 2.5 Pipeline 变更

在 `_step_subtitle` 步骤中，当 `style_mode == "llm"` 时：

1. 先生成标准 SRT（现有逻辑）
2. 调用 `screenwriter.generate_subtitle_styles(srt_path, width, height, hints)` 生成样式 JSON
3. 将样式 JSON 路径存入 task state

在 `_step_concatenate` 中传递 `subtitle_styles` 参数。

#### 2.6 前端变更

字幕位置上方的控件改为样式模式选择：

```
样式模式: [固定样式 ▼]  /  [AI 智能样式 ▼]
```

- 选固定样式时：下方显示原有的位置下拉、颜色、字号等全局控件
- 选 AI 智能样式时：这些控件隐藏（或灰化作为默认值参考），改为显示一个 `style_hints` 多行文本框，placeholder 示例："强调词用红色大号字，普通叙述白色小字放底部。字幕避免遮挡画面中央。变化位置不要太频繁。"

i18n 新增 key：`subStyleMode`, `subStyleFixed`, `subStyleLLM`, `subStyleHints`, `subStyleHintsPlaceholder`。

---

### 三、数字人口播类型

**方案概述：** 新增第四种任务类型 `anchor`（数字人口播）。用户提供主播形象 prompt 和口播稿件，系统生成主播形象图片，以图片为视觉主体，配合 TTS 读稿音频和字幕，合成最终视频。

#### 3.1 任务模型（models/task.py）

新增 `AnchorVideoTask`：

```python
class AnchorVideoTask(BaseTaskState):
    task_type: Literal["anchor"] = "anchor"
    
    # 用户输入
    anchor_prompt: str = ""          # 主播形象描述 prompt
    anchor_reference_image: str = "" # 可选：用户上传的参考图（URL 或本地路径）
    script_text: str = ""            # 口播稿件
    subtitle_position_hints: str = "" # 字幕位置要求（单独输入框）
    
    # 配置
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    subtitle_config: SubtitleConfig = Field(default_factory=SubtitleConfig)
    
    # 步骤状态
    step_generate_anchor: StepStatus = StepStatus.PENDING   # 生成主播形象图
    step_generate_clip: StepStatus = StepStatus.PENDING     # i2v 生成动态视频片段
    step_generate_audio: StepStatus = StepStatus.PENDING    # TTS 读稿
    step_generate_subtitle: StepStatus = StepStatus.PENDING # 字幕 + LLM 定位
    step_composite: StepStatus = StepStatus.PENDING         # 循环拼接 + 叠加音视频字幕
    
    # 产物
    anchor_image_url: str = ""       # 生成的主播形象图 URL
    anchor_image_path: str = ""      # 本地路径
    anchor_clip_url: str = ""        # i2v 生成的动态视频片段 URL
    anchor_clip_path: str = ""       # 本地路径（约 5 秒）
    audio_path: str = ""
    srt_path: str = ""
    styles_path: str = ""            # LLM 生成的字幕样式（位置+颜色+字号）
    final_video_path: str = ""
```

`TaskType` 枚举新增 `"anchor"`。`parse_task_state` 多态反序列化新增 `anchor` 分支。

#### 3.2 默认配置（core/config.py）

```python
DEFAULT_ANCHOR_CONFIG = {
    "anchor_prompt": "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中，面带微笑，正面半身照，高清画质，专业灯光",
    "audio_voice": "zh-CN-XiaoxiaoNeural",
    "audio_rate": "+0%",
    "subtitle_enabled": True,
    "subtitle_font": "STHeitiMedium.ttc",
    "subtitle_fontsize": 42,
    "subtitle_color": "white",
    "subtitle_stroke_color": "black",
    "subtitle_stroke_width": 2,
    "video_width": 768,
    "video_height": 1344,     # 竖屏 9:16
    "video_duration": 5,      # 单段视频时长（秒）
}
```

#### 3.3 Pipeline（core/pipelines/anchor_video.py）

新增 `AnchorPipeline`，继承 `BasePipeline`。流程分五步：

**Step 1: `_step_generate_anchor`** — 生成主播形象图

两条分支，取决于用户是否上传了参考图：

- **无参考图**：调用 `AgnesImageAPI.text_to_image(anchor_prompt, size="768x1152")` 纯文本生成
- **有参考图**：调用 `AgnesImageAPI.image_to_image(reference_image, anchor_prompt, size="768x1152")` 以参考图为基底 + prompt 微调风格

下载图片到本地 `output/{task_id}/anchor.png`。状态更新 + WS 推送。

**Step 2: `_step_generate_clip`** — i2v 生成动态视频片段

这是唯一的视频模型调用。以主播形象图为输入，通过 i2v（图生视频）生成一段约 5 秒的动态视频：

- 调用 `AgnesVideoAPI.image_to_video(anchor_image_path, prompt=clip_prompt, duration=5)`
- `clip_prompt` 由 LLM 根据 `anchor_prompt` 生成，描述主播的自然动态（如"主播面向镜头微笑，偶尔轻微点头，背景灯光柔和"），避免出现大幅运动以利于循环拼接
- 轮询等待视频生成完成（复用现有轮询 + 限速逻辑）
- 下载视频到本地 `output/{task_id}/anchor_clip.mp4`

**API 调用总量：1 次图片 API + 1 次视频 API**，不随稿件长度增长。

**Step 3: `_step_generate_audio`** — TTS 读稿

- 将 `script_text` 整体送入 `EdgeTTSEngine.generate()`，生成读稿音频 + SubMaker cues
- 失败降级到 `SilentTTSEngine`
- 音频时长决定最终视频时长

**Step 4: `_step_generate_subtitle`** — 字幕生成 + LLM 定位

- 从 SubMaker cues 生成 SRT（复用 `SubtitleGenerator.cues_to_srt`）
- 用户在 `subtitle_position_hints` 中描述字幕位置要求（如"字幕放在主播下方，不遮挡人脸"）
- LLM 调用 `screenwriter.generate_subtitle_styles`（复用功能二的 LLM 样式决策），Prompt 特殊设计：
  - 告知 LLM 这是数字人口播场景，画面主体是主播形象
  - 提供主播图片的大致构图描述（半身照/全身照等，可从 anchor_prompt 推断）
  - 用户的位置偏好作为约束
  - 输出逐条字幕位置 JSON

**Step 5: `_step_composite`** — 循环拼接 + 叠加音视频字幕

核心思路：将 5 秒动态视频片段循环拼接至覆盖完整音频时长，再叠加音频和字幕。

```python
@staticmethod
def composite_anchor_video(
    clip_path: str,            # 5 秒主播动态视频
    audio_path: str,           # TTS 读稿音频
    srt_path: Optional[str],   # 字幕 SRT
    subtitle_styles: Optional[str],   # LLM 样式 JSON（位置+颜色+字号）
    output_path: str,
    audio_duration: float,     # 音频总时长
    subtitle_style: Optional[SubtitleStyle] = None,
) -> str
```

实现流程：

1. 读取 `clip_path` 获取片段时长 `clip_duration`
2. 计算循环次数 `n = ceil(audio_duration / clip_duration) + 1`
3. 构建 `[clip_path] * n` 传入 `VideoConcatenator.concat_videos()` 拼接为足够长的循环视频
4. 裁剪循环视频至 `audio_duration + 1.0` 秒（留 1 秒 padding）
5. 叠加 TTS 音频（音量 2.5x 放大，与其他任务类型一致）
6. 若有字幕，解析 SRT + styles JSON，逐条叠加 TextClip（复用功能二的逐条样式渲染逻辑）
7. 输出最终视频

循环拼接的接缝处理：由于 i2v 生成的主播视频动作幅度小（微表情、呼吸），首尾帧差异不大，直接拼接视觉上可接受。若需更平滑，可用 ffmpeg 的 `xfade` 滤镜做 0.3 秒交叉淡入淡出过渡。

#### 3.4 API 端点（server.py）

新增 `POST /api/tasks/anchor`：

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `anchor_prompt` | `str` | 系统默认 prompt | 主播形象描述 |
| `anchor_reference_image` | `str` | `""` | 可选：参考图 URL（有则走 i2i，无则走 t2i） |
| `script_text` | `str` | **必填** | 口播稿件 |
| `subtitle_position_hints` | `str` | `""` | 字幕位置要求 |
| `audio_voice` | `str` | `"zh-CN-XiaoxiaoNeural"` | 语音角色 |
| `audio_rate` | `str` | `"+0%"` | 语速 |
| `subtitle_enabled` | `bool` | `True` | 是否启用字幕 |
| `subtitle_*` | 各种 | 同默认配置 | 字幕样式参数 |

返回 `{"ok": true, "task_id": "...", "task_type": "anchor"}`。

任务列表 `GET /api/tasks` 已支持多态，无需额外修改。`GET /api/tasks/{id}` 返回 `task_type: "anchor"`。

#### 3.5 前端变更（static/index.html）

新增第四个 Tab："数字人口播"（anchor）。

UI 布局：

```
┌─────────────────────────────────────────┐
│  [简单视频] [创意视频] [稿件视频] [数字人口播] │
├─────────────────────────────────────────┤
│ 主播形象描述 (textarea, 预填默认值)       │
│ ┌─────────────────────────────────────┐ │
│ │ 一位专业的新闻主播，穿着正式西装...   │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ 参考图 (可选, 文件上传 + 预览)            │
│ ┌──────┐                                │
│ │ 📷   │  上传后可预览，不传则纯 AI 生成  │
│ │ +    │                                │
│ └──────┘                                │
│                                         │
│ 口播稿件 (textarea, 必填)                │
│ ┌─────────────────────────────────────┐ │
│ │                                     │ │
│ │                                     │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ▸ 音频设置                              │
│   ☑ 启用旁白  语音角色: [Xiaoxiao ▼]    │
│                                         │
│ ▸ 字幕设置                              │
│   ☑ 启用字幕  位置: [AI智能定位 ▼]      │
│                                         │
│ 字幕位置要求 (textarea, AI定位时显示)    │
│ ┌─────────────────────────────────────┐ │
│ │ 字幕放在画面下方三分之一区域，         │ │
│ │ 不要遮挡主播面部                     │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ [开始生成]                              │
└─────────────────────────────────────────┘
```

参考图上传交互：用户选择文件后，前端将图片通过 `POST /api/upload` 上传（复用现有 `utils/image.py` 的上传逻辑，如已有则直接复用），返回 URL 填入 `anchor_reference_image` 字段。上传后在控件旁显示缩略图预览，支持点击删除重新选择。

进度步骤显示：

```
1. 生成主播形象    ●○○○○
2. 生成动态片段    ○○○○○
3. 语音合成        ○○○○○
4. 字幕生成        ○○○○○
5. 视频合成        ○○○○○
```

i18n 新增 key（7 语言）：`tabAnchor`, `anchorPrompt`, `anchorPromptPlaceholder`, `anchorRefImage`, `anchorRefImageHint`, `scriptText`, `scriptTextPlaceholder`, `subPositionHints`, `subPositionHintsPlaceholder`, `aStepGenerateAnchor`, `aStepGenerateClip`, `aStepAudio`, `aStepSubtitle`, `aStepComposite`。

---

### 四、实施顺序与依赖关系

```
Phase 1: 拆分字幕和旁白（基础设施）
  ├── 1.1 models/task.py: SubtitleConfig + 向后兼容
  ├── 1.2 core/config.py: 默认配置调整
  ├── 1.3 server.py: 端点参数拆分
  ├── 1.4 creative_video.py: 步骤拆分
  ├── 1.5 manuscript_video.py: 步骤拆分
  ├── 1.6 concatenator.py: 条件判断调整
  ├── 1.7 task_manager.py: 反序列化兼容
  └── 1.8 static/index.html: UI 拆分

Phase 2: 字幕随机位置（依赖 Phase 1 的 SubtitleConfig）
  ├── 2.1 models/task.py: position_mode + position_hints
  ├── 2.2 core/screenwriter.py: generate_subtitle_positions
  ├── 2.3 concatenator.py: 逐条位置支持
  ├── 2.4 creative_video.py: LLM 位置步骤
  ├── 2.5 manuscript_video.py: LLM 位置步骤
  └── 2.6 static/index.html: "AI智能定位"选项

Phase 3: 数字人口播（依赖 Phase 1 + 2）
  ├── 3.1 models/task.py: AnchorVideoTask + TaskType 枚举 + 参考图字段
  ├── 3.2 core/config.py: 默认主播配置
  ├── 3.3 core/pipelines/anchor_video.py: 新建 5 步 Pipeline（t2i/i2i + i2v + TTS + 字幕 + 合成）
  ├── 3.4 core/compositor/concatenator.py: composite_anchor_video（循环拼接 + 叠加）
  ├── 3.5 core/screenwriter.py: clip_prompt 生成 + 口播场景字幕定位 prompt
  ├── 3.6 server.py: /api/tasks/anchor 端点 + 图片上传接口
  ├── 3.7 task_manager.py: anchor 类型持久化
  └── 3.8 static/index.html: 第四 Tab + 参考图上传 + i18n
```

Phase 1 是基础设施，Phase 2 和 Phase 3 都依赖它。Phase 2 和 Phase 3 之间有弱依赖——数字人口播使用 LLM 定位功能，但可以先用 fixed 模式上线，后接入 LLM 定位。

### 五、涉及文件汇总

| 文件 | Phase 1 | Phase 2 | Phase 3 | 改动量 |
|------|---------|---------|---------|--------|
| `models/task.py` | 改 | 改 | 改 | 大 |
| `core/config.py` | 改 | — | 改 | 小 |
| `server.py` | 改 | — | 改 | 大 |
| `core/pipelines/creative_video.py` | 改 | 改 | — | 中 |
| `core/pipelines/manuscript_video.py` | 改 | 改 | — | 中 |
| `core/pipelines/anchor_video.py` | — | — | 新建 | 大 |
| `core/pipelines/__init__.py` | — | — | 改 | 小 |
| `core/compositor/concatenator.py` | 改 | 改 | 改 | 中 |
| `core/screenwriter.py` | — | 改 | 改 | 中 |
| `core/task_manager.py` | 改 | — | 改 | 小 |
| `core/audio/subtitle.py` | 改 | — | — | 小 |
| `static/index.html` | 改 | 改 | 改 | 大 |
| `docs/system_design.md` | — | — | 改 | 小 |
| `AGENTS.md` | — | — | 改 | 小 |

### 六、风险与注意事项

**内容审查风险：** 数字人口播的主播形象 prompt 可能触发 Agnes Image API 的内容审查（生成真人肖像有时会被拦截）。默认 prompt 应使用"虚拟主播"风格描述，避免真实人物特征。同时在 UI 提示中引导用户避免敏感描述。

**字幕位置 LLM 调用成本：** 每条字幕都需要 LLM 决策位置，但实际上是一次性调用（将所有字幕条目一次性发给 LLM），而非逐条调用。单次 Chat 调用即可完成，限速影响可控。

**向后兼容：** `AudioConfig` 移除 `subtitle_style` 字段是破坏性变更。`TaskManager.load()` 的反序列化需要做字段迁移——检测到旧格式时自动转换为新格式，并保留旧数据不删除。

**i2v 片段循环接缝：** 5 秒动态片段循环拼接时，首尾帧可能存在跳变。缓解策略：(1) i2v 的 clip_prompt 明确要求动作幅度小、起止姿态一致；(2) 拼接时使用 ffmpeg `xfade` 滤镜在接缝处做 0.3 秒交叉淡入淡出。实际效果需原型验证。

---

### 七、分批实施计划

> 进度标记：⬜ 待开始  🔄 进行中  ✅ 已完成  ⏸️ 暂停  ❌ 取消

#### Phase 1：拆分字幕和旁白配置

| 批次 | 内容 | 涉及文件 | 验证方式 | 状态 |
|------|------|---------|---------|------|
| 1.1 | 数据模型变更：新增 `SubtitleConfig`，`AudioConfig` 移除 `subtitle_style`；`TaskManager.load()` 字段迁移兼容旧数据 | `models/task.py`, `core/task_manager.py`, `core/config.py` | `python -m py_compile` 语法检查；`from models.task import SubtitleConfig, AudioConfig` 导入验证；单元测试旧格式反序列化 | ✅ |
| 1.2 | Pipeline 步骤拆分：`_step_audio` + `_step_subtitle` 替代 `_step_audio_subtitle`；独立 `enabled` 逻辑；无旁白有字幕时从纯文本生成 SRT | `core/pipelines/creative_video.py`, `core/pipelines/manuscript_video.py`, `core/audio/subtitle.py` | 场景矩阵验证：(1) 旁白+字幕均开启 (2) 仅旁白 (3) 仅字幕 (4) 均关闭；每种场景 curl 创建任务，检查输出文件 | ✅ |
| 1.3 | 拼接层条件调整：`_step_concatenate` 判断逻辑从 `audio_config.enabled` 改为 `audio_config.enabled or subtitle_config.enabled` | `core/compositor/concatenator.py` | 1.2 的四种场景任务均能正常生成最终视频，无异常日志 | ✅ |
| 1.4 | API 端点 + 前端：`server.py` 新增 `subtitle_enabled` 参数；前端 UI 拆分字幕/旁白为独立控制区 | `server.py`, `static/index.html` | curl 校验端点参数接收正确；浏览器操作：分别勾选/取消字幕和旁白开关，确认提交参数正确 | ✅ |
| 1.5 | Phase 1 集成验证：端到端回归，确保现有功能无退化 | 全部 | 按 AGENTS.md 0.4 部署验证清单执行；创建创意视频 + 稿件视频各 4 种组合场景，确认产物完整 | ✅ |

#### Phase 2：字幕 LLM 智能样式

| 批次 | 内容 | 涉及文件 | 验证方式 | 状态 |
|------|------|---------|---------|------|
| 2.1 | `SubtitleStyle` 新增 `style_mode` + `style_hints`；SRT 侧车 JSON 格式扩展为 position + color + fontsize | `models/task.py` | 构造 `style_mode="llm"` 的 `SubtitleStyle`，序列化/反序列化往返正确；手写一份 `subtitle_styles.json`，验证各字段解析正确 | ✅ |
| 2.2 | LLM 样式决策：`screenwriter.generate_subtitle_styles()` 方法，输入 SRT + 视频尺寸 + 用户偏好，输出含 position/color/fontsize 的 JSON 数组 | `core/screenwriter.py` | 单元测试：准备一段 10 条字幕的 SRT 样例，调用 `generate_subtitle_styles`，验证 JSON 格式正确、条目数一致、position 合法、color 可解析、fontsize 在 18-80 范围 | ✅ |
| 2.3 | 拼接层逐条样式：`_parse_srt_to_clips` 读取 `subtitle_styles.json`，逐条覆盖 position/color/fontsize，每条字幕独立创建 TextClip | `core/compositor/concatenator.py` | 准备固定 SRT + 手写 styles JSON，调用 `concat_videos_with_audio_overlay`，输出视频中每条字幕的位置、颜色、大小与 JSON 设定一致 | ✅ |
| 2.4 | Pipeline 集成：在 `_step_subtitle` 中当 `style_mode == "llm"` 时调用 LLM 生成样式 JSON | `core/pipelines/creative_video.py`, `core/pipelines/manuscript_video.py` | 创建带 `style_mode="llm"` 的创意视频任务，确认生成了 `subtitle_styles.json`，最终视频字幕外观多样化 | ✅ |
| 2.5 | 前端：样式模式下拉（固定/AI 智能），选 AI 智能时显示 `style_hints` 文本框，隐藏全局位置/颜色/字号控件 | `static/index.html` | 浏览器操作：切换两种模式 → 控件显隐正确 → 提交任务，确认后端收到 `style_mode=llm` 和 `style_hints` | ✅ |
| 2.6 | Phase 2 集成验证：固定样式 vs LLM 样式两种模式端到端对比 | 全部 | 创建两组创意视频任务（fixed vs llm），对比产物差异；确认 LLM 模式不引入崩溃，字幕按预期呈现多样化 | ✅ |

#### Phase 3：数字人口播

| 批次 | 内容 | 涉及文件 | 验证方式 | 状态 |
|------|------|---------|---------|------|
| 3.1 | 任务模型：`AnchorVideoTask` + `TaskType.anchor` + 枚举扩展；`parse_task_state` 多态分支 | `models/task.py`, `core/task_manager.py` | 语法检查 + 导入验证；`parse_task_state({"task_type":"anchor",...})` 返回 `AnchorVideoTask` 实例；序列化/反序列化往返正确 | ✅ |
| 3.2 | Pipeline Step 1-2：`_step_generate_anchor`（t2i/i2i 分支）+ `_step_generate_clip`（i2v 视频片段） | `core/pipelines/anchor_video.py`（新建454行）, `core/pipelines/__init__.py` | `AnchorPipeline` 继承 `BasePipeline`，step 1 分 t2i/i2i 两条路径，step 2 调用 `AgnesVideoAPI.submit_video + wait_for_video` 轮询生成；断点续传支持 | ✅ |
| 3.3 | Pipeline Step 3-5：TTS + 字幕 + LLM 定位 + 循环拼接合成 | `core/pipelines/anchor_video.py`, `core/compositor/concatenator.py`, `core/screenwriter.py` | Step 3 EdgeTTS/SilentTTS 双路降级；Step 4 复用 Phase 2 `generate_subtitle_styles`，新增 `role="anchorperson digital human"` 参数指导 LLM 定位；Step 5 `composite_anchor_video` 实现循环拼接 + xfade 淡入淡出 + 逐条字幕样式叠加 | ✅ |
| 3.4 | API 端点 + 前端：`POST /api/tasks/anchor` + 第四 Tab UI + i18n | `server.py`, `static/index.html` | `server.py:742-820` 完整端点（14 个参数）+ `_create_pipeline_for_type` 分发；前端 Tab 表单 + 5 步进度条 + 7 语言完整 i18n（80 个 key） | ✅ |
| 3.5 | Phase 3 集成验证：三种场景 + 全量回归 | 全部 | (1) 纯 t2i 生成主播 (2) 有参考图 i2i (3) 仅字幕无旁白；每个场景生成完整视频；跑 AGENTS.md 0.4 部署验证清单确认无回归 | ⬜ |

#### v3.1 数字人口播方案 B（分段生成 + 口型近似匹配）

> 取代 v3.0 Phase 3 的「单段 5 秒循环」方案，每段生成不同动作的视频片段。

| 批次 | 内容 | 涉及文件 | 验证方式 | 状态 |
|------|------|---------|---------|------|
| B1 | 数据模型重构：`AnchorVideoTask` 新增 `paragraphs`/`combined_audio`/`combined_subtitle`/`subtitle_styles_path` 字段，步骤改为 7 步（generate_anchor → split → clip_prompts → clip_generation → audio → subtitle → concatenation） | `models/task.py` | 语法检查 + `parse_task_state` 反向兼容旧 anchor 任务 | ✅ |
| B2 | Screenwriter 新增 `generate_anchor_clip_prompt`：基于段落语义 + 主播形象生成不同英文动态 prompt（含口型/手势描述，相邻段落动作变化） | `core/screenwriter.py` | 导入验证 + 不同段落生成不同 prompt | ✅ |
| B3 | Pipeline 重写：复用稿件视频拆段逻辑（5-12s/段）+ 批量提交 i2v + 两阶段并行 + 统一拼接叠加 | `core/pipelines/anchor_video.py`（重写） | `AnchorPipeline` 7 步流程，断点续传支持，复用 `concat_videos_with_audio_overlay` | ✅ |
| B4 | 前端更新：7 步骤进度条 + 7 语言 i18n 更新 | `static/index.html` | 进度条显示 7 步，多语言标签正确 | ✅ |
| B5 | 集成验证 | 全部 | 创建数字人口播任务，验证分段视频生成 + 拼接效果 | ⬜ |

#### 最终验收

| 批次 | 内容 | 验证方式 | 状态 |
|------|------|---------|------|
| F1 | 全量回归：扩展场景矩阵（现有 10 场景 + 新增 anchor 3 场景） | `python scripts/regression_runner.py --auto-start`（需先扩展场景配置） | ⬜ |
| F2 | 文档更新：`AGENTS.md` 新增 anchor 任务类型描述、决策记录；`docs/system_design.md` 更新架构图 | 文档评审 | ⬜ |
| F3 | 发布检查：变更日志、README 更新 | 人工复核 | ⬜ |

---

### 八、进度更新日志

| 日期 | 批次 | 内容 |
|------|------|------|
| 2026-06-19 | — | 方案制定完成，文档建立 |
| 2026-06-19 | 1.1-1.4 | Phase 1 代码变更全部实现（数据模型 + Pipeline 拆步 + 拼接层 + API/前端），文档进度更新为 ✅ |
| 2026-06-19 | 1.5 | Phase 1 集成验证 ✅ 完成 — 创意视频 + 稿件视频各 4 种组合共 8 场景全部验证通过，产物完整 |
| 2026-06-19 | Fix | `SilentTTSEngine.generate()` 返回 `None` 而非 `{}`，修复纯字幕模式下 SRT 文件 0 字节 bug |
| 2026-06-19 | 2.1-2.6 | Phase 2 全部实现完成：数据模型扩展（style_mode/style_hints）+ LLM 样式决策 + 拼接层逐条样式 + Pipeline 集成 + 前端 UI + 7 语言 i18n，API 端点验证通过 |
| 2026-06-19 | 3.1-3.4 | Phase 3 代码变更全部实现：AnchorVideoTask 数据模型 + AnchorPipeline 5 步流程（t2i/i2i 主播生成→i2v 动态片段→TTS 读稿→字幕+LLM 样式→循环拼接合成）+ composite_anchor_video（xfade 淡入淡出 + 逐条字幕叠加）+ API 端点 + 前端第四 Tab 表单 + 7 语言 i18n（80 key），文档进度更新为 ✅ |
| 2026-06-20 | B1-B4 | v3.1 方案 B 实现完成：AnchorVideoTask 重构为 7 步流程 + `generate_anchor_clip_prompt` 分段动态 prompt + Pipeline 重写（复用稿件拆段 + i2v 分段 + 统一拼接）+ 前端 7 步骤 7 语言更新 |
