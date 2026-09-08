# Release v6.4.5 — Agnes 3.0 Flash Text Model Upgrade

> Release date: 2026-09-08

## Overview

v6.4.5 is a **maintenance release** that upgrades the default text/LLM model from `agnes-2.5-flash` to **`agnes-3.0-flash`** — Agnes AI's newest generation reasoning model. This brings improved script generation quality, better instruction following, and more reliable JSON output for all long-video pipelines (creative, manuscript, anchor, poetry).

## Usage

From v6.4.4:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.4.5`.

No breaking changes or data migration required. The upgrade is transparent — existing tasks and configurations remain valid. If you have manually selected `agnes-2.5-flash` in the Settings panel, that selection is preserved; the new default only applies to fresh installations or when no explicit model is configured.

## What's New

### Features & Improvements

* **Agnes 3.0 Flash as default text model** — all LLM-powered features (AI screenwriting, scene prompt generation, poetry splitting, manuscript segmentation) now use `agnes-3.0-flash`, Agnes AI's latest reasoning model. It delivers more stable end-to-end task execution, stronger instruction following in long contexts, and higher-quality structured JSON output compared to the previous `agnes-2.5-flash`.

* **Reasoning capability (transparent)** — Agnes 3.0 Flash is a reasoning model that internally performs chain-of-thought before generating output. This happens transparently with no configuration needed; the API response format remains fully backward-compatible (`choices[0].message.content`).

* **Fallback model list updated** — when the `/v1/models` endpoint is unreachable, the application now falls back to `["agnes-3.0-flash", "agnes-2.5-flash"]` for text model selection, ensuring graceful degradation.

---

The `agnes-2.5-flash` model remains available in the model selector for users who prefer it. No action is required after upgrading.
