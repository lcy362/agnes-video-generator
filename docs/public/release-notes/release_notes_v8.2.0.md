# Release v8.2.0 — Long Task Mode for Queued Video Jobs

> Release date: 2026-11-19

## Overview

v8.2.0 is a feature release focused on **waiting** — the part of video generation nobody controls.
It adds a long task mode that trades a retry attempt cap for a configurable wait budget (60 minutes
by default), auto-chained fast retry so a busy queue is re-attacked without manual clicking, and a
first-visit guide that explains the difference between the two switches. Errors that can never
succeed now stop retrying immediately and say why. The task types are also renamed to
**Single-shot clip** and **Multi-shot story**, with a one-line hint about each mode's output range
and success rate.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.2.0` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no required configuration changes. Existing API keys, workspaces, task state
  files and unfinished tasks keep working; older tasks read the new long-task and retry-chain fields
  as "off".
- The frontend in `static/` was rebuilt, so source installs should hard-refresh the page once.
- Long task mode is **off by default**. New optional settings: `AGNES_LONG_TASK_ENABLED` (default `0`)
  and `AGNES_LONG_TASK_MINUTES` (default `60`). The progress view can still switch it on per task.
- New optional API fields (`POST /api/tasks/{id}/long-task`, `interval_minutes` on the fast-retry
  endpoints) are additive — clients that ignore them behave exactly as before.

## What's New

### Features & Improvements

#### Long task mode: wait hours instead of minutes

- When the upstream video queue is saturated (HTTP 503 / queue full), retries used to stop after a
  fixed number of attempts — roughly 15 minutes with one API key, less with more. Long task mode
  replaces that attempt cap with an **accumulated wait budget**, 60 minutes by default and
  configurable from 5 to 480 minutes.
- Only time actually spent waiting on a busy queue counts. Rendering, storyboard generation, TTS and
  stitching time are never charged against the budget, and multi-scene tasks share a single budget
  across all their segments.
- Retry cadence is untouched: the first retry is still immediate and later ones still back off. If
  fast retry is on, it keeps its own frequency. Long task mode only decides **how long** the app is
  willing to keep asking.
- Turn it on from the retry panel on the progress view, next to fast retry, or set a default for new
  tasks in Settings (`POST /api/config/long-task`, `POST /api/tasks/{id}/long-task`).

#### Errors that can never succeed now fail fast

- An invalid API key, a rejected parameter, a missing endpoint or a content-moderation block no
  longer burns the whole retry budget. These are classified as fatal and the task ends immediately
  with a specific reason in your UI language instead of a generic timeout.
- Everything unknown stays retryable on purpose — an unrecognised upstream error is never treated as
  fatal, so a missing rule cannot kill a task that would have succeeded.

#### Auto-chained fast retry

- A fast-retry round is short by design (3 minutes by default). It now takes a **gap between rounds**
  (default 5 minutes, 1–60) and re-opens itself automatically: when a round expires the task returns
  to the normal cadence, and at the first busy signal after the gap a new round starts with the same
  parameters.
- The chain stops on success, when you switch it off, or when a long-task budget runs out. Manual
  rounds chain too, not just rounds started automatically.

#### A guide the first time the retry panel appears

- Fast retry speeds up the rhythm; long task mode extends the total budget. That distinction is easy
  to miss while anxiously watching a queue, so the retry panel now shows a two-step tip the first
  time it appears: what each switch does, then a short "got it". It shows once across tasks and
  never blocks the page.

#### Task types renamed to match what they produce

- **Simple video** is now **Single-shot clip** and **creative video** is now **Multi-shot story**, in
  all 22 UI languages.
- Each of the two types now carries a one-line hint under the selector: one 4–12 s single shot per
  run with a high success rate, versus 1–30 shots stitched into a story of several minutes where any
  failing shot breaks the chain. Other task types keep their own parameter forms and gain no extra
  text.

### Refactoring & Optimizations

- Retry decisions and their user-facing messages collapsed into one declarative table
  (`core/api/error_taxonomy.py`): each rule states whether the error is retryable, a stable reason id
  for logging and a message key for the 22 UI languages. Supporting a newly reported upstream error
  is now a table row rather than a change in the retry loop, and unknown errors fall back to
  retryable by construction.
- Long task mode and fast retry are injected as optional hooks that default to `None`, so tasks
  without them run the previous code path unchanged — the features cannot regress pipelines that
  never enable them.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place; a hard refresh is recommended once because the frontend bundle changed.
Long task mode is opt-in, and the new request fields are optional.
