# PRD: 三项稳定性加固（chat 超时与重试预算 / 稿件场景 prompt 失败隔离 / Windows 启动脚本对齐）

> **Status**: Implemented（Phase 1-3 已按本 PRD 落地，2026-09-22；Phase 1 采样未跑真实 API，按"出现 120-300s 区间成功/超时样本"预判实施联合调参；Phase 3 平台实测待 Windows 验证——两处均已记录在案）
> **Date**: 2026-09-20
> **Scope**: 三项改动均由本项目独立实现，仅借鉴问题定位与行为语义，不做代码级复用（见 §1.3）
> **Related docs**: `optimization_roadmap.md`、`docs/dev/regression_test_plan.md`、`AGENTS.md`
> **Related issues**: #35（manuscript 在 scene_prompts 环节失败）、#61/#62（story 环节失败，根因为 401，与本 PRD 无因果）

---

## 1. Background

### 1.1 问题来源

本 PRD 的三项改动，来自"同类产品功能形态的横向扫描 + 本项目代码逐行核对"两条线索的交叉结果：先抽象出同类产品在相应环节的典型行为，再回到本项目代码确认问题是否存在。**三项均已确认在当前 `master` 上未修复**（2026-09-20 逐行核对）。

横向扫描中一并发现的其他候选改动，处置如下（详见 §6）：

| # | 改动内容 | 处置 |
|---|---------|------|
| 1 | chat 读超时由 120s 提升至 300s | 本 PRD Phase 1（收敛为"超时 + 重试预算"联合调整） |
| 2 | 稿件场景 prompt 单段失败隔离 | 本 PRD Phase 2（补充控制流异常分类） |
| 3 | Windows 启动脚本：`py` 启动器回退 + 轮询就绪后再开浏览器 | 本 PRD Phase 3（与 `start.sh` 语义对齐） |
| 4 | 云端部署配置模板 | §6 Backlog |
| 5 | 前端构建 `base` 改为相对路径 | §6 Backlog（不建议） |
| 6 | 环境变量文件纳入版本控制 | 不采纳（存在误提交密钥的情形） |
| 7 | 垂直业务批量生成脚本 | §6 Backlog（业务适配层，仅借鉴形态） |

### 1.2 为什么这三项值得做

三项分别对应三类不同的缺口：

- **Phase 1（静默可靠性）**：`chat()` 的 120s 读超时与 `chat_multimodal()` 的 300s 不一致，长 prompt 场景存在中途被打断的可能。
- **Phase 2（可用性）**：稿件模式任一段场景描述生成失败即导致整个任务 FAILED，与项目"可续传"的设计目标相悖。
- **Phase 3（平台一致性）**：`start.sh` 已实现"轮询就绪后再开浏览器"，`start.bat` 仍是固定 `timeout /t 3`，Windows 用户是唯一没拿到该修复的群体。

### 1.3 处理原则

1. 三项均由本项目按现有架构独立实现；本文档只描述问题定位与目标行为，读者无需任何外部上下文即可理解与实施。
2. 若本 PRD 的取舍与常见做法不同（Phase 1 的联合调参、Phase 2 的控制流异常分类、Phase 2 拒绝降并发），**以本 PRD 为准**，并在实施记录中写明取舍理由。
3. 若某项改动源自社区反馈，按项目既有规范处理署名与来源记录（不在本 PRD 中列举）。

---

## 2. Goals / Non-goals

**Goals**

- **G1**：chat 长 prompt 调用的超时与重试策略不再出现"最坏等待时间过长且大概率仍失败"的形态。
- **G2**：稿件模式下单个段落的场景描述生成失败不导致整个任务 FAILED，失败段可经续传重试。
- **G3**：`start.bat` 与 `start.sh` 在"环境探测"与"就绪后再开浏览器"两项行为上语义对齐。

**Non-goals**

- 不调整稿件场景 prompt 的并发上限（`Semaphore(3)` 保持不变，理由见 §4.5）。
- 不涉及任何前端改动（Phase 3 只改 `start.bat`）。
- 不引入对照过程中发现的其他候选改动（云端部署模板、构建 `base` 变更、环境变量文件入库）。
- 不新增"任务级总超时预算"机制（记录在 §6 Backlog）。

---

## 3. Phase 1 — chat 读超时与重试预算联合加固

### 3.1 现状盘点

