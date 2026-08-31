# Release v6.4.0 — PR #33 Backend Absorption, Security Hardening, China Domestic Domain & Pipeline Reliability

> Release date: 2026-08-31

## Overview

v6.4.0 is a **medium release** that absorbs the backend bug fixes and features from PR #33 (Arabic tashkeel, manuscript reference images, preview endpoints, configurable CORS), resolves two GitHub CodeQL security alerts, fixes the rare rate-limiter live-lock that could stall all pipelines, corrects the China domestic API domain (`api.agnes-ai.cn`), and hardens overall pipeline reliability. 16 commits across 30 files.

## Usage

From v6.3.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.4.0`.

No breaking changes or data migration required.

## What's New

### Features & Improvements

- **Preview ("dry-run") endpoints for creative and manuscript tasks** — `POST /api/creative/preview-script` and `POST /api/manuscript/preview-split` let you inspect the generated script or manuscript segments before submitting a full task. Synchronous, no task created. Preview calls share the Chat API rate limiter and have a lightweight in-process concurrency cap (429 + Retry-After) to prevent abuse. (Credit: @Khaled97Sho, PR #33)
- **Arabic tashkeel for TTS narration** — creative and manuscript pipelines now automatically apply Arabic diacritic marks (harakat) to narration text before TTS synthesis, improving pronunciation quality. Tashkeel only affects TTS input; subtitle text and `narration.txt` remain clean. (Credit: @Khaled97Sho, PR #33)
- **Manuscript reference images** — per-segment reference images for manuscript tasks are now supported via `reference_images` + `reference_images_map` parameters, matching the same feature used in creative pipelines. (Credit: @Khaled97Sho, PR #33)
- **Language-aware narration budget** — narration length for non-CJK languages now uses a language-specific characters-per-second rate (Arabic: 4.0, CJK: 5.0, others: 12.0), fixing the "narration too short for non-CJK text" issue. (Credit: @Khaled97Sho, PR #33)
- **Configurable CORS origins** — the `AGNES_CORS_ORIGINS` environment variable (comma-separated) allows any companion tool to call the core API cross-origin. `AGNES_CORS_ENABLED` can force-enable or disable; auto-detects when origins are set.
- **China domestic API domain** — the `cn` domain in `AGNES_DOMAIN_MAP` now correctly points to `api.agnes-ai.cn` (the official China service endpoint), updated from the incorrect `apihub.agnes-ai.cn` (international-site fallback). The frontend domain picker reflects the correct hostname.

### Refactoring & Optimizations

- **`split_manuscript_text()` extracted as a public utility** — the manuscript-splitting algorithm is now available as a standalone function, used by both the manuscript pipeline and the new preview-split endpoint.

### Bug Fixes

- **Fixed rate-limiter live-lock** — a rare synchronous acquire path race condition could stall all pipelines indefinitely. The token bucket's async path is now the primary path, with the sync path hardened to prevent the live-lock. (Credit: @Khaled97Sho, PR #33)
- **Fixed image save not persisting** — `POST /api/images/generations` now `await`s the image download, ensuring the generated image is actually written to disk before the response.
- **Fixed GitHub CodeQL alerts #43 and #47** — path-injection and information-disclosure security alerts resolved.
- **Fixed PBKDF2-HMAC-SHA256 for config key IDs** — config key IDs are now hashed with a proper key-derivation function instead of weaker hashing.
- **Fixed Docker Hub Cloudflare WAF blocking** — the Docker Hub overview update script now strips `<script>` blocks and escapes `<` in the JSON payload to bypass the WAF XSS rule.
- **Fixed China domestic site domain** — `AGNES_DOMAIN_MAP["cn"]` corrected to `api.agnes-ai.cn` per the official Agnes model catalog. (Issue #37)

---

**Compatibility notes**: The `core/audio/tashkeel.py` module adds a new optional dependency (`mishkal`). It is installed by default via `requirements.txt`; if missing, tashkeel silently falls back to the original text. Existing task state files are forward-compatible; no migration needed.