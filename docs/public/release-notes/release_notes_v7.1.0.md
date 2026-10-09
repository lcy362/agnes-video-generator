# Release v7.1.0 — Resilient Upstream Retries, Off-Peak Retry Guidance, Key Authentication Diagnostics

> Release date: 2026-10-09

## Overview

v7.1.0 is a **minor release** that hardens how the app talks to the upstream video, image and chat APIs, and makes upstream trouble visible in the interface. Upstream retries are unified into a single "busy / fault" two-track policy: rate limits, server-busy 503s and queue-full signals now retry right up against the rate limit with a capped number of attempts, while genuine faults keep the gentler escalating backoff. When the video queue is full, the failure panel and the create-task toast now suggest the off-peak windows when upstream is historically smoother, rendered in the viewer's own timezone and localized in all 22 interface languages. The API key panel also surfaces upstream authentication failures (401) so you can decide whether a key needs to be replaced.

## Usage

From v7.0.6:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.1.0` (then `docker compose up -d` to recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

Upgrade notes:

- No breaking changes and no data migration. Existing tasks, checkpoints and `config.json` files are read as-is.
- **Retry configuration variable renamed.** `AGNES_VIDEO_QUEUE_RETRY_SECONDS` (a time budget in seconds) is replaced by `AGNES_VIDEO_BUSY_RETRY_ATTEMPTS` (an attempt count, default `15`). A new `AGNES_BUSY_RETRY_ATTEMPTS` covers the non-video busy track (image generation / image upload / chat). If you had exported the old variable, it no longer takes effect — remove it and use the new ones.

## What's New

### Features & Improvements

- **Off-peak retry guidance for AI video generation.** When the upstream video queue is full (HTTP 503 / queue-full) the failure panel and the create-task toast now suggest the time windows in which upstream is historically smoother, based on observed success rates rather than guesswork. The windows are stored in UTC and rendered in each viewer's own local time with a timezone label, so users in different regions see their own best hours; the wording is localized in all 22 interface languages.
- **API key panel shows upstream authentication failures.** Keys that hit an upstream `401 Invalid token` are now badged **Auth failed ×N** in the key list, with a tooltip showing the failure count, the last failure time and the upstream message, plus a matching log line. Registration is observation only: no key is removed, reweighted or reordered automatically — whether to delete a key stays entirely your decision in the configuration panel. Keys are only ever shown masked.

### Refactoring & Optimizations

- **Unified upstream retry policy ("busy / fault" two-track model).** Every upstream call — video submission, image generation, image upload and chat — now shares one retry policy module (`core/api/retry_policy.py`) as the single source of truth for classifying a response and computing the next interval:
  - **Busy track** (HTTP 429, *all* 503 including bare 503 without an error code, and queue-full codes): the first retry fires immediately, hugging the rate limit so the token bucket — not a hand-rolled sleep — sets the pace; subsequent retries use a fixed interval (steady "knocking") under an attempt cap.
  - **Fault track** (other 5xx, timeouts, connection errors): the previous escalating backoff `base × (n + 1)`, also attempt-capped.
  This replaces the previously scattered per-provider retry branches, so behavior is consistent across all upstream calls and easier to reason about and tune. The busy-track cap also moved from a wall-clock budget to an attempt count, which on multi-key setups lets the same number of attempts finish sooner.
- **Robust image upload path.** The image-upload retry loop was rebuilt on the same two-track policy, with a bounded loop and consistent backoff instead of a hard-coded pause.

### Bug Fixes

- **Queue-full 503s are no longer mistaken for hard failures.** Bare 503 responses carrying no error code are now classified as "server busy" and retried on the busy track, so video tasks ride out queue saturation instead of giving up early.
- **Image upload can no longer spin on an unusable response.** An upload response that contains no usable hosting URL no longer loops indefinitely and falls back cleanly.

---

No action is required after upgrading. If you previously set `AGNES_VIDEO_QUEUE_RETRY_SECONDS`, switch to `AGNES_VIDEO_BUSY_RETRY_ATTEMPTS` (see Upgrade notes).