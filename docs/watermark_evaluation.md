# 视频水印方案评估

> **日期**：2026-06-30
> **需求**：在生成的所有视频上添加水印 —「由 Agnes Video Generator 生成」+ 官网地址 `video.lichuanyang.top`

---

## 一、现状分析：四条管线的最终视频产出路径

| 管线 | 最终输出方式 | 是否经过合成器 | 关键代码位置 |
|------|-------------|:---:|------------|
| **Simple** | API 响应直接保存为 `final_video.mp4` | ❌ 不经过 | `simple_video.py:_submit_and_wait()` L102 |
| **Creative** | `concat_videos_with_audio_overlay()` 或 `concat_videos()` | ✅ 经过 | `creative_video.py:_step_concatenate()` L1833-1847 |
| **Manuscript** | `concat_videos_with_audio_overlay()` 或 `concat_videos()` | ✅ 经过 | `manuscript_video.py:_step_concatenate()` L794-809 |
| **Anchor** | `composite_anchor_video()` 或直接引用 | ✅ 经过 | `anchor_video.py:_step_composite_anchor()` L474-487 |

**结论**：Simple 管线完全不走合成器，其他三条管线在合成器中完成最终编码。这意味着**无法仅在一个地方添加水印**。

---

## 二、三种技术方案对比

### 方案 A：ffmpeg drawtext 统一后处理 ⭐ 推荐

**思路**：在每条管线产出 `final_video.mp4` 后，统一调用一个后处理方法，用 ffmpeg drawtext 滤镜叠加水印文本。

```bash
ffmpeg -i input.mp4 -vf \
  "drawtext=fontfile=STHeitiMedium.ttc: \
   text='由 Agnes Video Generator 生成 | video.lichuanyang.top': \
   fontsize=22:fontcolor=white@0.85: \
   box=1:boxcolor=black@0.35:boxborderw=8: \
   x=w-tw-24:y=h-th-16: \
   shadowx=1:shadowy=1:shadowcolor=black@0.4" \
  -c:v libx264 -preset fast -c:a copy output.mp4
```

| 维度 | 评价 |
|------|------|
| 实现复杂度 | **低** — 新增一个 `WatermarkProcessor` 模块，4 条管线各加一行调用 |
| 性能 | 需重新编码视频流（音频 `copy`），约增加视频时长 5-15% 的处理时间 |
| 视觉效果 | **好** — 带半透明黑底圆角框，白色文字+阴影，CJK 字体原生渲染 |
| CJK 支持 | **完美** — 已有 `STHeitiMedium.ttc` 字体，ffmpeg 原生支持 TrueType |
| 可维护性 | **高** — 统一入口，改一次影响所有管线 |
| 可配置性 | **中** — 通过参数控制位置/大小/透明度，修改需改代码 |

✅ **优点**：
- 单一代码路径，逻辑清晰
- ffmpeg 原生 drawtext 性能优异，耗时可预期
- 音频流直接 copy，无质量损失
- 文本内容/样式改一处即全局生效

⚠️ **缺点**：
- Simple 视频需额外一次重新编码（但 Simple 视频通常较短：5-20s）
- 无法实现像素级精确的渐变/圆角效果（drawtext 的 box 只有直角）

---

### 方案 B：moviepy TextClip 叠加（内嵌合成）

**思路**：在 `VideoConcatenator` 的 `CompositeVideoClip` 阶段追加一个水印 TextClip。Simple 管线需单独处理。

| 维度 | 评价 |
|------|------|
| 实现复杂度 | **中** — 需修改 `VideoConcatenator` 的两个方法 + Simple 特殊处理 |
| 性能 | 对 Creative/Manuscript/Anchor 无额外开销（已在编码中），Simple 需额外 moviepy 编码 |
| 视觉效果 | **好** — 与现有字幕系统一致，支持 `bg_color` 圆角背景 |
| CJK 支持 | **好** — 复用现有 `resolve_font_path()` |
| 可维护性 | **低** — 逻辑分散在两处（合成器 + Simple 特殊路径） |

✅ **优点**：
- 对已有合成步骤的管线零额外开销
- 复用现有字体和 TextClip 基础设施

⚠️ **缺点**：
- 逻辑分散：3 条管线走合成器、1 条管线走特殊处理
- moviepy TextClip 的 `bg_color` 不支持圆角（与字幕行为一致但不够精致）
- `CompositeVideoClip` 层数增加，内存占用微增

---

### 方案 C：预渲染 PNG + ffmpeg overlay

**思路**：启动时用 Pillow 预渲染一张带水印文字的透明 PNG（支持渐变、圆角等高级效果），然后通过 ffmpeg overlay 滤镜叠加。

```bash
# 第一步：用 Pillow 生成水印 PNG（项目启动时一次）
# 第二步：ffmpeg overlay
ffmpeg -i input.mp4 -i watermark.png -filter_complex \
  "overlay=W-w-24:H-h-16:enable='between(t,0,9999)'" \
  -c:v libx264 -preset fast -c:a copy output.mp4
```

| 维度 | 评价 |
|------|------|
| 实现复杂度 | **中** — 需新增 PNG 生成逻辑 + overlay 调用 |
| 性能 | 与方案 A 相当（额外一次编码），PNG 预渲染一次不占运行耗时 |
| 视觉效果 | **最优** — 支持渐变、圆角、阴影、图标等任意设计 |
| CJK 支持 | **好** — Pillow + 已有字体渲染 |
| 可维护性 | **中** — 设计变更需重新生成 PNG |
| 可配置性 | **低** — 文字内容变更必须重新渲染 PNG |

