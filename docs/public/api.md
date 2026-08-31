# 📋 API Endpoints

> Frontend polls task state via `GET /api/tasks/{id}` — there is **no WebSocket** endpoint.

## 配置与工作区

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web UI |
| GET | `/api/config` | Get API key (masked) |
| POST | `/api/config` | Save API key |
| DELETE | `/api/config` | Clear API key |
| GET | `/api/models` | List available Agnes models (text/image/video groups, cached) |
| POST | `/api/config/models` | Save selected models |
| POST | `/api/config/watermark` | Save watermark toggle |
| POST | `/api/config/domain` | Set Agnes API domain suffix (`com`/`cn`) |
| GET | `/api/workspaces` | List workspaces |
| POST | `/api/workspaces` | Create workspace |
| DELETE | `/api/workspaces` | Delete workspace |
| POST | `/api/workspaces/active` | Activate workspace |
| GET | `/api/workspaces/pick-directory` | Native directory picker |

## CORS 跨源白名单（供独立本地伴侣工具调用）

> PR #33 吸收（Phase 2）：可配置 CORS，取代原硬编码的 `localhost:8787`。
> 默认**不启用**（攻击面不变）；设置白名单后，任意独立本地工具均可从浏览器跨源调用本服务 API。

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `AGNES_CORS_ORIGINS` | 空 | 逗号分隔的允许源列表，如 `http://localhost:8787,http://127.0.0.1:3000`；空 = 不启用 CORS |
| `AGNES_CORS_ENABLED` | auto | `auto`（缺省）= 设置了 `AGNES_CORS_ORIGINS` 才启用；`false` = 即使设置了 origins 也禁用中间件 |

行为：启用时注入 `CORSMiddleware`，`allow_methods=["*"]`、`allow_headers=["*"]`、`allow_credentials=False`（API 认证走显式 API Key 请求头，不使用 Cookie，故始终安全）。同源页面使用不受影响。

```bash
# 示例：允许本地 :8787 的独立简化前端调用本服务
AGNES_CORS_ORIGINS=http://localhost:8787,http://127.0.0.1:8787 bash start.sh
```

> **参考图 API 语义差异（重要，避免混淆）**：
> - **创意模式 `scene_reference_images`**：按场景**顺序**对齐——第 `i` 张上传图 → 第 `i` 个场景（`POST /api/tasks/creative` 的 `scene_reference_images` 文件列表）。
> - **稿件模式 `reference_images` + `reference_images_map`**：按**段落 index 显式映射**——`reference_images_map` 为 JSON 数组（顺序与上传图一致），第 `i` 张图对应 `reference_images_map[i]`（非负整数数组，每项是段落 index）；**一张图可服务多个段落**。段落数在任务执行拆段后才确定，越界 index 记 warning 并忽略该图（不 422）。
> - 两者命名相似但对齐规则不同，调用时请按上文分别处理。

## 音色 (TTS Voices)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/voices` | List available TTS voices (grouped by 13 languages) |
| GET | `/api/voices/preview` | Voice preview (generated/cached sample) |
| GET | `/api/voices/compat` | Voice × language compatibility check |

## 图片 (Image)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/image/generate` | Generate simple image (t2i / i2i) |
| GET | `/api/image/{task_id}` | Download/preview generated image |

## 任务创建 (Task Creation)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tasks/simple` | Create simple video task |
| POST | `/api/tasks/creative` | Create creative video task |
| POST | `/api/tasks/manuscript` | Create manuscript video task |
| POST | `/api/tasks/poetry` | Create poetry video task |
| POST | `/api/tasks/anchor` | Create digital-anchor task |
| POST | `/api/tasks` | Legacy task creation (mapped to creative) |
| GET | `/api/poetry-scene-prompt` | Pre-generate poetry scene prompts |

**PR #33 吸收新增表单参数**：
- `audio_add_tashkeel`（creative / manuscript，默认 `false`）：阿拉伯语旁白自动加变音符号（tashkeel/harakat），提升 TTS 朗读准确度。**只作用于送入 TTS 的文本**——字幕与 `narration.txt` 产物始终保持无变音符号的干净版本（字幕隔离）。
- `reference_images`（manuscript，文件列表）+ `reference_images_map`（JSON 数组字符串）：逐段参考图，按段落 index 显式映射（见上「参考图 API 语义差异」）。

## 预览端点 (Preview — PR #33 吸收)

> 同步「干跑」预览，**不创建任务**。供独立本地伴侣工具在提交正式任务前展示
> LLM 产出/分段结果，供用户确认。

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/creative/preview-script` | 同步生成故事 + 分场景脚本 + 旁白文案（参数同 `/api/tasks/creative`，另加 `content_lang`∈`{"ar","en"}`、`add_tashkeel`） |
| POST | `/api/manuscript/preview-split` | 按正式稿件算法预览分段结果与估算时长（`manuscript_text`、`add_tashkeel`） |

**成本与防滥用（务必阅读）**：
- `preview-script` 每次调用 = **3 次真实 LLM Chat 调用**（develop_story + write_script + generate_narration_for_video），消耗共享限速桶配额，**并非零成本接口**——请勿将其当作免费接口高频轮询。
- 进程内并发上限 2（`asyncio.Semaphore`），超限返回 `429 + Retry-After: 5`。
- `preview-split` 不调用 LLM（纯文本拆分），但同样计入并发上限。

## 任务查询与控制 (Task Query & Control)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List all tasks (with `task_type`) |
| GET | `/api/tasks/{task_id}` | Query task detail (polling progress) |
| POST | `/api/tasks/{task_id}/resume` | Resume interrupted task |
| POST | `/api/tasks/{task_id}/stop` | Stop running task |
| POST | `/api/tasks/sweep` | Sweep zombie task directories from disk |
| GET | `/api/concurrency` | Concurrency semaphore utilization |
| GET | `/api/video/{task_id}` | Download/stream final video |

## 中间产物 (Artifacts)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks/{task_id}/artifacts` | List task artifacts |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}/file` | Download artifact file |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview` | Preview cascade-deletion impact |
| DELETE | `/api/tasks/{task_id}/artifacts/{artifact_id}` | Delete artifact (with cascade) |

## 运维 (Ops)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/cleanup-regression` | Clean up regression-test artifacts |

## 快速示例（curl）

```bash
# 1. 保存 API Key（免费获取：https://platform.agnes-ai.com）
curl -X POST http://localhost:8765/api/config -F "api_key=sk-你的Key"

# 2. 创建简单视频任务
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=一只橘猫趴在雨后窗台上打盹，4K 写实" \
  -F "mode=t2v" \
  -F "duration=5" \
  -F "resolution=768x1152"

# 3. 轮询任务状态，直到 status=completed
curl http://localhost:8765/api/tasks/<task_id>

# 4. 下载最终视频
curl -o output.mp4 http://localhost:8765/api/video/<task_id>
```
