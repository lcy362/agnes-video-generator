# Release v6.4.6 — Digital Human (Anchor) Video Fix for Docker

> Release date: 2026-09-13

## Overview

v6.4.6 is a **maintenance release** that fixes a failure in the **digital human / anchor (数字人口播)** video pipeline when running in Docker. Anchor tasks previously crashed at the "video stitch & composite" step and never recovered on retry. If you generate talking-presenter / digital-human videos inside a container, this release makes them complete reliably again.

## Usage

From v6.4.5:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:6.4.6`.

No breaking changes and no data migration are required. Existing tasks and configurations remain valid.

## What's New

### Bug Fixes

* **Digital human (anchor) videos no longer fail at the stitch/composite step in Docker** — anchor tasks crashed while looping the presenter clip and compositing it with narration audio and subtitles, and retrying did not help because the underlying cause was permanent. The container ships only the bundled `ffmpeg` binary (no `ffprobe`), and the clip-duration probe did not handle a missing `ffprobe`. Media duration is now probed through `ffmpeg` whenever `ffprobe` is unavailable, with a safe default as a final fallback, so digital-human video composition completes normally in Docker and other minimal environments.

---

No action is required after upgrading.
