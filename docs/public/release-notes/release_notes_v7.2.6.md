# Release v7.2.6 — Video Polling Fix for the CN Site (api.agnes-ai.cn)

> Release date: 2026-11-07

## Overview

v7.2.6 is a maintenance release that fixes video task polling on the CN site
(`api.agnes-ai.cn`). Every status request for a task created there returned "task not found",
so finished videos were reported as still rendering until the 30-minute polling timeout.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.2.6` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no configuration changes. Existing API keys, key/domain bindings, workspaces
  and task state files keep working.
- Tasks that were stuck at "waiting for video" before the upgrade can be resumed from the progress
  page: the finished file is downloaded and watermarked instead of being rendered again.

## What's New

### Bug Fixes

- **Video tasks submitted to the CN site now complete.** The status check now falls back to the
  provider's REST task endpoint when the gateway endpoint reports the task as missing, which is
  what the CN site always returns. Previously such jobs polled until the 30-minute timeout even
  though the video had already been generated.
- **Finished videos are recovered without re-rendering.** Resuming one of those tasks downloads
  the existing video and applies the watermark, so no extra render quota is used.
- **Failed lookups caused by a mismatched API key are detected on both endpoints.** When the
  key that submitted a job is no longer part of the key pool, the one-time owner probe now also
  queries the REST endpoint, so single-site or multi-site key setups both recover.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place.
