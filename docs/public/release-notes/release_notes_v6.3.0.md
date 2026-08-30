# Release v6.3.0 — Complete v6 Optimization Roadmap, Full 22-Language Support & Privacy Transparency

> Release date: 2026-08-30

## Overview

v6.3.0 is a **minor release** that completes the **entire v6 optimization roadmap** (all 29 items across reliability, performance, frontend UX, i18n and observability), adds **full multi-language support for 22 languages** (including Arabic and 8 new voice-catalog languages with script-aware subtitle fonts), and introduces **transparent analytics disclosure with privacy controls**. This is the biggest performance and quality release in the v6 line: final compositing is now up to 3-10x faster, the first-screen bundle shrinks by over 50%, and pipeline failures expose complete tracebacks for faster issue diagnosis.

## Usage

From v6.2.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.3.0` (see `docker-run.sh` / `docker-compose.yml`).

No breaking changes or data migration required.

## What's New

### Features & Improvements

- **Complete v6 optimization roadmap (29/29 items)** — every batch of the v6 roadmap is now shipped:
  - **Performance (batch 2)**: the final compositing chain is now ffmpeg-based — identical-parameter scene concatenation uses `-c copy`, audio alignment/volume/silence-padding merge into a single filter pass, and subtitles render through the ASS path with per-entry styles (`AGNES_SUBTITLE_ASS`, with automatic fallback to the moviepy path). Poetry videos compose all scenes in one pass instead of re-encoding per scene. A dedicated encoding thread pool isolates heavy ffmpeg/moviepy work from API requests, and the token-bucket rate limiter gained a native async path so stopping a task during rate-limit waits is instant.
  - **Reliability & engineering (batch 1)**: task state follows a single-writer principle with per-task locking, resume supports persisted word-level TTS cues (no re-synthesis on resume), video polling is adaptive and multi-scene waits run concurrently, task listing is indexed with `limit/offset/status` pagination, stale artifacts/error logs are governed, and the frontend stops polling in background tabs with exponential backoff and a connection-loss banner.
  - **Frontend & i18n**: translations are split into per-language lazy-loaded chunks — the first-screen JS bundle drops from ~721 kB to ~305 kB (gzip 226 kB → 97 kB, **-58%**). Form submission/confirm/toast flows were unified into shared composables, mobile layout, focus-trap modals, `prefers-reduced-motion` and form drafts were added.
  - **Observability & ops (batch 3)**: new `GET /api/health` and `GET /api/metrics` endpoints, optional rotating file logging (`AGNES_LOG_FILE`), and a Docker `HEALTHCHECK`. Runtime settings are now converged through typed `pydantic-settings` (with `.env` support) so concurrency limits scale dynamically with API-key count.
  - **Immediate defect fixes (batch 0)**: stop now cancels instantly without retry backoff, event-loop blocking (watermark re-encode, sync downloads) is moved off the loop, multi-key delete works correctly, a frontend `v-html` XSS vector is closed, and image generation got a duplicate-submit guard.
- **Full 22-language support incl. Arabic** — the UI already had 22 languages; this release completes the voice catalog for all of them. Arabic UI is fully supported (PR #32), and 8 UI languages (Turkish, Vietnamese, Thai, Tagalog, Hindi, Persian, Bengali, Urdu) now have edge_tts voice groupings with native-voice name display, script-detection regexes (Thai/Devanagari/Bengali) and per-script subtitle font fallback (new bundled Noto fonts; Persian/Urdu reuse the Arabic reshape+bidi pipeline).
- **Transparent analytics disclosure & privacy controls** — the settings panel now shows a clear, collapsible privacy card listing exactly what usage statistics are reported (and what is never uploaded: prompts, manuscripts, poems, API keys and reference images are redacted before reporting). Analytics can be turned off entirely from the panel.
- **Complete error tracebacks in the feedback report** — pipeline failures now persist the full `traceback` into the task state; the diagnostics endpoint and the in-app feedback report include it, so you can paste complete error details (e.g. environment-level `[WinError 2]`) into GitHub issues without checking the server console.

### Refactoring & Optimizations

- **ffmpeg-first compositing chain** — the final assembly path for creative/manuscript/anchor/poetry videos was reworked from 3-4 full re-encodes into copy-concat + a single filter pass (with graceful fallback to the previous moviepy path). This is the largest performance win in the v6 line, cutting final-assembly time by roughly 3-10x on typical outputs.
- **Asynchronous rate limiting with dedicated encoding thread pool** — the token bucket now offers a native async acquire path (stop-aware), and heavy encoding runs on a dedicated executor so long encoding jobs no longer starve the request path.

### Bug Fixes

- **Fixed stopping behavior** — cancelling a task no longer triggers retry backoff (up to ~2 minutes) and no longer deletes a resumable `video_id`.
- **Fixed multi-Key configuration** — key IDs are now hashed from the actual key so deleting one Key from multiple configured Keys removes exactly that Key.
- **Fixed event-loop freezes** — watermark re-encoding and synchronous downloads no longer block the whole service; a semaphore release bug that could permanently break the concurrency cap under low-rate-limit configurations is fixed.
- **Fixed frontend issues** — a stored-XSS vector via unescaped `v-html` is closed, duplicate image-submit without guard is prevented, and fetch errors now surface readable backend messages instead of silent failures.

---

No configuration changes are required. Existing tasks remain resumable; task state files are unchanged in format.