✅ **优点**：
- 视觉效果最精致，可实现渐变圆角半透明等高级效果
- 可嵌入 logo 图标

⚠️ **缺点**：
- 文本内容固定（"由 Agnes Video Generator 生成"），多语言支持需多张 PNG
- 文字内容变更需重新生成 PNG（不如 drawtext 灵活）
- 引入额外依赖：需要 Pillow 做字体渲染（项目已有 moviepy 间接依赖 Pillow）

---

## 三、方案对比矩阵

| 评估维度 | 方案 A (ffmpeg drawtext) | 方案 B (moviepy TextClip) | 方案 C (PNG + overlay) |
|---------|:---:|:---:|:---:|
| 实现复杂度 | ⭐⭐⭐ 低 | ⭐⭐ 中 | ⭐⭐ 中 |
| 性能开销（Simple） | ~5-15% | ~10-20% | ~5-15% |
| 性能开销（其他） | ~5-15% | ~0% | ~5-15% |
| 视觉效果 | ⭐⭐⭐ 好 | ⭐⭐⭐ 好 | ⭐⭐⭐⭐ 最优 |
| 圆角支持 | ❌ | ❌ | ✅ |
| CJK 渲染 | ✅ ffmpeg 原生 | ✅ 复用字幕系统 | ✅ Pillow 渲染 |
| 统一代码路径 | ✅ 单入口 | ❌ 分散两处 | ✅ 单入口 |
| 多语言扩展性 | ✅ 运行时文本 | ✅ 运行时文本 | ❌ 需重新渲染 |
| 可配置性 | ⭐⭐⭐ | ⭐⭐ | ⭐ |
| 推荐度 | **🏆 强烈推荐** | 不推荐 | 可选（需精致设计时） |

---

## 四、推荐方案：方案 A — ffmpeg drawtext 统一后处理

### 4.1 推荐理由

1. **简洁性**：一条 ffmpeg 命令解决，不引入新依赖
2. **统一性**：4 条管线共享同一个后处理入口，未来新增管线自动受益
3. **性能可接受**：Simple 视频 5-20 秒，额外编码通常 1-3 秒；长视频的额外耗时也在可接受范围
4. **可维护性**：水印文本/位置/样式集中管理，改动一处全局生效

### 4.2 架构设计

```
core/compositor/watermark.py          ← 新增 WatermarkProcessor
├── WatermarkProcessor.add_watermark(input, output, config)
│   └── ffmpeg drawtext 单次调用
│
调用点（每条管线在 final_video.mp4 保存后调用）：
├── simple_video.py    _submit_and_wait()     L116 后
├── creative_video.py  _step_concatenate()    L1857 前
├── manuscript_video.py _step_concatenate()   L812 前
└── anchor_video.py    _step_composite_anchor() L498 前
```

### 4.3 水印设计规格

> 完整的语言感知设计规格请参阅 **[watermark_design_spec.md](./watermark_design_spec.md)**。
>
> 核心要点：
> - 根据 prompt 语言自动选择中/英文水印（检测 CJK 字符）
> - 字号自适应：`font_size = max(12, round(h × 0.022))`
> - 字体统一使用 `STHeitiMedium.ttc`
> - 双行布局：归属行 + 地址行，右下角定位

### 4.4 性能测算

| 视频类型 | 典型时长 | 预估额外耗时 |
|---------|---------|------------|
| Simple | 5-20s | 1-3s |
| Creative | 30-120s | 3-15s |
| Manuscript | 30-180s | 3-20s |
| Anchor | 30-120s | 3-15s |

> 使用 `-preset fast` 参数，实测性能表现稳定。

### 4.5 可选增强：合成路径优化

对于 Creative/Manuscript/Anchor 管线，可以在合成步骤的 ffmpeg 命令中**追加** drawtext 滤镜链，避免「合成后保存 → 再解码加水印 → 再编码」的二次损耗。但考虑到代码改动量和维护性，**推荐先采用统一后处理**，后续性能如有瓶颈再优化。

### 4.6 实现要点

1. **水印文本**：`由 Agnes Video Generator 生成 | video.lichuanyang.top`
2. **字体路径**：`resource/fonts/STHeitiMedium.ttc`
3. **字号自适应**：`fontsize = max(14, int(video_height * 0.022))`
4. **配置化**：水印文本、位置、透明度通过 `core/config.py` 管理，支持运行时关闭
5. **中断安全**：水印生成的中间文件使用 `.tmp` 后缀，完成后 `os.replace` 原子替换

---

## 五、实施计划（供确认后执行）

| 步骤 | 内容 | 涉及文件 |
|:---:|------|---------|
| 1 | 新增 `core/compositor/watermark.py` | 新文件 |
| 2 | `core/config.py` 增加水印配置项 | 修改 |
| 3 | `simple_video.py` 集成水印后处理 | 修改 |
| 4 | `creative_video.py` 集成水印后处理 | 修改 |
| 5 | `manuscript_video.py` 集成水印后处理 | 修改 |
| 6 | `anchor_video.py` 集成水印后处理 | 修改 |
| 7 | 端到端测试验证 4 种模式水印输出 | 测试 |
