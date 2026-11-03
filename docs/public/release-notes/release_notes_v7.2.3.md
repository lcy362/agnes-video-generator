# Release v7.2.3 — Collapsible Provider Help and a Per-Key Rotation Switch

> Release date: 2026-11-03

## Overview

v7.2.3 is a **patch release** for the provider settings screen. The long third-party provider
explanation stays collapsed until you open it, the Agnes settings dialog keeps a single Save
action, and each Agnes API key can be paused so it stays in the list but leaves the rotation pool.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.2.3` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks. Existing API keys, domains, and workspaces keep working.
- Every key stays **in rotation** after the upgrade until you turn its switch off.
- Turning a key off does not delete it. Config keys keep an `enabled: false` flag; a key that
  comes only from the environment is recorded in `api_keys_disabled` and is not removed from
  the environment.

## What's New

### Features & Improvements

- **Provider help starts collapsed.** In Provider Management, the third-party provider guide
  (free-model notes and the AMD Radeon Cloud setup) is hidden behind **Read more** / **Show less**
  in all 22 interface languages, so the provider list is visible without scrolling through the guide.
- **Agnes settings use one Save button.** Domain and new API keys are saved together from the
  bottom of the Agnes dialog. The extra Close button is gone; dismiss the dialog with the title-bar
  control.
- **Pause an Agnes key without deleting it.** Each key has a rotation switch. Off keeps the key
  in the list and out of the round-robin pool used for chat, image, and video calls, including
  keys supplied by the environment. Turn it back on to return that key to the pool. The shared
  rate limits follow the number of keys still in rotation.

---

**Compatibility:** no API breaks and no configuration changes required. Existing `.env` files,
API keys, domains, and workspaces keep working; source, Docker, and npm installs upgrade in place.
