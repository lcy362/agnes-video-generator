# 回归测试方案完善与脚本修复计划 v2

> **状态**：🎉 全部完成（12/12）
> **创建日期**：2026-06-17
> **最近更新**：2026-06-17 — 全部 12 项完成
> **关联**：`docs/regression_test_plan.md`（目标规范）、`docs/plans-v2.0/code_review_report.md`（v1 审查）、`docs/plans-v2.0/fix_plan.md`（v1 修复）
> **范围**：仅 `scripts/regression_runner.py` 的场景定义与验证逻辑修复，不动 `server.py` / `core/` / `models/`

---

## 背景

2026-06-17 对回归测试方案（`regression_test_plan.md` + `regression_runner.py`）做了系统审查，发现 **2 个测试用例盲点**和 **12 个代码实现问题**。本计划是分批实施的依据。

测试用例补强（C5 场景 + M 文本加长）已同步进 `regression_test_plan.md`，本文档只承载**脚本代码修复**的迁移路径。

### 图例
- ⬜ 待修复 / 🔄 修复中 / ✅ 已修复 / ✔️ 已验证

---

## 修复状态总览

| 编号 | 严重度 | 问题 | 批次 | 状态 |
|------|--------|------|------|------|
| B1.1 | P0 | 新增 C5 场景定义（`chaining_mode=ti2vid` 链式分支） | 1 | ✅ |
| B1.2 | P0 | M1/M2 `manuscript_text` 加长（激活拆段算法） | 1 | ✅ |
| B2.1 | P0 | F7 实现：从 task_state 读段落/音频时长做区间校验 | 2 | ✅ |
| B2.2 | P0 | E3-E5 改为非破坏性验证（`creative_name` 前缀 + 不强制 `ok`） | 2 | ✅ |
| B3.1 | P1 | 断点续传：`failed/timeout` 应重提交而非复用旧 task_id | 3 | ✅ |
| B3.2 | P1 | 加权信号量：拆分"提交窗口持锁" vs "轮询阶段释放" | 3 | ✅ |
| B4.1 | P2 | F3 分辨率匹配校验 | 4 | ✅ |
| B4.2 | P2 | R3 simple 顶层 status 校验 + 未完成步骤名记入 errors | 4 | ✅ |
| B4.3 | P2 | R6 严格 URL 匹配 + 移除子目录短路守卫 | 4 | ✅ |
| B4.4 | P2 | `ReportManager._save` 原子写（对齐 Manifest 的 tmp+replace） | 4 | ✅ |
| B4.5 | P2 | `WeightedSemaphore` 死锁防护 + release 风格统一 | 4 | ✅ |
| B5.1 | P3 | docstring 场景数（10）+ 轮询间隔文档同步 | 5 | ✅ |

---

## 批次 1：测试用例同步（P0）

> 让脚本的场景定义与 `regression_test_plan.md` 第 2 章矩阵对齐。**无验证逻辑改动**，最低风险。

### B1.1 新增 C5 场景定义

**现象**：`creative_video.py:617-632` 三路分发中，`ti2vid` 链式分支（`_generate_chained_scenes`，含 ffmpeg 抽尾帧 → transition 生成 → 下一段参考图传递）在 9 个回归场景中完全没有覆盖。

**根因**：`SCENARIO_DEFS` 未定义 `chaining_mode="ti2vid"` 的场景。

**修复方案**：在 `SCENARIO_DEFS` 的 C4 后追加 C5：

```python
ScenarioConfig(
    "C5", "链式续传 ti2vid + 无配音", "creative", "/api/tasks/creative",
    {"idea": "一只猫在花园里探索的冒险故事",
     "user_requirement": "3个场景，每个场景5秒，动画风格",
     "style": "动画风格", "chaining_mode": "ti2vid",
     "video_duration": 5, "audio_enabled": False},
    TIMEOUT_CREATIVE, SCENARIO_WEIGHTS["C5"]),
```

并在 `SCENARIO_WEIGHTS` 字典新增 `"C5": 4`。

**涉及代码**：

| 位置 | 修改 |
|------|------|
| `regression_runner.py:47-55` `SCENARIO_WEIGHTS` | 新增 `"C5": 4` |
| `regression_runner.py:163` 后（C4 定义后） | 追加 C5 `ScenarioConfig` |
| `regression_runner.py:187` `SCENARIO_MAP` | 自动包含（字典推导无需改） |