| 位置 | 现状 |
|------|------|
| `core/api/agnes_chat.py:112` | `_request_with_retry(self, payload, timeout: int = 120)` |
| `core/api/agnes_chat.py:190` | `chat()` 传 `timeout=120` |
| `core/api/agnes_chat.py:300` | `chat_multimodal()` 传 `timeout=300` |
| `core/api/agnes_chat.py:30-31` | `_MAX_RETRIES = 3`、`_RETRY_BASE_DELAY = 15` |
| `core/api/rate_limiter.py:268-327` | `request_with_key_rotation` 对 `ConnectionError/Timeout` 按 `retry_base_delay × (retries+1)` 退避，`retries < max_retries` 才重试 |

`chat()` 是 story / script / narration / 场景 prompt 的公共入口（`chat_json()` 内部也调用 `chat()`），因此其超时策略影响创意与稿件两条主线。

### 3.2 问题分析

按现有参数，单次 `chat()` 调用的最坏耗时（全部因读超时失败）为：

```
4 次尝试 × 120s + (15 + 30 + 45)s 退避 = 570s ≈ 9.5 分钟
```

（`max_retries = 3` 表示首试 + 3 次重试 = 4 次尝试。）

**若只把 `timeout` 提到 300 而不动重试**，最坏耗时变为 `4 × 300 + 90 = 1290s ≈ 21.5 分钟`——失败路径反而恶化，用户等待时间翻倍以上。这是本 Phase 必须一并处理的决策点。

关于"文本模型在长 prompt 下常超 120s"这一判断，**目前尚无本项目侧实测数据**，现有依据仅为现象层面的经验描述。因此本 Phase 的第一项工作不是改代码，而是采集数据（见 3.3）。

### 3.3 方案

**3.3.1 实测采样（前置，必须先行）**

对 story / script / narration / scene-prompt 四类真实调用各采样 ≥ 20 次，记录单次 `requests` 耗时，得出 P50 / P95 / max 与超时发生率。

- 若 **P95 < 120s 且无超时**：判定无需改超时，仅保留"超时类错误的专门日志"，本 Phase 以"不实施"结案（结论写入实施记录）。
- 若 **出现 120-300s 区间的成功样本或超时样本**：执行 3.3.2。

**3.3.2 超时与重试联合调整（推荐方案）**

1. 新增 `AGNES_CHAT_TIMEOUT`（默认 300），接入 `core/config.py` 的 typed Settings，`chat()` 读取该值（与 `chat_multimodal()` 的 300 保持一致，消除双标准）。
2. 给 `request_with_key_rotation` 增加**按异常类型区分重试上限**的能力：新增关键字参数 `timeout_retry_limit: int | None = None`，默认 `None`（行为完全不变，回归面为零）。仅 `chat()` 传入 `timeout_retry_limit=1`，即超时最多重试 1 次（5xx / 429 的重试上限不受影响）。
3. 调整后最坏耗时：`2 × 300 + 15 = 615s`，与现状 570s 基本相当，但**成功窗口从 120s 扩到 300s**，属于净收益。

**3.3.3 候选方案与取舍**

| 方案 | 最坏耗时 | 评价 |
|------|---------|------|
| A. 仅把 timeout 提到 300 | ≈ 21.5 分钟 | 不推荐，失败路径显著恶化 |
| B. 3.3.2 联合调整（推荐） | ≈ 10.3 分钟 | 成功窗口扩大，失败时长持平 |
| C. 不改，仅加超时日志 | 不变 | 3.3.1 判定"无超时"时的正确选择 |

### 3.4 验收标准

- `curl` 端到端跑通一个 creative 任务与一个 manuscript 任务（故事/脚本/旁白环节均成功），产物完整。
- `AGNES_CHAT_TIMEOUT` 未设置时行为与当前默认一致（除超时值）；设置非法值（非正整数）时回退默认并告警，不抛异常。
- `request_with_key_rotation` 的既有调用方（image / video / upload / poll）行为无变化：`timeout_retry_limit=None` 时重试次数与现状一致（用现有单测覆盖）。
- 单测新增：模拟 `requests.Timeout`，验证 `timeout_retry_limit=1` 时仅重试 1 次。

### 3.5 风险

