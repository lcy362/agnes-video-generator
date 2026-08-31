# PRD: Absorbing agnes-simple-ui (PR #33) into the Core Project

> **Status**: Draft v0.2 — pending maintainer approval
> **Date**: 2026-08-31（v0.2 修订，吸收实现审查发现的 10 项问题）
> **Source**: PR #33 (`feat: add agnes-simple-ui companion tool, Arabic tashkeel, and per-language narration fixes`) by @Khaled97Sho
> **Related docs**: `docs/public/architecture.md`, `docs/dev/regression_test_plan.md`, `docs/dev/pipeline_products.md`

---

## 1. Background

PR #33 bundles three logically distinct contributions:

1. **A standalone companion web app** (`agnes-simple-ui/`): Flask + vanilla JS, its own venv, its own port (:8787), ~1,600 of the 2,090 added lines.
2. **Backend bug fixes**: non-Chinese stories written in Chinese (screenwriter language pinning); narration too short for non-CJK languages (language-aware chars/sec budget).
3. **Backend features**: Arabic tashkeel for TTS, manuscript-mode reference images, preview ("dry-run") endpoints, `split_manuscript_text()` extraction, CORS for :8787.

The maintainer decision: **do not merge the PR as-is.** Instead:

- Absorb items 2 and 3 into the core project (they fix real bugs and benefit the existing Vue UI directly).
- For the companion UI itself, spinning it off into a **separate repository** is one possible path — offered to the author as an option, not a requirement. The core project will provide configurable CORS either way, so any local companion tool can call the API cross-origin.

### Why the companion app is not merged into this repository

Stated in general software-design terms (not project-internal rules):

- **Two parallel web stacks in one repo.** The repository would simultaneously contain a FastAPI app and a Flask app, two `server.py` entry points, two `static/` directories, two virtualenvs, and two ports. Parallel stacks drift apart over time; shared fixes (auth, rate limiting, path security) have to be applied twice.
- **A coverage blind spot.** The companion app sits outside the project's regression matrix, i18n completeness check, and frontend build chain. Nothing fails when it breaks — the worst kind of test gap.
- **Duplicated frontend surface.** Voice picking with preview, task progress polling, and subtitle options already exist in the main Vue UI. Shipping a second implementation of the same UI logic doubles the maintenance cost for identical behavior.
- **One PR, many concerns.** Bundling a new tool, pipeline bug fixes, and new API endpoints in a single PR makes review and selective rollback effectively impossible.

The engineering quality of the PR itself is high — the tashkeel fallback design (strip-diacritics-must-equal-original validation before use) and the language-aware narration budget are excellent work. This plan exists to preserve that value.

---

## 2. Goals

- G1: Land the backend bug fixes and features from PR #33 inside the existing architecture (`web/routes/`, `core/`, `models/`).
- G2: Replace the hardcoded `localhost:8787` CORS with a **configurable allowed-origins mechanism**, so any independently hosted companion UI can call the core API.
- G3: Document the API contract the companion UI depends on, so it can be developed independently — whether as a separate repository (one option offered to the author) or in whatever form the author prefers.
- G4: (Follow-up, separate batch) Optionally surface a "simple mode" inside the main Vue UI, reusing the new preview endpoints, fully i18n'd.

## 3. Non-goals

- Merging `agnes-simple-ui/` into this repository in any form.
- Maintaining the Flask server, its endpoints, or its launch scripts here. The cover-compositing endpoint belongs to the companion repo.
- Adding Arabic UI translation for the main frontend as part of this batch (it follows the normal i18n contribution flow).

---

## 4. Phase 1 — Backend absorption (immediate, from PR #33)

All items below are taken from PR #33 with the adaptations listed; credit to @Khaled97Sho in commit messages and release notes.