**验收**：
- `.venv/bin/python -m py_compile scripts/regression_runner.py` 通过
- `.venv/bin/python -c "from scripts.regression_runner import SCENARIO_DEFS; assert len(SCENARIO_DEFS) == 10; assert SCENARIO_DEFS[-1].id == 'C5'"`（注意：scripts 不是包，需用 `importlib` 或直接 `python scripts/regression_runner.py --help` 验证 argparse 正常）
- `python scripts/regression_runner.py --quick` 能列出 C5（即便 skipped）

---

### B1.2 M1/M2 稿件文本加长

**现象**：M1/M2 当前用 56 字短文本，经 `_step_split_text`（`manuscript_video.py:250-349`）贪心合并后只产生 **1 段（14s）**，导致拆段算法、多段批量提交、多段拼接路径全部未被触发。

**根因**：`SCENARIO_DEFS` 中 M1/M2 的 `manuscript_text` 过短。

**修复方案**：替换为 ~130 字 / 6 句号的稿件（预期拆 3-4 段）：

```
春天的花园里，一只小猫正在追逐蝴蝶。阳光明媚，花朵盛开，空气中弥漫着花香。小猫跳来跳去，非常开心，尾巴翘得高高的。蝴蝶停在一朵花上，小猫悄悄靠近，屏住呼吸。突然蝴蝶飞走了，小猫扑了个空，翻了个跟头。它并不气馁，爬起来继续追逐，在花丛中穿梭。最后小猫累了，趴在树荫下休息，看着蝴蝶越飞越远。
```

**涉及代码**：

| 位置 | 修改 |
|------|------|
| `regression_runner.py:166-184` M1/M2 的 `manuscript_text` | 替换为新文本（M1/M2 共用同一文本） |

**验收**：
- `py_compile` 通过
- 单元验证拆段结果（可在 venv 中直接调用 `_step_split_text` 或重写为纯函数测试）：
  ```python
  # 预期：新文本拆成 3-4 段，每段时长 ∈ [5, 12]s
  ```

---

## 批次 2：验证逻辑核心修复（P0）

> 修复两个"形同虚设"的验证项。这是回归有效性的核心。

### B2.1 F7 实现：总时长合理性校验

**现象**：`regression_runner.py:886` `checks["F7_duration_reasonable"] = clip.duration > 0`，与 F2 `duration > 0`（L882）完全重复，没有实现"总时长 ≈ max(Σ各段视频时长, 合并音频时长 + 1s)"的语义（AGENTS.md 8.6 D4/D10 音视频同步策略的唯一自动校验入口）。

**根因**：实现偷工，未从 task_state 读取各段时长与音频时长做区间校验。

**修复方案**：

1. 新增辅助函数 `_compute_expected_duration(task_state, scenario) -> float | None`：
   - **simple**：`expected = task_state["duration"]`（或从 `video_duration`）
   - **manuscript**：`expected = sum(p.get("duration", len(p["text"])/4.0) for p in paragraphs)`；若 `combined_audio` 存在，取 `max(sum_segments, audio_duration + 1.0)`
   - **creative**：`expected = sum(s.get("duration", video_duration) for s in scenes)`；同样与音频时长取 max
   - 读不到关键字段时返回 `None`（F7 标 `N/A`）

2. 替换 L886：
   ```python
   expected_dur = _compute_expected_duration(sd, scenario)  # sd = task_state dict
   if expected_dur:
       tol = 0.15
       checks["F7_expected_duration"] = round(expected_dur, 2)
       checks["F7_duration_reasonable"] = (
           abs(clip.duration - expected_dur) / expected_dur <= tol
       )
   else:
       checks["F7_duration_reasonable"] = "N/A"
   ```

**涉及代码**：

| 位置 | 修改 |
|------|------|
| `regression_runner.py:886` | 替换 F7 赋值逻辑 |
| `regression_runner.py:793` 附近（`_get_expected_narration` 同区） | 新增 `_compute_expected_duration` |
| `regression_runner.py:895, 900, 945`（三处 except/else 分支的 F7 赋值） | 保持 `"skip"` / `False` 语义不变 |

**前置确认（实施时必须做）**：先从一个真实的 `task_state.json` 确认 `paragraphs[*]` / `scenes[*]` 是否真的带 `duration` 字段、`combined_audio` 字段名是否准确。若 schema 不符，需调整字段读取逻辑。

**验收**：
- `py_compile` 通过
- 对一个真实的 completed manuscript 任务跑 `--quick`，F7 输出 `F7_expected_duration` 与 `F7_duration_reasonable` 均非 `"N/A"` 且为 True

---

### B2.2 E3-E5 改为非破坏性验证