| 风险 | 缓解 |
|------|------|
| 公共封装 `request_with_key_rotation` 被多处复用，改签名有连带风险 | 新参数默认 `None` = 现行为；仅新增分支，不改变既有控制流 |
| 长超时占用 worker（`asyncio.to_thread` 线程）导致并发下降 | 稿件场景 prompt 已有 `Semaphore(3)` 约束；实测阶段观察线程池饱和度 |
| 实测样本不足导致误判 | 每类调用 ≥ 20 次；记录原始耗时数据到调研附录，可复查 |

---

## 4. Phase 2 — 稿件场景 prompt 单段失败隔离

### 4.1 现状盘点

| 位置 | 现状 |
|------|------|
| `core/pipelines/manuscript_video.py:291` | `pending = [p for p in paragraphs if not p.scene_prompt]`（续传语义基础） |
| `core/pipelines/manuscript_video.py:298` | `sem = asyncio.Semaphore(3)` |
| `core/pipelines/manuscript_video.py:307-312` | 逐段调用 `generate_scene_prompt_for_paragraph`，结果直接 `strip()` 赋值 |
| `core/pipelines/manuscript_video.py:314` | `await asyncio.gather(*[_gen_one(p) for p in pending])`（无 `return_exceptions`） |
| `core/pipelines/manuscript_video.py:358-363` | `_generate_videos` 中无 `scene_prompt` 的段落已有 `skipping` 分支 |

即：当前实现"后续步骤已具备跳过能力"，但**场景描述这一步中一处 LLM 调用失败就会把整个任务打成 FAILED**，跳过逻辑永远没机会生效。这正是 issue #35 一类现象的结构性来源。

### 4.2 方案

**4.2.1 异常分类（本 PRD 的关键加固点）**

一种朴素实现是"凡 `BaseException` 即视为失败段"。本项目**不采用该边界**，因为它会误吞两类**控制流异常**，破坏已有语义：

- `asyncio.CancelledError`（`BaseException` 子类）——用户取消/服务关闭时不得被当成"某段失败"；
- `PipelineShutdown`（`core/pipelines/__init__.py:73`）与 `CheckpointPause`（同文件 `:78`）——流水线中止与手动模式暂停信号，吞掉会破坏停止/暂停语义（`_gen_one` 内的 `self._check_shutdown()` 正是抛 `PipelineShutdown` 的地方）。

因此分类策略为：

```python
results = await asyncio.gather(*(_gen_one(p) for p in pending), return_exceptions=True)

failures = []
for para, res in zip(pending, results):
    if isinstance(res, (asyncio.CancelledError, PipelineShutdown, CheckpointPause)):
        raise res                      # 中止类异常：继续向上传播，不隔离
    if isinstance(res, BaseException):
        para.scene_prompt = ""         # 业务失败：留空，交下游跳过 + 续传重试
        failures.append((para, res))
```

**4.2.2 行为定义**

1. 单段（部分）失败：任务继续，进度文案改为 `场景描述生成完成 (succeeded/total 段)`，失败段附 `，N 段失败可 resume 重试`。
2. 全段失败：显式 `raise`（不静默产出空片），异常信息含首个失败的段落 index 与原因。
3. 日志：逐段成功日志仅在 `scene_prompt` 非空时打印；失败汇总打一条 `warning`，含失败 index 列表与首个错误摘要（截断 200 字符）。
4. 返回值防御：`generate_scene_prompt_for_paragraph` 理论上可能返回 `None`/非 `str`，赋值前统一归一化为 `str`（`(prompt or "").strip() if isinstance(prompt, str) else ""`）。
5. **续传闭环验证**（本 Phase 的核心验收项）：失败段落 `scene_prompt` 为空串 → `task_manager.update_state(paragraphs=...)` 落盘 → 用户点续传 → `_split_text` 命中 resume 早退（`core/pipelines/manuscript_video.py:251-257`）复用已存段落 → `_generate_scene_prompts` 的 `pending` 过滤（同文件 `:291`）重新纳入该段 → 重新调用 LLM。

   `_build_scenes`（同文件 `:204-214`）会用空 `scene_prompt` 填充 `SceneTask`，`_generate_videos`（同文件 `:358-363`）依据空值跳过并在 `pending` 阶段不再提交——空值语义在链路上已自洽。

   **注意**：`save_prompts()`（`core/pipelines/__init__.py:398`）只做产物导出（供外部工具读取），**不参与状态恢复**，因此写入空 prompt 不会造成"续传被跳过"。实施时需在回归中确认这一点（避免后续有人误把 `save_prompts` 当恢复源）。

