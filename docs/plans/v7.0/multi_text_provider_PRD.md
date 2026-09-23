# 增量 PRD：接入多免费文本模型（自定义供应商）

- **版本线**：v7.0.0（大版本，功能更新为主；发版升位由用户触发，见 `docs/dev/release_process.md`）
- **分支**：`v7.0-dev`
- **状态**：🟡 方案设计（未实现）
- **关联文档**：`docs/public/architecture.md`、`docs/dev/pipeline_products.md`、`docs/plans/v6.0/optimization_roadmap.md`
- **对接参考**：`/Users/lcy/Documents/trae_projects/deepseek-harness`（`llm-pi-ai` 的 `ProviderSpec` / 线协议表）。本 PRD 中"供应商相关配置"**完全参考 deepseek-harness** 的形态与字段命名（见 §四）。

---

## 一、背景与目标

### 1.1 背景

当前系统唯一接入的 LLM 是 Agnes Chat API（`agnes-3.0-flash`，内置于 [AgnesChatAPI](file:///Users/lcy/video/agnes-video-generator/core/api/agnes_chat.py)），承担编剧拆解、诗词分镜、稿件改写、视频 image-prompt 等全部文本生成任务。它被**硬耦合**在 Agnes 域名、KeyRing、限速器上。用户希望把系统文本模型开放为**可插拔的多供应商**：

- 项目口径是"免费模型"优先，但用户把付费模型 key 配进来同样可用（纯协议兼容，不区分价格）；
- 目前没有合适的图片/视频模型，**本 PRD 只做文本模型**（Text Provider），图片/视频沿用 Agnes；
- **供应商相关配置完全参考 deepseek-harness**：`ProviderSpec` 结构 + 线协议表（OpenAI 兼容 / Anthropic 兼容），用户输入 key + base_url 拉取模型列表并配置为系统文本模型。

### 1.2 目标

1. 新增「文本模型供应商」配置能力：`api + base_url + key`，可拉取模型列表、保存、切换。
2. 支持 **OpenAI 兼容**（`/chat/completions` + `/models`）与 **Anthropic 兼容**（Messages API + `/models`）两种线协议。
3. 系统各流水线文本调用按当前所选文本供应商**自动路由**到对应客户端。
4. **100% 向后兼容**：Agnes 作为内置默认供应商不可删，未配置任何自定义供应商或未切换时行为与现状完全一致。

### 1.3 非目标（明确不做）

- 不做图片/视频模型的多供应商接入（无合适模型，单独排期）。
- MVP 不做 Anthropic 图像 content block 的多模态输入——**所需改造已在 §九分析**，属二期。
- 不做自定义供应商的"多 Key 轮询"（Agnes KeyRing 语义仅归 Agnes；自定义供应商单 key）。
- 不做供应商间模型自动限价/自动切换。

---

## 二、术语

| 术语 | 含义 |
|------|------|
| 文本供应商（Text Provider Route） | 一个可用 LLM 来源，含 `api / base_url / key / models`。`agnes` 为内置不可删。与 deepseek-harness 的"route"同义。 |
| 线协议（`api`） | `openai-completions` / `anthropic-messages` 之一，决定鉴权头与消息体结构。 |
| ProviderSpec | deepseek-harness 的供应商描述结构（`provider / displayName / api / baseURL / models / namesCredential`），见 [llm-pi-ai/provider.ts](../../../../../../Users/lcy/Documents/trae_projects/deepseek-harness/packages/llm/llm-pi-ai/src/provider.ts)。 |
| 所选文本模型 | `models.text`（模型 id）+ `models.text_provider`（归属供应商 route key）共同确定。 |

---

## 三、方案总览

复用 deepseek-harness `ProviderSpec` 抽象；新增**协议客户端**分派与**客户端工厂**，替换现有两处 `AgnesChatAPI(...)` 硬编码构造点。分层：

```
web/deps.py / 流水线
  └─ get_or_build_text_chat_client()          ← 新增：按 text_provider(route) 分派
       ├─ 空/agnes → AgnesChatAPI(agnes_key, models.text)   （现有行为不变）
       └─ <自定义>  → ProviderChatClient(route_config, models.text)
                      └─ OpenAIClient / AnthropicClient      ← 新增协议实现
```

数据流：前端「拉取模型」→ `POST /api/config/text-providers/test`（不落盘探测）→ 选模型 → 「保存」落盘 `config.json.text_providers` → 运行时工厂按 `models.text_provider` 路由。

---

## 四、供应商相关配置（完全参考 deepseek-harness）

### 4.1 ProviderSpec → 本项目映射

deepseek-harness 的 `ProviderSpec`（源见 [llm-pi-ai/provider.ts:88-107](file:///Users/lcy/Documents/trae_projects/deepseek-harness/packages/llm/llm-pi-ai/src/provider.ts#L88-L107)）：

```ts
interface ProviderSpec {
  provider: string            // route key；一等键
  displayName: string         // 选择器/状态标签用展示名
  api?: string                // 线协议覆盖（openai-completions / openai-responses / anthropic-messages）
  baseURL?: string            // 覆盖端点
  models: readonly Model[]    // 该 route 的模型列表（配置顺序）
  namesCredential: boolean    // 是否经 apiKeyEnv 引用凭据
}
```

对应本项目 `config.json`：

```jsonc
{
  "text_providers": [
    {
      "provider": "deepseek",                 // ← ProviderSpec.provider（route key，唯一）
      "display_name": "DeepSeek",             // ← displayName
      "api": "openai-completions",            // ← api（线协议；openai-completions | anthropic-messages）
      "base_url": "https://api.deepseek.com/v1",  // ← baseURL（覆盖端点；+ 兼容 URL 拼接）
      "api_key": "sk-xxxx",                   // 凭据存放（见 4.2 差异说明）
      "models": ["deepseek-chat", "deepseek-reasoner"]  // ← models（配置顺序）
    }
  ],
  "models": {
    "text": "deepseek-chat",
    "text_provider": "deepseek",              // ← 当前所选 route key；缺省/空 = agnes
    "image": "...",
    "video": "..."
  }
}
```

- `agnes` 内置 route：`api=openai-completions`，`base_url` 由现有 `get_base_url_for_key` 推导（不落盘），`provider=agnes`，不可删、不可改 `api`。
- `api` 合法值集合即 deepseek-harness 支持的**线协议表**（本 PRD 只启用 `openai-completions` / `anthropic-messages` 两个消费方的子集；`openai-responses` 暂不启用，留作一行扩展——见 §五）。

### 4.2 与 deepseek-harness 的差异：凭据存储（已定稿）

> 决定：**一期凭证落盘**；与 dsh「仅引用(apiKeyEnv)不落盘」的差异、前因后果与后续优化方向，另见 `custom_provider_research_notes.md`（§十二）。

- 一期：`api_key` 落盘 `config.json`（原子写 + 0o600，开发/自部署易用），回传前端一律掩码。
- 二期（可选优化）：严格对齐 dsh，将 `api_key` 改为 `api_key_env`（环境变量引用）+ 运行时从 env 解析，不落盘。实现细节见参考文档。

### 4.3 `config.py` 数据类型

`AppSettings`（[config.py:130](file:///Users/lcy/video/agnes-video-generator/core/config.py#L130)）补充 `text_providers: list[TextProvider | None]`；`TextProvider` Pydantic 模型字段：`provider:str / display_name:str / api:str / base_url:str / api_key:str="" / models:list[str]`。strict 校验，既存配置缺省 `text_provider` 走兼容分支（回退 agnes）。

---

## 五、协议客户端（新增 `core/api/providers/`）

### 5.1 统一接口

对齐现有 `AgnesChatAPI` 三方法签名，screenwriter / video_routes **零改动**：
`chat(...) -> str`、`chat_json(...) -> dict`（复用 `strip_code_fence` 与 JSON 修复 loader）、`chat_multimodal(...) -> str`。

### 5.2 OpenAI 兼容（`api = openai-completions`）

- chat：`POST {base_url}/chat/completions`，Header `Authorization: Bearer <key>`，body 同现有 Agnes；取 `data.choices[0].message.content`。
- 多模态：`image_url`（URL 或 base64 `data:` URI）透传 —— **MVP 支持项**。
- 拉模型：`GET {base_url}/models`。

### 5.3 Anthropic 兼容（`api = anthropic-messages`）

- chat：`POST {base_url}/v1/messages`，Header `x-api-key: <key>` + `anthropic-version: 2023-06-01`；body：`model / system(顶层) / messages / max_tokens / temperature`；取 `data.content[0].text`。
- 多模态：**MVP 不支持**，所需改造见 §九。
- 拉模型：`GET {base_url}/v1/models`。

### 5.4 重试 / 限速

复用共享桶 `get_rate_limiter().acquire()`（[rate_limiter.py:225](file:///Users/lcy/video/agnes-video-generator/core/api/rate_limiter.py#L225)）。自定义供应商**不复用** Agnes KeyRing 换 key；独立轻量退避（5xx/429 → 指数退避，默认 3 次、15s 基数）。失败统一进 `collect_error`（`error_collector.py`）。

---

## 六、后端 API 端点（新增至 `web/routes/config_routes.py`）

| 方法+路径 | 作用 | 关键约束 |
|---|---|---|
| `GET  /api/config/text-providers` | 列出供应商 | api_key 只回掩码+稳定 id；内置 `agnes` 标 `builtin`、不可删 |
| `POST /api/config/text-providers` | 新增/更新供应商 | 校验 `api ∈ {openai-completions, anthropic-messages}`、base_url 合法 |
| `DELETE /api/config/text-providers/{id}` | 删除供应商 | 内置 agnes 拒绝（400）；删除当前所选 → 回退 agnes |
| `POST /api/config/text-providers/test` | 用**用户此刻输入**的 key+base_url 探测拉模型 | **不落盘**，返回 `{ok, models:[...], error?}`；对应 deepseek-harness `listConfigurableProviders` 探测思路 |
| `POST /api/config/text-providers/{id}/sync` | 正式将候选模型写入该供应商并落盘 | 刷新内存模型缓存 |
| `POST /api/config/models` | 扩展：接收可选 `text_provider` 一并保存 | 不传则不改 `text_provider` |

---

## 七、前端（`ConfigPanel.vue` + `useConfig.ts` + `store.ts`）

- 新增「文本模型供应商」分节（沿用 glass-card 折叠样式+掩码交互）：供应商列表（名称/协议/baseURL/key 掩码/删除，Agnes 内置置灰）；新增/编辑表单（display_name、协议下拉、base_url、api_key、**「拉取模型」**按钮→`test` 端点拉回候选→模型选择→保存）。
- 「模型选择」分节：文本模型下拉**合并所有供应商模型**（Agnes 默认在前）；`appState.models` 增加 `text_provider`。
- `useConfig.ts` 增 `loadTextProviders / syncTextProviderModels / saveTextProvider / deleteTextProvider`；`api/index.ts` 增端点封装。
- **i18n（铁律）**：新文案 zh/en key 100% 对齐；`python scripts/i18n_check.py` 通过 + `cd frontend && npm run build` 成功。

---

## 八、改造点清单与向后兼容

涉及文件：`core/api/chat_providers.py`(新，工厂/持久化/路由)、`core/api/providers/{openai,anthropic}.py`(新)、`core/config.py`、`core/screenwriter/__init__.py:119`(替换)、`web/routes/video_routes.py:686/704`(替换)、`web/routes/config_routes.py`、前端 `ConfigPanel.vue/useConfig.ts/store.ts/api/index.ts`、`i18n zh/en`。

向后兼容（铁律）：
1. 未配置自定义供应商/未切换 → 完全走现有 Agnes 路径。
2. `models.text_provider` 缺省回退 `agnes`；旧 `config.json` 无需迁移即可读。
3. 不删任何现有导出；新增包独立。日志前缀 `[ChatProvider] / [OpenAIProvider] / [AnthropicProvider]`。

---

## 九、Anthropic 多模态支持分析（暂缓，不在本期）

> 决定：**本期不实施 Anthropic 多模态**，此节仅存档后续需求与实现路径，后续再启动。

若需让 Anthropic 文本模型支持图片输入，相对 OpenAI 需要额外做：

### 9.1 差异性

| 维度 | OpenAI（已支持） | Anthropic（需改造） |
|---|---|---|
| 图片编码 | `image_url`（URL 或 `data:<mime>;base64,<b64>` URI） | **仅 base64**，content block `{"type":"image","source":{...}}`；**不接收远程 URL** |
| 请求结构 | 图片混在 `messages[].content[]` | `image` content block，`source.type="base64"`、`source.media_type`、`source.data` |
| 协议 | 无需额外 header | 需 `x-api-key` + `anthropic-version`（chat 已具备） |
| media_type 白名单 | 通用 | 仅 `image/jpeg | image/png | image/gif | image/webp` |
| 角色轮换 | 灵活 | system 单列顶层、assistant/user 需交替（Anthropic 强校验跨消息的角色）。多轮图像对话要做角色轮换，改动比 OpenAI 大 |
| 多图限制 | 宽松 | 单条 user 消息图片 content block 数与总字节有配额 |

### 9.2 需新增的改造

1. 现有 [AgnesChatAPI._image_to_b64_uri](file:///Users/lcy/video/agnes-video-generator/core/api/agnes_chat.py#L86-L90) 生成 OpenAI 风格 `data:` URI；Anthropic 客户端需保留 base64 与 mime 拆分：
   ```python
   # 输入：本地路径 → 输出：anthropic image block
   {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
   # 媒体类型不在白名单（如 image/webp 之外）→ 校验/转换
   ```
2. Anthropic 客户端新增 `_build_messages()`：将 system 抽出到顶层；`chat_multimodal` 组装 `image` content block。
3. **远端 URL → 需先下载再 base64**（Anthropic 不接受 URL）。复用 `utils/image.py` 的下载能力。
4. 角色轮换辅助（多轮时），确保 `assistant`/`user` 交替。
5. 多模态降级：某个图像类型不支持或超出配额 → 告警并丢弃该图（保持纯文本调用不失败）。

### 9.3 建议

后续启动时优先保障：
- 本地图片 base64 + webp/png/jpeg 覆盖；
- 远端 URL 下载折 base64；
- 失败降级（不阻塞主流程）。

---

## 十、验收与自验

1. `bash start.sh` 正常启动，Uvicorn 监听 8765 无报错。
2. 静态：`.venv/bin/python -m py_compile <改动文件>` + 关键模块导入。
3. 端点 curl：`test` 用合法 key+base_url 返回模型列表；保存后 `GET` 只见掩码无明文；`DELETE` 内置 agnes 返回 400。
4. 路由验证：切换自定义供应商后文本生成打到自定义 base_url；切回 agnes 行为不变。
5. 多语言：`python scripts/i18n_check.py` 通过 + `cd frontend && npm run build` 成功。
6. 回归：`./scripts/run_mock_regression.sh` 通过（不破坏现有 6 类流水线）。

---

## 十一、分阶段实施建议

- **Phase A（协议+工厂）**：`TextProvider` 配置模型（ProviderSpec 对齐）、OpenAI/Anthropic 客户端、客户端工厂、替换两处构造点；Agnes 回退保持现状。自验 2/4/6。
- **Phase B（后端 API+前端）**：6 端点、ConfigPanel 供应商分节、模型下拉合并、i18n。自验 1/3/5。
- **Phase C（收尾）**：文档增量（`architecture.md`/`api.md`）、回归报告、v7.0 发版映射。

---

## 十二、Open Questions（评审待定）

> 已定稿：凭据一期落盘（§4.2，详见 `custom_provider_research_notes.md`）；Anthropic 多模态本期不做（§九）。

- `openai-responses` 线协议是否一并启用（默认不启用，一行可扩展）。
- 是否需要暴露供应商级 `max_tokens`/`temperature` 覆盖（默认沿用 4096/0.7）。