| # | Item | Files (target state) | Notes |
|---|------|----------------------|-------|
| 1.1 | Preview "dry-run" endpoints | `web/routes/preview_routes.py` + registration in `server.py` | `POST /api/creative/preview-script`, `POST /api/manuscript/preview-split`. Synchronous, no task created. **每次 preview-script 调用 = 3 次真实 LLM Chat 调用（develop_story + write_script + generate_narration_for_video），消耗共享限速桶配额与真实 API 调用，并非零成本**——文档与 UI 文案如实表述为"提交前预览（会调用 AI）"，并在实现上做防滥用收敛（见 1.1a）。 |
| 1.1a | Preview 端点防滥用 | `web/routes/preview_routes.py` | preview 调用走 `get_rate_limiter()` 共享桶（与 Chat 一致），另外增加**轻量进程内并发上限**（如 `asyncio.Semaphore(2)`，超限返回 429 + Retry-After）：preview 不经 `WeightedSemaphore` 流水线并发门控，若不加防护，一个循环脚本可以在正式任务之外无限制地刷 LLM 调用。 |
| 1.2 | Arabic tashkeel for TTS | `core/audio/tashkeel.py`, `AudioConfig.add_tashkeel`, wiring in creative + manuscript pipelines | mishkal-based, with the strip-and-compare validation gate and fallback-to-original. **依赖模式：optional-dependency**（与 json-repair 相同的"缺失自动降级"模式）：代码不 import mishkal 也能正常工作（tashkeel 静默回退原文）；但 `requirements.txt` 默认安装它，保证开箱即用。**字幕隔离：tashkeel 只作用于送入 TTS 的文本，字幕文本必须在加 tashkeel 之前留一份干净版本**（详见 1.2a）。 |
| 1.2a | Tashkeel 与字幕隔离 | `core/pipelines/creative/steps_audio.py`, `core/pipelines/manuscript_video.py` | PR #33 原实现把 tashkeel 后的文本直接写回 `state.narrations` / `full_text`，而字幕 SRT 正是从同一文本（及 word cues）生成的——**字幕会连带显示 harakat 变音符号**，与 PR 描述 "subtitles unaffected" 不符。修正方案：流水线保留 `narration_plain`（无 tashkeel，供字幕与 `narration.txt` 产物）与 `narration_tts`（加 tashkeel，仅送 TTS）两份文本；若 cue-aware SRT 从 TTS cues 生成，cue 文本同样在进字幕前 strip 变音符号（复用 tashkeel 模块导出的 `_DIACRITIC_RE`，升级为公共函数 `strip_diacritics()`）。 |
| 1.3 | Language-aware narration budget | `core/screenwriter/story.py` | Replaces the hardcoded 4 chars/sec (Chinese) budget with per-language estimation; prompt changes from a ceiling to a target range. **语速估算函数收敛为单一公共实现**（见 1.3a），story.py 不再自定义副本。 |
| 1.3a | 语速估算公共化 | `core/audio/voices.py` | PR #33 在 `story.py`（`_narration_chars_per_sec`）与 `manuscript_video.py`（`_estimate_chars_per_sec`）重复定义了两份 4.0/13.0 常量与脚本判断。收敛为 `core/audio/voices.py` 中的公共函数 `estimate_chars_per_sec(text: str) -> float`（紧邻 `detect_text_script`，复用其返回值），两个调用方与 `preview_routes` 统一改用该公共函数；`_duration_len`（diacritics strip 计数）同样移入该模块并导出公共名 `duration_len()`，消除 `preview_routes` 对 `manuscript_video` 私有函数的导入。 |
| 1.4 | Screenwriter language pinning | `core/pipelines/creative/pipeline.py`, `core/pipelines/manuscript_video.py` | Pass `language="en"` explicitly so non-Chinese ideas do not come back in Chinese. **与 PROMPT_LANGUAGE 配置的交互（决策）**：`PROMPT_LANGUAGE` 已是 RuntimeSettings 配置项（v6.0 优化 3.5 收敛）。实现改为**"默认 en、尊重显式配置"**：仅当用户未显式设置 `PROMPT_LANGUAGE`（即使用默认值 `zh`）时才固定传 `language="en"`；若用户显式配置了 `PROMPT_LANGUAGE`，则以用户配置为准（显式配置代表用户知情选择，不应被硬编码覆盖）。Not applied to poetry/anchor（breaks their mock fixtures; bug unconfirmed there）。 |
| 1.5 | Manuscript reference images | `models/task.py`, `web/routes/task_creation_routes.py`, `core/pipelines/manuscript_video.py` | `reference_images` + `reference_images_map` (paragraph-index JSON) on `POST /api/tasks/manuscript`, wired to per-paragraph i2v submission. **类型与校验收紧**：`models/task.py` 中 `reference_images: Dict[str, List[str]]`（显式类型注解，不用裸 `dict`）；`reference_images_map` 解析后校验每个元素为 `List[int]` 且 index 在 `0..len(paragraphs)-1` 范围内（当前稿件未拆段，先用"非负整数"做下限校验，越界 index 记 warning 并忽略该图，不 422——拆段结果在任务执行时才确定，创建时无法精确校验上界）。 |
| 1.6 | `split_manuscript_text()` extraction | `core/pipelines/manuscript_video.py` | Single implementation shared by the real pipeline and the preview endpoint. 保留 PR #33 已处理的 `fix_double_utf8` 与 resume 逻辑。 |
| 1.7 | `_get_pausable_steps` 注释更新 | `core/pipelines/manuscript_video.py` | 稿件模式引入逐段参考图后，"稿件无参考图 → references 检查点不可暂停"的前提不再恒成立。实现 1.5 时同步更新该方法的注释与逻辑（若参考图存在，`step_reference_images` 恢复为可暂停检查点）。 |