**现象**：`regression_runner.py:1273-1291` 的 `_post_ok` 要求 `r.json().get("ok")` 为真，即**真实提交任务**。每次回归会在 `.working_dir/` 中额外产生 3 个孤儿任务，与 9 个主场景混淆，且 E4/E5 默认 `audio_enabled=True` 会触发完整 LLM+TTS 链路，端点验证拖延数十秒到几分钟。

**根因**：文档（plan E3-E5）定义为"参数校验返回 200/422"，但实现走真实提交。

**修复方案**：

1. E3/E4/E5 改为提交**带 `creative_name="__ep_probe__"` 前缀**的最小任务，且对 creative/manuscript 显式传 `audio_enabled=False` 避免 TTS：

   ```python
   check("E3", "POST /api/tasks/simple → ok",
         lambda: _post_ok("/api/tasks/simple",
                          {"prompt": "__ep_probe__", "mode": "t2v",
                           "duration": 5, "creative_name": "__ep_probe__"})),
   check("E4", "POST /api/tasks/creative → ok",
         lambda: _post_ok("/api/tasks/creative",
                          {"idea": "__ep_probe__", "user_requirement": "1个场景，5秒",
                           "audio_enabled": "false", "creative_name": "__ep_probe__"})),
   check("E5", "POST /api/tasks/manuscript → ok",
         lambda: _post_ok("/api/tasks/manuscript",
                          {"manuscript_text": "__ep_probe__.第二句。",
                           "audio_enabled": "false", "creative_name": "__ep_probe__"})),
   ```

2. `--quick` 模式的任务匹配（`main()` 约 1390-1423）增加排除规则：`creative_name` 以 `__ep_probe__` 开头的任务不作为 M1/M2/C 候选。

**涉及代码**：

| 位置 | 修改 |
|------|------|
| `regression_runner.py:1283-1291` | 三处 check payload 加前缀 + `audio_enabled=false` |
| `regression_runner.py:~1400`（`--quick` 任务匹配处） | 增加 `__ep_probe__` 排除 |

**前置确认**：核实 server.py 的 simple/creative/manuscript 端点是否接受 `creative_name` Form 参数（creative/manuscript 已确认有；simple 需确认——若无则 E3 不加该字段，改用别的隔离方式）。

**验收**：
- `py_compile` 通过
- E1-E9 仍全部 passed
- `--quick` 不再把 `__ep_probe__` 任务误识别为主场景

---

## 批次 3：控制流修复（P1）

### B3.1 断点续传：failed/timeout 应重提交

**现象**：`run_scenario`（L1136-1142）续传判定只看 `existing.get("task_id")`，不看 status。若上次 status=`failed`/`timeout`，只要 result 里残留 task_id，就会无脑复用旧任务轮询——而旧任务早已失败/过期，永远拿不到 `completed`，导致 **failed 任务无法重试**。这与 plan 6.3 节"status=failed/pending → 重新提交并运行"矛盾。

**根因**：续传分支未结合 status 判断。

**修复方案**：

```python
existing = report.data["scenarios"].get(scenario.id, {})
existing_status = existing.get("status")
existing_result = existing.get("result") or {}
task_id = None
dir_name = None

# 只有 submitted/running（崩溃中断）才复用旧 task_id；
# failed/timeout 必须重新提交
if existing_result.get("task_id") and existing_status in ("submitted", "running"):
    task_id = existing_result["task_id"]
    dir_name = existing_result.get("dir_name", task_id)
    logger.info(f"[{scenario.id}] 续传已有任务 {task_id[:12]}")
else:
    submit_result = await submit_task(scenario)
    ...
```

**涉及代码**：

| 位置 | 修改 |
|------|------|
| `regression_runner.py:1136-1142` | 续传判定加 status 条件 |

**验收**：
- `py_compile` 通过
- 手工构造一个 status=failed 且带 task_id 的报告，跑 `--resume`，确认重新提交（日志出现"提交 →"而非"续传已有任务"）

---

### B3.2 加权信号量：拆分持锁窗口

**现象**：`run_scenario`（L1128 acquire, L1244-1246 release）信号量在**整个场景执行期间**持有（含轮询等待 30-120min、验证含 whisper 数分钟）。文档定义为"每分钟 API 调用估算"，但实际控制的是"同时运行场景的权重和 ≤ 10"，导致实际并发度远低于设计（约 2 个场景而非 4 个）。

**根因**：持锁粒度过粗。

**修复方案**（二选一，推荐方案 A）：

