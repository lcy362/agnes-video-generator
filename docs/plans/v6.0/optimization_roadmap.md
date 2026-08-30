# 优化路线图（合并版 / Consolidated Optimization Roadmap）

> **文档定位**：本项目**当前唯一生效**的可落地优化点清单与实现指引。本文**取代并废弃**以下两份旧文档：
> - `docs/plans/v5.0/optimization_roadmap.md`（v5.0 路线图，六项已全部完成，仅作历史存档）
> - `docs/plans/optimization-research/` 存档条目的一次性评定（2026-08-26，评定结论见本文「遗留条目处置」，存档文件本身按流转规则保留）
>
> **来源**：2026-08-26 全项目架构评审（后端并发/可靠性/性能/可维护性/测试 + 前端/i18n/构建/部署基础设施），结合旧路线图完成状态核对与调研存档评定汇总而成。2026-08-28 二次 review 修订：修正 0.5 误判、补齐 0.6/1.1/1.4 方案缺口、纳入新发现的 3 个高优先级缺陷（0.7~0.9），并将前端新增问题并入 1.7/3.1/3.4。
>
> **版本计划**：全部 **29 项**计划在 **v6 版本线内完成**（当前 v6.2.1；批次 0~3 随后续版本分批落地、分批发版）。
>
> **优先级标记**：🔴 高（建议优先）| 🟡 中 | 🟢 低（锦上添花）
> **批次语义**：批次 0 为即修缺陷（均为小改动，可随发现随修）；批次 1~3 按序推进，批内 🔴 优先。

---

## 目录

| 批次 | 主题 | 条目数 |
|------|------|--------|
| 0 | 即修缺陷（小成本高收益） | 9 |
| 1 | 可靠性与工程基础 | 8 |
| 2 | 性能 | 5 |
| 3 | 体验与长期健康度 | 7 |

| # | 优化点 | 优先级 | 一句话价值 | 工作量 | 状态 |
|---|--------|--------|-----------|--------|------|
| 0.1 | `docker-run.sh` 版本脱节 + 端口映射 bug | 🔴 | Docker 一键脚本用户不再拉到旧镜像、自定义端口可用 | 小 | ✅ |
| 0.2 | 用户停止被重试 2 分钟 + 误删可续传 video_id | 🔴 | 停止即时生效；续传不再浪费 1 次/分的视频配额 | 小 | ✅ |
| 0.3 | 事件循环阻塞点（水印重编码 + 同步下载） | 🔴 | 收尾/下载阶段不再冻结整个服务 | 小 | ✅ |
| 0.4 | 信号量未获取即释放 + 权重越界静默失败 | 🔴 | 并发上限在边界配置下不再失守 | 小 | ✅ |
| 0.5 | 并发安全小修（水印坐标函数属性传参） | 🟡 | 消除并发下水印坐标互相覆盖隐患 | 小 | ✅ |
| 0.6 | 文档与代码同步（完善 `.env.example` + 文档引用） | 🔴 | 新用户可发现多 Key 配置方式 | 小 | ✅ |
| 0.7 | `_key_id` 未哈希 data → 多 Key 按 id 删除失效 | 🔴 | 多 Key 场景删除单个 Key 不再误删 | 小 | ✅ |
| 0.8 | 前端 `v-html` 未转义 → XSS | 🔴 | 后端可控字符串不再注入前端脚本 | 小 | ✅ |
| 0.9 | 图片生成无重复提交守卫 | 🔴 | 快速连点不再并发重复提交扣费 | 小 | ✅ |
| 1.1 | 任务状态单写者原则 | 🔴 | 停止/删除后磁盘状态不再回跳 | 中 | ✅ |
| 1.2 | 断点续传补全（cues 持久化等） | 🟡 | 长任务续传不再重采 TTS | 中 | ✅ |
| 1.3 | 并发等待 + 自适应轮询 | 🟡 | 多场景等待时延从线性叠加降为并行 | 中 | ✅ |
| 1.4 | 任务索引 + 列表接口性能 + 分页 | 🟡 | 任务查询从 O(N) 全扫降为 O(1) | 中 | ✅ |
| 1.5 | 产物与日志治理（sweep/error_logs/poetry 映射） | 🟡 | 长期运行工作区不再无限膨胀 | 小~中 | ✅ |
| 1.6 | 测试补齐（API 重试/并发/续传） | 🔴 | 批次 0 类 bug 从此有回归护栏 | 中 | ✅ |
| 1.7 | 前端轮询体验（退避/后台暂停/断连提示/竞态） | 🟡 | 服务异常时用户看得到原因；轮询不堆积 | 小~中 | ✅ |
| 1.8 | i18n 拆分懒加载 + 检查脚本硬化 + 接 CI | 🔴 | 首屏 bundle 大幅瘦身，翻译缺失 CI 拦截 | 大 | ✅ |
| 2.1 | 成片合成链 ffmpeg 化（消除 3~4 遍重编码） | 🟡 | 合成阶段 3~10 倍提速 | 大 | ✅（2.1a/2.1b/2.1c） |
| 2.2 | poetry 逐场景双份编码合并 | 🟡 | 诗词视频编码开销减半以上 | 中 | ✅ |
| 2.3 | 限速器异步化 + 编码专用线程池 | 🟡 | 停止即时响应限速等待；线程池不再饥饿 | 中 | ✅ |
| 2.4 | 进度状态写盘节流 | 🟢 | 事件循环周期性卡顿消除 | 小~中 | ✅ |
| 2.5 | 独立环节并行化（t2i 尾帧 / 稿件 prompt） | 🟢 | 长流水线总时长缩短 | 小~中 | ✅ |
| 3.1 | 前端交互层统一（api 层/Toast/表单去重） | 🟢 | 错误处理集中治理，改一处生效全局 | 中 | ✅ |
| 3.2 | 可观测与运维（/api/health、文件日志、metrics） | 🟢 | 部署可探活、事后可查日志 | 小~中 | ✅ |
| 3.3 | CI 补强（Python 3.10 矩阵 / lint / 前端单测） | 🟢 | 承诺的 3.10+ 兼容有背书 | 小~中 | ✅ |
| 3.4 | 移动端/可访问性/杂项体验 | 🟢 | 窄屏可用、模态可达、表单不丢草稿 | 小~中 | ✅ |
| 3.5 | 配置收敛（typed Settings） | 🟢 | 12+ 环境变量统一口径，消除默认值冲突 | 中 | ✅ |
| 3.6 | chained 模式双参考图提交（调研存档 R1 拆出） | 🟢 | 链式模式角色身份漂移缓解 | 小 | ✅ |
| 3.7 | 回归矩阵补全（poetry/simple_image/C4） | 🟡 | 六种任务类型全部有真实回归覆盖 | 小~中 | ✅ |

---

## 批次 0 — 即修缺陷

### 0.1 `docker-run.sh` 版本脱节 + 端口映射 bug 🔴

**现状问题**：
1. `docker-run.sh:67` 默认镜像固定 `free-short-video:4.7.2`，而 `docker-compose.yml` 已随发版更新到 6.1.0。根因是 `.github/workflows/release.yml` 发版 bump 时只 `sed` 更新 `docker-compose.yml`，漏了 `docker-run.sh`，导致用该脚本的用户一直拉旧版镜像。
2. `docker-run.sh:79` `-p "$PORT:$PORT"`：容器内固定监听 8765（未向容器注入 PORT 环境变量），用户设 `AGNES_PORT=9000` 时会映射成 `9000:9000`，直接不可访问。

