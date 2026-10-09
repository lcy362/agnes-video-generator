# 上游视频接口可靠性加固计划（v7.0）

> **实施状态**：🟢 **已实施**（2026-09-28；U1–U6、U8 已落地，U7 为待实测条目；细节见 §六实施记录）
> **来源**：Issue #75（用户报 `[Bug] Video generation timed out. Please try again`）排查过程中的真实链路实测 + 官网 demo 源码比对。
> **事实依据**：[`docs/dev/agnes_video_upstream_behavior.md`](../../dev/agnes_video_upstream_behavior.md)（本文所有编号 U* 的问题现象都在该文档有实测记录，本文只写「改哪里、怎么改、怎么验收」）
> **优先级标记**：🔴 高（直接影响用户能否拿到正确成片）| 🟡 中 | 🟢 低

---

## 一、现状盘点（读代码所得，非推测）

| 位置 | 现状 |
|------|------|
| `core/api/agnes_video.py:121-122` | `max_retries=5`、`retry_base_delay=30.0` |
| `core/api/agnes_video.py:470-489` | 提交侧 `status_code >= 500` 统一走「退避重试」，`error_type=f"HTTP{code}"`、`error_message=f"HTTP {code}: server error"`，**未解析响应体的 `code`/`message`** |
| `core/api/agnes_video.py:413-414` | 重试次数上限 `attempt < self.max_retries`，与视频提交桶（1 次/分钟/Key）叠加后，5 次尝试实际覆盖约 **5.5 分钟** |
| `core/api/agnes_video.py:368-378` | 轮询到 `status=failed` 时 `err = result.get("error")` 是**对象** `{code, message}`，直接 `f"Video generation failed: {err}"` 拼进异常与 `error_logs/` |
| `core/api/agnes_video.py:294-296` | 轮询 `interval=60`、整体超时经 `AGNES_VIDEO_POLL_TIMEOUT` 配置（默认 1800s），**长于上游约 15 分钟的推理硬闸**，因此自托管能拿到真实终态（这点优于 demo） |
| `core/config.py:1202-1222` | `agnes-video-2.5-flash` 能力元数据：固定 `720P`、比例枚举含 `9:16`，UI 会正常提供竖屏档 |
| `docs/public/faq.md` | 尚无「免费队列饱和 / 上游 15 分钟推理硬超时」的解释条目 |

---

## 二、优化点清单