**方案 A（推荐，改动小）**：信号量只在"提交 + 首次状态确认"窗口持有，轮询阶段释放。
```python
await sema.acquire(scenario.weight)
try:
    submit_result = await submit_task(scenario)   # 含 API 调用
    task_id = submit_result["task_id"]
    # 确认任务已被服务端接收（status != pending 初始态）
finally:
    await sema.release(scenario.weight)

# 轮询阶段不持锁（仅查 /api/tasks/{id}，无 Agnes API 调用）
deadline = ...
while time.monotonic() < deadline:
    ...
# 验证阶段也不持锁
checks = await validate_task(...)
```

**方案 B（保守）**：保持现状，但在文档中明确"信号量是并发场景数控制，非 API 限流"，并调低权重使并发度更合理。

**涉及代码**：

| 位置 | 修改 |
|------|------|
| `regression_runner.py:1127-1246` | acquire/release 范围收窄到提交窗口（方案 A） |

**验收**：
- `py_compile` 通过
- 观察 `--auto-start` 全量回归时的日志，确认多个场景能并发进入轮询阶段（而非排队）

---

## 批次 4：验证严格化与健壮性（P2）

### B4.1 F3 分辨率匹配校验

**现象**：L883-884 只记录 `F3_width` / `F3_height` 数值，无匹配判断；且在通过率统计（L313 `_recalc_summary`）中被排除。

**修复方案**：
```python
exp_w = scenario.params.get("video_width", 768)
exp_h = scenario.params.get("video_height", 1152)
checks["F3_width"] = clip.w
checks["F3_height"] = clip.h
checks["F3_resolution_matches"] = (clip.w == exp_w and clip.h == exp_h)
```
并在 `_recalc_summary` 的排除列表中**移除** `F3_resolution_matches`（保留排除 `_width`/`_height` 信息项）。

**涉及代码**：`regression_runner.py:883-884` + `regression_runner.py:313`。

**验收**：对默认 768×1152 任务跑验证，`F3_resolution_matches=True`。

---

### B4.2 R3 simple 顶层 status 校验 + 未完成步骤名记入 errors

**现象**：
1. simple 任务的 `task_state.json` 无 `step_*` 字段（只有顶层 `status`），当前 R3 对 simple 永远返回 `N/A`，等于不校验。
2. creative/manuscript 的 R3 只输出布尔，不记录哪些 step 未完成，调试困难。

**修复方案**：
```python
if scenario.type == "simple":
    checks["R3_all_completed"] = sd.get("status") == "completed"
else:
    active_steps = {k: v for k, v in steps.items() if k not in _SKIPPABLE_STEPS}
    incomplete = [k for k, v in active_steps.items() if v != "completed"]
    checks["R3_all_completed"] = not incomplete
    checks["R3_incomplete_steps"] = ",".join(incomplete) if incomplete else ""
```

**涉及代码**：`regression_runner.py:959-973`。`R3_incomplete_steps` 加入 `_recalc_summary` 的排除列表（信息项）。

**验收**：simple 任务的 R3 不再是 N/A；人为破坏一个 step 值，errors 含该 step 名。

---

### B4.3 R6 严格 URL 匹配 + 移除子目录短路守卫

**现象**：
1. `"video_id=" in f.read()`（L1005/1028/1049）是宽松子串匹配，注释/残留都会误判 True。文档（plan R6）要求 `agnesapi?video_id=` 完整模式。
2. 子目录检查带 `if not _curl_has_video_id` 守卫（L1026/1047），一旦根目录命中就跳过所有子目录，无法发现子目录缺失。

**修复方案**：
```python
import re
_VIDEO_ID_RE = re.compile(r"agnesapi\?\S*video_id=|mode=\S*&video_id=")

def _curl_has_valid_video_id(path: str) -> bool:
    if not os.path.exists(path):
        return False
    with open(path) as f:
        return bool(_VIDEO_ID_RE.search(f.read()))
```
R6 对根目录 / 每个 scene_N / 每个 para_N **独立**检查（移除短路守卫），记录 `R6_dirs_checked` / `R6_dirs_with_curl`。

**涉及代码**：`regression_runner.py:1003-1049` 三处 + 新增 `_curl_has_valid_video_id` helper。

**验收**：构造一个只含裸 `video_id=` 注释的 curl.sh，R6 判 False。

---

### B4.4 ReportManager._save 原子写

**现象**：`_save`（L322-326）直接 `open(path, "w")` 截断写，崩溃会留下损坏 JSON——而它正是 `should_run`/断点续传依赖的状态文件。对比 `RegressionManifest.save`（L547-553）用了 tmp+`os.replace`。

**修复方案**：直接套用 Manifest 的原子写模式：
```python
def _save(self):
    self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(self.path), exist_ok=True)
    tmp = self.path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(self.data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, self.path)
```