**方案**：端口映射改为 `-p "$PORT:8765"`；`release.yml` 的 bump 步骤同时更新 `docker-run.sh` 中的镜像标签（或脚本改用 `:latest` 并文档说明版本锁定方式）。

**验收**：
1. 模拟发版 bump 后，`docker-run.sh` 与 `docker-compose.yml` 镜像标签一致。
2. `AGNES_PORT=9000 ./docker-run.sh` 后 `http://localhost:9000/api/config` 返回 `ok: true`。

### 0.2 用户停止被当作失败重试 + 误删可续传 video_id 🔴

**现状问题**：停止时 `_poll_task` 抛 `RuntimeError("Video generation cancelled by user")`（`core/api/agnes_video.py:253/357`，属 `Exception` 子类），而 `MultiScenePipeline._wait_for_video_with_retry`（`core/pipelines/multi_scene.py:274-293`）捕获**所有** Exception 并重试 3 次（退避 20s/40s）→ 停止延迟最长 ~120s；manuscript（`manuscript_video.py`）、anchor（`anchor_video.py`）、creative（`steps_video.py:228/322/558`）同构。更糟的是重试耗尽后 `os.remove(task.json)`——超时、取消这类"服务端任务可能仍在跑"的情形也删掉了 video_id，续传只能重新提交，浪费最宝贵的视频配额（1 次/分钟/Key）。

**方案**：
1. `_check_shutdown()` 触发的异常直接穿透，不进入重试循环（区分「用户取消」与「可重试的临时错误」）。
2. `task.json` 仅在确认服务端失败（status=failed / 4xx）时删除；超时、取消、网络中断一律保留，续传继续轮询原 video_id。

**验收**：
1. 视频生成中途点停止，任务在 10s 内进入停止态（无 20s/40s 退避日志）。
2. 模拟等待超时后 `task.json` 保留；`POST /api/tasks/{id}/resume` 复用原 video_id（日志显示 resume 而非 resubmit）。

### 0.3 事件循环阻塞点：水印重编码 + 同步下载 🔴

**现状问题**：
1. `multi_scene.py:131` 与 `simple_video.py:61` 同步调用 `_apply_watermark` → `core/compositor/watermark.py:194` `subprocess.run(ffmpeg, timeout=300)` 对整片重编码，持续数十秒~数分钟期间整个服务冻结（其他任务的轮询、进度落盘、API 请求全部停摆）。
2. `utils/video.py:13`、`utils/image.py:13` 用同步 `requests.get` 下载，调用点全部在协程中直接执行（`multi_scene.py:270`、`manuscript_video.py:367`、`anchor_video.py:248`、`creative/steps_video.py` 多处、`simple_video.py:104/113/148`、`creative/steps_frames.py:274/304`），每个场景下载 5~30s+ 阻塞事件循环。

**方案**：水印与下载统一 `await asyncio.to_thread(...)`（推荐，避免引入新依赖；下载层亦可换 httpx/aiohttp，二选一）；`utils/video.py` tenacity 重试补充 wait 间隔（当前无间隔）。

**验收**：
1. 开启水印的任务收尾期间，并发任务的 `GET /api/tasks/{id}` 响应 <1s。
2. 视频下载期间其他任务进度事件持续更新。

### 0.4 信号量未获取即释放 + 权重越界静默失败 🔴

**现状问题**：`web/deps.py:181-213` `run_pipeline_with_concurrency` 的 `finally` 无条件 `semaphore.release(weight)`。若 `acquire` 抛 `ValueError`（`web/app_state.py:54-56`，weight > max_weight）或协程在排队中被取消，则从未获取槽位却执行释放 → `current` 变负，并发控制永久失效。触发场景真实存在：`MAX_CONCURRENT_WEIGHT = AGNES_RATE_LIMIT // 2`，若用户设 `AGNES_RATE_LIMIT=6`，则 MAX=3 < 稿件权重 4 → 每个稿件任务都抛 ValueError，永远卡 QUEUED 且异常被后台任务静默吞掉。

**方案**：引入 `acquired` 标志，仅获取成功才释放；任务创建端点校验 `weight <= MAX_CONCURRENT_WEIGHT`，越界给出可读错误；后台任务未捕获异常落盘为 FAILED（不再静默）。

> **与 3.5 的关联**：`weight > MAX` 硬拒绝只是临时止血。根治是 3.5「并发上限随 Key 数/配额动态缩放」，使 `MAX_CONCURRENT_WEIGHT` 不再依赖用户可能设低的 `AGNES_RATE_LIMIT`。0.4 先保底（不静默、不破坏信号量），3.5 再做缩放。

**验收**：
1. 单测：acquire 失败 / 排队中取消两种路径下 `semaphore.current` 不变负。
2. 低限速配置下创建稿件任务返回可读错误而非静默卡 QUEUED。

### 0.5 并发安全小修：水印坐标函数属性传参 🟡

1. **水印坐标经函数属性传递**：`watermark.py:120-123` 把 `_wm_pos_x/_wm_pos_y` 写到 `_render_watermark_png` 函数对象上再读回（`:177-178`），两任务并发叠加水印时互相覆盖坐标。改为函数返回坐标（dataclass/tuple）。

**评审勘误（2026-08-28）**：原 0.5 第 2 点「尾帧缓存键类型不一致（int 键 / str 查找恒 False）」经复核为**误判**——`steps_frames.py` 落盘与消费都是 `cached[str(scene_idx)]` ↔ `steps_video.py:428 str(scene_idx)`，二者本就是 str 键一致（源自 v5.0 Batch4 重构）。该项从路线图移除，仅作为「补一个尾帧缓存命中单测」并入 1.6 测试补齐。

**验收**：两任务并发开水印，各自水印位置正确。

### 0.6 文档与代码同步（完善 `.env.example` + 文档引用） 🔴

**本次合并评审中已直接修复**（2026-08-26）：
- `AGENTS.md §6.2` 曾标注"多 Key 轮询/分层限速为规划未实施、单一共享桶"，实际代码早已实现（`core/api/key_manager.py` KeyRing + `rate_limiter.py` 双桶）→ 已更正。
- `AGENTS.md §6.6` 曾写"TTS 输出放大 2.5 倍音量"，实际代码为 1.5（`audio_overlay.py` `_AUDIO_VOLUME_FACTOR = 1.5`）→ 已更正。

**剩余工作**（两项，均已随 0.6 落地完成）：
1. **完善 `.env.example` 内容**（该文件自 v5.0 提交 `724ef5f` 起已存在，非新建）：
   - 补充 `HOST` / `PORT`、视频提交桶、并发权重与限速的联动提示；
   - 移除已废弃项 `AGNES_BASE_URL` / `AGNES_IMAGE_MODEL` / `AGNES_VIDEO_MODEL`（代码中已不再读取，模型改由 Web UI / `POST /api/config` 配置）；
   - 保留原有 `python-dotenv` 依赖说明与 Key 获取链接。
