# v8.3 增量设计：长任务模式 + 错误分类表

> 配套：`docs/plans/v8.3/long_task_mode_PRD.md`（需求与验收）
> 原则：**默认零回归**——两个钩子默认 `None`、状态字段默认 `False`，未开启时行为与 v8.2 完全一致。

## 一、模块

| 文件 | 变更 |
|---|---|
| `core/api/error_taxonomy.py` | 新增：错误分类表 + `classify()`（唯一出处） |
| `core/api/long_task.py` | 新增：长任务模式的钩子协议、参数边界、默认值 |
| `models/task.py` | 新增 `LongTaskConfig`，挂在 `BaseTaskState.long_task` |
| `core/api/agnes_video.py` | 新增 `long_task_hook`、`UpstreamFatalError`；忙轨封顶处问钩子；不可重试错误直接抛 |
| `core/pipelines/__init__.py` | 新增 `_PipelineLongTaskHook`；`_attach_fast_retry` 一并注入 |
| `web/routes/task_routes.py` | 新增 `POST /api/tasks/{id}/long-task`；resume 重置计时 |
| `utils/network.py` | 新增 `describe_fatal_error()` / `fatal_error_message_params()` |
| `core/pipelines/simple_video.py`、`multi_scene.py` | 失败分支接入上面的结构化文案 |
| `core/i18n_backend.py` | 新增 `error.video.fatal_*`、`progress.video.long_task.*`（zh/en） |
| 前端 | `types.ts` / `api/index.ts` / `useProgress.ts` / `FastRetryPanel.vue` / 22 语言 |

## 二、状态模型

```python
class LongTaskConfig(BaseModel):
    enabled: bool = False
    timeout_minutes: int = 60      # 5–480
    waited_s: float = 0.0          # 累计忙轨等待（跨段累计）
    started_at: str = ""           # 首次忙信号时刻（仅展示/排查）
    finished_reason: str = ""      # "" | expired | success | non_retryable | disabled
    last_reason: str = ""          # 最近触发终态的分类 reason（统计用）
```

## 三、钩子协议（duck typing）

```python
class Hook:
    def notify_busy(self, payload: dict) -> None: ...
        # 每次忙信号调用：payload = {status, code, retries, waited_s}
        # 实现累计 waited_s（按 waited_s 增量，跨段用「回绕视为新 tracker」处理）

    def allow_extend(self, payload: dict) -> bool: ...
        # 常规忙轨次数耗尽时调用；True = 继续重试，False = 按现有逻辑抛最终结果

    def on_fatal(self, reason: str) -> None: ...     # 不可重试错误即将抛出（可选）
    def on_success(self) -> None: ...                # 提交成功（可选）
```

`AgnesVideoAPI.long_task_hook = None` 时：`notify_busy` / `allow_extend` 全是空操作，
忙轨封顶与异常路径与 v8.2 逐字一致。

## 四、API 层数据流（`_submit_with_retry`）

1. 收到 429/503/队列码 → `classify()`：
   - `retryable=False` → `collect_error` + `hook.on_fatal()` → 抛 `UpstreamFatalError`；
   - `retryable=True` → `hook.notify_busy({..., waited_s: busy.waited_s})` → 快速重试判定 → 常规忙轨。
2. 忙轨次数耗尽（`busy.exhausted()`）：
   - `hook.allow_extend(payload)` 为真 → 打日志、`busy.retries += 1`、按 `busy_delay` 继续；
   - 否则保持原逻辑（`AgnesQueueFullError` / `RuntimeError`）。
3. 故障轨 / 兜底 `raise` 前同样先 `classify()`，不可重试则抛 `UpstreamFatalError`。

`UpstreamFatalError` 携带 `fatal_reason` / `fatal_status` / `fatal_code` / `fatal_message_key` /
`fatal_message_params`，流水线据此下发 `current_message_key` + `current_message_params`，
前端用 22 语言渲染；后端 `CATALOG` 只给 zh/en 兜底句。

## 五、端点

`POST /api/config/long-task`（全局默认，设置页）

| 参数 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | 新任务是否默认开启 |
| `minutes` | int | 默认超时（0 = 保留原值；5–480，越界 422） |

`TaskManager.create()` 里通过 `core.config.get_long_task_config()` 应用一次：
视频类任务写入 `long_task.enabled/timeout_minutes`，图片任务跳过；配置损坏静默跳过，
绝不影响建任务。`GET /api/config` 同步下发 `long_task`。

`POST /api/tasks/{task_id}/long-task`

| 参数 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | 开 / 关 |
| `timeout_minutes` | int | 0 = 沿用当前值（默认 60）；合法区间 5–480，越界 422 |

响应：`{"ok": true, "task_id": ..., "long_task": {...}}`。

隔离性：只改 `state.long_task`，不改 `fast_retry`，不重启流水线。

## 六、前端

> 回填时序（v8.3.1 修复）：`/api/config` 由 App 启动时**异步**拉取，而设置页组件
> `setup` 早于它返回（子 setup → 父 onMounted）。因此设置页必须用 `watch(appState.xxx)`
> 回填开关，不能只在 setup 一次性调用，否则刷新/重启后开关停在默认值（表现为
> 「保存无效」）。`GET /api/config` 同时加了 `cache: 'no-store'`，避免浏览器启发式缓存。

- `FastRetryPanel.vue` 增加长任务区块；`visible` 条件扩展为
  `enabled || available || long_task.enabled || long_task.finished_reason`。
- 轮询周期：长任务模式不改变现有 30s 常规轮询（不需要秒级刷新）。
- 埋点：`data-track="long_task_toggle"`，参数 `{to: 'on'|'off'}`，与 v8.2 契约一致。

## 七、风险与兜底

| 风险 | 兜底 |
|---|---|
| 钩子异常打断提交循环 | API 层 `try/except` 吞掉，`allow_extend` 失败按「不允许延长」处理 |
| 长任务模式让用户无限占位 | 上限 480 分钟；到期自动关闭并给出队列满最终结果 |
| 分类表误判导致本可重试的错误直接失败 | 未知状态码/未知 code 一律按可重试处理；仅 4xx（除 408/425/429）判定不可重试 |
| 续传后重复计预算 | resume 重置 `waited_s` / `started_at`，保留 `enabled` 与 `timeout_minutes` |
