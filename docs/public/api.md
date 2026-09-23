# 📋 API Endpoints

> Frontend polls task state via `GET /api/tasks/{id}` — there is **no WebSocket** endpoint.
>
> Backend-generated messages (task progress, `HTTPException` details, diagnostics) are localized
> per request: `X-Agnes-UI-Lang` > `Accept-Language` > `zh`.

## 配置与工作区

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web UI |
| GET | `/api/config` | Get API key (masked) |
| POST | `/api/config` | Save API key |
| DELETE | `/api/config` | Clear API key |
| GET | `/api/models` | List available Agnes models (text/image/video groups, cached) |
| POST | `/api/config/models` | Save selected models (optional `text_provider` switches the text route) |
| POST | `/api/config/watermark` | Save watermark toggle |
| POST | `/api/config/domain` | Set Agnes API domain suffix (`com`/`cn`) |
| GET | `/api/config/text-providers` | List text providers (built-in `agnes` first, keys masked) |
| POST | `/api/config/text-providers` | Add / update a text provider (upsert by `provider`) |
| DELETE | `/api/config/text-providers/{provider}` | Delete a text provider (built-in `agnes` → 400) |
| POST | `/api/config/text-providers/test` | Probe a provider's model list — **not persisted** |
| POST | `/api/config/text-providers/{provider}/sync` | Save that provider's model list (no probe) |
| GET | `/api/workspaces` | List workspaces |
| POST | `/api/workspaces` | Create workspace |
| DELETE | `/api/workspaces` | Delete workspace |
| POST | `/api/workspaces/active` | Activate workspace |
| GET | `/api/workspaces/pick-directory` | Native directory picker |

## 文本模型供应商 (Text Model Providers — v7.0)

> 文本模型可插拔：除内置 Agnes 外，可配置任意 **OpenAI 兼容** / **Anthropic 兼容** 的 LLM
> 端点（`base_url` + `api_key`），供编剧拆解 / 分镜 / 诗词拆分 / 图片 prompt 改写等全部文本调用。
> 内置 `agnes` 恒在列表首位且不可删除；未选择自定义供应商时行为与旧版一致，旧 `config.json`
> 无需迁移即可读取。
>
> ⚠️ 自定义供应商的 `api_key` 一期**落盘**在本地 `config.json`（文件权限 `0600`），接口一律只回掩码。

**供应商字段**（`config.json` → `text_providers[]`）：

| Field | Type | Description |
|-------|------|-------------|
| `provider` | str | Unique route key (also the path param); `agnes` is reserved for the built-in |
| `display_name` | str | Label shown in the UI |
| `api` | str | Wire protocol: `openai-completions` \| `anthropic-messages` |
| `base_url` | str | Endpoint base; `/chat/completions`, `/v1/messages` and `/models` are appended per protocol |
| `api_key` | str | Credential (stored locally, always returned masked) |
| `models` | list[str] | Candidate models in configured order (probe result or hand-written) |

当前生效的文本供应商记录在 `models.text_provider`（空串 = 内置 Agnes），模型 id 记录在 `models.text`。

| Method | Path | Form fields | Description |
|--------|------|-------------|-------------|
| POST | `/api/config/text-providers/test` | `base_url`, `api_key`, `api`, optional `provider` | Probe the endpoint's model list, **not persisted**; returns `{ok:true, models:[...]}` or `{ok:false, error}`. Passing `provider` reuses that provider's stored `base_url`/`api_key` |
| GET | `/api/config/text-providers` | — | List providers — built-in `agnes` first with `builtin:true`, keys masked; also returns `selected` and `current_model` |
| POST | `/api/config/text-providers` | `provider`, `display_name`, `api`, `base_url`, `api_key`, `models_json` | Add / update (upsert by `provider`); an empty `api_key` keeps the stored one |
| DELETE | `/api/config/text-providers/{provider}` | — | Delete; deleting the currently selected one falls back to `agnes` |
| POST | `/api/config/text-providers/{provider}/sync` | `models_json` | Replace that provider's model list without probing |

**错误响应**：`400` = 删除/同步内置 `agnes`、`provider` 为空；`404` = 供应商不存在；`422` = `api` 非法、`base_url` 为空、`models_json` 不是合法 JSON 数组。

```bash
# 1) 探测（不落盘）：用此刻输入的 key + base_url 拉模型列表
curl -X POST http://localhost:8765/api/config/text-providers/test \
  -F "api=openai-completions" \
  -F "base_url=https://api.deepseek.com/v1" \
  -F "api_key=sk-你的Key"

# 2) 保存供应商（models_json 可来自上一步，也可手写）
curl -X POST http://localhost:8765/api/config/text-providers \
  -F "provider=deepseek" \
  -F "display_name=DeepSeek" \
  -F "api=openai-completions" \
  -F "base_url=https://api.deepseek.com/v1" \
  -F "api_key=sk-你的Key" \
  -F 'models_json=["deepseek-chat","deepseek-reasoner"]'

# 3) 切换当前文本模型到该供应商（text 必填）
curl -X POST http://localhost:8765/api/config/models \
  -F "text=deepseek-chat" -F "text_provider=deepseek"

# 4) 切回内置 Agnes
curl -X POST http://localhost:8765/api/config/models \
  -F "text=agnes-3.0-flash" -F "text_provider="
```

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
| GET | `/api/voices` | List available TTS voices (grouped by 22 languages) |
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
