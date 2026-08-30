# PRD: Absorbing agnes-simple-ui (PR #33) into the Core Project

> **Status**: Draft — pending maintainer approval
> **Date**: 2026-08-30
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

All items below are taken from PR #33 with minimal adaptation; credit to @Khaled97Sho in commit messages and release notes.

| # | Item | Files (target state) | Notes |
|---|------|----------------------|-------|
| 1.1 | Preview "dry-run" endpoints | `web/routes/preview_routes.py` + registration in `server.py` | `POST /api/creative/preview-script`, `POST /api/manuscript/preview-split`. Synchronous, no task created, no quota consumed. |
| 1.2 | Arabic tashkeel for TTS | `core/audio/tashkeel.py`, `AudioConfig.add_tashkeel`, wiring in creative + manuscript pipelines | mishkal-based, with the strip-and-compare validation gate and fallback-to-original. New dependency: `mishkal>=0.4.1,<0.5.0`. |
| 1.3 | Language-aware narration budget | `core/screenwriter/story.py` | Replaces the hardcoded 4 chars/sec (Chinese) budget with per-language estimation; prompt changes from a ceiling to a target range. |
| 1.4 | Screenwriter language pinning | `core/pipelines/creative/pipeline.py`, `core/pipelines/manuscript_video.py` | Pass `language="en"` explicitly so non-Chinese ideas do not come back in Chinese. Not applied to poetry/anchor (breaks their mock fixtures; bug unconfirmed there). |
| 1.5 | Manuscript reference images | `models/task.py`, `web/routes/task_creation_routes.py`, `core/pipelines/manuscript_video.py` | `reference_images` + `reference_images_map` (paragraph-index JSON) on `POST /api/tasks/manuscript`, wired to per-paragraph i2v submission. |
| 1.6 | `split_manuscript_text()` extraction | `core/pipelines/manuscript_video.py` | Single implementation shared by the real pipeline and the preview endpoint. |

**Acceptance criteria**

- `py_compile` clean on all touched files; `pytest tests/ -q` green.
- Manual: Arabic topic-mode creative task produces Arabic story + narration of proportionate length (audible length ≈ video duration ±20%).
- Manual: manuscript task with 2 reference images mapped to paragraphs produces i2v segments referencing those images (check task state artifacts).
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
- If the author does spin it off, the core repo will link to it from `README.md` / `docs/public/getting-started.md` ("Community tools").
- Breaking changes to the contract endpoints above get a heads-up in release notes.

## 7. Phase 4 — (Optional, separate plan) Simple mode in the main Vue UI

Not scheduled yet; recorded here so the intent is explicit. A "simple mode" tab in the existing frontend would reuse the Phase 1 preview endpoints, the existing voice picker, task list, and progress page — fully i18n'd via the standard 22-language pipeline. This would eventually obsolete the companion UI for most users, but the companion repo remains valid for users who prefer a zero-build standalone tool.

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Companion UI breaks after core API changes | Phase 6 contract list + release-note heads-up; preview endpoints are additive |
| mishkal dependency weight / availability | Optional-dependency pattern already used in this project (auto-degrade, behavior unchanged) — tashkeel silently falls back to original text if mishkal is missing |
| CORS misconfiguration exposes API beyond localhost | Document clearly: origins are an allowlist, credentials stay off; default is disabled |
| Losing the author's live end-to-end verification knowledge | Invite the author to review the absorption PRs (Phases 1–2) |

## 9. Milestones

| Milestone | Content | Depends on |
|-----------|---------|------------|
| M1 | Phase 1 absorption PR (items 1.1–1.6) | — |
| M2 | Phase 2 configurable CORS PR | M1 |
| M3 | API contract docs + (if the author opts in) Community-tools link | M2 |
| M4 | (optional) Simple mode in main UI | M1; own PRD |

---

*Document version: v0.1 (draft) — 2026-08-30*
