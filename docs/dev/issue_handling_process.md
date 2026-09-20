# Issue 处理流程（初版）

> 面向对象：维护 / 开发本项目的 AI Agent
> 目标仓库：`lcy362/agnes-video-generator`
> 状态：🟢 初版可用，后续持续迭代
> 版本：v0.1 | 更新日期：2026-08-27

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

**据此分两种情况判定用户语言：**

* **情况 A：用户采用了反馈模板**。

  * **首选信号：模板结构字段语言**。多语言化后结构随用户界面语言变化（如 `## Diagnostic Info (Agnes Video Generator)` 表明英文界面、`## 诊断信息（Agnes Video Generator）` 表明中文界面），可作用户语言的强指示。

  * **辅助信号**：用户在 `### 复现步骤` / `### 期望行为` 中填写的真实内容、正文 / 评论追加描述。

  * 若用户自行填写的字段皆空、仅剩结构与报错 → 以结构语言为准回复，并在开头补一句「如你需要，我可以改用英文 / 中文回复」（或按用户其余行为推断）。

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
| 请求报 `HTTP 401` / `无效的令牌`（含 `api.agnes-ai.cn/v1`、simple/manuscript 提交、creative `scene_config` 编剧 LLM 调用等） | API Key 与请求域名不匹配：跨站 key（国际站 key 用国内站专属域名 `api.agnes-ai.cn`，或反之）认证失败；亦可能 key 过期/抄写不完整（含首尾空格） | 升级 v6.4.2：per-key 域名绑定 + 「自动探测域名」按钮逐 key 补全匹配域名；国际站 key 用 `apihub.agnes-ai.com` 或 `cn_bak` 兜底（兼容国内/国际 key）。注意：**env/`.env` 来源的 key 不参与探测**（无法持久化域名，只走全局默认域名），需在 Web 配置页添加 key 或将全局默认域名切到与 key 站点一致 | #38, #44, #58, #61, #62 |
| 生成参考图后下载报 `platform-outputs.agnes-ai.space` SSL 中断（`SSLEOFError: UNEXPECTED_EOF_WHILE_READING`）或 DNS 失败（`Errno 11001 getaddrinfo failed`），creative/manuscript init 环节失败 | 上游图片文件服务域名 `platform-outputs.agnes-ai.space` 偶发不可达 / 本机 DNS、代理、VPN 或防火墙拦截                                     | 稍后重试；刷新 DNS / 换 DNS（如 223.5.5.5）；检查代理与防火墙；应用内置 3 次下载重试（间隔 3s）                                              | #45, #46 |
| creative 跑到最后才失败，视频下载环节报 `socket.gaierror [Errno 11004] getaddrinfo failed` 解析不了 `cos-platform-outputs.agnes-ai.cn`；反馈里「失败环节」却显示 `scene_config` | 本机 DNS / 代理 / 安全软件解析不到视频输出域名（腾讯云 COS）。实测 issue 里的 mp4 URL 返回 HTTP 206、文件完整，服务端已生成成功。环节名失真是另一回事：反馈面板取页面挂载时的 `current_step` 快照，且终态进度写入被 0.5s 节流丢弃 | 换能解析该域名的 DNS（223.5.5.5 / 119.29.29.29）、关 VPN/代理 DNS 劫持与 hosts/安全软件拦截、`ipconfig /flushdns` 后点「重试任务」续传（video id 已保留，不重复提交）；v6.4.8 已修：网络类异常翻译为「网络诊断」提示、失败终态强制落盘并保留真实环节、报告改用实时环节名 | #56, #57 |
| 视频提交持续报 `HTTP 503 server error` → `max retries (5) exceeded`，或 `HTTP 429 rate limited`，随后轮询返回 `job cancelled`                                                           | 上游视频服务过载 / 限流，提交重试耗尽且任务被上游取消                                                                                  | 错峰稍后重试；降低并发生成以减少限流；必要时更换视频模型 / 域名                                                                          | #47      |
| 视频提交返回 `{"code":"video_queue_full","message":"video queue is full, please retry later"}`，错误面板直接显示这段原始 JSON                                                                                                              | 上游视频服务队列饱和（与 #47 的 503 / 429 同族容量问题），请求在入队前就被拒。应用当前的自动重试只覆盖 HTTP 429 与 5xx（`core/api/agnes_video.py`），该业务错误码不在其中，因此立即硬失败；前端 `feedback.ts` 的 `HTTP 40[0-4]` 预筛还会把它误判为「确定性故障」，给出「重试无效」的错误引导 | 等几分钟错峰重试；长任务点「重试任务」续传（已生成片段保留 video id，不重复提交）；降时长/分辨率或换视频模型；多 Key 可线性提升配额，或用 `AGNES_VIDEO_RATE_LIMIT` 主动放慢提交；持续失败再附 `GET /api/tasks/{id}/diagnostics` 反馈。**已记录为已知缺口**（瞬态业务码应纳入退避重试 + 前端不应归类为确定性故障），本轮按外部故障处理，未改代码 | #63      |
| Issue 正文只有一段视频提示词（无报错、无环境、无复现步骤，标题多为乱码或 "first"），期望维护者代跑生成                                                                                             | 用户把开源仓库的 Issue 当成在线生成入口；本项目是**自托管工具**，服务端不代用户执行任务                                                | 按垃圾噪音关闭（`--reason not_planned`，不展开回复）；已补 FAQ 双语条目「贴提示词到 Issue 能生成视频吗」+ `.github/ISSUE_TEMPLATE/config.yml` 的 contact_links 指向本地部署与官网在线体验 | #39, #41, #48, #51, #52 |
| 桌面版长视频（creative/manuscript）里角色不开口说话，只有一段旁白；而网页在线版能看到角色原声 | 流水线默认跑 TTS 旁白（narration）+ 字幕叠加，`concat_videos_with_audio_overlay` 用旁白/静音轨覆盖并替换掉视频模型自带音频 | 关闭「启用旁白配音」（Audio → Enable narration=off），并尽量同时关字幕，让每个片段保留模型生成音；在视频提示词里直接描述角色说话（"the character says, '…'"）驱动模型自带口型与声音。注意：Agnes 视频模型自带音频质量/口型弱于画面，长多场景视频尤甚，属模型限制；要清晰台词仍用 TTS 旁白更稳 | #58 |

***

## 四、范围与后续迭代

* **本版为初版**：先跑通「查看 → 分析 → 沟通 → 回复/修复 → 归档」闭环，最小可落地。

* **后续可迭代方向**（未实现，仅记录）：

  * 自动化：定期扫描 open issue 并生成待处理清单。

  * 分类机器人：为 issue 打标签（bug / 需求 / spam）。

  * 处理 SLA 与升级机制。

  * 从归档表自动生成 FAQ 草稿。