2. 在 `README.md` / `README_ZH.md` / `docs/public/getting-started.md` 补充 `.env.example` 引用与多 Key 配置说明。

**验收**：`.env.example` 覆盖全部在用的环境变量且无过时项（无真实密钥）；三个文档出现 `.env.example` 与 `AGNES_API_KEY_2..N` 说明。

### 0.7 `_key_id` 未哈希 data → 多 Key 按 id 删除失效 🔴

**现状问题**：`web/routes/config_routes.py:113` 的 `_key_id` 实现为 `hashlib.blake2b(key=secret, digest_size=12).hexdigest()`——只传了 `key=`（keyed mode 的密钥）而**未传 data**，`blake2b` 对空字节串 `b''` 做哈希，导致**无论输入什么 Key 都返回相同 id**。后果：
- `GET /api/config/keys` 返回的每个 Key 的 `id` 完全相同；
- `DELETE /api/config/keys` 按 id 定位时 `matched[0]` 恒为第一个 Key → **多 Key 场景下删除单个 Key 永远误删第一个**（`config_routes.py:172-177`）。

**方案**：`hashlib.blake2b(key.encode("utf-8"), key=secret, digest_size=12).hexdigest()`——对 Key 明文本身做 keyed hash。

**验收**：配置 2 个 Key，`GET /api/config/keys` 返回的两个 `id` 互不相同；按第二个 id 删除后仅第二个被移除（`key_count` 减 1、`removed` 掩码对应第二个 Key）。

### 0.8 前端 `v-html` 未转义 → XSS 🔴

**现状问题**：`frontend/src/components/ProgressPage.vue:247` 用 `v-html` 渲染 `progressMessage`；`useProgress.ts:93-94` 把 `dirName`（来自后端 `state.dir_name`）与 `taskId` 直接拼进 HTML 字符串，`pollTaskProgress` 又把后端 `current_message` 直接赋给 `progressMessage`。这些值后端可控（任务名/目录名/进度消息），未转义即注入 HTML。项目内已定义 `escapeHtml()`（`i18n/index.ts:60`）但**全库从未被调用**（死代码）。

**方案**：所有拼入 `progressMessage` 的动态值（`dirName`/`taskId`/`current_message`）一律先经 `escapeHtml()`；或改用分字段渲染（`v-text`）替代 `v-html`。

**验收**：任务名/进度消息含 `<img src=x onerror=...>` 时前端按纯文本展示，不执行脚本。

### 0.9 图片生成无重复提交守卫 🔴

**现状问题**：`frontend/src/components/forms/SimpleForm.vue` 的 `submitSimple`（视频）有 `submitting` 守卫，但 `submitImage`（图片）完全无守卫，对应按钮（`:419-424`）也未绑定 `:disabled`。用户快速连点「生成图片」会并发重复提交，触发后端重复生成/扣费。

**方案**：`submitImage` 增加独立 `imageSubmitting` 守卫，对应按钮绑定 `:disabled`；与视频提交的守卫统一抽取为可复用模式。

**验收**：图片生成提交期间按钮禁用，连点不产生第二次请求。

---

## 批次 1 — 可靠性与工程基础

### 1.1 任务状态单写者原则 🔴

**现状问题**：每个 `TaskManager` 实例持有独立内存 `_state` 副本，`_save()`（`core/task_manager.py:130-152`）全量覆盖写、无锁。竞态路径：`POST /stop`（`task_routes.py:271-276`）新建 TaskManager 写 PENDING，运行中 pipeline 随后的 `_emit` 用内存中的 RUNNING 全量覆盖回去 → 停止后磁盘状态长期停留 RUNNING；产物级联删除在"已 stop 但 pipeline 未退出"窗口同样交叉写。另外删除"已 stop"任务时，pipeline 收尾写盘会 `os.makedirs` 重建僵尸目录（`task_manager.py:56-59`）。

**方案**：确立单写者——停止/删除端点只发信号（`_stop_event` / 删除标记），终态由 pipeline 自己落盘；状态写路径统一走 per-task asyncio 锁 + `load→merge→save`。删除前确认对应后台任务已结束（`app_state.background_tasks` 已持有强引用可查 `done()`）。

> **补：崩溃兜底（2026-08-28 修订）**：单写者原则默认「pipeline 存活才能落终态」，但进程被 `os._exit`（二次 Ctrl+C）/ OOM / 信号杀死时 pipeline 无法落盘，任务会永久停在 RUNNING。需在启动时做一次状态校正（启动扫描将「无活跃 pipeline 但状态为 RUNNING/QUEUED 的遗留任务」标记为可续传的 PENDING 或 FAILED），并配合 sweep 兜底。

**验收**：
1. 停止后 `task_state.json` 不回跳 RUNNING。
2. 删除"刚停止"任务后无僵尸目录重建。
3. 并发读写状态单测通过。
4. 启动校正后无「无 pipeline 却 RUNNING」的孤儿任务。

### 1.2 断点续传补全 🟡

**现状问题**：
1. 续传重采 cues：`BasePipeline._recover_sub_maker`（`core/pipelines/__init__.py:564-590`）在音频已存在时重新调用 edge_tts 完整消费一遍 TTS 流只为拿词级时间戳；10 分钟长稿件续传多花等量网络时间。
2. poetry 的 `_scene_sub_makers` 仅存内存（`poetry_video.py:285`），同样依赖重采。
3. `_poll_task` 整体超时 1800s 对长视频偏紧，超时叠加 0.2 会丢 video_id（0.2 修复后仍需放宽）。

**方案**：生成音频时把词级 cues 序列化落盘（如 `{audio_stem}_cues.json`），续传直接读取；poetry 同步落盘；轮询总超时参数化（`AGNES_VIDEO_POLL_TIMEOUT`，默认保持 1800）。

**验收**：长稿件中断后 resume，无 TTS 网络重采（日志无 edge_tts 调用）；字幕与一次性完成的产物一致。

### 1.3 并发等待 + 自适应轮询 🟡

**现状问题**：`_poll_task` 固定 60s 间隔（每个视频平均 +30s 检测延迟）；Phase 2 逐场景串行等待，N 场景延迟线性叠加；每次轮询消耗共享桶令牌，与 chat/image 争抢。

**方案**：自适应轮询（首个 15~20s，逐步退避至 60s 上限）；等待阶段改 `asyncio.gather` 并发等待 + 进度聚合上报；轮询走独立小桶或更低优先级（配合 2.3 异步限速器）。

**验收**：5 场景任务"等待探测"总时长 ≈ 单场景时长；前端进度展示不回退。

### 1.4 任务索引 + 列表接口性能 + 分页 🟡

**现状问题**：`helpers.find_dir_name` → `TaskManager.list_tasks()` 对每个任务目录做一次 `json.load`；`GET /api/tasks/{id}` 每次先全量扫描再加载目标任务；`GET /api/tasks` 轻读一遍后又对每个任务完整 `TaskManager.load()` 做 Pydantic 校验。100 个任务时每次列表请求 = 200 次文件读 + 100 次完整校验，且阻塞事件循环。

**方案**：内存维护 `task_id → dir_name` 索引（创建/删除时增量更新，启动时一次扫描）；列表端点一次扫描取轻字段；`GET /api/tasks` 增加 `limit/offset/status` 分页过滤参数。

