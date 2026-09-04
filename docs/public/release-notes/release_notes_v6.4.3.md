# Release v6.4.3 — Google Analytics Tracking Fix & Multi-Key Domain Reliability

> Release date: 2026-09-04

## Overview

v6.4.3 is a **patch release**. It restores working **Google Analytics (GA4) usage tracking** in the web app — page views and interaction events were being silently dropped and never reported — and hardens multi-API-Key authentication so a stale bound domain is re-validated instead of causing a `401`. Recommended for anyone running the app in production who relies on analytics, or who mixes global and domestic API keys.

## Usage

From v6.4.2:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.4.3`.

No breaking changes or data migration required. After upgrading, hard-refresh the web UI once (or clear the browser cache) so the rebuilt frontend bundle is loaded.

## What's New

### Bug Fixes

* **Google Analytics tracking now reports correctly** — the GA4 bootstrap pushed commands to the data layer in a form the Google Tag silently ignored, so no `page_view` or event was ever sent. The loader now emits valid data-layer commands, and page views plus UI / task events are collected as intended. Content fields (prompts, manuscripts, API keys) remain redacted before reporting.

* **Multi-key domain re-validation** — API Key auto-detect now re-validates a key's bound domain, correcting stale bindings that previously surfaced as repeated `401` authentication failures against a migrated endpoint.

* **Missing translations backfilled** — the domain-detect UI strings were present only in Chinese and English; all 20 remaining locales are now filled in, so the config panel no longer falls back to untranslated text.

---

This is a maintenance release focused on analytics reliability and multi-key authentication stability.
