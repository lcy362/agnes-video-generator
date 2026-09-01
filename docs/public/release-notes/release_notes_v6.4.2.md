# Release v6.4.2 — Per-Key Domain Binding & Auto-Detect

> Release date: 2026-09-01

## Overview

v6.4.2 is a **patch release** that fixes multi-key authentication failures (kit issues #38, #44) by letting each API Key bind its own access domain, and adds a one-click **auto-detect** for network. Users with several keys across the global and domestic sites no longer need a single global domain for everyone. `apihub.agnes-ai.cn` is back as a China fallback that works with both domestic and global keys.

## Usage

From v6.4.1:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.4.2`.

No breaking changes or data migration required. Existing keys keep working; keys without a bound domain simply fall back to the global domain setting.

## What's New

### Features & Improvements

* **Per-Key domain binding** — each API Key saved in the projects config can now carry its own access domain (`com` / `cn` / `cn_bak`), so keys issued on the global site and keys issued on the domestic site can coexist and be routed to the correct endpoint automatically. Keys can from the environment still use the global domain.

* **One-click "Auto-detect domains" button** — in the API Key config panel, trigger a probe that tests each key across the candidate domains and fills in the matching domain automatically, instead of guessing it by hand.

* **Restored China fallback domain** **`apihub.agnes-ai.cn`** — this endpoint accepts both domestic and global keys, giving users a migration path when their key domain changes. It is not listed in the official docs and may be removed later, so we recommend choosing the domain that matches your key.

### Bug Fixes

* **Fixed multi-key authentication failures across domains** — after the Chinese domain migration, global-site keys could fail authentication against the strict domestic endpoint; domain is now resolved per key with the restored fallback, so mixed global/domestic keys authenticate successfully.

* **Domain mismatch hints in the config UI** — keys without a bound domain now show a clear "domain not set" hint, prompting users to pick or auto-detect the matching domain on their next visit.

