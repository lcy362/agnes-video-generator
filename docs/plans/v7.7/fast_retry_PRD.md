# 快速重试模式（Fast Retry）PRD — v7.7

> **状态**：🟢 已实施（2026-11-06）
> **触发词**：快速重试、503 连打、提高重试频率
> **关联**：`docs/dev/agnes_video_upstream_behavior.md` §4 / §4.1、`docs/plans/v7.0/upstream_error_handling_plan.md` U1/U7

---

## 一、背景与实测依据

v7.2 起忙轨采用「首跳 0s 贴限流 + 之后固定 30–60s + 次数封顶 15」。实测发现两个事实：

| 实测（2026-11-06，本机 3 Key / com+cn 双站点） | 结论 |
|---|---|
| 单 Key 背靠背连打 26 次，全部 503 `video_queue_full`，零 429 | **503 阶段提频不会触发限流**；被拒不建任务、不耗渲染配额 |
| 3 Key + 两个域名在同一秒全部 503 | 队列是**按模型全局分池**，不按 Key、不按站点隔离 → 换 Key 不会立刻排进队 |
| 忙轨第 3 跳起间隔恒为 30–60s，与 Key 数无关 | 多 Key 对重试频率**毫无加速**（只有首跳受益） |
| `stream` / `stream_options` / `webhook` / `callback_url` / `async_mode` 一律 400 `not an allowed request field` | 提交接口无流式/回调能力，「stream 更易 503」不适用于本上游 |

结论：既然被拒请求是免费的、且不会触发限流，那么在队列饱和时**把探测频率提到用户需要的水平**是安全且有效的（更早捕获空位）。缺的只是一个「用户说了算」的加速开关。

## 二、需求（用户原话拆解）

1. 连续两次 503 之后，页面上出现开关；
2. 用户可开启，开启后即**快速连打**；
3. 可配置「每分钟 x 次」+「持续 y 分钟」；
4. 提交成功或到达 y 分钟后，恢复**正常模式**；
5. **不干扰其他逻辑**。

## 三、行为定义

### 3.1 状态机（`FastRetryConfig`，挂在 `BaseTaskState.fast_retry`）

```
idle ──(连续 2 次忙信号)──> available ──(用户开启)──> active
                                  ↑                      │
                                  └──(到期 expired)──────┤
                                                         ├─(提交成功)──> success（清 available）
                                                         └─(用户关闭)──> disabled
```

| 字段 | 含义 | 默认 |
|---|---|---|
| `available` | 连续 2 次忙信号后 True，前端据此显示开关 | False |
| `enabled` | 用户已开启 | False |
| `per_minute` | 每分钟次数 x（1–120） | 30（`AGNES_FAST_RETRY_PER_MINUTE`） |
| `minutes` | 持续分钟数 y（1–30） | 3（`AGNES_FAST_RETRY_MINUTES`） |
| `consecutive_busy` | 连续忙信号计数（成功清零） | 0 |
| `attempts` | 快速模式期间**已发出的请求次数**（含成功那跳，面板显示「已发 N 次」） | 0 |
| `started_at` | 开启时刻（本地 ISO，用于到期判定） | "" |
| `finished_reason` | `success` / `expired` / `disabled` | "" |

### 3.2 节奏

- 快速模式间隔 = `max(0.5, 60 / x)` 秒；
- 快速模式期间**跳过共享视频提交令牌桶**（否则 x 次/分钟无法兑现，且不会抢占其他任务配额）；
- 快速模式期间**不递增**常规忙轨次数（`BusyTracker.retries` 保持不变），否则 15 次额度会在几分钟内烧光；
- 到期/关闭后原样回到常规忙轨（重新取桶、继续消耗剩余次数）；
- 仍受 `shutdown_event`（用户停止）与 `max_retries` 循环边界约束。

### 3.3 触发条件

只有 `is_busy_signal()` 命中（429 / 所有 503 / `video_queue_full`、`fail_to_fetch_task`）才计一次「忙信号」。故障轨（非忙 5xx / 超时）不参与计数。

## 四、接口契约

```
POST /api/tasks/{task_id}/fast-retry
Content-Type: multipart/form-data
  enabled: bool (required)
  per_minute: int = 0   # 0 = 用后端默认
  minutes: int = 0      # 0 = 用后端默认

200 → {"ok": true, "task_id": "...", "fast_retry": {...最新字段...}}
400 → 任务不存在 / 未到 available（"连续 2 次 503 后开放"）
422 → 参数越界（1–120 次/分，1–30 分钟）
500 → 落盘失败
```

