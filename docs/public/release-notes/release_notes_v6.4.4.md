# Release v6.4.4 — Open Image Model Selection & Agnes Image 2.5 Flash

> Release date: 2026-09-04

## Overview

v6.4.4 is a **maintenance release** that adds a small but useful capability: you can now **select the image model** in the settings panel instead of it being fixed. It introduces **Agnes Image 2.5 Flash** (`agnes-image-2.5-flash`) as the new default image model (text-to-image and image-to-image) and retires the deprecated **agnes-2.0-flash** text model in favor of `agnes-2.5-flash`, keeping text and image generation on the current generation 2.5 line.

## Usage

From v6.4.3:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.4.4`.

No breaking changes or data migration required. After upgrading, hard-refresh the web UI once (or clear the browser cache) so the rebuilt frontend bundle (with the newly opened model selector) is loaded.

## What's New

### Features & Improvements

* **Image model selection enabled** — you can now choose the image model used for reference images, end frames, and standalone image generation directly in the Settings panel, instead of it being fixed to the built-in default.

* **Agnes Image 2.5 Flash added and set as default** — the latest generation image model `agnes-image-2.5-flash` is now the default for both text-to-image and image-to-image workflows; the older `agnes-image-2.1-flash` and `agnes-image-2.0-flash` remain available as selectable options.

* **LLM upgraded to Agnes 2.5 Flash** — the deprecated `agnes-2.0-flash` text model is removed from the selector and replaced by `agnes-2.5-flash` for story, script, and narration generation, following the official model deprecation notice.

---

This is a maintenance release focused on model flexibility: open image model selection, a newer default image model, and migration off the deprecated text model.