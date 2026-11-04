# Release v7.2.4 — Video Polling Uses the Right API Key and Region

> Release date: 2026-11-04

## Overview

v7.2.4 is a **patch release** for multi-region API key setups. Video tasks are now polled with
the same API key that submitted them, so the status request always goes to the same region
(international or China site) as the job. This fixes a case where a video finished upstream but
the task was reported as failed with `401 Invalid token`.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.2.4` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks. Existing API keys, key/domain bindings, domains, and workspaces keep working.
- If a video task previously failed with `401 Invalid token` while the video itself finished on
  the provider side, generate it again (or resume the task) after upgrading; the status request
  now reaches the site the task was created on.
- Polling no longer switches keys on `429`: the task keeps its own key and only backs off.

## What's New

### Bug Fixes

- **Video polling uses the key that submitted the job.** A task is now polled with the same API
  key — and therefore the same site — it was created on, instead of a domain taken from the global
  domain setting. Previously, with an API key bound to the China site while the global domain was
  the international site, every status request went to the wrong endpoint and failed with
  `401 Invalid token`, even though the video had been generated successfully.
- **No more key switching while polling.** Rate-limited status requests now back off and continue
  with the task's own key. Rotating keys during polling could send the request to a different
  site or to an account that cannot see the task.
- **Polling auth failures are now attributed.** A `401` on a status request is recorded in the
  per-key diagnostics shown in settings, so a key/domain mismatch is visible as a diagnostic
  instead of looking like a broken key.
- **Debug `curl.sh` commands match the task's site.** The generated status command now uses the
  same domain as the task's key instead of a hard-coded international endpoint.

---

**Compatibility:** no API breaks and no configuration changes required. Existing `.env` files,
API keys, key/domain bindings, domains, and workspaces keep working; source, Docker, and npm
installs upgrade in place.
