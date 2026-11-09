# Release v7.5.0 — One-Click Simple Video Presets and Agnes 2.5 Media Support

> Release date: 2026-11-09

## Overview

v7.5.0 is a feature release focused on simple video generation. Simple videos now open with a
one-click preset (free 2.5 Flash, text-to-video, 5s, 16:9, 720P) so a single prompt is enough to
get a usable result, while keyframe video, multi-image references and reference audio are exposed
as first-class options. Free and paid models are clearly separated, and fast retry for busy video
queues gets a correct per-minute rate and a live attempt counter.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.5.0` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no configuration changes. Existing API keys, key/domain bindings, workspaces
  and task state files keep working.
- The default task type is now **simple video**; the last used type is remembered in the browser.
- Paid video/image models are still available but require an explicit confirmation before use.
- Fast retry keeps its existing backend contract; the progress panel, status line and progress
  messages all show attempts per minute again (1–120).

## What's New

### Features & Improvements

- **One-click simple video preset.** The simple video form now leads with your prompt plus a
  one-line summary of the preset in use: free `agnes-video-2.5-flash`, text-to-video, 5 seconds,
  16:9, 720P. Everything else moved under "Customize", so a single prompt is enough for a usable
  clip. The preset is served by `GET /api/models` (`simple_default`) so the UI, the form defaults
  and the API defaults cannot drift apart.
- **Keyframe video, reference images and reference audio for Agnes 2.5.** Submit a native first
  frame and last frame, up to 5 reference images (Flash) or 8 (2.5), and up to 3 public reference
  audio URLs, directly from the simple video form.
- **Free vs paid models are explicit.** Free models are labelled and sorted first; paid tiers are
  marked and require confirmation before a request is sent.
- **Fast retry accuracy and live feedback.** The panel, status line and progress messages use
  attempts per minute (1–120) again, the "sent N times" counter refreshes every second while fast
  retry runs, and resuming a task no longer shows a leftover switch from the previous run.

### Refactoring & Optimizations

- The simple video form was restructured into a preset-first layout with a single source of truth
  for defaults (`/api/models` → `simple_default`), keeping frontend, API and pipeline defaults in
  sync for future model changes.

### Bug Fixes

- Fixed video size tiers (960P replaced by the correct 1080P / 1K / 2K options), normalized legacy
  size values and validated mode/media combinations before submitting, so invalid pairs are
  rejected in the form instead of failing upstream.
- Aspect ratios now show landscape/portrait labels instead of raw width × height.
- Fixed the fast retry counter appearing frozen and the rate being shown in inconsistent units.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place.