| # | 问题 | 优先级 | 落点 | 方案要点 | 验收 |
|---|------|--------|------|----------|------|
| U1 | `video_queue_full` 可持续 12 分钟以上，5.5 分钟的重试预算会在排进队前放弃，用户看到「生成失败」而实际是「没排上队」 | 🔴 | `core/api/agnes_video.py` `_submit_with_retry` 的 `>= 500` 分支 | 解析响应体 `code`；命中 `video_queue_full` / `fail_to_fetch_task` 时走**独立退避轨道**（上限可配 `AGNES_VIDEO_QUEUE_RETRY_SECONDS`，默认 900s，固定 30–60s 抖动间隔），不计入普通 5xx 的 5 次配额；期间经 `progress_callback` 向前端推「**Agnes** 视频队列已满（HTTP 503 · video_queue_full），正在排队重试（第 N 次 / 已等 X 分钟）。建议错峰重试或稍后再试。」（文案须点名 Agnes、带上接口原样报错、给出错峰方案） | 单测：mock 连续 503 `video_queue_full` → 断言重试次数与总时长受控、普通 5xx 仍只 5 次；mock 回归不因此变慢（默认关闭或短超时） |
| U2 | 失败原因在链路上被丢弃：提交侧丢 body `code`，轮询侧把 `error` 对象整个字面量化 | 🔴 | 同上 + `core/api/agnes_video.py:368-378` | 统一提取器 `_upstream_error(resp_or_body) -> (code, message)`，异常文案改为 `Video generation failed: {message} (code={code})`；`collect_error` 的 `error_message` 用 message、`extra` 带 code | 单测断言 `RuntimeError` 文案含 "inference not finished after 15 minutes"；`error_logs/*.json` 的 `error_message` 不再是 dict 字面量 |
| U3 | 2.5-flash + `9:16` 产物**容器竖、像素横**（上游只换容器不转像素，无 rotation 元数据），自托管同样中招并一路带进拼接与字幕 | 🔴 | `utils/video.py` 下载后 / `core/pipelines/__init__.py` 场景收尾 | 见 §三「U3 方案细化」：先做**可开关的方向校正**，再决定是否默认启用 | 竖屏 2.5-flash 单场景任务成片方向正确；`ffprobe` 容器与画面方向一致；关闭开关时行为与现状完全一致 |
| U4 | UI 承诺的像素档与上游实际产物档可能不一致（非标准档被吸附），且 `perf_params` 是推理内部尺寸、与容器不同 | 🟡 | `docs/dev/pipeline_products.md`、`docs/dev/regression_test_plan.md` F3、`core/config.py` 模型能力表 | 文档固化「标准档保真 / 非标准档吸附」规律（实测：768×1152 与 1280×720 保真；1152×768→1088×832、768×1360→704×1280）；明确**禁止用 `perf_params` 做产物校验**；本项目 UI 三档保持现状（都是标准档），但在模型说明里加一句「输出分辨率由上游按标准档归一」 | 回归 F3 文案更新；新增断言：只用 ffprobe 读容器，不读 `perf_params` |
| U5 | `progress` / `internal_progress` 互相矛盾（实测 0 vs 100），`started_at` 可为 `null` | 🟡 | `core/api/agnes_video.py` `_poll_task` / `_adaptive_poll_interval` | 确认自适应间隔不依赖进度值（只按次数/时间推进）；进度条语义改为「已等待时长 + 阶段」而非百分比真值；前端 `useProgress` 对 `progress` 缺失/跳变做兜底 | 代码走查 + 单测：`progress` 恒为 0 时任务仍能正常完成并推进 UI |
| U6 | 用户与 FAQ 都没有「免费队列饱和 / 上游 15 分钟硬超时」的解释，Issue #75 类问题会反复出现 | 🟡 | `docs/public/faq.md`、`docs/public/usage.md` | 新增 FAQ：为什么长时间卡在 0%、为什么提示超时、为什么自托管反而能看到具体报错、如何错峰 / 换模型 / 多 Key | 文档审阅；Issue 回复可直接引用 |
| U7 | 多 Key 场景下 `video_queue_full` 是否按 Key 分池未知（实测单 Key 连续 25 次被拒，未验证换 Key 是否可解） | 🟢 | `core/api/key_manager.py` + 实测 | 先实测（多 Key 时命中 503 是否换 Key 成功），再决定是否把 U1 的队列重试与换 Key 结合 | 实测步骤与记录位已补进 `docs/dev/agnes_video_upstream_behavior.md` §4.1（**待实测**，需 ≥2 Key + 饱和时段；当前代码对 503 不换 Key，保持现状） |
| U8 | **本地可选档位随发版硬编码，旧版本用户看不到新模型的能力档位**——Issue #75 用户「本地找不到 9:16 Portrait 720×1280、画质比 demo 差、如何配置 Video 2.5 Flash」三条困惑同源 | 🔴 | `core/config.py:1148-1222`（`VIDEO_MODEL_CAPABILITIES`）、`web/routes/config_routes.py:447-480`（`/api/models`）、`frontend/src/composables/useVideoModelCaps.ts:5`/`:58`/`ratioOptions` | 见 §三之二 | 旧版本下拉对未适配模型给出显式提示；FAQ 有 demo↔自托管能力对照与升级路径 |

---

## 三、U3 方案细化（唯一需要设计决策的条目）

**问题边界**：上游在 `aspect_ratio=9:16` 下返回 720×1280 容器、内部为顺时针躺倒的横屏构图；**`16:9` 与 `3:4` 实测方向正常**（`3:4` 容器 834×1112，比例保真），故缺陷范围目前收窄到 9:16 一档，`1:1` / `4:3` / `21:9` 未测。

**候选做法**：

1. **无条件校正**（简单但不安全）：只要 `model=2.5-flash` 且请求比例为竖屏，就 `transpose` 一次。风险：上游一旦修复即反向出错。
2. **探测式校正**（推荐）：下载后抽一帧，判定「容器方向」与「画面主方向」是否一致（重力/地平线类启发式对视频不可靠；本项目可用**低代价代理**：请求竖屏但上游 `perf_params.width > perf_params.height` 时视为可疑），命中才 `transpose`，并在日志打 `[UpstreamRotate]` 前缀记录。
3. **只做提示不修**（最保守）：在 2.5-flash 竖屏选项旁提示「上游竖屏存在画面旋转缺陷，建议改用 v2.0 竖屏档或自行旋转」，等上游修复。

**建议路径**：先按 3 落文档与 UI 提示（零风险），同时把 2 的探测实现为 **默认关闭** 的开关 `AGNES_FIX_V25_PORTRAIT_ROTATION`，跑一轮真实竖屏任务验证后再定默认值。校正点放在下载之后、缩放之前（`utils/video.py` → 场景产物注册前），保证拼接与字幕叠加拿到的已是正向素材。

> **已按建议路径落地（2026-09-28）**：候选 3（UI 提示 `vmPortraitRotateHint`）为默认行为；候选 2 实现为默认关闭的探测式校正（`VideoOutput._maybe_fix_rotation`，判定签名 `_needs_portrait_rotation_fix`，校正点 = `VideoOutput.save()`，即下载后、场景产物注册前）。默认值待真实竖屏任务验证后再定。

