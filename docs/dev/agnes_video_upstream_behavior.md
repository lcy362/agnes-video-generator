# Agnes 视频上游接口实测行为（Upstream Video API Behavior）

> **文档定位**：记录 `apihub.agnes-ai.com` 视频接口**实测**的行为、错误语义与产物规格，供流水线重试策略、错误透出、回归判定与对外文档撰写时引用。本文只写「观测到的事实」，改进项见 `../plans/v7.0/upstream_error_handling_plan.md`。
> **最近实测**：2026-09-28 上午（UTC+8），用本机 `AGNES_API_KEY` 直连上游，请求体逐字段复刻官网 `/en/demo` 前端（`video-website/components/demo/TextToVideo.tsx`）。样本量小（每档 1–2 次），标注为「单例」的结论不得当作稳定规律。
> **关联**：Issue #75（demo 报 "Video generation timed out"）、`docs/public/faq.md`、`docs/dev/regression_test_plan.md` F3、`docs/dev/pipeline_products.md`。

---

## 1. 接口清单

| 用途 | 端点 | 实测结论 |
|------|------|----------|
| 提交生成 | `POST /v1/videos` | 正常。返回体同时含 `id` / `video_id` / `task_id` 三个字段（语义见 §2） |
| 轮询状态 | `GET /agnesapi?video_id=<id>` | **唯一能拿到终态与失败原因的端点**。2.5 系列需追加 `&model_name=<model>` |
| 查询单任务 | `GET /v1/videos/<id>` | 对本项目产生的任务一律 `400 {"code":"task_not_exist"}`，不可用 |
| 任务列表 | `GET /v1/videos` | `404 {"message":"Invalid URL (GET /v1/videos)"}`，不存在 |
| 模型清单 | `GET /v1/models` | 正常，含 `agnes-video-2.5-flash` 等 |
| 文生图 | `POST /v1/images/generations` | 正常，同步返回（实测 11.6s 出 `data[0].url`） |

**双域名同库**：同一个 `video_id` 在 `apihub.agnes-ai.com` 与 `apihub.agnes-ai.cn` 上查到的记录完全一致（`created_at`/`completed_at`/`error` 全同），说明两域名共享任务存储。多 Key 域名回退（`core/config.py` 的域名映射）不会因为切换域名而丢失已在途的任务。

**网关身份**：响应头带 `x-new-api-version` / `x-oneapi-request-id` / `x-trace-id`，即 apihub 是 new-api 网关。**网关自造的错文案都带 `(request id: ...)` 后缀**（如 `task not found (request id: ...)`、`video queue is full, please retry later (request id: ...)`）；不带该后缀的（如 §3 的 15 分钟错）是从推理后端透传出来的任务记录内容。

---

## 2. 任务 id 的三个字段（易踩坑）

提交响应里三个字段的值**不总是相同**，且**只有 `video_id` 一定能轮询**：

| 模型 | `id` | `video_id` | `task_id` | 用哪个轮询 |
|------|------|-----------|-----------|-----------|
| `agnes-video-v2.0` | `task_jnDq1BTH…` | `video_bGl0ZWxsbT…`（base64，内嵌 `video_1e081f87…`） | 同 `id` | **`video_id`**。用 `id` 轮询 → `404 task not found` |
| `agnes-video-2.5-flash` | `task_putf0OHP…` | 同 `id` | 同 `id` | 三者等价 |

`video_id` 解码后形如 `litellm:custom_llm_provider:openai;model_id:agnes-video-v2.0;video_id:video_xxx`，是网关的路由键，**长度可变、不要假设格式**。

> 现状核对：`core/api/agnes_video.py:437` 与官网 demo `TextToVideo.tsx:274` 都按 `video_id || task_id || id` 取值，顺序正确。任何新代码（含脚本、回归工具）都必须沿用这个优先级，不要图省事用 `id`。

---

## 3. 终态与错误语义

### 3.1 失败是 HTTP 200

轮询端点在任务失败时**仍返回 HTTP 200**，失败信息在响应体里：

```json
{
  "status": "failed",
  "internal_status": "stuck_inference",
  "error": {"code": "500", "message": "ComfyUI internal error: inference not finished after 15 minutes"},
  "url": null,
  "created_at": 1790562564,
  "started_at": null,
  "completed_at": 1790563517,
  "progress": 0,
  "internal_progress": 100
}
```

只判断 HTTP 状态码的客户端会把它当成成功。**判据只能是 body 的 `status` + `error`。**

