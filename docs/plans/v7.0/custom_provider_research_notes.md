# 自定义文本供应商：决策前因后果 & deepseek-harness 实现参考

- **版本线**：v7.0.0
- **性质**：设计/调研存档（供后续优化与实现对照，非当前实施清单）
- **关联**：`multi_text_provider_PRD.md`（本 PRD 的配置形态与凭据决策直接引用本文件）
- **上游参考**：`/Users/lcy/Documents/trae_projects/deepseek-harness`（`llm-pi-ai` 包）

---

## 一、起因（Why）

系统当前唯一 LLM 是 Agnes Chat API（`agnes-3.0-flash`），被硬编码在 `AgnesChatAPI` 中。用户要求把系统文本模型开放为**可插拔的多供应商**：

- 项目口径"免费模型优先"，但用户配付费模型 key 同样可用（协议兼容，不区分价格）；
- 现无合适图片/视频模型，故一期只做**文本模型**；
- 明确要求**供应商相关配置完全参考 deepseek-harness**：OpenAI / Anthropic 兼容线协议，用户输入 key + base_url 拉取模型列表并配置。

参考来源（deepseek-harness）的核心动机即"自定义供应商可声明式配置、可探测、可在 UI 选择"，与本需求一致。

---

## 二、核心决策（已定稿）

| 决策点 | 结论 | 说明 |
|--------|------|------|
| 线协议范围 | `openai-completions` / `anthropic-messages` | `openai-responses` 暂不启用，一行可扩展 |
| 供应商配置形态 | 完全参考 dsh `ProviderSpec`（§三） | route key + displayName + api + baseURL + models |
| **凭据存储（一期）** | **落盘 `config.json`**（原子写 + 0o600，回传掩码） | 便利自部署/开发；与 dsh「仅引用不落盘」不同（见 §四） |
| Anthropic 多模态 | **本期不做**，仅存档 | 动手所需改造见 PRD §九 |
| 向后兼容 | Agnes 内置不可删、默认路由 | 未配置/未切换行为与现状完全一致 |

---

## 三、deepseek-harness 实现参考

### 3.1 ProviderSpec（供应商/路由描述）

源文件：`packages/llm/llm-pi-ai/src/provider.ts`

```ts
export interface ProviderSpec {
  provider: string            // route key；同时是 Models 集合 key 与各 model 的 provider
  displayName: string         // 选择器/状态标签用展示名
  api?: string                // 线协议覆盖；缺省=走该 model 在 catalog 里的协议
  baseURL?: string            // 端点覆盖（含已套用到 models 的覆盖）
  models: readonly Model<Api>[]
  namesCredential: boolean    // 是否经 apiKeyEnv 引用凭据（只带引用、不带密钥）
}
```

要点：route key（`provider`）是"一等键"，模型列表挂到 route 之下；`api` 不声明即复用内置 catalog 协议，声明则指明线协议覆盖；凭据只声明"是否命名了引用"（`apiKeyEnv`），**密钥本身从不进配置**。

### 3.2 线协议表（Wire Protocol）

`provider.ts`：

```ts
const PROTOCOLS = {
  'openai-completions': openAICompletionsApi,
  'openai-responses':   openAIResponsesApi,
  'anthropic-messages': anthropicMessagesApi,
}
```

- 每个协议是懒加载的 `ProviderStreams` 实现；手声明 route 据此落到具体 API 实现。
- 刻意收窄：只有 key+endpoint+headers 可完整描述的协议才纳入（Bedrock/Vertex/Azure/Codex 因鉴权形态无法用该配置表达而不提供）。

### 3.3 凭据解析（本项目与 dsh 分歧点）

- dsh：**配置只存凭据引用** `apiKeyEnv`（如 `<PROVIDER>_API_KEY`），请求进入适配器前由 harness 经 `ctx.credentials` 解析出明文，以流选项交给协议层（provider.ts 注释明确"Credentials never reach this module's storage"）；`routeAuth` 只在 catalog provider 无 api-key 方法时才补一个 harness 自己的 api-key auth（`harnessApiKeyAuth`）。
- 本项目（决策）：一期直接落盘 `api_key`（开发/自部署易用）；返回给前端掩码（复用 `config_routes.py:_mask_key/_key_id`）。后续若要对齐 dsh，改造为 `api_key_env` 引用 + env 运行时解析即可，路由/协议层无需变（见 §五 优化方向）。

### 3.4 兼容行为声明（PiAiCompatProfile）

`packages/llm/llm-pi-ai/src/catalog.ts`：对 OpenAI/Anthropic 兼容网关无法自动推断的行为（`supportsStore / thinkingFormat / supportsTemperature / supportsStrictTools` 等）用 profile 显式声明，弥补兼容网关缺省行为不明的部分。本项目一期协议简单（chat/json/multimodal 均已固定请求/响应字段），暂无对等需求；若遇"某兼容网关字段差异"，可仿此加 per-route 兼容开关。

### 3.5 UI 侧（settings-models）

`packages/client/ui-settings-models/src/client/store.ts`：Models 设置页并行拉取 `listProviders` + `listConfigurableProviders` + settings mirror，合并已注册/自定义 provider，按 `apiKeyEnv` 读 credential，渲染可配置行。本项目前端 ConfigPanel 供应商分节即仿此交互：列表 + 新增 + 探测（`test` 端点）+ 选模型 + 保存（PRD §七）。

---

## 四、凭据落盘：前因后果

**为什么一期落盘**

- 便利性：开发/自部署单机场景，用户 UI 里贴 key 保存即可用，无需设置环境变量或改启动脚本。
- 一致性与复用：与现有 `api_keys` 落盘 `config.json`（原子写 + 0o600）机制一致；回传掩码走既有 `_mask_key`/`_key_id`，安全口径对齐。
- 成本：一期实现量小、回归面小。

**代价 / 待后续优化**

- 与 dsh 的"密钥不入库"践行存在差距；`config.json` 若被他人/工具读取可拿到明文（仅 0o600 缓解）。
- 多用户/多机/云端部署时，落盘键共享与轮换更脆弱。

**后续优化方向（不改变接口/协议层）**

1. `api_key` → `api_key_env`：配置只存 `{api_key_env: "MY_PROVIDER_KEY"}`，运行时 `os.environ` / `.env` 解析；未设置时 `test` 端点可提示"需要环境变量"。
2. 可选：增加"仅测试不保存"模式，把 key 放请求体即测即用、不持久化。
3. 迁移策略：读到旧 `api_key` 字段时提示迁移，不静默删除。

---

## 五、后续优化路线（非本期）

- 严格对齐 dsh 凭据引用（§四第 2 项）。
- 开放 `openai-responses` 线协议（协议表 +1 行 + 客户端）。
- Anthropic 多模态（PRD §九，已列差异与实现清单）。
- per-route 兼容开关（仿 `PiAiCompatProfile`，按需）。
- 供应商级 `max_tokens`/`temperature` 覆盖暴露。

---

## 六、文档索引

- 本功能主案：`docs/plans/v7.0/multi_text_provider_PRD.md`
- 后端视频/文本流水线产物逻辑：`docs/dev/pipeline_products.md`
- 发版规范：`docs/dev/release_process.md`（v7.0 升位与发版）