# 快速重试自动模式 PRD（设置页全局开关 + 任务页「以后自动」）— v8.0

> **状态**：🟢 已实施（2026-11-11）
> **前置方案**：`docs/plans/v7.7/fast_retry_PRD.md`（快速重试模式本体）
> **回归**：`docs/dev/regression_test_plan.md` §十七（`FR*`）

---

## 一、背景

v7.7 的快速重试是**逐任务、需手动触发**：连续 2 次忙信号（503 / 队列满）后进度页
出现开关，用户点开才按「每分钟 x 次、持续 y 分钟」连打。实测（2026-11-06）503 阶段
被拒请求免费、不耗配额，因此提高探测频率是安全且有效的——但它依然要求用户**守在
页面前点一下**，队列饱和时段（多发生在夜间/高峰）没人点就白等。

## 二、需求（用户原话拆解）

1. 设置页加开关，配置快速重试的**开启**与**频率**；
2. 设置页开启后，到条件（连续 2 次忙信号）**自动执行**，不再需要用户点；
3. 未开启（设置页关闭）时，任务详情页现有的配置**仍然保留**；
4. 任务详情页加一个开关，让用户选择「一次性执行」还是「永久打开自动开关」；
5. 用户什么都不点时，保持之前的**慢速重试**继续跑（零行为变化）。

## 三、方案

### 3.1 两层配置

| 层 | 位置 | 作用域 | 内容 |
|---|---|---|---|
| 全局设置 | 设置页 → `04 快速重试` | 跨任务、跨进程持久化（`config.json` → `fast_retry`） | `auto` / `per_minute` / `minutes` |
| 任务状态 | 任务状态 → `fast_retry` | 单任务单轮运行 | 本次是否自动（`auto`）、已打次数、收尾原因、是否手动关过（`auto_off`） |

全局 `auto=True` ⇒ 任意任务连续 2 次忙信号后**直接**进入快速重试，参数取全局 x / y。
全局 `auto=False`（默认）⇒ 行为与 v7.7 完全一致（只有开关，不自动开）。

### 3.2 状态机（增量）

```
idle ──(连续 2 次忙信号)──┬─ 全局 auto=True 且未 auto_off → active(auto=True)，立即连打
                          └─ 否则 → available（等用户点）

available ──(用户点开 + remember)──> active(auto=False) + 写入全局 auto=True
available ──(用户点开，不 remember)──> active(auto=False)    # 一次性

active ──(用户关闭)──> disabled + auto_off=True   # 本轮不再被自动模式拉起
active ──(到期)──────> expired + auto=False + consecutive_busy=0  # 需重新累计 2 次（天然冷却）
active ──(提交成功)──> success + auto=False + available=False
```

要点：

- **手动关闭优先**：`auto_off=True` 后本任务内不再自动开启（否则「关了又自己开」）。
  续传视为新一轮，由 resume 的 reset 逻辑一并清零 `auto` / `auto_off`。
- **到期冷却**：到期清零 `consecutive_busy`，自动模式需重新累计 2 次忙信号才会再开，
  避免「到期即重开」变成无缝连打。

### 3.3 契约

| 端点 | 变更 |
|---|---|
| `GET /api/config` | 新增 `fast_retry: {auto, per_minute, minutes}` |
| `POST /api/config/fast-retry` | 新增：`auto`（bool）、`per_minute`、`minutes`（0 = 保留原值）；越界 422，其余收敛 |
| `POST /api/tasks/{id}/fast-retry` | 新增可选 `remember`（bool）：`enabled=true` 时把本次 x / y 写入全局并置 `auto=True`；响应新增 `fast_retry_settings` |
| 任务状态 | `fast_retry` 新增 `auto` / `auto_off`（旧 task_state.json 自动补默认） |

### 3.4 前端

- **设置页**（`ConfigPanel.vue`）：新增 `04 快速重试` 面板 = 自动开关 + x / y 输入 + 保存；
  折叠标题行展示「自动 · x 次/分」或「未开启自动」（隐私设置编号顺延为 `05`）。
- **任务进度页**（`FastRetryPanel.vue`）：
  - 未开启：保留 x / y 输入与开启按钮，新增「以后自动开启（保存到设置）」勾选
    （不勾 = 一次性；勾 = 同时写全局）；
  - 全局已开启：不再显示该勾选，改显示「设置页已开启自动快速重试」提示；
  - 运行中：增加「自动」筹码，区分自动/手动来源。

### 3.5 隔离性

- 全局 `auto` 默认 `False`：不配置时任何行为与 v7.7 一致（零回归）。
- 自动模式只替换**忙轨等待节奏**：不改 `retry_policy` 两轨判定、不改次数上限、不改令牌桶；
  快速模式期间仍不消耗常规忙轨次数、不占共享视频提交桶。
- 图片 / 上传 / Chat 忙轨完全不涉及。
- 单测用 autouse 夹具隔离真实 `config.json`，避免开发机开了自动模式导致用例误判。

## 四、验收

1. 设置页开启自动 → 任务连续 2 次 503 后日志出现
   `[FastRetry] Task ...: started automatically x=.../min`，进度页显示「自动」；
2. 设置页关闭自动 → 与 v7.7 一致（出现开关、需手动点）；
3. 任务页勾「以后自动」开启 → 设置页立即显示已开启且频率一致，后续任务自动连打；
4. 自动模式进行中手动关闭 → 本轮不再自动重开，慢速重试继续；
5. `pytest tests/test_fast_retry.py` 全绿，`npm run build` 通过。

## 五、实施记录

| 文件 | 变更 |
|---|---|
| `core/config.py` | `get_fast_retry_config()` / `set_fast_retry_config()`（延迟导入 `clamp_params` 规避 config ↔ api 循环依赖） |
| `models/task.py` | `FastRetryConfig` 新增 `auto` / `auto_off` |
| `core/pipelines/__init__.py` | 钩子新增自动分支、`_auto_params()`、`_start_fast_retry()`；到期清零连续计数；成功清 `auto` |
| `web/routes/config_routes.py` | `GET /api/config` 下发 `fast_retry`；新增 `POST /api/config/fast-retry` |
| `web/routes/task_routes.py` | `remember` 参数、`auto` / `auto_off` 维护、响应带 `fast_retry_settings`、resume 重置扩展 |
| `core/i18n_backend.py` | 新增 `progress.video.fast_retry.auto`（zh/en） |
| 前端 | `types.ts` / `store.ts` / `App.vue` / `api/index.ts` / `useConfig.ts` / `useProgress.ts` / `ConfigPanel.vue` / `FastRetryPanel.vue` + 22 语言 11 个新键 |
| 测试 | `tests/test_fast_retry.py` 新增自动/抑制/到期/全局设置/remember 用例 + 配置隔离夹具 |