**Attribution (must-do, do not forget at implementation time)**

PR #33 is a single squashed commit mixing the UI and backend changes, so the original commit cannot be cherry-picked. Attribution is carried via the standard `Co-authored-by` trailer on every absorption commit instead:

```
Co-authored-by: Khaled97Sho <Khaled97Sho@users.noreply.github.com>
```

- The noreply address guarantees the commit links to the author's GitHub account (avatar + contributions graph credit).
- Commit body also states the source: "Ported from PR #33 by @Khaled97Sho, adapted to the existing architecture."
- Release notes for the version that lands these changes mention the source PR and author.
- Rewritten parts (e.g., configurable CORS) still carry the trailer as design-origin credit — that is the intended convention here.

**Acceptance criteria**

- `py_compile` clean on all touched files; `pytest tests/ -q` green.
- Manual: Arabic topic-mode creative task produces Arabic story + narration of proportionate length (audible length ≈ video duration ±20%).
- Manual: manuscript task with 2 reference images mapped to paragraphs produces i2v segments referencing those images (check task state artifacts).
- Manual（1.2a 新增）: 开启 tashkeel 的阿拉伯语任务，**最终视频字幕不含 harakat 变音符号**，`narration.txt` 产物为无 tashkeel 纯文本；TTS 音频仍为加 tashkeel 版本。
- Manual（1.4 新增）: 显式设置 `PROMPT_LANGUAGE=zh` 时中文 idea 仍产出中文故事（用户配置不被覆盖）；未设置时英文 idea 产出英文故事（pinning 生效）。
- Mock regression (`./scripts/run_mock_regression.sh`) green.
- New regression scenarios added to `docs/dev/regression_test_plan.md`: Arabic creative with tashkeel; manuscript with reference images + preview-split.

## 5. Phase 2 — Configurable CORS (replaces hardcoded :8787)

Replace the PR's fixed origin list with an environment-driven allowlist:

```python
# web/app_state.py or server.py — applied at startup only
AGNES_CORS_ORIGINS   # comma-separated, e.g. "http://localhost:8787,http://127.0.0.1:3000"
AGNES_CORS_ENABLED   # "false" disables the middleware entirely (default: enabled iff ORIGINS set)
```

Behavior:

- Empty/unset → no CORS middleware (current behavior, no attack-surface change for existing users).
- Set → `CORSMiddleware` with exactly those origins; `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=False` (no cookies are used by the API; key auth is explicit).
- Documented in `docs/public/api.md` and `.env.example` as the official way for **any** local companion tool (agnes-simple-ui or others) to call the API.

**Acceptance criteria**: with `AGNES_CORS_ORIGINS=http://localhost:8787`, a page served from :8787 can create/list tasks from the browser; without it, preflight requests fail. Existing same-origin usage unaffected.

## 6. Phase 3 — Supporting an independently developed companion UI

The companion UI's future home is the author's call. **One option** (offered, not required): extract `agnes-simple-ui/` into its own repository — it is already self-contained. Whatever the author chooses, the core project's side of the deal is the same:

- An environment-driven CORS allowlist (Phase 2) so the companion can call the core API from the browser.
- A documented API contract — the endpoints the companion UI depends on:
  - `GET /api/voices`, `GET /api/voices/preview`
  - `POST /api/tasks/creative`, `POST /api/tasks/manuscript` (incl. `reference_images`, `audio_add_tashkeel`)
  - `POST /api/creative/preview-script`, `POST /api/manuscript/preview-split`
  - `GET /api/tasks/{id}` (polling), artifact download URLs
- **契约文档必须写清两种参考图 API 的语义差异**（避免第三方调用方混淆）：
  - 创意模式 `scene_reference_images`：按场景**顺序**对齐（第 i 张图 → 第 i 个场景）；
  - 稿件模式 `reference_images` + `reference_images_map`：按**段落 index 显式映射**（一张图可服务多个段落）。两者命名相似但对齐规则不同，文档需各自举例。
- **preview 端点的成本说明**：preview-script 每次调用触发 3 次真实 LLM 调用（计入限速配额），契约文档中如实标注，避免调用方当作免费接口高频轮询。
- If the author does spin it off, the core repo will link to it from `README.md` / `docs/public/getting-started.md` ("Community tools").
- Breaking changes to the contract endpoints above get a heads-up in release notes.

## 7. Phase 4 — (Optional, separate plan) Simple mode in the main Vue UI

