# Release v6.4.8 — Clearer Failure Diagnosis for Video Download and DNS Errors

> Release date: 2026-09-16

## Overview

v6.4.8 is a **patch release** for video generation failures that happen at the very end of a job. When your machine cannot resolve or download the generated result files, the failure panel now explains that it is a local DNS or network problem and names the domain involved, and the diagnostic report now points at the step that actually failed instead of an earlier one.

## Usage

From v6.4.7:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:6.4.8`.

No breaking changes and no data migration are required. Existing tasks, checkpoints and configurations remain valid.

## What's New

### Features & Improvements

* **Readable diagnosis for local network and DNS failures.** Long-running creative, manuscript, anchor and poetry jobs that died right at the download step used to surface only `RetryError[<Future ... raised ConnectionError>]`. Such failures are now translated into a message that names the domain that could not be resolved (or the host that refused the connection) and lists what to check: a resolver that can reach the output domain, VPN or proxy DNS hijacking, and hosts-file or security-software blocking.
* **Retry guidance that matches the failure type.** A failure that retrying cannot fix is now labelled as such, so the panel tells you to repair the local network first instead of pushing another retry. Resuming after the fix still reuses the already generated video, so no extra generation quota is spent.
* **Accurate step attribution in diagnostic reports.** The failed step reported by the feedback panel and the pre-filled GitHub Issue is read live from the running task. Previously it came from a snapshot taken when the page opened, so clicking Retry on the same page could report `scene_config` while the job had actually failed in `video_gen`.

### Bug Fixes

* Terminal progress events are persisted immediately, so the final failure or completion message no longer disappears behind the write-throttling used for high-frequency updates.
* Failures in simple image generation report the same readable network diagnosis instead of a raw exception string.

---

No action is required after upgrading.
