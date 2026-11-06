# 轮询健壮性修复（v7.8）— 任务数据恢复实录

> **状态**：🟢 已实施并端到端验证（2026-11-06）
> **触发**：用户任务 `d5abb609fb3e` 提交成功后服务重启，本地状态冻结在
> `video_gen`，页面一直显示「等待视频生成」。排查发现轮询侧三个问题。
> **关联**：`docs/dev/agnes_video_upstream_behavior.md` §8（Key 与域名严格配对 / 任务级 Key 绑定）

---

## 一、实测现象与根因

| 观测 | 结论 |
|---|---|
| 服务日志 `17:35:37 Shutting down gracefully (Ctrl+C)`，之后无轮询日志 | 进程被外部终止，不是轮询崩溃；上游任务成了「没人轮询」的孤儿 |
| 用 3 把 Key 查同一个 `video_id`：key2 `…lMbx` → 200，key1 `…nNFM` → 404 `task not found`，key3 `…j5ak`（cn 站）→ 404 `任务不存在` | **上游视频任务按账号/Key 隔离**，同站点不同账号也查不到 |
| `_task_keys` 是内存 dict，提交时的绑定没有落盘 | 进程重启 / resume 后绑定丢失，`ring.next()` 随机挑一把 → 约 2/3 概率 404 |
| U9 把 404 一律当「网关记录入库延迟」：不换 Key、不消耗失败配额、不报错 | 错 Key 导致的 404 被无限容忍，一直轮询到 `AGNES_VIDEO_POLL_TIMEOUT`（1800s）才超时 |
| `simple_video.py` 提交/恢复两条路径的 `wait_for_video(video_id)` 都不传 `progress_callback`；`_emit` 只推一次且进度固定；`_poll_task` 每 10 次才打一行日志 | 上游明明有 `status/progress`，前端与日志都看不到 → 看起来像卡死 |

## 二、修复（全部是可选钩子，未注入时零回归）

### 2.1 Key 绑定持久化

- `BaseTaskState.video_key_hints: dict[str, str]`：`video_id → sha256(Key)[:16]` 指纹，**不落明文**；旧 `task_state.json` 加载自动补 `{}`。
- `AgnesVideoAPI._remember_task_key()` 提交成功时回调 `on_task_key_bound(video_id, key)`；
  `BasePipeline._on_task_key_bound()` 写入状态并落盘（上限 128 条，长视频多场景兜底）。
- `wait_for_video()` 的 Key 解析顺序：显式 `key` → 内存 `_task_keys` → `key_hint_resolver(video_id)`（按指纹在当前 Key 池反查）→ `None`（交给 2.2 探测）。
- 钩子经 `BasePipeline._attach_fast_retry()` 一次性注入，5 个流水线构造点无需改动；`AgnesVideoAPI` 上三个新属性默认 `None`。

### 2.2 404 分流：Key 归属探测

- **仅当** `pinned_key is None` 且第一次 404 时，做一次只读探测 `_probe_owner_key()`：
  对 Key 池每把 Key 各查一次，返回第一个 HTTP 200 的 Key。
- 命中且不等于当前 Key → 打 `[KeyBind]` 日志、固定 `poll_key` / `pinned_key`、按该 Key 的域名重建 `poll_url`，**立刻重查**（不额外 sleep）。
- 全部 Key 都 404 → 打 WARNING 并**保留 U9 语义**（不误伤高峰期真实的入库延迟，总超时兜底不变）。
- 已有绑定（内存或指纹恢复）时**不探测**，避免每次 resume 多发 N 个请求。

### 2.3 轮询可观测性

- `poll_progress_hook(video_id, status, progress, elapsed)` 每轮由 `_poll_task` 调用；
  `BasePipeline._on_poll_progress()` 按「状态变化 或 每 ≥25s」节流，推送
  `progress.video.polling {status} {t} {vid}`（后端 zh/en 兜底 + 前端 22 语言）。
- 轮询日志从 `poll_count % 10` 改为 `% 5`，并带上所用 Key 尾号；404 周期日志同步改 `% 5`。
- `retry_policy`、令牌桶配置、忙轨/故障轨判定、自适应间隔全部**未改动**。

## 三、真实任务恢复实录（未新建任何任务）

上游此时已生成完成：`status=completed / progress=100 / url=.../task_hlYHKOl86yN... .mp4`。

```
17:55:10 [Pipeline] Starting run for task d5abb609fb3e, type=TaskType.SIMPLE
17:55:10 [Simple]   Resuming from saved task.json video_id: task_hlYHKOl86yN...
17:55:10 [AgnesVideo] 无提交 Key 记录（进程重启或旧任务）...
17:55:10 [AgnesVideo] Polling ... (poll #1, elapsed 0s, key=...nNFM)
17:55:11 [AgnesVideo] not yet visible (404 task not found), poll #1
17:55:12 [KeyBind]   归属 Key 探测命中 (key=...lMbx, domain=https://apihub.agnes-ai.com)
17:55:12 [KeyBind]   404 系 Key 错配，已探测到所属账号并固定改用该 Key 轮询
17:55:13 [AgnesVideo] status=completed progress=100%
17:55:13 [AgnesVideo] Done: https://platform-outputs.agnes-ai.space/videos/...
17:55:17 [Watermark] Processing final_video.mp4 (1280x720, lang=zh) via ffmpeg overlay
17:55:19 [Watermark] Complete
17:55:19 [Pipeline] Completed run for task d5abb609fb3e
```

结果：`status=completed` / `progress=1.0` / `final_video_file=.../final_video.mp4`
（**1.92 MB，10.144s**），未重新提交视频、未消耗额外渲染配额。

> 该任务是修复前提交的，状态里没有指纹（`video_key_hints={}`），因此走的是
> 「404 归属探测」兜底路径；此后新提交的任务会把指纹落盘，连探测都省掉。

## 四、验收

| 项 | 证据 |
|---|---|
| 指纹落盘（非明文）/ resume 反查 / Key 被删时降级 | `tests/test_poll_key_binding.py::test_bind_persists_fingerprint_not_plaintext` / `test_resolve_restores_key_after_restart` / `test_resolve_missing_key_falls_back_to_probe` |
| 404 → 探测 → 固定切换 → completed | `test_poll_404_switches_to_owner_key_and_completes` |
| 全部 404 保留 U9 语义 / 有绑定不探测 | `test_poll_all_keys_404_keeps_u9_semantics` / `test_pinned_key_skips_owner_probe` |
| 进度透传与节流 / 零回归 | `test_poll_progress_hook_is_attached_and_throttled` / `test_no_hooks_is_zero_regression` |
| 全量回归 | `pytest tests/` 全绿；`i18n_check` exit 0；`npm run build` 通过 |
| 端到端 | 见第三节真实任务恢复 |

## 五、仍不做的事

- 服务重启后**自动 resume** 未完成任务（部署层，需评估是否会误恢复历史 pending 任务，涉及资源消耗，另立计划）。
- 404 单独设时长上限：目前仍由 `AGNES_VIDEO_POLL_TIMEOUT` 总闸兜底；有了 Key 探测后「错 Key 无限等」已消除，真实入库延迟仍按 U9 容忍。
