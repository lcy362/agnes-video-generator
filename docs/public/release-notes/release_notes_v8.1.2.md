# Release v8.1.2 — Routine Maintenance and Stability Fixes

> Release date: 2026-11-19

## Overview

v8.1.2 is a small maintenance release. It bundles routine cleanups, minor interface polish and a
set of small reliability fixes across the app. There is no new workflow to learn and no change to
the API, so existing installations keep working as before.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.1.2` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no required configuration changes. Existing API keys, workspaces, task state
  files and unfinished tasks keep working.
- The frontend bundle in `static/` was rebuilt, so source installs should hard-refresh the page
  once after upgrading.

## What's New

### Features & Improvements

- **Minor interface polish.** Assorted small refinements to spacing, labels and interaction
  feedback. No behaviour changes are required from users.

### Bug Fixes

- **Small fixes and reliability improvements.** A handful of edge cases around task creation and
  the progress view were addressed, including a few rare states where the interface could lag
  behind the actual task status.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place; a hard refresh is recommended once because the frontend bundle changed.
