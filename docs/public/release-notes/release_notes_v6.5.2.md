# Release v6.5.2 — Style Preset Library and Media Gallery

> Release date: 2026-09-22

## Overview

v6.5.2 is a **feature release** that adds two quality-of-life surfaces on top of the existing task list: a reusable **style / prompt preset library** for filling the style field in one click, and a **read-only media gallery** for browsing finished videos and images side by side. Style presets are fully localized across all 22 interface languages, and the gallery reuses the existing task directory structure with no new data files or delete operations.

## Usage

From v6.5.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.5.2`.

No breaking changes and no data migration are required. Existing tasks, checkpoints and configurations remain valid.

## What's New

### Features & Improvements

* **Style / prompt preset library.** Creative and poetry video forms now offer a style picker beside the style input. It ships with 18 curated, non-overlapping presets across six categories (photographic, cinematic, oriental, painting, animation, fantasy), each structured as medium + lighting + color + texture to compose cleanly with your subject prompt. Clicking a preset fills the style box in one click and you can keep editing it. Saved as a preset is supported too.
* **One-click preset reuse with controls.** The picker lists your custom presets first, brings recently used presets to the front, shows the full prompt on hover, and lets you save the current style edit as a named custom preset. System presets are read-only; custom presets can be renamed and deleted.
* **Media gallery (read-only).** A new parallel "Gallery" tab shows finished videos and images in a filterable grid (type × status). Video cards use the native first frame as a cover with hover playback, and images link to the existing media endpoint. Clicking a card opens the task detail. The gallery is strictly read-only — it exposes no delete or batch operations — and reads entirely from the existing task directory, so no new data files are written into task folders.
* **Lazy thumbnail cache (gallery).** For larger galleries, video covers are extracted to a rebuildable cache under the config directory (never inside task folders) to keep the grid snappy without touching the task directory structure.
* **Localization.** All preset category names and system-preset display names are translated across all 22 supported interface languages; the English and Chinese key sets are fully aligned.

### Bug Fixes

* Creative and poetry forms no longer pre-fill the style field with hardcoded Chinese text on non-Chinese interfaces; an empty value is now a valid choice, matching the backend default.

---

No action is required after upgrading.