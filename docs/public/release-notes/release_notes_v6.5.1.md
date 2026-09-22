# Release v6.5.1 — Pipeline Stability Hardening and Scene-State Fixes

> Release date: 2026-09-22

## Overview

v6.5.1 is a **patch release** that hardens long-form video pipelines against transient model API failures and improves task-resume accuracy. It isolates a single failing scene during manuscript prompt generation so the rest of the task still completes, makes chat request timeouts consistent between text and multimodal calls, aligns the Windows startup script with the Unix one, and backfills per-scene video state so task queries and resumes reflect real generation results.

## Usage

From v6.5.0:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Windows users: `start.bat` now falls back to the `py` launcher when `python` is not on `PATH` and auto-opens the browser only after the service is ready, matching `start.sh`.

Docker users: `docker pull ghcr.io/lcy362/agnes-video-generator/free-short-video:6.5.1`.

No breaking changes and no data migration are required. Existing tasks, checkpoints and configurations remain valid.

## What's New

### Features & Improvements

* **Resilient manuscript generation.** During manuscript long-video prompt creation, a failure in a single scene no longer aborts the whole task. The failing scene is skipped, the remaining scenes are generated normally, and a resume only re-generates the failed scene — reducing wasted API quota and failed tasks under transient model errors.
* **Consistent chat timeouts and retry budget.** Text chat now shares the same 300s read timeout as multimodal calls and, on timeout-class errors, retries only once instead of consuming the full retry budget — widening the success window while keeping failure wait times short.
* **Aligned Windows launcher.** `start.bat` detects Python via the `py` launcher when needed, builds the venv and dependencies accordingly, and opens the browser only once the local service is reachable, so first-run startup no longer opens a dead page.

### Bug Fixes

* Manually-authored manuscript scene prompts (per-scene paragraph mapping) were not being isolated on failure; hard failures now carry the scene index for accurate reporting.
* Fixed creative-video task state not reflecting completed scene videos: generated per-scene videos are now written back to the task state, so the task list and resumes show accurate scene status instead of stuck "pending" values.

---

No action is required after upgrading.