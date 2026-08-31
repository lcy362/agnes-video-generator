# Release v6.4.1 — Windows ffmpeg Stability Fix

> Release date: 2026-08-31

## Overview

v6.4.1 is a **patch release** that fixes the "ffmpeg not found" failure (`FileNotFoundError`) that could occur during video composition on Windows and other systems without a system `ffmpeg`. The server now automatically falls back to the static ffmpeg binary bundled with `imageio-ffmpeg`, so no manual ffmpeg installation is required.

## Usage

From v6.4.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.4.1`.

No breaking changes or data migration required.

## What's New

### Bug Fixes

* **Fixed "ffmpeg not found" failure (`FileNotFoundError`) during video composition** — on Windows or systems where `ffmpeg` is not on the `PATH`, creative / manuscript / anchor / poetry composition (concatenation, audio overlay, watermark) could fail at the composition step with `[WinError 2]`. The server now automatically falls back to the static ffmpeg binary bundled with `imageio-ffmpeg`, so no manual ffmpeg installation is required. A non-blocking startup check logs which ffmpeg source is being used. (Issues #35, #36)