`GET /api/tasks/{id}` 的 `fast_retry` 字段随任务状态下发，前端 30s 轮询读取。

## 五、隔离性设计（对应需求 5「不干扰其他逻辑」）

| 位置 | 改动方式 | 未开启时的行为 |
|---|---|---|
| `core/api/retry_policy.py` | **未改动** | 判定与两轨间隔完全不变 |
| `core/api/rate_limiter.py` | **未改动** | 令牌桶配置不变（快速模式只是「不取令牌」，不改桶） |
| `core/api/agnes_video.py` | 新增可选属性 `fast_retry_hook`（默认 None）+ 忙轨分支前置判定 | `hook is None` → 与升级前逐行一致（单测 `test_no_hook_keeps_original_busy_track` 锁定） |
| 流水线 | 5 个提交点所在类构造时 `_attach_fast_retry(api)` | 只是挂一个读任务状态的钩子，不改变提交参数 |
| 任务状态 | 新增 `fast_retry` 字段（有默认值） | 旧 `task_state.json` 加载自动补默认（已验证） |

钩子异常一律被捕获并退化到常规忙轨（`test_hook_errors_do_not_break_submission`）。

## 六、可观测性

| 位置 | 内容 |
|---|---|
| 日志前缀 | `[FastRetry]`（available / expired / success / attach / persist 失败） |
| **逐跳请求日志** | `[FastRetry] probe #N → POST <url> \| key=<脱敏> \| payload=<完整字段，prompt 截断至 80 字>` |
| **逐跳响应日志** | `[FastRetry] probe #N ← HTTP <code> in <耗时>s \| body=<响应体前 400 字>` |
| 节奏日志 | `[AgnesVideo] ... fast mode active (probe #N, HTTP ...), next in <间隔>s (busy quota intact)` |
| 面板计数 | `fast_retry.attempts` 每 5 跳落盘一次（避免 30 次/分钟把状态文件写成每秒 2 次），到期/成功/关闭各落一次保证终值；前端随 30s 轮询刷新，最多滞后 5 跳 |
| 任务消息 | `progress.video.fast_retry.{available,active,expired,success,disabled}`（后端 zh/en 兜底 + 前端 22 语言） |
| `error_logs/` | 快速模式**降采样**：仅第 1 跳与每 20 跳落盘（否则 30 次/分钟 × 3 分钟会刷掉诊断目录轮转上限） |

## 七、验收

| 项 | 证据 |
|---|---|
| 状态机正确 | `tests/test_fast_retry.py`（available / active / expired / success / disabled） |
| 快速模式不取桶、不耗忙轨次数 | `test_fast_mode_skips_submit_bucket_and_keeps_busy_quota` |
| 到期回落常规 | `test_fast_mode_expiry_falls_back_to_normal_busy_track` |
| 零回归 | `test_no_hook_keeps_original_busy_track` |
| 端点校验 | `TestFastRetryEndpoint`（enable / 未 available 400 / 越界 422 / disable） |
| 落盘与向后兼容 | 真实 `TaskManager` 落盘 `available=true`；旧 JSON 加载默认值 |
| i18n | `python scripts/i18n_check.py` → exit 0 |
| 计数与逐跳日志 | `test_attempts_tracked_and_persisted_every_five_probes` / `test_expiry_keeps_attempts_for_review` / `test_success_with_probe_count` / `test_fast_mode_logs_every_request_and_response` |
| 前端 | `cd frontend && npm run build` 通过 |
| 全量回归 | `pytest tests/` 全绿 |
| **真实任务端到端**（用户 16:43 提交的 `d5abb609fb3e`，未新建任务） | 续传后按 30 次/分钟连打：逐跳 `probe #N → POST ...` / `← HTTP 503 ... body=...` 共 13 组，间隔 2.0s、3 Key 轮转（com/cn）、`fast_retry.attempts` 随状态增长；**第 13 跳命中队列空位 → HTTP 200**，`finished_reason=success` / `attempts=13` / `available=False`，任务进入视频生成。「到期回落」分支由单测 `test_fast_mode_expiry_falls_back_to_normal_busy_track` 与 `test_expiry_keeps_attempts_for_review` 覆盖 |

## 八、不做的事

- 不对**上传图片**、Chat、图片生成的忙轨开放快速模式（首期只覆盖视频提交）；
- 不做「自动开启」（必须用户点，避免默认行为变化）；
- 不改 `retry_policy` 的两轨判定与次数上限；
- 不做跨任务的全局断路器（进程级 queue_full 熔断留待后续评估，需要时另立计划）。