### 4.3 验收标准

- 构造 A/B/C 三段稿件，注入"B 段 LLM 调用抛异常"，验证：
  - 任务不 FAILED；A、C 段正常生成视频；B 段无 `scene_prompt` 并被 `_generate_videos` 跳过；
  - 状态落盘后 `paragraphs[B].scene_prompt == ""`；
  - 对同一任务执行续传且 B 段调用成功 → 仅 B 段被重新生成，A/C 不重复调用（用 mock 计数断言）。
- 注入"三段全部失败"→ 任务 FAILED，异常信息含首段 index。
- 注入 `PipelineShutdown`（模拟用户停止）→ 任务进入原有停止流程，不被当作"失败段"。
- 进度事件文案包含成功/失败计数。

### 4.4 风险

| 风险 | 缓解 |
|------|------|
| 吞掉中止类异常导致"停止/暂停失效" | 4.2.1 的显式重抛 + 专门的停止/暂停回归用例 |
| 失败段静默跳过，用户以为视频完整 | 进度文案与日志明确标注失败段数；全失败显式报错 |
| 空 prompt 落盘后被误认为"已完成" | 4.2.2 第 5 条的续传闭环用例固化为回归项 |

### 4.5 为什么不采用"降并发"的做法

对照过程中出现的另一种改法是"把 `Semaphore(3)` 降为 2"，理由为"模型响应变长后与限速桶叠加更易触发读超时"。本项目**不采用**，原因：

1. 共享限速桶配额随 Key 数线性缩放（见 `AGENTS.md` §6.2），多 Key 用户降并发是纯损失；
2. Phase 1 已把成功窗口从 120s 扩到 300s，直接针对同一根因；
3. 若实测仍显示并发导致超时，正确做法是把并发数做成配置项（`AGNES_SCENE_PROMPT_CONCURRENCY`，默认 3），而不是为所有用户硬编码降级。

该项作为 Phase 1 实测的观察指标：若 P95 超时与并发呈正相关，再另开小项实施可配置化。

---

## 5. Phase 3 — Windows 启动脚本与 `start.sh` 对齐

### 5.1 现状盘点

| 位置 | 现状 |
|------|------|
| `start.sh:122-139` | 已有 `wait_ready()`：最多 120 次 × 0.5s 轮询 `http://localhost:8765/`，就绪后才 `open` / `xdg-open` |
| `start.bat:24-37` | `where python` 判定，失败直接报错退出（未回退 `py` 启动器） |
| `start.bat:65` | `python -m venv "%VENV_DIR%"`（依赖 `python` 命令） |
| `start.bat:82-83` | `start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8765"`（固定 3s 延迟） |
| `start.bat:48-54` | 已有端口 8765 占用检查（良好，保留） |

两个问题：

1. **Windows 上 `python` 不可靠**：未安装官方安装器 / 仅装了 `py` 启动器，或 `python` 被 Microsoft Store 别名劫持时，`where python` 可能命中坏路径或直接失败，而 `py -3` 是官方推荐入口。
2. **固定 3s 延迟**：首次启动需建 venv + 装依赖（`start.bat:63-74`）耗时远超 3s；慢机器上浏览器打开即"无法访问"。`start.sh` 已经修掉这个问题，Windows 未同步。

### 5.2 方案

**5.2.1 Python 探测（`PY_CMD` / `PY_ARGS` 模式）**

在环境校验段引入两个变量，贯穿所有后续调用（venv 创建、版本检查；服务启动仍走 `%VENV_PYTHON%`）：

```bat
set "PY_CMD=python"
set "PY_ARGS="
where python >nul 2>nul || (
    where py >nul 2>nul && (set "PY_CMD=py" & set "PY_ARGS=-3")
)
```

- 两者都没有 → 报错信息改为"未找到 python / py"并给出 python.org 链接；
- 版本检查统一走 `%PY_CMD% %PY_ARGS% -c "..."`；
- **注意**：`start.bat` 已 `setlocal EnableDelayedExpansion`，在 `if (...)` 块内赋值需用 `&` 连接或改用 `if ... goto` 结构，避免经典的括号块变量展开陷阱（实施时以实测为准）。

**5.2.2 就绪后再开浏览器**

保持"异步不阻塞服务启动"的形态，把固定延迟换成轮询，判定语义与 `start.sh` 对齐（HTTP 可连通即视为就绪）：