---

## 四、U8 方案细化与 Issue #75 用户诉求对照

### 4.1 根因链

**模型清单是动态的，能力档位表是静态的**：

| 数据 | 来源 | 更新时机 |
|------|------|----------|
| 可选模型（下拉项） | 上游 `GET /v1/models?all=true`（`web/routes/config_routes.py:447`，失败回退硬编码列表） | 上游上新即可见 |
| 该模型可选的分辨率/时长/模式 | 本地硬编码 `core/config.py:1148-1222`，经 `/api/models` 的 `video_capabilities` 下发 | **只在发版时变** |
| 比例 → 提交像素 | 前端硬编码 `useVideoModelCaps.ts:5` 的 `RATIO_TO_WH` | 只在发版时变 |

因此旧版本安装会出现「模型能看到、档位不能用」的错位：`capsOf()` 对未知模型返回 `{}`（`useVideoModelCaps.ts:58`），`ratioOptions()` 回退到全量 6 比例（看起来"有档位"），但 2.5 系列识别只靠模型名前缀 `V25_PREFIX`（`:5`）——一旦该版本还没有 2.5 分支，用户选了 2.5-flash 也会按 v2.0 的像素档提交，或干脆在下拉里看不到。

**Issue #75 用户的表现完全对应这条链**：他贴出的能力卡片（`Modes: t2v / i2v(1 ref) / Keyframes`、`Durations 5/10/15/18/20`、`Resolution 768x1152 / 1152x768 / 1024x1024`、`Negative prompt Yes`、`Ref. video No`）逐字对应**旧版** `VIDEO_MODEL_CAPABILITIES` 的 v2.0 条目——其中横屏仍是 `1152x768`（3:2），说明其版本早于 v7.0.2（`6bd4dec` 才改为 true 16:9）；下拉里没有 2.5-flash，说明早于 v6.2（`ec84e11` 引入 2.5 / 2.5-flash）。

### 4.2 改进方案

1. **可见性**：`/api/config` 与前端页脚暴露应用版本号 + 能力表版本标识；用户与排障 Agent 一眼能判断「是否版本过旧」。
2. **未适配显式提示**：上游模型清单里有、本地 `VIDEO_MODEL_CAPABILITIES` 里没有的视频模型，下拉里标注「当前版本未适配，升级到 vX.Y.Z+ 可用」，**不允许静默按 v2.0 像素协议提交**（现在会静默提交，用户以为模型生效了）。
3. **文档补齐**：`docs/public/faq.md` + `docs/public/getting-started.md` 增加「在线 demo 与自托管的能力对照 + 升级路径」小节（含 `git pull && ./start.sh` 与重新拉镜像两条命令），并说明画质差异来自模型代际而非参数。

### 4.3 Issue #75 用户诉求 → 条目对照

| 用户原话诉求 | 实测/代码结论 | 承载条目 |
|--------------|---------------|----------|
| 「本地找不到 `9:16 Portrait · 720×1280`」 | 该档位只挂在 2.5-flash（v6.2 引入）；用户版本早于 v6.2，且 720×1280 是 2.5 系列 `size=720P + aspect_ratio=9:16` 的产物 | U8 |
| 「本地质量差很多」 | 同 prompt 下 2.5-flash 码率 4.1 Mb/s、v2.0 仅 1.5 Mb/s，观感差异明显；属模型代际差异，不是设置问题 | U8 + FAQ |
| 「如何配置 Video 2.5 Flash / 与 demo 相同设置」 | 升级到 v7.0.2+ 后在模型下拉选 2.5-flash，档位为 720P + 6 种比例；但竖屏 9:16 当前会命中上游躺倒缺陷 | U8 + U3 |
| 「demo 连续 3 天超时」 | 上游免费队列饱和（实测连续 25 次 `503 video_queue_full`）+ 约 15 分钟推理硬闸判死；非用户 prompt/设置问题 | U1 / U2 + 官网 W2 / W3 |

---

## 五、不在本计划内（已分流）

- **官网 demo 侧的问题**（超时文案掩盖真实原因、`failed` 分支把对象塞进字符串 state 导致渲染崩、模型档位标注、提交不重试 503）：属独立仓库 `video-website`，方案已写入该仓库 `docs/plans/demo-video-reliability-plan.md`，本仓库不重复承载。
- **向 Agnes 上游报缺陷**（2.5-flash 9:16 像素未旋转、v2.0 非标准档吸附、`status=failed` 却返回 HTTP 200、`progress` 字段矛盾）：站外动作，证据文件与复现请求已整理在 `docs/dev/agnes_video_upstream_behavior.md` §3/§5，可直接附单提工单。

---

## 六、实施记录