### 3.2 上游有约 15 分钟的推理硬闸

上例从 `created_at` 到 `completed_at` 为 **953 秒**，`error.message` 明写 "not finished after 15 minutes"，`url` 为 `null`。即：**这类任务再等也不会有产物**，不是"等得不够久"。（单例观测；阈值起点未独立验证——该记录 `started_at` 为 `null`，无法确认 15 分钟是从创建还是从推理开始计时。）

### 3.3 字段可靠性

| 字段 | 可用性 | 说明 |
|------|--------|------|
| `status` | ✅ 可作判据 | 观测到 `pending` / `in_progress` / `completed` / `failed` |
| `error` | ✅ 但**是对象** `{code, message}` | 直接当字符串用会污染文案或崩渲染 |
| `url` | ✅ 终态产物地址 | 失败时为 `null`；域名会在 `platform-outputs.agnes-ai.space` 与 `cos-platform-outputs.agnes-ai.cn` 之间变化 |
| `progress` / `internal_progress` | ❌ 不可作判据 | 失败样本里 `progress=0` 而 `internal_progress=100`，互相矛盾 |
| `started_at` | ⚠️ 可能为 `null` | 不能用来推算排队/推理耗时 |
| `perf_params` | ⚠️ 是**推理内部尺寸**，非产物尺寸 | 见 §5 |
| `expires_at` | 观测均为 `null` | 产物链接有效期未知，仍应尽快下载落盘 |

### 3.4 状态迁移（实测样本）

- 2.5-flash：`pending`(progress 0) → `in_progress`(10 → 70) → `completed`(100)。接受后 **158s**（5s/9:16）与 **86s**（4s/16:9）完成。
- v2.0：`in_progress`(30) → `completed`(100)。接受后 **92s**（5s）/ **88s**（5s 竖屏）完成。
- 排队→开始渲染的间隔：`created_at → started_at` 实测 36s（2.5-flash 一例）。

---

## 4. 提交侧瞬时错误

| HTTP | body `code` | 实测行为 | 含义 |
|------|-------------|----------|------|
| 503 | `video_queue_full` | `video queue is full, please retry later (request id: ...)`。2.5-flash 上观测到**连续 25 次提交、跨约 12 分钟全部被拒**（10:40–10:52），期间同 Key 的 v2.0 提交正常通过 | 免费 2.5-flash 队列饱和，按模型分池；被拒不产生任务、不消耗渲染配额，可安全重试 |
| 503 | `fail_to_fetch_task` | 一次观测（11:05:13），25s 后重试即成功 | 上游内部瞬时故障，可重试 |
| 429 | — | 未在本轮复现 | 现有换 Key 逻辑针对此码 |
| 401 | — | 未在本轮复现 | Key 与域名不匹配（见 FAQ） |

**关键区分**：`video_queue_full` 是「没排进队」，§3.2 的 `stuck_inference` 是「排进去了但渲染卡死」。两者用户侧表现完全不同，文案与重试策略也应不同。当前代码把 503 一律并入 `status_code >= 500` 分支（`core/api/agnes_video.py` `_submit_with_retry`），只记 `HTTP 503: server error`，**丢掉了 body 里的 `code`**。

> **v7.0 已落地**（`docs/plans/v7.0/upstream_error_handling_plan.md` U1/U2）：503 分支解析 body `code`，命中
> `video_queue_full` / `fail_to_fetch_task` 走独立退避轨道（默认预算 900s，`AGNES_VIDEO_QUEUE_RETRY_SECONDS`），
> 错误文案透出 `message` + `code`。

### 4.0.1 已知缺口：body 无 `code` 的裸 503 走普通 5xx 配额（Issue #80 / #81 / #83，2026-10-02）

**实测证据**（用户反馈的 `Model call error` 序列，#81，App 6.4.5 / Windows）：

| 时间 | 错误 |
|------|------|
| 20:09:08 | `HTTP 503: server error` |
| 20:09:38 | `HTTP 503: server error`（+30s） |
| 20:10:39 | `HTTP 503: server error`（+60s） |
| 20:12:09 | `HTTP 503: server error`（+90s） |
| 20:14:10 | `HTTP 503: server error`（+120s） |
| 20:16:40 | `RetriesExhausted: reference (2 images, keyframe fallback): max retries (5) exceeded`（+150s） |