**涉及代码**：`regression_runner.py:322-326`。

**验收**：回归中断后 `regression_report.json` 始终可解析。

---

### B4.5 WeightedSemaphore 死锁防护 + release 风格统一

**现象**：
1. `acquire`（L206-210）对 `weight > max_weight` 无防护，会永久 wait 死锁（当前场景最大权重 4 不触发，但新增场景时是隐患）。
2. `release`（L212-215）用 `async with self._cond` 而 `acquire` 用 `async with self._lock`，风格不一致（当前因 Condition 复用 lock 而等价）。

**修复方案**：
```python
async def acquire(self, weight: int):
    if weight > self.max_weight:
        raise ValueError(f"scenario weight {weight} > max {self.max_weight}")
    async with self._lock:
        while self.current + weight > self.max_weight:
            await self._cond.wait()
        self.current += weight

async def release(self, weight: int):
    async with self._lock:
        self.current -= weight
        self._cond.notify_all()
```

**涉及代码**：`regression_runner.py:206-215`。

**验收**：构造一个 weight=11 的场景，acquire 立即抛 ValueError 而非死锁。

---

## 批次 5：文档零散同步（P3）

### B5.1 docstring 与轮询间隔同步

**现象**：
1. `regression_runner.py:12` docstring 写"10 个测试场景"（历史遗留），实际新增 C5 后才是 10（巧合一致，但需核实表述准确）。
2. 轮询间隔 AGENTS.md 8.2 写 15s（pipeline 内部 Agnes Video API），回归脚本用 20s（任务状态轮询），易混淆。

**修复方案**：
- 核实 docstring 场景数描述与实际 `SCENARIO_DEFS` 一致
- 在 `regression_runner.py` 顶部注释或 `POLL_INTERVAL` 处加注：此为任务状态轮询间隔，区别于 pipeline 内部 15s 的 Agnes API 轮询

**涉及代码**：`regression_runner.py:1-20`（docstring）+ `regression_runner.py:74`（POLL_INTERVAL 注释）。

**验收**：`python scripts/regression_runner.py --help` 输出与文档一致。

---

## 通用验证方法（每批完成后执行）

```bash
# 1. 语法检查
.venv/bin/python -m py_compile scripts/regression_runner.py

# 2. 导入验证（确认无运行时 import 错误）
.venv/bin/python -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('rr', 'scripts/regression_runner.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('SCENARIO_DEFS:', len(m.SCENARIO_DEFS), '个场景')
print('IDs:', [s.id for s in m.SCENARIO_DEFS])
print('Weights:', m.SCENARIO_WEIGHTS)
"

# 3. 帮助信息正常
python scripts/regression_runner.py --help

# 4. （可选，需服务运行）快速验证不破坏现有报告
python scripts/regression_runner.py --quick
```

---

## 实施顺序与依赖

```
批次 1 (B1.1, B1.2)  ──┐
                       ├── 独立，可并行
批次 4 (B4.1-B4.5)  ───┘

批次 2 (B2.1, B2.2)  ── 依赖批次 1 的场景定义就绪（B2.1 需读 task_state schema，B2.2 需 creative_name 字段确认）

批次 3 (B3.1, B3.2)  ── 独立于其他批次，但建议在批次 2 后做（避免回归中途崩溃时报告逻辑还在变）

批次 5 (B5.1)        ── 最后做，确认所有场景数和文档表述与最终代码一致
```

**建议执行顺序**：批次 1 → 批次 4 → 批次 2 → 批次 3 → 批次 5。

---

## 不在本次范围

以下问题审查中发现，但**不在本计划范围**（属于业务代码或需更大改动）：

| 问题 | 原因 |
|------|------|
| `models/task.py` 的 Pydantic 请求模型未被端点使用（端点用 Form） | 文档型死代码，不影响回归，留作后续清理 |
| `server.py` 的 `/api/cleanup-regression` 与脚本 `cleanup_regression_artifacts()` 逻辑重复 | 双实现维护风险，但功能正确，留作后续统一 |
| creative 字幕参数覆盖不全（`audio_rate`/`subtitle_position=top` 等） | 属于"场景补强"而非"代码修复"，本次测试用例策略已定为最小补强 |
| Simple 的 `seed`/`negative_prompt` 参数未覆盖 | 同上，最小补强策略下不新增 S4/S5 |
| `release_notes_v2.1.md` 与 `code_review_report.md` 的 H1-H6 描述不一致 | release notes 写作问题，与回归脚本无关 |

---

*文档版本：v1.0 | 创建：2026-06-17 | 下一步：按批次实施，每批完成后更新本表状态列*
