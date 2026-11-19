# v8.3 长任务模式（Long Task Mode）PRD

> 状态：🟢 已实施
> 关联：`docs/plans/v7.7/fast_retry_PRD.md`（快速重试）、`docs/plans/v8.0/fast_retry_auto_PRD.md`（自动快速重试）
> 用户诉求原话（2026-11-19）：
> 「除 503 外的其他失败，保持现有重试节奏，不用改；增加一个"长任务模式"开关，和快速重试开关放一起，
> 搭配一个超时时间配置。默认 1 小时。开启时，重试模式改为：保留现有重试频率的基础上，时间延长到配置的
> 超时时间。注意，一些明确已无法重试的报错，不再进行重试，向用户返回最终结果。报错和结果信息的关系
> 维护一份数据，后期可能根据用户反馈补充。对于重试能成功的场景，则一直重试到用户配置的时间，或任务成功。」

---

## 一、问题

队列饱和（503 `video_queue_full`）时，忙轨默认按次数封顶（`AGNES_VIDEO_BUSY_RETRY_ATTEMPTS`，
默认 15 次）。单 Key 下约等于 15 分钟，多 Key 下更短。用户愿意为一个长视频任务等 1 小时，
但当前没有「延长等待」的手段：快速重试只能加快节奏（3 分钟窗口），不能延长总预算。

同时存在另一类问题：**明确不可能成功的报错**（401 Key 无效、400 参数被拒、404 接口不存在…）
也会被当成可重试错误反复打，既浪费配额也拖延用户拿到最终结论的时间。

## 二、范围

### 2.1 做什么

1. 新增任务级开关「长任务模式」，与快速重试开关放在同一个面板（进度页 `FastRetryPanel`）。
2. 配套超时时间配置，**默认 60 分钟**（5–480 分钟，步进 5）。
3. 开启后：**重试节奏完全不变**（忙轨仍是首跳 0s + 固定 30–60s；若同时开了快速重试，仍按 x 次/分钟），
   只把「次数封顶」换成「累计等待时长封顶」。
4. 新增错误分类表：命中「不可重试」的报错立即结束重试，向用户返回结构化最终结果。
5. 任务成功即结束长任务模式（预算不再消耗）。

### 2.2 不做什么

- 不改故障轨（非忙 5xx / 超时 / 连接错误）的节奏与次数：用户明确要求「除 503 外的其他失败保持现状」。
- 不改轮询阶段（`_poll_task`）的 10 次连续失败预算与自适应间隔。
- 不改图片 / 上传 / Chat 的重试策略（`AGNES_BUSY_RETRY_ATTEMPTS` 保持原样）。
- 不引入全局「所有任务默认长任务模式」的开关（首版只做任务级，避免默认放大等待）。

## 三、时间预算口径（关键约定）

**预算 = 累计「忙轨等待时长」，不是墙钟时长。**

- 每收到一次忙信号，按 `BusyTracker.waited_s` 的增量累加进 `long_task.waited_s`；
- 视频渲染、分镜生成、TTS、拼接等非等待时间**不计入**；
- 多段流水线（creative / manuscript / anchor / poetry）跨段累计，一个任务只有一个预算；
- 累计值 ≥ `timeout_minutes × 60` 时：关闭长任务模式（`enabled=False`），
  `finished_reason="expired"`，并在下一次忙信号处按现有逻辑抛出队列满最终结果。

为什么不用墙钟：creative 单段渲染就要几分钟到十几分钟，墙钟口径会让「成功渲染」反过来吃掉等待预算，
与用户直觉（我等了多久）不一致。

## 四、错误分类表（可扩展数据）

唯一出处：`core/api/error_taxonomy.py::ERROR_RULES`。
每条规则包含 `retryable` / `reason`（稳定 id，用于统计）/ `message_key`（用户可见最终结果的 22 语言 key）。

| 条件 | 可重试 | reason | 用户结果 key |
|---|---|---|---|
| HTTP 429 | ✅ | `rate_limited` | —（忙轨，继续重试） |
| HTTP 503（含裸 503） | ✅ | `service_busy` | — |
| body code `video_queue_full` / `fail_to_fetch_task` | ✅ | `queue_full` | — |
| HTTP 408 / 425 | ✅ | `request_timeout` | — |
| 其他 5xx | ✅ | `server_error` | — |
| HTTP 401 | ❌ | `auth_invalid` | `error.video.fatal_auth` |
| HTTP 403 | ❌ | `forbidden` | `error.video.fatal_forbidden` |
| HTTP 404（提交阶段） | ❌ | `not_found` | `error.video.fatal_not_found` |
| HTTP 413 | ❌ | `payload_too_large` | `error.video.fatal_too_large` |
| HTTP 422 | ❌ | `invalid_parameter` | `error.video.fatal_bad_request` |
| HTTP 400 + code 命中内容审核类 | ❌ | `content_blocked` | `error.video.fatal_content` |
| HTTP 400（其余，`num_frames` 降帧特例在 API 层先处理） | ❌ | `bad_request` | `error.video.fatal_bad_request` |
| 其他 4xx | ❌ | `client_error` | `error.video.fatal_client` |
| 未知 / 无状态码 | ✅（保守） | `unknown` | — |

扩展方式：在 `ERROR_RULES` 里加一条 `ErrorRule`，或在 `CODE_RULES` 里补 code；
新增 `message_key` 时需同步 `core/i18n_backend.py`（zh/en）与前端 `langs/*.json`。

## 五、交互

两层结构与「快速重试」一致：

- **设置页（全局默认）**：新增「05 长任务模式」区块，开关 + 默认超时（分钟，默认 60）。
  开启后**新建的视频任务自动带上**长任务模式与默认超时（`TaskManager.create` 时应用一次）。
  端点 `POST /api/config/long-task`，`GET /api/config` 下发 `long_task`。
- **进度页（本次任务）**：紧邻「快速重试」面板。未开启时出现「超时 + 开始」入口，
  点击即开启；开启后只显示状态（已等待 / 剩余 / 到期原因），**不再提供关闭入口**——
  关闭统一走设置页，避免误关后长任务白等。任务失败后面板随进度页隐藏。
- 与快速重试相互独立，可同时开启：快速重试决定「多久打一次」，长任务模式决定「总共等多久」。

## 六、验收

| 编号 | 场景 | 预期 |
|---|---|---|
| LT1 | 开启 60 分钟，上游持续 503 | 不再在 15 次后失败，持续重试到累计等待 60 分钟 |
| LT2 | 等待 20 分钟后成功 | 任务成功，长任务模式停止消耗预算 |
| LT3 | 开启 + 快速重试同时开 | 按 x 次/分钟连打，直到成功或累计等待到期 |
| LT4 | 上游返回 401 | 立即失败，文案为 `error.video.fatal_auth`，不重试 |
| LT5 | 上游返回 400 参数错误 | 立即失败，文案 `error.video.fatal_bad_request`，不降帧重试（`num_frames` 除外） |
| LT6 | 未开启长任务模式 | 行为与升级前完全一致（15 次忙轨后失败） |
| LT7 | 续传 | `enabled` / `timeout_minutes` 保留，`waited_s` 与 `started_at` 重置 |