| 日期 | 条目 | 落地文件 | 自验记录 |
|------|------|----------|----------|
| 2026-09-28 | U1 队列满独立退避轨道 | `core/api/agnes_video.py`（`_submit_with_retry` + `_QUEUE_FULL_CODES`）、`core/config.py`（`agnes_video_queue_retry_seconds`）、`core/i18n_backend.py`（`progress.video.queue_full`）、`core/pipelines/__init__.py`（`_submit_progress_callback`）、simple/multi_scene/creative/anchor 提交站点 | 单测 `tests/test_upstream_error_handling.py` N1–N4 全绿；默认预算 900s，退避 30–60s 抖动，不计入普通 5xx 配额 |
| 2026-09-28 | U2 错误提取与透出 | `core/api/agnes_video.py`（`_upstream_error` + 提交 5xx 分支 + 轮询 failed 分支） | 单测 N5/N6：`RuntimeError` 文案含 "inference not finished after 15 minutes (code=500)"；`error_message` 不再为 dict 字面量；`is_remote_video_failure` 语义未变 |
| 2026-09-28 | U3 竖屏躺倒：先提示 + 可开关校正 | `core/api/agnes_video.py`（`_needs_portrait_rotation_fix` / `_probe_video_size` / `VideoOutput._maybe_fix_rotation`）、`core/config.py`（`agnes_fix_v25_portrait_rotation`）、`SimpleForm.vue` + `vmPortraitRotateHint` i18n | 单测 N7/N8；开关默认关闭（关闭时行为与现状完全一致，校正失败保留原片）；UI 在 2.5 系列选中 9:16 时给出提示 |
| 2026-09-28 | U4 分辨率/方向规律固化 | `docs/dev/pipeline_products.md` §1.6/§1.7、`docs/dev/regression_test_plan.md` F3、`core/config.py` 模型 desc | 文档评审；F3 明确「只用 ffprobe/moviepy 读容器，禁止用 `perf_params`」 |
| 2026-09-28 | U5 进度语义兜底 | `core/api/agnes_video.py`（`_poll_task` 注释固化） | 单测 N9：`progress` 恒 0 时仍完成并产出 URL；自适应间隔只按次数推进（走查确认无逻辑依赖 progress） |
| 2026-09-28 | U6 FAQ / usage 补齐 | `docs/public/faq.md`（4 条新增）、`docs/public/usage.md`（上游限制小节 + 日志前缀） | 文档审阅；Issue 回复可直接引用 |
| 2026-09-28 | U7 多 Key 分池实测 | `docs/dev/agnes_video_upstream_behavior.md` §4.1 | **待实测**（需 ≥2 Key + 饱和时段；已给出 curl 步骤与记录位） |
| 2026-09-28 | U8 版本可见性 + 未适配显式提示 | `web/routes/config_routes.py`（`/api/models` 返回 `app_version`）、`useVideoModelCaps.ts`（`isAdapted`）、`SimpleForm.vue` / `ConfigPanel.vue`（`⚠` + `vmUnadaptedHint`）、`App.vue` 页脚版本、22 语言 i18n | 前端 `vue-tsc --noEmit` 通过；22 个语言包 JSON 校验通过；`/api/config` 与 `/api/models` 均暴露版本 |
| 2026-10-09 | v7.1 归拢 + v7.2 节奏改造：所有上游重试收敛到 `core/api/retry_policy.py` 的两轨模型（判定 + 间隔唯一出处，裸 503 并入忙轨）；忙轨封顶由「总时长预算（秒）」改为「**重试次数**」，并改为「**首跳 0s 贴着限流**（人工退避不叠加在令牌桶之上）+ 之后固定间隔 + 次数封顶」，多 Key 下可打满突发额度以缩短总重试耗时 | `core/api/retry_policy.py`（`BusyBudget`→`BusyTracker`、`busy_delay(..., attempt)` 首跳 0）、`core/config.py`（`AGNES_VIDEO_BUSY_RETRY_ATTEMPTS` 默认 15 / `AGNES_BUSY_RETRY_ATTEMPTS` 默认 None）、`core/api/agnes_video.py`（提交 15 / 上传 10）、`core/api/agnes_image.py`（15）、`core/api/rate_limiter.py`（`busy_max_retries` 默认 20） | 全量 `pytest tests/` 通过；`scripts/i18n_check.py` 退出码 0；断言首跳 0s、固定间隔、次数封顶、上传忙轨用尽回退 base64、Chat 忙轨次数封顶。**开关更名并改语义**：`AGNES_VIDEO_QUEUE_RETRY_SECONDS` → `AGNES_VIDEO_BUSY_RETRY_ATTEMPTS`、`AGNES_BUSY_RETRY_SECONDS` → `AGNES_BUSY_RETRY_ATTEMPTS` |

---

*创建：2026-09-28 | 关联：Issue #75、`docs/dev/agnes_video_upstream_behavior.md`*
