# Release v8.2.3 — Keyframe Video Generation No Longer Rejected by the Upstream API

> Release date: 2026-11-28

## Overview

v8.2.3 is a small maintenance release that fixes keyframe video generation (first-frame / last-frame
image-to-video) failing with an upstream HTTP 400 `invalid_request` error. The upstream API now
requires the output aspect ratio to follow the input frame in keyframe mode and rejects requests that
send an explicit `aspect_ratio`. The app no longer sends that field in keyframe mode, so creative
long videos, simple videos and any other pipeline using first/last frames generate normally again.
Text-to-video and reference-image modes are unchanged, and there are no API or configuration changes.

## Usage

Source:

```bash
git pull
pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.2.3` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`; the launcher reinstalls
dependencies when `requirements.txt` changes.

### Upgrading notes

- No action required. Nothing to reinstall, no configuration to edit, no task state or checkpoint to
  reset.
- Existing tasks that previously failed at `video_gen` with
  `keyframe mode cannot set aspect_ratio; output follows the input image` can be resumed after
  upgrading — the corrected request is built at submission time, so no saved task data changes.
- The built-in fallback (`AGNES_KEYFRAME_NATIVE=0`, first/last frames submitted as reference images)
  still behaves as before and is not needed for this fix.

## What's New

### Bug Fixes

- **Keyframe video generation works again.** First-frame / last-frame requests no longer send an
  explicit `aspect_ratio`, which the upstream now rejects with HTTP 400 `invalid_request` in keyframe
  mode. Output continues to follow the input frame's aspect ratio, as the upstream requires. This
  restores creative long videos and simple videos that use keyframe chaining.
- **Other generation modes are unaffected.** Text-to-video requests and the reference-image
  fallback path keep sending `aspect_ratio` exactly as before.

---

**Compatibility:** no API or configuration changes. Task state files and checkpoints are unaffected,
and unfinished tasks can resume.
