# Release v7.2.5 — Fast Retry for Busy Video Queues and Recoverable Video Polling

> Release date: 2026-11-06

## Overview

v7.2.5 is a maintenance release for Agnes AI video generation that also delivers two user-facing
improvements. When the upstream video queue returns `503 video_queue_full`, a new user-controlled
**Fast retry** mode probes much more frequently instead of waiting a fixed 30–60 seconds between
attempts. Video status polling is now recoverable after a server restart in multi-API-key setups,
and long-running jobs report live upstream status plus per-attempt request/response logs.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.2.5` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks. Existing task state files, API keys, key/domain bindings and workspaces keep
  working; new task-state fields have defaults.
- Fast retry is off by default and only appears after two consecutive busy 503 responses. Defaults
  can be changed with `AGNES_FAST_RETRY_PER_MINUTE` (30) and `AGNES_FAST_RETRY_MINUTES` (3).
- Tasks left at "waiting for video" after a restart can now be resumed from the progress page. The
  finished upstream video is downloaded, watermarked and marked complete without re-submitting.
- Progress-page wording for the new controls is available in all 22 UI languages.

## What's New

### Features & Improvements

- **Fast retry mode for busy video queues.** After two consecutive 503 / queue-full responses the
  progress page offers a switch with two settings: attempts per minute (1–120) and duration in
  minutes (1–30). Once enabled, the submit loop probes at `60/x` seconds, bypasses the shared
  submit rate limiter and preserves the normal retry budget. It switches itself off on a successful
  submit, on expiry, or when the user stops it, then returns to the normal cadence. Available via
  `POST /api/tasks/{id}/fast-retry`.
- **Retry counter and per-attempt logs.** The progress page shows how many probes were sent. Each
  probe logs its request payload and the upstream response body
  (`[FastRetry] probe #N → POST ...` / `← HTTP ...`), with masked API keys and truncated prompts.
- **Live video polling status.** While a video renders upstream, the progress page shows the
  provider status and elapsed time instead of a static "waiting" line; polling logs are emitted
  more frequently.
- **Video jobs survive a restart in multi-key setups.** The API key used to submit a job is saved
  as a SHA-256 fingerprint (never plaintext) and restored on resume. If the binding is missing, a
  one-time read-only probe finds the key that owns the upstream job and pins polling to it.

### Bug Fixes

- **Video tasks no longer get stuck at "waiting for video" after a restart.** Previously a wrong
  polling key returned `404 task not found`, which was treated as delayed task visibility and
  retried until the 30-minute timeout — even when the video had already finished upstream.
- **404 status errors are no longer always treated as delayed visibility.** A 404 caused by the
  wrong key now triggers the owner probe; only a 404 across all keys keeps the existing
  "not yet visible" behaviour.

---

**Compatibility:** no API breaks and no required configuration changes. Existing `.env` files,
API keys, key/domain bindings and workspaces keep working; source, Docker and npm installs
upgrade in place.
