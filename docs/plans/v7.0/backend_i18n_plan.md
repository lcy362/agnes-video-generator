# v7.0 后端用户可见消息多语言化（Backend i18n）

> 状态：🟢 **已全部落地**（issue #64 修复批次 + 2026-09-24 收尾批次清除 P1~P4 剩余消息；
> issue #65 暴露的 screenwriter「图片分析失败」也在收尾批次内完成）
> 触发：GitHub issue #64 —— 英文 UI 用户在 `video_gen` 失败时收到一段硬编码中文的
> 「网络诊断」提示，看不懂又误以为是服务侧故障。
> 关联：`docs/dev/issue_handling_process.md` §4.1（回复语言判定）、
> `AGENTS.md` §九「多语言（i18n）规范」（铁律：禁止硬编码中文）。

---

## 一、问题定位

`AGENTS.md` 的 i18n 铁律只约束了**前端**文案（`frontend/src/i18n/langs/*.json`），
后端 Python 里生成的用户可见消息一直是硬编码中文。这些消息通过三条路径到达用户：

| 路径 | 载体 | 典型来源 |
|------|------|----------|
| 任务进度 / 失败面板 | `BaseTaskState.current_message` | `_emit(...)`、`update_state(current_message=...)` |
| HTTP 错误响应 | `HTTPException(detail=...)` | 各 `web/routes/*.py` 的参数校验、鉴权失败 |
| 诊断报告 | `GET /api/tasks/{id}/diagnostics` 的 `summary.current_message` | 继承前两者 |

前端 i18n（`t()`）只翻译**静态 UI 文案**，不会翻译从后端收到的动态字符串，
因此后端写什么用户就看什么。

## 二、本轮已落地（issue #64 修复批次）

### 2.1 基础设施

- **`core/i18n_backend.py`**（新增）：后端 i18n 运行时
  - `SUPPORTED_UI_LANGS`：与前端 22 语言对齐的白名单；
  - `normalize_lang(raw)`：把 `en-US` / `zh_Hans_CN` / 未知值归一到 2 字母代码；
  - `parse_accept_language(header)`：按 RFC 7231 q 权重解析浏览器头；
  - `CATALOG`：`{key: {lang: template}}` 消息目录，**当前含 zh / en 两种**；
  - `translate(key, lang, **params)`：渲染模板，三级回退（目标语言 → zh → en → key 名），
    **永不抛异常**（i18n 缺陷不得放大成业务 500）；
  - `current_lang` ContextVar + `set/get/resolve_lang`：请求级语言上下文。
- **`web/middleware.py`**（新增）：`LangContextMiddleware`
  - 每个 HTTP 请求进入时，按 `X-Agnes-UI-Lang` 头 > `Accept-Language` > `zh`
    的优先级写入 ContextVar；
  - `finally` 里 `reset(token)`，避免协程复用残留。
- **`server.py`**：`app.add_middleware(LangContextMiddleware)`。
- **`models/task.py::BaseTaskState.ui_language`**（新增字段，默认 `"zh"`）：
  任务创建时快照前端 UI 语言，落盘到 `task_state.json`；异步 Pipeline 在整个
  生命周期里读它，保证即便用户中途切了 UI 语言，已创建任务的消息语种也不漂移。
  旧 JSON 缺字段时 Pydantic 自动补默认值，**向后兼容**。

### 2.2 前端管道

- **`frontend/src/api/langHeader.ts`**（新增）：`UI_LANG_HEADER` 常量 +
  `getUiLang()` + `withUiLangHeader(init)` 合并工具。
- **`frontend/src/api/fetchPatch.ts`**（新增）：`installFetchLangHeader()`
  全局 monkey-patch `window.fetch`，给**所有**请求（含第三方库、组件里的一次性
  `fetch('/api/xxx')`）自动追加 `X-Agnes-UI-Lang` 头。幂等安装，尊重调用方
  已显式设置的同名头。
- **`frontend/src/main.ts`**：`applyLanguage` 之后立即 `installFetchLangHeader()`。
- **`frontend/src/api/index.ts`**：内部 `apiFetch` 包装 + 33 处 `return fetch(`
  统一替换为 `return apiFetch(`（双保险：patch 失效时仍走显式注入）。
- **`frontend/src/utils/feedback.ts`**：
  - 诊断报告新增 `- 界面语言: <lang>` 行（i18n key `fbRepUiLang`，zh/en 已补），
    让维护者一眼看出用户看到的后端消息应该是什么语种；
  - `LOCAL_NETWORK_PATTERNS` 追加英文关键词（`Network diagnosis` /
    `cannot resolve` / `cannot reach` / `connection reset by peer`），
    保证英文诊断也能被前端正确归类为「本机网络故障」。

### 2.3 已双语化的消息（CATALOG 现有 key）