> **补：索引归属（2026-08-28 修订）**：`TaskManager` 是每请求新建实例，索引**必须放在应用级全局单例**（如 `web/app_state.py` 模块级，配合 per-task 锁做增量失效），而非 TaskManager 实例属性；否则每个请求各自维护一份、永不共享。当前单进程部署下可行，若未来上多 worker 需改为磁盘索引或共享存储。

**验收**：
1. 100 任务时列表请求耗时降一个数量级。
2. 创建/删除后索引一致性单测通过。
3. 前端任务列表接入分页/状态筛选（与 3.4 联动，可分期）。

### 1.5 产物与日志治理 🟡

**现状问题**：
1. `sweep_stale_tasks`（`core/artifacts.py:684-756`）默认保护 `{RUNNING, QUEUED, PENDING}`，PENDING（续传候选）永不清理，`/api/tasks/sweep` 未暴露 `protect_statuses` 参数 → 长期工作区只增不减。
2. `error_logs/` 无轮转，每次失败落一个 JSON；诊断端点 `_iter_error_logs`（`task_routes.py:119-131`）每次全量读取所有日志文件，延迟无上限增长。
3. `_checkpoint_to_step_field`（`artifacts.py:886-921`）无 `PoetryVideoTask` 分支 → poetry checkpoint 状态恒为 pending，级联删除的 approved_checkpoints 重置失效。

**方案**：sweep 增加按任务数/磁盘配额策略与参数化保护集；error_logs 按数量/天数轮转（诊断端点配套增量读取）；补 poetry 映射。

**验收**：构造超配额工作区跑 sweep 后磁盘下降；诊断端点在 1000 条 error_logs 下响应 <200ms；poetry 检查点状态正确流转。

### 1.6 测试补齐 🔴

**现状缺口**：mock 回归把 `AgnesVideoAPI/AgnesImageAPI/AgnesChatAPI/EdgeTTSEngine` 整类替换，因此 `_submit_with_retry`（429 换 Key、5xx 退避、400 降帧）、`_poll_task`（超时、连续失败）、`request_with_key_rotation`、令牌桶数学、KeyRing 轮换**零覆盖**——批次 0 的多数 bug 正集中于此。并发控制层（`WeightedSemaphore`、释放语义、stop/resume 竞态）与 resume 正确性（仅 1 例 manuscript 续传）同样薄弱。

**方案**：
1. requests-mock/responses 建 API 重试矩阵单测（单 Key 429 / 多 Key 429 / 5xx / 超时 / 400 降帧 / 轮询连续失败）。
2. 并发单测：信号量释放语义、权重越界、停止竞态。
3. resume 单测：simple video_id 续传、停止后 `task.json` 保留、检查点恢复不重复调 LLM。
4. 补 `_key_id` 哈希唯一性单测（0.7）、尾帧缓存命中单测（0.5 勘误后剩余部分）。

> **实施节奏（2026-08-28 修订）**：本项与批次 0 并行推进——每修一个批次 0 项，同步补一个对应回归测试，而非等批次 0 全部修完再补，避免缺陷在无护栏窗口复发。

**验收**：上述矩阵全部有对应用例；CI 覆盖率门槛相应上调；批次 0 每个修复都有回归测试。

### 1.7 前端轮询体验 🟡

**现状问题**：
1. `useProgress.ts` 固定 30s 轮询、catch 为空（服务故障时无限静默轮询）；`useTasks.ts` 5s 轮询无 in-flight 守卫；全代码库无 `visibilitychange` 处理，后台标签页持续发请求。
2. **（2026-08-28 补充）`loading` 状态失效**：`loadTaskList` 只在 catch 置 false，正常路径从不置 true，该状态从未被真正使用；`TaskListPanel.loadList` 用裸 `fetch` 且无 catch（未处理 rejection）。
3. **（2026-08-28 补充）轮询竞态**：`pollTaskProgress` 首次慢请求与 interval 下一次请求的响应可能乱序覆盖进度，且 interval 回调里已进入的异步 `getTask` 无法取消。

**方案**：页面隐藏时暂停轮询、恢复时立即补一次；连续失败 N 次指数退避并显示"连接异常"横幅；列表轮询加 in-flight 守卫、间隔放宽到 10~15s；`loading` 状态补全赋值逻辑（或列表真正使用）；`pollTaskProgress` 加 in-flight 标志或改用 `setTimeout` 链式调度消除并发。

**验收**：后台标签页 0 请求；服务宕机时前端显示断连提示而非静止进度条；慢网络下进度不出现回跳。

### 1.8 i18n 拆分懒加载 + 检查硬化 + 接 CI 🔴

**现状问题**：
1. `frontend/src/i18n/translations.ts` 6035 行 / 615KB、22 语言全量静态导入，构建产物 `static/assets/index-*.js` 总共才 795KB——翻译是首屏 bundle 绝对大头，而每个用户只用 1 种语言。
2. `scripts/i18n_check.py` 用正则解析（只认单引号值，脆弱）；只查 key 存在、查不出值未翻译/占位符不一致；退出码语义与 `AGENTS.md` 描述矛盾（文档说其余 20 语言缺失仅提醒，实际脚本硬阻断）；未接入 CI。

**方案**：
1. 拆为 `i18n/langs/{lang}.json` 22 个文件，`t()` 读当前语言响应式对象，切换语言时动态 `import()`（zh/en 随首屏预载）；vite 动态分包。
2. `i18n_check.py` 改 JSON diff 校验，增加"en 值与 zh 完全相同"可疑项提示与占位符一致性检查；对齐文档与脚本的阻断语义（zh→en 缺失硬阻断，其余语言列出提醒）。
3. `.github/workflows/test.yml` 增加 i18n check job。

**验收**：
1. 首屏 JS bundle 体积下降 ≥50%。
2. 切换语言功能与现状一致（22 语言抽查）。
3. CI 中人为删除一个 en key 被拦截。

**落地记录（2026-08-28）**：
- `translations.ts`（6035 行 / 615KB）拆为 `frontend/src/i18n/langs/{lang}.json` 22 个文件（zh 基准 554 keys，全部语言 key 集合完整覆盖）；
- `index.ts` 改为 `zh/en` 静态预载 + `import.meta.glob` 动态加载其余 20 语言（每个语言独立 chunk）；
- `i18n_check.py` 硬化：JSON diff 校验 + 占位符 `{xxx}` 一致性 + en 与 zh 相同可疑项提醒 + **en 缺失硬阻断（返回码 2）**、其余语言缺失返回 1、占位符/可疑仅提醒；
- `.github/workflows/test.yml` 新增独立 `i18n-check` job；
- 实测：主 bundle `721 kB → 305 kB`（gzip `226 kB → 97 kB`，**-58%**），20 个语言 chunk 各 ~30-38 kB（按需加载）；
- 现存可疑未翻译项（仅提醒）：`keySrcConfig`（en 与 zh 相同）。

---

## 批次 2 — 性能

### 2.1 成片合成链 ffmpeg 化 🟡（收益最大）✅（2.1a/2.1b/2.1c 全部落地）

