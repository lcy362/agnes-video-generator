# Agnes Video Generator 改造 — 测试计划

*版本：v1.0 | 日期：2025-06-14*

---

## 一、测试范围

| 维度 | 覆盖 |
|------|------|
| 新增模块 | 11 个新文件（api/×3, compositor/×2, audio/×2, pipelines/×3, 1 init） |
| 重写模块 | 4 个（models/task.py, server.py, core/config.py, static/index.html） |
| 修改模块 | 3 个（requirements.txt, core/task_manager.py, core/screenwriter.py） |
| 保持模块 | 验证未破坏 |

---

## 二、测试轮次

### 第 1 轮：全面验证

#### Step 1 — 静态分析（离线）

| # | 检查项 | 命令/方法 | 通过标准 |
|---|--------|----------|---------|
| S1 | Python 语法 | `python -m py_compile core/**/*.py models/*.py server.py` | 全部无 SyntaxError |
| S2 | 导入验证 | `python -c "from core.api.agnes_video import AgnesVideoAPI; from core.audio.tts import EdgeTTSEngine; from core.pipelines.simple_video import SimpleVideoPipeline"` | 无 ImportError |
| S3 | HTML 语法 | 浏览器打开 `static/index.html`，检查 console 无 JS 错误 | 无错误 |

#### Step 2 — 单元测试（离线 + 可选在线）

| # | 模块 | 测试内容 | 离线/在线 |
|---|------|---------|----------|
| U1 | `models/task.py` | TaskType 枚举值；SimpleVideoTask/CreativeVideoTask/ManuscriptVideoTask 字段校验；JSON 序列化/反序列化 | 离线 |
| U2 | `models/task.py` | 旧数据兼容：无 task_type → 自动识别为 CREATIVE | 离线 |
| U3 | `core/config.py` | get_default_audio_config() 返回结构完整性 | 离线 |
| U4 | `core/config.py` | get_default_subtitle_style() 返回结构完整性 | 离线 |
| U5 | `core/audio/subtitle.py` | cues_to_srt() 输出合法 SRT（时间戳格式 `HH:MM:SS,mmm`） | 离线 |
| U6 | `core/audio/tts.py` | EdgeTTSEngine 初始化参数校验 | 离线 |
| U7 | `manuscript_video.py` | split_manuscript() 拆段算法 | 离线 |
|  | | - 空文本 → [] | |
|  | | - 单句短文本 → 1 段 | |
|  | | - 长句（> 12s 预估）→ 接受不拆 | |
|  | | - 多句合并到 5-12s 范围 | |
| U8 | `core/task_manager.py` | 旧 task_state.json 加载兼容 | 离线 |
| U9 | `core/audio/tts.py` | EdgeTTSEngine.generate() 实际调用 edge_tts（需网络） | 在线 [skip if no network] |

#### Step 3 — 集成测试（需服务启动）

| # | 方法 | 路径 | 验证点 | 预期 |
|---|------|------|--------|------|
| I1 | GET | `/` | 首页加载 | 200, 包含三个 Tab 按钮 |
| I2 | GET | `/api/config` | API Key 获取 | `{"ok": true, ...}` |
| I3 | POST | `/api/tasks/simple` | 创建简单视频任务 | 200, 返回 task_id + task_type="simple" |
| I4 | POST | `/api/tasks/creative` | 创建创意视频任务 | 200, 返回 task_id + task_type="creative" |
| I5 | POST | `/api/tasks/manuscript` | 创建稿件视频任务 | 200, 返回 task_id + task_type="manuscript" |
| I6 | GET | `/api/tasks` | 任务列表 | 包含三种类型任务 |
| I7 | GET | `/api/tasks/{id}` | 任务详情 | 含 task_type 字段 |

#### Step 4 — 手动验收（前端）

| # | 操作 | 验证点 |
|---|------|--------|
| M1 | 页面加载 | 语言选择器 7 种语言，切换正常 |
| M2 | Tab 切换 | 简单视频 → 创意长视频 → 稿件长视频，表单正确切换 |
| M3 | 简单视频 Tab | 选择"图生视频" → 参考图上传区出现；选择"关键帧" → 尾帧上传区出现 |
| M4 | 创意长视频 Tab | 音频配置区可见：旁白开关、语音角色下拉、语速滑块、字幕样式 |
| M5 | 稿件长视频 Tab | 大 textarea、[预览拆分] 按钮可见 |
| M6 | i18n | 切换日语 → 所有文案翻译正确 |

---

### 第 2 轮：回归验证（仅在 1 轮发现源码 Bug 时触发）

| # | 操作 | 验证点 |
|---|------|--------|
| R1 | 重新运行第 1 轮中所有失败的测试 | 原失败项全部通过 |
| R2 | 随机抽查 3 个第 1 轮通过的测试 | 未引入回归 |
| R3 | 前端全流程走查（三种 Tab 各一次） | 无 JS 报错 |

---

## 三、智能路由判定流程

```
第 N 轮测试完成
       ↓
  ┌ 失败项分析 ───────────────────────────┐
  │                                        │
  │  是源码逻辑问题？                       │
  │  ├─ YES → 反馈给工程师                  │
  │  │   └─ 附带：失败测试文件路径 +         │
  │  │      错误信息 + 期望 vs 实际          │
  │  │                                      │
  │  是测试代码问题（断言错/mock不当）？      │
  │  ├─ YES → QA 自行修复                    │
  │  │                                      │
  │  全部通过？                              │
  │  └─ YES → ALL_PASS，输出报告             │
  └──────────────────────────────────────────┘
```

---

## 四、通过标准

| 等级 | 条件 |
|------|------|
| 🟢 全部通过 | 所有测试（S×3 + U×9 + I×7 + M×6）通过，无遗留问题 |
| 🟡 有遗留 | ≥ 2 轮后仍有失败项，但非 P0 阻塞性 Bug |
| 🔴 阻塞 | P0 功能不可用（服务无法启动、核心 Pipeline 崩溃） |

---

## 五、交付产物

QA 完成测试后输出到对话中（不落盘文件，除非用户要求）：

```
### QA 测试报告

**轮次**：第 X 轮
**判定**：ALL_PASS / 反馈工程师 / QA自修复

**静态分析**：S1 ✓ / S2 ✓ / S3 ✓
**单元测试**：U1-U9 ✓ / ✗（标注失败项）
**集成测试**：I1-I7 ✓ / ✗
**手动验收**：M1-M6 ✓ / ✗

**发现的问题**（如适用）：...
**修复建议**（如适用）：...
```