```bat
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "for ($i=0; $i -lt 120; $i++) { try { $r = Invoke-WebRequest -Uri 'http://localhost:8765/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { Start-Process 'http://localhost:8765'; break } } catch {} ; Start-Sleep -Milliseconds 500 }"
```

要点：

- 判定条件与 `start.sh` 一致（"能连通"而非"必须 200"），避免首页重定向/静态资源异常时永不打开；
- 最多等待 60s（120 × 0.5s），超时静默放弃（不阻塞服务，用户可手动访问）；
- 使用 `Invoke-WebRequest -UseBasicParsing`，不依赖系统 PowerShell 版本的 IE 引擎初始化；
- 若系统无 PowerShell（极少见），用户仍可手动打开 `http://localhost:8765`——脚本不因此中断服务。

### 5.3 验收标准

- Windows 上分别在三种环境实测：仅有 `python`、仅有 `py`、两者都有 → 均能创建 venv 并启动服务；
- 慢速首次启动（清空 `.venv` 后运行）→ 浏览器不出现"无法访问"页面；
- 端口已占用场景（`start.bat:48-54`）行为不变；
- 非 Windows 平台不受影响（`start.sh` 未改动）。

### 5.4 风险

| 风险 | 缓解 |
|------|------|
| `start.bat` 无法在开发机（macOS）直接验证 | 合并前需取得 Windows 环境的实测记录（截图或日志），否则不合并 |
| PowerShell 执行策略限制导致轮询失效 | `-ExecutionPolicy Bypass` + `-NoProfile`；失败时仅"不自动开浏览器"，不影响服务 |
| 延迟变量展开陷阱导致 `PY_CMD` 赋值未生效 | 实施后逐分支打印实际使用的命令并人工确认三种环境 |

---

## 6. Backlog（本次不做，记录在案）

| 项 | 性质 | 结论 |
|----|------|------|
| 云端部署配置模板 | 部署方式 | 需先修正端口（应为 8765）、改用有效的内存字段、创建持久卷、关闭自动停机、补访问控制；且与"长任务 + ffmpeg 资源占用"耦合，国内访问体验差。仅在"海外团队自托管公共实例"场景有价值 |
| 前端构建 `base` 改为相对路径 | 构建配置 | 与 `base: '/static/'` + 后端伺服产物的设计冲突，不采纳 |
| 环境变量文件纳入版本控制 | 配置管理 | 与现有 `.env.example` 机制重复；且存在把真实密钥提交进仓库的情形（安全问题），均不采纳 |
| 垂直业务批量生成脚本 | 业务适配层 | 不吸收；可借鉴的只有"CLI 批量 + `--dry-run` 校验 + 单条失败隔离"的形态，项目当前无 CLI 需求 |
| 任务级总超时预算 | 本 PRD 衍生 | Phase 1 只解决单次调用超时；"单个步骤总耗时上限"（如 story 步骤 10 分钟）可另立小项评估 |
| 场景 prompt 并发可配置化 | §4.5 | 仅在 Phase 1 实测显示"并发与超时正相关"时实施 |

---

## 7. 实施记录要求

1. 三项各自独立提交，便于单独回滚；
2. 每个 Phase 的实施记录需写明：实测数据（Phase 1）与方案取舍理由（Phase 1 为何联合调参、Phase 2 为何区分控制流异常并拒绝降并发）；
3. Phase 1 若因实测判定为"无需改动"，同样需留下采样数据与结案说明，作为后续复查依据；
4. 三项落地后同步更新 `docs/dev/regression_test_plan.md` 的回归条目（Phase 2 的续传闭环、Phase 3 的 Windows 启动为必测项）。

---

## 8. Milestones

| Milestone | 内容 | 依赖 |
|-----------|------|------|
| M1 | Phase 1 实测采样 + 结论（实施或结案） | — |
| M2 | Phase 1 代码落地（`AGNES_CHAT_TIMEOUT` + `timeout_retry_limit`）+ 单测 | M1 |
| M3 | Phase 2 异常隔离 + 续传闭环回归用例 | — |
| M4 | Phase 3 `start.bat` 改造 + Windows 实测 | — |
| M5 | 三项编入 `optimization_roadmap.md` 并更新 `docs/dev/regression_test_plan.md` 回归条目 | M2-M4 |

---

*Document version: v0.1 — 2026-09-20*