**现状问题**：`concat_videos_with_audio_overlay`（`core/compositor/concatenator/audio_overlay.py`）链路为：moviepy compose 全量重编码拼接 → ffmpeg tpad 再全片重编码对齐 → moviepy 第三次全片重编码写音频+字幕 →（开水印再第四次）。3 分钟成片消耗 3~4 倍片长的 CPU 编码时间。

**方案**：
1. 拼接：片段同参数时用 ffmpeg concat demuxer + `-c copy`（秒级），仅分辨率不一致才重编码。
2. 对齐与音量：`tpad/apad/volume` 合并进一条 filter 链一次编码完成。
3. 字幕：LLM 逐条样式（`subtitle_styles.json`）转 ASS 后走 `subtitles` 滤镜，摆脱 moviepy 逐帧文本渲染；保留 moviepy 路径作兜底，配置开关灰度。

> **取舍（2026-08-28 修订）**：字幕 ASS 化与**词级细粒度字幕**（`generate_cue_aware_srt`，以 edge_tts 词级时间戳为真值）+ **逐条样式**存在冲突——`subtitles` 滤镜对词级逐字高亮/动画支持弱，libass 的 CJK 描边/字体渲染与 moviepy 存在观感差异。方案需明确：ASS 路径首版**降级为句级样式**（保描边/字体/位置，放弃词级逐字动效），词级动效仍走 moviepy 兜底路径；二者由配置开关按场景灰度，避免字幕观感回退。

**验收**：合成阶段耗时下降 ≥3 倍；输出与旧路径做音画字幕对照回归（含逐条样式场景）；旧路径开关可回退。

### 2.2 poetry 逐场景双份编码合并 🟡 ✅

**现状问题**：`poetry_video.py:444-507` 每场景单独走一遍 2.1 的三遍编码链路，最后 `concat_videos` 再全量重编码——5 场景约 20 次片段级编码开销。

**方案**：场景间静音填充用 ffmpeg `apad` + concat filter 一条链完成；最终拼接同参数 `-c copy`。依赖 2.1 的基础设施。

**验收**：poetry 成片时长/音轨对齐与现状一致，编码总时长显著下降。

### 2.3 限速器异步化 + 编码专用线程池 🟡

**现状问题**：`rate_limiter.acquire()` 阻塞式 `time.sleep`（最长 60s）无法响应停止信号，且占用默认线程池；所有重型工作（分钟级 moviepy/ffmpeg 编码、requests、screenwriter）共享默认 executor（min(32, cpu+4)），多任务并发时长编码占满线程池导致限速等待/HTTP 请求排队。

**方案**：令牌桶改异步原生（asyncio 条件变量定时补令牌），停止时跳过限速等待直接退出；重型编码用专用 `ThreadPoolExecutor`（`loop.run_in_executor`），与轻量请求隔离。

> **补：同步调用方兼容（2026-08-28 修订）**：`acquire()` 同时被**纯同步脚本**调用（`scripts/regression_runner.py`、`scripts/scene_runner.py`，非 asyncio 上下文）。异步化须**保留同步 `acquire()`**（供脚本/测试/`to_thread` 场景），仅新增异步原生路径供流水线使用，二者共享同一桶状态；否则回归脚本会坏。另补边界：`AGNES_RATE_LIMIT=0` 时 `refill_rate=0` 导致 `acquire()` 内 `wait_time = 1/0` 除零崩溃，须在 `refill_rate == 0` 时明确放行或报错。

**验收**：限速等待中点停止即时退出；并发编码任务下 API 请求不排队线程池；同步脚本回归不破。

### 2.4 进度状态写盘节流 🟢

**现状问题**：`_emit` 每次进度事件触发全量 `model_dump()` + `indent=2` JSON + 原子写；大稿件任务单次写数百 KB，生成循环内每步都写，全部跑在事件循环线程。

**方案**：进度类字段节流合并（500ms~1s 一次）；`_save` 去掉 `indent=2`（体积减半）；终态/关键节点写保持即时，崩溃恢复语义不变。

**验收**：长稿件任务磁盘写量下降 ≥80%；重启后状态恢复正确。

### 2.5 独立环节并行化 🟢

**现状问题**：
1. creative 尾帧预生成（`steps_frames.py:190-312`）逐场景串行，每场景后硬编码 `asyncio.sleep(2)`；t2i 模式（场景间独立）本可并发。
2. manuscript 段落 prompt（`manuscript_video.py:236-267`）逐段串行 LLM 调用。

**方案**：独立环节改有限并发 `asyncio.gather`（2~3 并发，全局令牌桶天然限速兜底）；去除硬编码 sleep。注意保留视觉链依赖场景（i2i 多图模式）的串行。

**验收**：N 场景 t2i 尾帧总耗时 ≈ 单场景 × ceil(N/并发数)；生成结果不变。

---

## 批次 3 — 体验与长期健康度

### 3.1 前端交互层统一 🟢 ✅

**现状问题**：`frontend/src/api/index.ts` 的 `request()` 不检查 `r.ok`，5xx/HTML 错误页抛出误导性解析错误；8 个文件绕过 api 层裸 `fetch`；原生 `alert()/confirm()` 散布 35+ 处；5 个任务表单重复同一套提交流程（`parseResolution()` 定义了三次）。

**（2026-08-28 补充）**：
- `saveApiKey`（`useConfig.ts:22-29`）`if (r.ok)` 无 else 分支，后端 5xx 时**静默失败**、用户无任何反馈。
- `TaskListPanel.loadList`（`:19-24`）裸 `fetch` 且无 catch。

**方案**：`request()` 统一检查 `r.ok` 并抛带 `detail` 的错误；收敛裸 fetch；抽 `useConfirm`/错误 Toast 替换原生弹窗；抽 `useTaskSubmit(taskType)` composable + `collectAudioSubtitleFields()`；`saveApiKey` 等补 else 分支提示用户。

**验收**：后端 500 时前端展示可读错误；表单提交逻辑改动只需改一处。

### 3.2 可观测与运维 🟢

**现状问题**：无 `/api/health`（`/api/config` 兼作探活但带业务语义）；日志仅 stdout 无文件落盘/轮转；限速器统计、信号量利用率无端点暴露；Docker 无 `HEALTHCHECK`。

**方案**：轻量 `GET /api/health`；`AGNES_LOG_FILE` 环境变量开启带 rotation 的文件日志；`/api/metrics`（限速器 stats + 信号量利用率 + API 调用计数 + 活跃任务阶段分布）；Dockerfile 加 HEALTHCHECK。

**验收**：compose 部署可通过健康检查自愈；日志文件按配置生成并轮转。

### 3.3 CI 补强 🟢

**现状问题**：只测 Python 3.12 单版本，而 `start.sh`/README 承诺 3.10+；无 Python lint；前端无单测（`utils/feedback.ts` 的确定性错误匹配等纯函数零覆盖）与 lint。

**方案**：test.yml 启用 Python 3.10 矩阵（注释中已预留写法）；引入 ruff；前端引入 vitest（先覆盖 `utils/` 与 `steps.ts`）+ eslint/prettier。

**验收**：3.10 下全量单测通过；lint 接入 CI 且现有代码清零告警。

### 3.4 移动端 / 可访问性 / 杂项体验 🟢 ✅