| Key | 触发场景 | 调用点 |
|-----|----------|--------|
| `network.dns_failed` | DNS 解析失败 | `utils/network.py::describe_network_error` |
| `network.connect_blocked` | 连接被拒 / reset / 拦截 | 同上 |
| `network.default_target` | 主机名提取失败时的兜底称呼 | 同上 |
| `config.api_key_missing` | 未配置 API Key | `core/config.py::api_key_missing_msg`，9 处路由 |
| `task.queued` | 任务排队中 | `web/deps.py::mark_task_queued` + `run_pipeline_with_concurrency` |
| `task.interrupted_resumable` | PipelineShutdown 中断 | `simple_video.py` / `multi_scene.py` |
| `task.start_failed` | 获取并发槽位阶段异常 | `web/deps.py` |
| `task.weight_exceeds_limit` | 任务权重超并发上限 | `web/deps.py` |
| `task.awaiting_checkpoint` | 手动模式检查点暂停 | `core/pipelines/__init__.py::_maybe_pause` |
| `image.save_failed` | 图片保存失败 | `web/routes/image_routes.py` |
| `ai_modify.failed` | AI 修改异常 | `web/routes/video_routes.py` |
| `ai_modify.image_regenerated` | AI 重生成图片的 diff 摘要 | 同上 |
| `ai_modify.unsupported_category` | 产物类型不支持 AI 修改 | 同上 |
| `ai_modify.diff_char_only` / `diff_no_change` / `diff_summary` | 文本 diff 摘要 | 同上 |
| `mode.switched_to_manual` / `_at` / `switched_to_auto` / `manual_unsupported_task_type` / `invalid` | 模式切换 | `web/routes/task_routes.py` |

### 2.4 调用链改造

- `describe_network_error(exc, lang=None)`：新增 `lang` 参数；Pipeline 传
  `self._ui_lang()`（读 `state.ui_language`），HTTP 路由传 `state.ui_language`
  或依赖 ContextVar。
- `BasePipeline._ui_lang()` / `_t(key, **params)`：新增快捷方法，所有 Pipeline
  子类统一走它，避免每处手写 `translate(key, self._state.ui_language, ...)`。
- `_CONNECT_MARKERS` 追加 `"connection reset"`：issue #64 里 macOS 到 Agnes
  视频域名的 TLS 握手被对端 reset，此前只有 `connection aborted` 命中不稳定。

### 2.5 测试

- `tests/test_backend_i18n.py`（新增，38 用例）：`normalize_lang` /
  `parse_accept_language` / `translate` 三级回退 / ContextVar / `resolve_lang`
  优先级 / **CATALOG zh-en 完整性**（每个 key 缺一不可）。
- `tests/test_network_diagnosis.py`（追加 7 用例）：英文分支断言（含「绝不混入
  中文关键词」的反向断言）、`connection reset` 归因、未知语言回退 zh、
  兜底称呼本地化。
- 全量回归：`pytest tests/ --ignore=tests/test_ai_modify.py` → **1293 passed**
  （`test_ai_modify.py` 的 11 个 error 是 v7.0 provider 重构遗留的 monkeypatch
  失配，与本轮无关，已单独记录）。

---

## 三、收尾批次：P1~P4 剩余消息（2026-09-24 已落地）

issue #64 修复批次后剩余的硬编码中文已在收尾批次全部清除（AST 复扫 `_emit` /
`HTTPException.detail` / `update_state(current_message=)` / 用户可见 `raise` 中文字面量为 0）。
新增 CATALOG key（zh/en 齐备，`test_catalog_zh_en_parity` 守护），按域分组
（2026-09-24 安全修复后净计 **157 个**，目录共 179 key，见 §四.7）：

| 组 | 范围 | key 前缀 | 数量 |
|----|------|----------|------|
| P1 | 6 个流水线 `_emit` 进度消息 + 步骤 raise（simple / multi_scene / creative 四步 / manuscript / anchor / poetry） | `progress.<域>.*` | 92 |
| P1+ | screenwriter 图片分析失败（issue #65 暴露；`describe_images(..., ui_lang=...)` 由 Pipeline 传 `self._ui_lang()`） | `screenwriter.*` | 1 |
| P2 | 路由参数校验（task_creation / preview / config / workspace / preset / gallery / image / video-checkpoint / voice / utility 含 cleanup errors） | `validation.*` `preview.*` `config.*` `checkpoint.*` `gallery.*` `image.*` `preset.*` `voice.*` `utility.*` `ai_modify.user_request_empty` | 59 |
| P3 | 音色兼容性两条长文案（语言标签渲染层初版用 `voice_compat.label.<code>` 动态 key，因 S5145 日志注入改为静态映射表，见 §四.7） | `voice_compat.*` | 2 |

改造要点与约束：