Not scheduled yet; recorded here so the intent is explicit. A "simple mode" tab in the existing frontend would reuse the Phase 1 preview endpoints, the existing voice picker, task list, and progress page — fully i18n'd via the standard 22-language pipeline. This would eventually obsolete the companion UI for most users, but the companion repo remains valid for users who prefer a zero-build standalone tool.

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Companion UI breaks after core API changes | Phase 3 contract list + release-note heads-up; preview endpoints are additive |
| mishkal dependency weight / availability | Optional-dependency pattern already used in this project（代码自动降级，行为不变）— tashkeel silently falls back to original text if mishkal is missing; `requirements.txt` 默认安装保证开箱即用，Docker 镜像构建时验证体积增量可接受 |
| Tashkeel 文本污染字幕 / 旁白导出产物 | 1.2a 双文本方案（plain 供字幕与产物、tts 供 TTS），回归场景中新增字幕无变音符号检查 |
| Preview 端点被滥用刷 LLM 调用 | 1.1a：共享限速桶 + 进程内并发上限（超限 429），契约文档标注成本 |
| CORS misconfiguration exposes API beyond localhost | Document clearly: origins are an allowlist, credentials stay off; default is disabled |
| Losing the author's live end-to-end verification knowledge | Invite the author to review the absorption PRs (Phases 1–2) |

## 9. Milestones

| Milestone | Content | Depends on |
|-----------|---------|------------|
| M1 | Phase 1 absorption PR (items 1.1–1.7) | — |
| M2 | Phase 2 configurable CORS PR | M1 |
| M3 | API contract docs + (if the author opts in) Community-tools link | M2 |
| M4 | (optional) Simple mode in main UI | M1; own PRD |

## 10. Backlog (low-priority follow-ups, handle opportunistically)

- **Frontend/backend language-set alignment check.** The frontend `LANGS` array
  (`frontend/src/i18n/index.ts`, 22 languages) and the backend voice catalog
  `PROJECT_LANGUAGES` (`core/audio/voices.py`, 22 languages) currently stay in
  sync only by hand — no automated check guarantees they match. Add a guard
  (either inside `scripts/i18n_check.py` or a small new script) that fails the
  CI `i18n-check` job when a language is added to one side without the other.
  Spotted 2026-08-30 while implementing the Arabic PR #32 follow-up
  (`docs/plans/optimization-research/arabic_pr_followup.md`); both sets were
  verified equal at that point.
- **泰文/天城文/孟加拉文语速实测校准。** 1.3 的 `estimate_chars_per_sec` 对全部非 CJK 脚本统一用 13 字/秒（沿自 PR #33 对阿拉伯文的实测）。泰文（无空格分词）、天城文、孟加拉文的真实 edge-tts 语速未实测，先用统一值上线，后续用真实 TTS 时长数据分脚本校准。

---

## 11. v0.2 修订记录（2026-08-31）

实现审查发现并修正的 10 项问题（相对 v0.1）：

1. **"no quota consumed" 表述错误** → §4 1.1 更正为"3 次真实 LLM 调用、消耗共享桶配额"，新增 1.1a 并发防护。
2. **Tashkeel 泄漏进字幕** → 新增 1.2a 双文本方案（plain/tts 分离），验收标准新增字幕检查项。原 PR 的 "subtitles unaffected" 声明与实际实现不符，以本方案为准。
3. **私有函数跨模块导入 + 语速常量重复两份** → 新增 1.3a，收敛为 `core/audio/voices.py` 公共函数。
4. **`language="en"` 硬编码覆盖 `PROMPT_LANGUAGE` 配置** → 1.4 改为"默认 en、尊重显式配置"，验收标准新增配置交互检查。
5. **`_language_directive` 未知语言静默默认阿拉伯语**（preview_routes 内部函数）→ 实现要求：`content_lang` 白名单校验（`{"ar", "en"}`），越界直接 422，不再有静默默认值。
6. **`reference_images` 裸 dict 注解 + map 无校验** → 1.5 收紧为 `Dict[str, List[str]]` + index 校验策略。
7. **两种参考图 API 语义差异未文档化** → §6 契约文档要求明确写出两种对齐规则。
8. **mishkal 依赖模式自相矛盾（风险表说 optional、requirements 是硬依赖）** → 1.2 明确为"optional-dependency 代码模式 + requirements 默认安装"。
9. **§8 风险表引用"Phase 6"笔误** → 更正为 Phase 3。
10. **`_get_pausable_steps` "稿件无参考图"注释将过时** → 新增 1.7，随 1.5 同步更新。

以上修订不改变原方案的目标（G1–G4）、Non-goals、Phase 结构、里程碑规划与作者归属承诺。

---

*Document version: v0.2 (draft) — 2026-08-31*