- 窄屏适配：任务类型按钮条（`CreatePanel.vue:140-150`）改 grid/横向滚动；任务卡片操作按钮行加 `flex-wrap`。
- 可访问性：抽通用 Modal（focus trap + ESC + 焦点还原）；补 `prefers-reduced-motion`。
- 刷新自动跳转运行中任务（`App.vue:86-101`）改为非阻断提示横幅。
- GA4（`useGa.ts` 硬编码测量 ID）加配置开关 + `task_failed` 上报脱敏（隐私合规）。
- 表单草稿保留（`CreatePanel` 用 `keep-alive` 或状态提升）；图片生成补提交中防抖；`ProgressPage` 加 `:key="task_id"`。

**（2026-08-28 补充）**：
- `useVoice.previewVoice` 的 `URL.createObjectURL` 从不 `revokeObjectURL`，反复试听泄漏 blob URL（`useVoice.ts:112-138`）。
- `useTheme` 的 `matchMedia` 监听器无移除（`useTheme.ts:65-71`，SPA 单例下风险低，记录待清理）。

**验收**：375px 宽视口无溢出不可点元素；模态可键盘完整操作。

### 3.5 配置收敛 🟢 ✅

**现状问题**：约 12 个环境变量散落各处；`web/app_state.py:26` 的 `AGNES_RATE_LIMIT` 默认固定 20，而 `core/api/rate_limiter.py` 默认 20×Key 数，多 Key 部署时口径冲突（并发权重上限不随 Key 扩展，注释"与 rate_limiter.py 一致"已失真）。

**方案**：引入 typed Settings（如 pydantic-settings）统一收敛；`app_state` 的并发上限对齐 `rate_limiter._effective_rate()`（使 0.4 的「权重越界」从硬拒绝变为随配额缩放）。

**验收**：环境变量清单唯一出处；多 Key 下并发上限随配额缩放。

### 3.6 chained 模式双参考图提交 🟢

**来源**：调研存档 `optimization-research/character_consistency_and_dialogue.md` 拆出的低成本小项。

**现状问题**：creative chained 模式逐场景 i2v 只传上一场景尾帧、不传角色参考图，身份漂移随场景累积。`submit_video` 已支持多参考图数组，纯项目内改动。

**方案**：`steps_video.py` chained 分支改为双图提交 `[last_frame, character_ref]`，prompt 侧沿用现有 `[PRESERVE]/[CHANGE]` 约束。

**验收**：同一多场景剧本新旧实现对照，角色外观漂移主观评估改善；回归无异常。

### 3.7 回归矩阵补全 🟡

**现状问题**：`regression_runner.py` 场景矩阵仅 8 场景，六种任务类型中 poetry 与 simple_image 完全无真实 API 回归（脚本 docstring 还写"10 个测试场景"）；`run_mock_regression.sh` 过滤器无 poetry 选项；旧路线图条目 5 的 C4（用户上传分镜图）场景一直未纳入主矩阵；限速常量在脚本与服务端双份硬编码。

**方案**：补 P1（poetry）、I1（simple_image）、C4 场景；mock 脚本加 poetry 过滤器；限速值改从服务端读取；同步更新 `docs/dev/regression_test_plan.md` 与脚本 docstring。

**验收**：`--quick` 与全量模式覆盖六种任务类型；文档与脚本场景数一致。

---

## 遗留条目处置（旧路线图 + 调研存档评定）

### 旧路线图（`docs/plans/v5.0/optimization_roadmap.md`）

经 2026-08-26 逐项代码核对，**六项全部于 2026-08-13 完成**，旧路线图整体废弃（文件保留作历史存档，顶部已加废弃标注）：

| # | 旧条目 | 核对结论 | 遗留处置 |
|---|--------|---------|---------|
| 1 | 多 Key 轮询 + 限流整合 + `.env.example` | ✅ 已完成（KeyRing + 双桶 + 配置 API，超出原设计） | 文档引用遗留 → 本文 0.6；§6.2 描述漂移已修 |
| 2 | 通用图片归一化模块 | ✅ 已完成 | 无 |
| 3 | 删除任务端点 | ✅ 已完成（实现严于设计：路径穿越防护 + 404） | 无 |
| 4 | json_repair 容错 | ✅ 已完成 | 无 |
| 5 | 用户上传分镜场景图 | ✅ 已完成（三模式全接入，字段命名与设计不同） | C4 回归场景未入矩阵 → 本文 3.7 |
| 6 | `start.bat` | ✅ 已完成（超出规格：双语提示 + 端口检测） | 无 |

`docs/plans/v5.0/refactor_plan.md`（工程化重构）18/18 任务全部完结，一并归档。

### 调研存档（`docs/plans/optimization-research/`）评定结论

| 条目 | 评定 | 理由与复查触发条件 |
|------|------|-------------------|
| R1 — chained 双参考图 | **转入可执行**（本文 3.6） | 无外部依赖、改动小、回归面小 |
| R1 — 对话（对白）支持 | **继续存档观望** | 核心阻碍是 Agnes 视频模型无口型同步能力（外部硬限制），音频+字幕层的对白"配音感"无法消除，且回归面大。复查触发：Agnes 支持对白口型同步，或产品定位转向接受无口型的形态（广播剧/有声短剧风格） |
| R2 — Kokoro 等替代 TTS | **继续存档观望（倾向维持现状）** | 与项目决策 D8（仅用 edge_tts）冲突；切换会使字幕从词级时间戳真值倒退为句级；调研痛点之一（音色少）已被动态音色目录化解；剩余价值（离线/隐私）为边缘需求。复查触发：edge_tts 出现持续性封禁/限流导致批量失败，或出现明确的离线部署刚需（届时以"可选插件引擎"而非默认替换重启评估） |

两份存档文档按流转规则保留不删。

### 明确不做 / 暂不做

| 事项 | 理由 |
|------|------|
| 状态模型 `step_*` 字段瘦身（改 `steps: dict`） | 向后兼容成本高、收益有限，除非未来大版本允许破坏性变更，再行评估 |
| 引入 Pinia 等状态库 | 当前模块级单例 composable 复杂度可控，视后续复杂度再定 |
| 默认更换 TTS 引擎 / 对白支持 | 见上方评定结论 |

---

## 实施约定

1. **批次顺序**：0 → 1 → 2 → 3；批内 🔴 优先。批次 0 各条目互相独立，可随时单独执行；**1.6（测试）与批次 0 并行**，每修一项同步补一个回归测试。
2. **每项完成后**：按 `AGENTS.md` 自验（`py_compile` → 端点冒烟 → 涉流水线跑 `./scripts/run_mock_regression.sh` → 涉前端跑 `i18n_check` + `npm run build`），并更新本文状态列与「实施记录」。
3. **回归联动**：凡改变任务状态机/产物结构的条目（1.1/1.2/2.1/2.2），同步更新 `docs/dev/regression_test_plan.md`。
4. **新增待调研点**：价值存疑的新点子仍按 `docs/plans/optimization-research/README.md` 流转规则存档，评定后转入本文编批次。

## 实施记录