1. **zh 模板逐字节不变**：所有 zh 模板渲染结果与改造前完全一致（空格 / `...` / 全角括号 /
   `{set}` repr 等原样），因此断言中文原文的既有测试与前端 `LOCAL_NETWORK_PATTERNS`
   中文匹配逻辑均不受影响；en 为新增能力。
2. **语言取值路径不变**：Pipeline 用 `self._t(key, **params)`（`state.ui_language` 快照），
   同步路由用 `translate(key, None, **params)`（ContextVar）。
3. **占位符注意**：`translate(key, lang=None, **params)` 的 `lang` 是保留参数名，
   模板占位符禁止用 `{lang}`（`voice_compat.lang_unsupported` 用 `{lang_name}`）。
4. **仍不翻译**（维持原排除项）：`logger.*`、LLM prompt、`models/task.py` 的
   `style` 默认值（内容语言）、Swagger description、路由 `responses=` OpenAPI 描述。
5. 已知遗留（非本方案范围）：video/image 路由中少量**英文硬编码** detail
   （`Task not found` 等）对中文 UI 用户仍是英文，方向与本次相反，后续可反转双语化。

验证：`py_compile` 全改动文件 + `import server` + 全量 `pytest tests/` **1394 passed** +
`./scripts/run_mock_regression.sh` 全绿。

---

## 四、新增消息的规范（给后续维护者）

1. **任何新的用户可见后端消息**（进 `current_message` / `HTTPException.detail` /
   响应体字段）一律走 `core.i18n_backend.translate(key, lang, **params)`，
   **禁止**直接写中文字面量。
2. **CATALOG key 命名**：`<域>.<语义>`，如 `network.dns_failed`、`task.queued`、
   `validation.prompt_too_long`。同一语义在不同路由复用同一 key。
3. **zh / en 缺一不可**：`tests/test_backend_i18n.py::test_catalog_zh_en_parity`
   会在 CI 拦住只加一种语言的 PR。其余 20 语言允许暂缺（运行时回退 zh）。
4. **占位符用关键字**：`{host}` 而非 `{0}`，便于翻译时调整语序。
5. **lang 参数来源**：
   - 同步 HTTP 路径：传 `None`，走 ContextVar（中间件已写入）；
   - 异步 Pipeline：传 `self._ui_lang()`（读 `state.ui_language` 快照）；
   - 任务创建端点：用 `get_current_lang()` 把语言快照写进 `state.ui_language`。
6. **前端配合**：新增的 fetch 调用自动带语言头（全局 patch），无需手动处理；
   若绕过 `window.fetch`（如 `XMLHttpRequest`、`EventSource`），需自行注入
   `X-Agnes-UI-Lang`。
7. **key 必须是模块级常量**：**禁止**把用户输入拼进 `translate()` 的 key
   （如 `f"voice_compat.label.{code}"`）——未知 key 会命中 `translate()` 内部的
   `logger.warning(..., key)`，构成 Sonar `pythonsecurity:S5145` 日志注入
   （2026-09-24 门禁红灯实录，见 `docs/dev/sonarcloud_analysis_workflow.md` §五）。
   按数据选择文案时用静态映射表（如 `web/helpers.py::_LANG_LABELS_EN`），
   用户输入只作查表键、不进日志。

---

## 五、验收清单

- [x] `core/i18n_backend.py` + `web/middleware.py` 落地，`server.py` 挂载中间件
- [x] `BaseTaskState.ui_language` 字段 + 5 个任务创建端点写入快照
- [x] `describe_network_error` 双语化 + `_CONNECT_MARKERS` 补 `connection reset`
- [x] `API_KEY_MISSING_MSG` → `api_key_missing_msg(lang)`，9 处路由改造
- [x] `web/deps.py` 排队 / 中断 / 启动失败 / 权重超限 4 条消息双语化
- [x] `task_routes.py` 模式切换 5 条消息双语化
- [x] `video_routes.py` AI 修改 6 条消息双语化
- [x] `image_routes.py` 图片保存失败双语化
- [x] 前端全局 fetch patch + `apiFetch` 双保险
- [x] 诊断报告新增「界面语言」行（zh/en i18n key）
- [x] `LOCAL_NETWORK_PATTERNS` 补英文关键词
- [x] 单测：`test_backend_i18n.py`（38）+ `test_network_diagnosis.py` 追加（7）
- [x] 全量回归 1293 passed（排除 pre-existing `test_ai_modify.py`）
- [x] P1~P4 剩余消息：2026-09-24 收尾批次完成（179 key，AST 复扫 0 残留，1394 passed + mock 回归全绿，见 §三）

---

*文档版本：v1.1 | 创建日期：2026-09-23 | 更新：2026-09-24 收尾批次清除 P1~P4 | 触发：GitHub issue #64*