间隔精确等于 `retry_base_delay(30s) × (attempt+1)`，**证明这些 503 的 body 里没有可识别的 `code`**
（否则会进 U1 队列轨道，表现为 30–60s 抖动、总预算 900s，而非 5 次线性退避）。

**问题**：`_QUEUE_FULL_CODES` 只覆盖 `video_queue_full` / `fail_to_fetch_task` 两个已知码。上游在过载期
也会返回**无 code 的裸 503**，此时应用只享 5 次普通配额（约 5.5 分钟），而本节实测队列饱和**可持续 12 分钟以上**
——应用会在「再等一分钟就能排上」时提前放弃，用户侧表现为无端失败。

**待办（v7.1 候选，未实施）**：对 `HTTP 503` 且 `code` 为空/未知的响应，比照队列满纳入长预算轨道
（复用 `AGNES_VIDEO_QUEUE_RETRY_SECONDS`），或至少把普通 503 的配额与 5xx 其他状态码区分开。
需补单测：mock 连续裸 503 → 断言总时长受控且不与普通 5xx 混用配额。

> 本轮（2026-10-02）按外部故障处理，仅回复用户 + 记档，未改代码。#80 与 #83 为同一用户（App 7.0.0，
> 无 traceback），#81 为 6.4.5 且附完整 traceback，三例错误文案与路径一致（`reference` / keyframes）。

### 4.1 待实测：`video_queue_full` 是否按 Key 分池（U7，未验证）

**已知**：单 Key 连续 25 次被拒（跨约 12 分钟）期间，同一 Key 的 v2.0 提交**正常通过** → 队列**按模型分池**。

**未知**：多 Key 场景下，命中 503 `video_queue_full` 时**换 Key 能否立刻排进队**（即队列是否也按 Key 隔离），
或只是全局同一池（换 Key 无帮助）。当前代码对 503 不换 Key（仅 429 换 Key）。

**待实测步骤**（需要 ≥2 个可用 Key，且 2.5-flash 队列处于饱和时段）：

```bash
# 1) Key A 提交，观察是否 503 video_queue_full
curl -sS -X POST https://apihub.agnes-ai.com/v1/videos \
  -H "Authorization: Bearer $AGNES_API_KEY_A" -H "Content-Type: application/json" \
  -d '{"model":"agnes-video-2.5-flash","prompt":"test","mode":"text","seconds":"5","size":"720P","aspect_ratio":"16:9"}'
# 2) 被拒后立即用 Key B 提交同一请求，记录是否仍为 503 及 body code
curl -sS -X POST https://apihub.agnes-ai.com/v1/videos \
  -H "Authorization: Bearer $AGNES_API_KEY_B" -H "Content-Type: application/json" \
  -d '{"model":"agnes-video-2.5-flash","prompt":"test","mode":"text","seconds":"5","size":"720P","aspect_ratio":"16:9"}'
```

**实测记录**（复测后填写本行）：`待补`。若证实按 Key 分池，再把 U1 的队列重试与「换 Key 立即重试」结合。

---

## 5. 分辨率与方向

### 5.1 v2.0：标准档保真，非标准档被吸附

| 请求 width×height | 产物容器（ffprobe 实测） | `perf_params`（推理内部） | 结论 |
|---|---|---|---|
| 768×1152（本项目竖屏档） | **768×1152** | 832×1088 | ✅ 保真 |
| 1280×720（本项目横屏档，v7.0.2 true 16:9） | **1280×720** | 1280×704 | ✅ 保真 |
| 1152×768（官网 demo 的"16:9"，实为 3:2） | **1088×832** | 1088×832 | ❌ 吸附到 ≈4:3，比例 1.50 → 1.31 |
| 768×1360（官网 demo 的"9:16"） | **704×1280** | 704×1280 | ❌ 吸附，但恰好落回真 9:16 |

规律：**请求命中常用标准像素档时容器即请求值；命中非标准值时上游按自己的 latent 桶重画**。所以 `perf_params` 不能用来校验产物分辨率，必须 ffprobe 产物文件（回归 F3 现行做法正确）。

### 5.2 2.5-flash：竖屏（9:16）产物画面躺倒 —— 上游缺陷

