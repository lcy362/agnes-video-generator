# Release v7.2.2 — In-App Notice for Agnes China-Site Real-Name Verification

> Release date: 2026-10-23

## Overview

v7.2.2 is a **patch release** that puts one upcoming change from the free Agnes API in front of you,
inside the app: the **China site requires real-name verification before 2026-10-26 12:00 (UTC+8)**, and
unverified accounts will see a reduced API call rate. The app now shows this as a **one-time notice** in
all 22 interface languages, explains that **accounts registered on the global site need to do nothing**,
and repeats the provider's outlook — that `503` / `queue is full` upstream busy errors are expected to
improve significantly after that deadline — wherever the app already explains those errors.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.2.2` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No configuration or API changes.
- The notice appears **once per browser** and stops appearing after you dismiss it. To see it again,
  clear the site data for the app (it is stored under the `agnes.notice.*` local-storage keys).

## What's New

### Features & Improvements

- **One-time real-name verification notice for the Agnes China site.** On first load the app shows a
  single dialog: China-site accounts must complete real-name verification before **2026-10-26 12:00
  (UTC+8)** at `platform.agnes-ai.cn`, unverified accounts will get a **lower API call rate**, and
  **accounts registered on the global site (`platform.agnes-ai.com`) need no action at all**. Both
  consoles are linked, and the dialog is localized in all 22 interface languages. It is shown once and
  never again after dismissal.
- **Queue-full failures now carry the upstream outlook.** When the retries on a saturated Agnes video
  queue are exhausted, the failure message — the same text that already named Agnes, quoted the raw
  `HTTP 503 · video_queue_full` and suggested retrying off-peak — now also states that these `503` /
  `queue is full` errors are expected to improve significantly after **2026-10-26 12:00 (UTC+8)**, in all
  22 languages.

---

**Compatibility:** no API breaks and no configuration changes. Existing `.env` files, API keys, domains
and workspaces keep working; source, Docker and npm installs upgrade in place.