| 日期 | 条目 | 落地文件 | 自验记录 |
|------|------|---------|---------|
| 2026-08-26 | 0.6（部分） | `AGENTS.md` | 修正式文档化漂移：§6.2 多 Key/双桶现状、§6.6 音量系数 1.5、路线图引用路径更新 |
| 2026-08-28 | 路线图 review 修订 | `docs/plans/v6.0/optimization_roadmap.md` | 修正 0.5 尾帧误判（移除该项，仅留水印坐标）；0.6 明确「完善已有 .env.example」；1.1 补崩溃兜底；1.4 补索引归属；2.1 补词级字幕取舍；2.3 补同步调用方兼容 + 除零边界；新增 0.7（`_key_id` 哈希）/0.8（前端 XSS）/0.9（图片重复提交）；前端新问题并入 1.7/3.1/3.4 |
| 2026-08-28 | 批次 0 全部 9 项落地 | 0.1 `docker-run.sh`；0.2 `core/api/agnes_video.py`+`core/pipelines/{multi_scene,manuscript_video,anchor_video,creative/steps_video}.py`；0.3 `core/api/{agnes_video,agnes_image}.py`+`core/pipelines/__init__.py`+`utils/{video,image}.py`+6 个 pipeline（15 处 `await …save()`）；0.4 `web/deps.py`；0.5 `core/compositor/watermark.py`；0.6 完善 `.env.example`+`README.md`/`README_ZH.md`/`getting-started.md`；0.7 `web/routes/config_routes.py`；0.8 `frontend/src/composables/useProgress.ts`；0.9 `frontend/src/components/forms/SimpleForm.vue` | `py_compile` 全通过；370 单测 + 28 项 mock 回归全通过（7m39s）；`i18n_check` 通过；`vue-tsc --noEmit` + `vite build` 通过；端点冒烟（`/`、`/api/config`、`/api/tasks`、`/api/voices` 均 200）；`_key_id` 3 个 Key 各自精确命中；信号量 `acquire(4)` 失败后 `current` 保持 0 不变负 |
| 2026-08-28 | 批次 1（1.1~1.7 落地；1.8 待办） | 1.1 复核确认（v6.0 P0/P1 已实现 per-task 锁 + 启动状态校正，本次补充验证）；1.2 `core/pipelines/__init__.py`（cues 序列化/落盘/读取）+ 5 个 pipeline 调用点；1.3 `core/api/agnes_video.py`（`_adaptive_poll_interval`）+`core/pipelines/multi_scene.py`（Phase 2 并发 gather）；1.4 `web/routes/task_routes.py`（`limit/offset/status` 分页）；1.5 `core/artifacts.py`（poetry 检查点映射）+`core/api/error_collector.py`（`_MAX_ERROR_LOGS` 轮转）+`task_routes.py`（sweep `protect` 参数）；1.6 新增 `tests/test_api_retry_matrix.py`（14 项，暴露并修复 KeyRing 429 换 Key 失效 bug）+`test_optimization_batch0.py`+`test_artifact_governance.py`+`test_cues_cache.py`+`test_task_list_pagination.py`；1.7 `useProgress.ts`/`useTasks.ts`/`ProgressPage.vue`/`TaskListPanel.vue`（in-flight 守卫、连续失败退避提示、`visibilitychange` 后台暂停、`loadList` 收敛裸 fetch） | `py_compile` 全通过；新增 5 个测试文件 41 项通过；`test_core`/`test_routes`/`test_server_app`/`test_pipeline_contract`/`test_manual_pause`/`test_creative_package` 全通过；`i18n_check` 通过（断连横幅复用既有 `connLost` key，未新增翻译）；`vue-tsc --noEmit` + `vite build` 通过 |
| 2026-08-28 | 批次 1.8 落地 | `frontend/src/i18n/translations.ts`（删除）→ `langs/{lang}.json` 22 个；`frontend/src/i18n/index.ts`（`zh/en` 静态预载 + `import.meta.glob` 动态加载）；`scripts/i18n_check.py`（JSON diff + 占位符 + en 硬阻断 2/其他缺失 1）；`.github/workflows/test.yml`（`i18n-check` job）；`AGENTS.md` 文案规范同步 | 主 bundle `721 kB → 305 kB`（gzip `226 kB → 97 kB`，-58%）；20 个语言 chunk 30-38 kB 按需加载；`i18n_check` 通过（仅提醒 `keySrcConfig` en 同 zh）；`vue-tsc --noEmit` + `vite build` 通过；`regression_runner` i18n 前置门槛兼容（返回码语义 0/1/2） |
| 2026-08-28 | 批次 2（2.3/2.4/2.5 落地；2.1/2.2 待独立批次） | 2.3 `core/api/rate_limiter.py`（`_try_acquire` 解耦 + `acquire_async(stop_event)` 异步原生 + 速率 0 除零防护）+ `core/api/{agnes_video,agnes_image}.py`（4 处调用改异步原生）+ `core/pipelines/__init__.py`（`_ENCODING_EXECUTOR` 专用线程池）；2.4 `core/task_manager.py`（`_save` 去 `indent=2`）+`core/pipelines/__init__.py`（`_emit` 进度节流 `_PROGRESS_SAVE_THROTTLE_SECONDS=0.5`）；2.5 `core/pipelines/manuscript_video.py`（段落 prompt `asyncio.Semaphore(3)` 有限并发，进度语义「开始→完成」） | 新增 `tests/test_rate_limiter_async.py`（5 项）+`test_progress_throttle.py`（3 项）通过；`test_api_retry_matrix`/`test_pipeline_contract`/`test_manual_pause`/`test_core` 全通过；同步 `acquire` 保留（chat/脚本兼容）；`FakeLimiter` 补 `acquire_async`；修复 acquire_async 预支语义重复 `_try_acquire` 无限等待 bug |
| 2026-08-28 | 批次 2 剩余评估 | 2.1（成片合成链 ffmpeg 化）/2.2（poetry 编码合并）为**大工程**：改动合成链核心（moviepy→ffmpeg concat demuxer + 单 filter 链 + 字幕 ASS 化），回归面广、验证成本高（需完整 mock 回归），建议作为独立批次（2.1a 拼接 /-c copy → 2.1b 对齐与音量单链 → 2.1c 字幕 ASS 灰度），不在当前批次内仓促实施 |
| 2026-08-28 | 2.1a 落地（拼接 ffmpeg 化第一步） | `core/compositor/concatenator/concat.py`（`_try_ffmpeg_copy_concat`：probe 分辨率/帧率一致 → concat demuxer + `-c copy`，失败自动回退 moviepy compose） | 新增 `tests/test_concat_ffmpeg_fastpath.py`（5 项）通过；`test_pipeline_contract`/`test_core` 无回归；2.1b（对齐/音量单链）/2.1c（字幕 ASS 灰度）待后续 |
| 2026-08-28 | 2.1b 落地（无字幕路径单链一次编码） | `core/compositor/concatenator/audio_overlay.py`（`_ffmpeg_mux_aligned`：`tpad` 冻结补帧 + `apad=whole_dur` 静音 + `volume=1.5` 单条 filter 链 + `-t` 对齐，一次编码替代 Step3/4/5 三遍编码；无字幕时启用，失败回退 moviepy） | 新增 `tests/test_overlay_single_pass.py`（2 项）通过（断言 `_run_ffmpeg` 仅 1 次 + 音频长于视频尾帧补齐）；2.1c（字幕 ASS 灰度，覆盖有字幕场景）仍待后续 |
| 2026-08-28 | 批次 3 部分（3.6/3.2/3.7） | 3.6 `core/pipelines/creative/steps_video.py`（chained 双参考图 `[尾帧, 角色参考图]`，首场景去重）；3.2 新建 `web/routes/health_routes.py`（`/api/health` + `/api/metrics`）+ `server.py`（路由注册 + `AGNES_LOG_FILE` RotatingFileHandler）+ `Dockerfile`（HEALTHCHECK）；3.7 `scripts/regression_runner.py`（场景 P1/I1/C4 + 权重/超时 + 并发上限从 `/api/metrics` 读取）+ `run_mock_regression.sh`（poetry 过滤器）+ `docs/dev/regression_test_plan.md`（矩阵 8→11 场景）；修复 2.3 引入的 `run_in_executor` 关键字参数 bug（`functools.partial`） | `test_health_metrics.py`（2 项）+ 端点冒烟（`/api/health`、`/api/metrics` 均 200）；`TestPoetryVideoPipeline` 9 项通过（暴露并修复水印 `run_in_executor` bug）；`py_compile` 全通过 |
| 2026-08-28 | 3.3 落地（CI 补强） | `.github/workflows/test.yml`（test job Python 3.10/3.12 矩阵 + `ruff` step + `setup-node` + `npm test`（vitest）+ 前端 `vue-tsc`/build）；`requirements-dev.txt`（加 `ruff`）；`frontend/package.json`（加 `vitest` + `npm test` script）；新增 `frontend/src/utils/feedback.test.ts`（4 项，`isDeterministicError` 纯函数）；新建 `ruff.toml`（select E/F/I + line-length 120 + 豁免 E501/E402/F821 误报/I001 刻意顺序）；`ruff check --fix` 清理 161 处存量告警（删 8 处死变量、2 处未用 import、4 处 lambda→def、2 处变量重命名等） | `ruff check` 全通过（零告警）；后端 `test_core`/`test_pipeline_contract` 全通过；前端 `vitest` 4 项通过；修复 ruff isort 排序破坏 `core/pipelines/__init__.py` 刻意导入顺序导致的循环导入（恢复顺序 + 配置豁免 I001） |
| 2026-08-28 | 批次 3 部分（3.5/3.1 核心） | 3.5 `web/app_state.py`（`WeightedSemaphore.update_max_weight` 动态调整 + `get_semaphore()` 按 `rate_limiter.effective_rate_per_min` 动态缩放并发上限，0.4 硬拒绝场景消除）；3.1 `frontend/src/api/index.ts`（`request()` 统一检查 `r.ok`，非 2xx 抛带后端 `detail` 的可读错误） | 新增 3 项信号量动态缩放测试通过；`test_health_metrics`/`test_pipeline_contract` 通过；`vitest` 4 项 + `vite build` 通过；3.1 的 useConfirm/useTaskSubmit 收敛与 3.5 的 pydantic-settings 完整版标注为后续增强 |
| 2026-08-30 | 2.1c 落地（字幕 ASS 灰度） | `core/compositor/concatenator/audio_overlay.py`（`_srt_to_ass` SRT+样式→ASS 句级样式转换：字体/字号/主色/描边/半透明底/位置→alignment+margins、逐条样式按 index 覆盖、`_ffmpeg_mux_aligned` 追加 `subtitles` 滤镜 + `fontsdir`）；`core/config.py`（`AGNES_SUBTITLE_ASS` 开关，默认开启，失败自动回退 moviepy） | 新增 `tests/test_subtitle_ass.py`（10 项）通过；`test_overlay_single_pass`/`test_concat_ffmpeg_fastpath` 无回归；修复无字幕分支 filter 链 `[v0][v]` 双标签语法错误 |
| 2026-08-30 | 2.2 落地（poetry 多场景单链一次合成） | `core/compositor/concatenator/audio_overlay.py`（`concat_scenes_single_pass`：场景视频 `-c copy` 拼接 + `_merge_scene_audios` adelay/amix/apad 合并 + `_merge_scene_srts` 偏移合并 → 最终一次编码；失败回退逐场景）；`core/pipelines/poetry_video.py`（`_composite_final` 重构：全量缺失时优先单链、续传快速路径复用已合成场景） | 新增 `tests/test_scenes_single_pass.py`（6 项）通过；`TestPoetryVideoPipeline` 12 项 mock 回归通过 |
| 2026-08-30 | 3.1 落地（前端交互层统一收尾） | `frontend/src/composables/useTaskSubmit.ts`（提交统一执行器 + `collectAudioSubtitleFields`）；`useConfirm.ts` + `ConfirmModal.vue`（确认弹窗）；`useToast.ts`/`Toast.vue`（type: error/success/info）；5 个表单 + `useTasks`/`useConfig`/`useArtifacts`/`useVoice`/`ConfigPanel`/`TaskListPanel`/`CheckpointDetail` 替换全部 44 处原生 `alert()/confirm()`；i18n 22 语言新增 `confirm` key | `vue-tsc --noEmit` + `vite build` 通过；`i18n_check` 通过；残留原生弹窗搜索为 0 |
| 2026-08-30 | 3.4 落地（移动端/可访问性/杂项） | `useGa.ts`（`localStorage 'ga_opt_out'` 开关 + `SENSITIVE_KEYS` 上报脱敏 + 长文本截断）；`useModalA11y.ts`（focus trap + ESC + 焦点还原，接入 ConfirmModal/VoicePickerModal）；`useVoice.ts`（blob URL revoke）；`useTheme.ts`（matchMedia 监听器清理）；`useDraft.ts`（表单草稿，接入 SimpleForm/CreativeForm）；`style.css`（`prefers-reduced-motion` + `:focus-visible`）；`App.vue`（窄屏字号/导航换行）；`ConfigPanel.vue`（隐私开关）+ i18n 22 语言 | `vue-tsc --noEmit` + `vite build` 通过；`i18n_check` 通过 |
| 2026-08-30 | 3.5 落地（pydantic-settings 完整版） | `core/config.py`（`RuntimeSettings(BaseSettings)`：host/port/限速×4/i2i 模型/prompt_language/字幕 ASS/轮询超时/log_file/sweep/hmac_key/regression 工作目录，env_file=.env，无缓存每次动态读取保证测试可覆盖）；`requirements.txt`（+`pydantic-settings`）；收敛调用点：`rate_limiter.py`×4、`app_state.py`、`agnes_image.py`、`agnes_video.py`（轮询超时参数化）、`screenwriter`、`server.py`（host/port/log/sweep）、`config_routes.py`、`config.py`；`audio_overlay.py` 经 `subtitle_ass_enabled()` 联动 | 新增 6 项 `test_config_settings.py` 用例通过；`test_core`/`test_rate_limiter_async`/`test_subtitle_ass`/`test_scenes_single_pass` 全通过；无 pydantic-settings 时降级读 os.environ 兜底 |

---

*文档版本：v1.3（2026-08-30）| 创建日期：2026-08-26 | 目标版本：v6 版本线内全部完成 | 状态：**29 项全部完成**（批次 0 全 9、批次 1 全 8、批次 2 全 6（2.1a/2.1b/2.1c/2.2/2.3/2.4/2.5）、批次 3 全 7）*
