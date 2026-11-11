# Release v8.0.1 — Automatic Fast Retry for Saturated Video Queues

> Release date: 2026-11-11

## Overview

v8.0.1 is a small maintenance release. It turns the fast retry mode introduced in v8.0.0 into an
automatic, configurable behaviour: when the free video queue reports full, tasks retry at your chosen
rate on their own instead of waiting for someone to press a switch.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.0.1` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no required configuration changes. Existing API keys, workspaces, task state
  files and unfinished tasks keep working.
- The frontend in `static/` was rebuilt, so source installs should hard-refresh the page once.
- Automatic fast retry is opt-in: with the setting off, retry behaviour is exactly the same as
  v8.0.0.

## What's New

### Features & Improvements

#### Automatic fast retry

- Settings now has a **Fast retry** block: turn it on, then choose how many attempts per minute and
  for how many minutes. Once the video queue reports full twice in a row, the task enters fast retry
  by itself instead of waiting for someone to press the switch.
- The progress page keeps the manual switch and adds a **remember this choice** option: apply
  automatic fast retry to this task only, or enable it for every future task.
- Turning it off by hand only affects the current run; a resumed task follows the saved global
  setting again. When the window expires the task returns to the normal retry rhythm and needs two
  fresh queue-full signals before entering fast retry again.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place; a hard refresh is recommended once because the frontend bundle changed.