| `aspect_ratio` | 请求 | 产物容器 | 画面方向 |
|---|---|---|---|
| `16:9` | `size=720P, seconds=4` | **1280×720** | ✅ 正常 |
| `9:16` | `size=720P, seconds=5` | **720×1280** | ❌ **内容顺时针躺倒 90°**：容器是竖的，像素是横屏构图；对产物做 `ffmpeg -vf transpose=2`（逆时针 90°）后得到正确的 1280×720 横屏画面 |
| `3:4` | `size=720P, seconds=4` | **834×1112**（比例 0.75 保真；绝对像素不是 UI 标注的 720×960） | ✅ 正常 |
| `1:1` | 未测 | — | — |

即上游在 9:16 下**只交换了容器宽高，没有旋转像素**（产物内无 `display matrix` / rotation 元数据，已用 ffprobe 确认）。由于本项目 2.5-flash 分支发送的 payload 与 demo 完全一致（`mode=text` / `size=720P` / `aspect_ratio=9:16`），**自托管用户选竖屏同样会拿到躺倒的成片**，且会一路带到拼接与字幕叠加环节。

**2.5 系列的分辨率规律**（与 v2.0 不同）：`aspect_ratio` 是枚举、`size` 固定 720P，**比例保真、绝对像素不保真**——`16:9` 恰好落在 1280×720，`3:4` 落在 834×1112。因此 UI 上给 2.5 系列标注的 `720×1280` / `720×960` 这类具体像素只是「比例示意」，不能当产物校验基准；回归校验该系列只能按比例（`docs/dev/regression_test_plan.md` F3 现行做法正确）。

---

## 6. 对内的直接影响（结论条目）

1. **重试预算**：`video_queue_full` 可持续 12 分钟以上，而视频提交重试当前为 5 次 × 30s 递增退避（约 5 分钟），免费 2.5-flash 场景下大概率在排进队之前就放弃。
2. **错误透出**：503 分支与轮询 `failed` 分支都没有提取 `error.message` / body `code`，用户与 `error_logs/` 看到的是 `HTTP 503: server error` 与整个 dict 的字面量，真实原因（队列满 / 上游 15 分钟卡死）丢失。这正是 Issue #75 用户被误导的根因。
3. **竖屏成片方向**：2.5-flash + 9:16 需要后处理校正或明确提示，否则自托管长视频流水线会产出横躺的多场景成片。
4. **回归判定**：分辨率校验必须读产物容器（现行正确），且**当前任何按宽高比做的校验都发现不了"容器对、内容躺倒"**这一缺陷。
5. **轮询节奏**：`progress` 字段不可信，自适应间隔（`_adaptive_poll_interval`）只能按次数/时间推进，不要依赖进度值做判断。
6. **404 可见性窗口会劣化**（2026-09-28 实测）：提交成功（200 + `video_id`）后，任务记录在 `/agnesapi` 可见前的 404 窗口平时 ~20s，上游高峰期可劣化到 **10min+ 甚至全程不可见**（三个观测样本 420s / 1100s+ 未出现）。因此轮询侧 404（`task not found`，带 request id 后缀的网关错误）按「任务未就绪」中间态处理（U9，v7.0.4）：不计入连续失败配额、不进 `error_logs`，仅周期性 info 日志，最终由 `max_poll_duration`（`AGNES_VIDEO_POLL_TIMEOUT`）整体兜底；超时异常不属于「服务端确认失败」，续传保留 `video_id`。

---

## 7. 复测方法

无需启动本项目服务，直接复放上游调用即可（与官网 demo 同链路）：

```bash
export AGNES_API_KEY=...
# 提交（2.5-flash 竖屏）
curl -sS -X POST https://apihub.agnes-ai.com/v1/videos \
  -H "Authorization: Bearer $AGNES_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"agnes-video-2.5-flash","prompt":"...","mode":"text","seconds":"5","size":"720P","aspect_ratio":"9:16"}'
# 轮询（务必用响应里的 video_id；2.5 系列带 model_name）
curl -sS "https://apihub.agnes-ai.com/agnesapi?video_id=<video_id>&model_name=agnes-video-2.5-flash" \
  -H "Authorization: Bearer $AGNES_API_KEY"
# 产物方向
ffprobe -hide_banner <file>.mp4          # 看 Stream 的 WxH 与有无 Display Matrix
```

v2.0 用 `{"model":"agnes-video-v2.0","prompt":"...","width":768,"height":1152,"num_frames":121,"frame_rate":24}`，轮询时**不带** `model_name`。

---

*创建：2026-09-28（Issue #75 排查过程中的实测沉淀）| 样本：v2.0 4 档成功、2.5-flash 3 档成功（9:16 / 16:9 / 3:4）、文生图 1 次、提交被拒约 40 次*
