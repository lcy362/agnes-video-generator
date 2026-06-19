# Release v2.2 — Image-to-Image End Frames + Stability Enhancements

> Release date: 2026-06-19

## Overview

v2.2 introduces the **i2i (Image-to-Image) end frame pipeline**, enabling visual consistency across creative video scenes. This release also delivers comprehensive stability fixes from the second code review batch, a global rate limiter, unified API retry logic, and i18n improvements.

---

## i2i End Frame Pipeline

Six-batch feature implementation for visual consistency across scenes:

- **Batch 1+2** — Image model unified to `agnes-image-2.1-flash`, i2i array API, character reference image size normalization
- **Batch 3** — Character appearance persistence across scenes, programmatic prompt injection
- **Batch 4** — Prompt structure optimization, facial detail requirements in character reference prompts
- **Batch 5** — Multi-image guided i2i end frames, visual chain linking across scenes
- **Batch 6** — Keyframes fallback branch synchronization, full 6/6 batches complete
- Creative videos now default to i2i end frames enabled, narrator subtitles disabled

---

## Stability & Bug Fixes

### Code Review Batch 2 Fixes (P1-P13)

| ID | Fix |
|----|-----|
| P1 | Video concatenation sync blocking → async |
| P2 | `active_pipelines` concurrent race condition |
| P3 | Custom end frame not applied |
| P4 | Manuscript step key alignment |
| P5 | `chat_json` robustness |
| P6 | Resource leaks |
| P7 | Parameter validation improvements |
| P8 | Prompt injection protection |
| P9 | SilentTTS return code handling |
| P10 | Subtitle silent degradation on failure |
| P11 | LLM retry logic |
| P12 | URL cache expiry |
| P13 | Temp filename uniqueness |

### Other Fixes
- **Resume crash** — `_upload_image_to_host` method name error, `_run_pipeline` `task_id` undefined, `load()` creating empty directories
- **Concatenator `AttributeError`** — video concatenation failure path
- **Global rate limiter** — token bucket (16 req/min) shared across Chat + Image + Video APIs
- **API retry** — exponential backoff for 429/5xx errors across all three API modules
- **Regression runner** — 404 polling detection, `--quick` manifest mode, resume enhancements

---

## i18n Improvements

- Duration parsing now supports all 7 languages (zh/en/ru/ja/ko/ms/id)
- User requirements and visual style defaults localized per language

---

## Documentation

- `docs/plans-v2.0/bug_fix_plan.md` — comprehensive bug fix plan (added)
- `docs/regression_test_plan.md` — updated scenarios and flow rules
- `AGENTS.md` — synced rate limiter architecture, runner resume strategy
- `docs/release-notes/` — v2.0 and v2.1 release notes (added)
- Fixed official website link label (not "Live Demo")

---

## Stats

```
23 files changed, 1,189 insertions(+), 479 deletions(-)
```

### Key Files

| File | Description |
|------|-------------|
| `core/api/rate_limiter.py` | New — global token bucket rate limiter |
| `core/api/agnes_chat.py` | LLM retry + JSON mode improvements |
| `core/api/agnes_image.py` | i2i array API + ref image support |
| `core/api/agnes_video.py` | Retry logic + 429 handling |
| `core/pipelines/creative_video.py` | i2i end frame pipeline integration |
| `core/screenwriter.py` | Character appearance persistence |
| `core/compositor/concatenator.py` | Async refactor + bug fixes |
| `core/task_manager.py` | Resume crash fixes + backward compat |
| `server.py` | Rate limiter integration + endpoint fixes |
| `static/index.html` | i18n duration parse + style defaults |
| `scripts/regression_runner.py` | Resume + quick-verify enhancements |
| `docs/plans-v2.0/bug_fix_plan.md` | New — bug fix tracking |

---

## Upgrade Notes

From v2.1:

```bash
git pull
./start.sh
```
