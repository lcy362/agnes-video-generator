# Release v7.0.6 — Language-Neutral Visual Style Defaults, Clearer Style Preset Picker

> Release date: 2026-10-08

## Overview

v7.0.6 is a **patch release** for the visual-style handling of AI long-video generation. The style field in Creative and Poetry video tasks no longer carries a hardcoded Chinese default. Previously, a user who left the style field empty in an English, Spanish or Arabic interface still had the Chinese phrase "电影质感写实风格" written into the task and sent to the scene-prompt model, and the same Chinese text surfaced in diagnostic reports. An empty style field is now pre-filled with the language-neutral default preset, and the style preset picker was rebuilt so the active preset is visible at a glance.

## Usage

From v7.0.5:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.0.6` (then `docker compose up -d` to recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

No breaking changes and no data migration are required. Tasks created before v7.0.6 keep the style text they were created with. API clients that omit the `style` field now send an empty value instead of a Chinese literal; the screenwriter keeps its own neutral wording internally, so scene prompts stay cinematic and no request body has to change.

## What's New

### Features & Improvements

* **Style preset picker shows what is active.** The preset dropdown was rebuilt as a native-select-style control: the trigger displays the currently selected preset name, the list marks the active entry with a checkmark, and a one-line hint under the field explains what picking a preset does. The trigger label, placeholder and hint are localized in all 22 interface languages.

### Bug Fixes

* **No more Chinese visual style inside non-Chinese tasks.** The hardcoded Chinese style default was removed from the Creative and Poetry task forms, from the shared legacy task-creation endpoint, and from the Creative and Poetry task models. Leaving the style field empty now pre-fills it on page load with the language-neutral default preset (an English cinematic prompt), so the task, the generated scene prompts and the diagnostic report all stay in the language the user is working in.

---

Existing projects do not need to be recreated. Reopening a Creative or Poetry form after upgrading shows the preset name in the style field, and you can pick any other preset — or clear the field — as before.
