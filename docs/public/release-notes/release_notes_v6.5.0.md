# Release v6.5.0 — One-Click Video Creation and In-Place AI Editing

> Release date: 2026-09-17

## Overview

v6.5.0 is a **minor release** that adds two new creative paths to the web app's main interface: a **Simple mode ("一键创作")** that turns a single idea into a complete creative long video through a guided three-step wizard with a previewed storyboard and narration, and the **channel-1 "AI 帮我改"** editing flow that lets you rewrite text or re-generate images directly on a manual-mode checkpoint before applying. It also improves the discoverability of the new entry point and completes translations across all 22 supported languages.

## Usage

From v6.4.8:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:6.5.0`.

No breaking changes and no data migration are required. Existing tasks, checkpoints and configurations remain valid.

## What's New

### Features & Improvements

* **Simple mode ("一键创作") — one idea to a finished creative video.** A new top-level tab in the main UI offers a three-step wizard: type an idea, generate a previewed storyboard with per-scene prompts and narration, then click once to submit a creative-video task with an automatic voice, subtitles and resolution preset. Because the storyboard is confirmed from the `preview-script` result before generation, wrong ideas are caught with a few cheap LLM calls instead of a full re-run of the video pipeline.
* **In-place "AI 帮我改" (channel 1) editing.** On a checkpoint, you can now ask the AI to modify an artifact directly: JSON/TXT/SRT scripts are rewritten while keeping their structure, and reference images are edited and re-generated with a derived image-to-image prompt. A diff preview shows what will change before you apply and re-run the downstream pipeline.
* **Discoverable, translated entry point.** The simple-mode tab is labelled "⚡ 一键创作" with a compact "新/NEW" badge so new users notice the quick path, and its labels are now natively translated across all 22 locales instead of falling back to a Chinese placeholder.

### Bug Fixes

* Completed the translation of the simple-mode tab label and its badge in the 20 non-zh/en locales, which previously displayed a Chinese placeholder.

---

No action is required after upgrading.