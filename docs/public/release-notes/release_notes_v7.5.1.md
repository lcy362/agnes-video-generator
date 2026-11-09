# Release v7.5.1 — Image Generation Task Detail Page Fixes

> Release date: 2026-11-09

## Overview

v7.5.1 is a patch release for simple image generation tasks. Opening a finished image task from the
task list now shows a correct detail page: the real stage list instead of the creative-video
pipeline, a 100% progress bar with a completed summary, the generated image itself instead of a
non-working video player, and the original prompt, negative prompt, system prompt and image size.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.5.1` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no configuration changes. Existing API keys, workspaces and task state files
  keep working; already generated images are displayed correctly without any regeneration.
- The frontend build in `static/` was rebuilt, so source installs should pull and reload the page
  (a hard refresh clears the cached bundle).

## What's New

### Features & Improvements

- **Image task detail page now renders the image.** The result block shows the generated PNG with a
  click-to-zoom lightbox under an "Image generated" header, served by `/api/image/{task_id}` instead
  of the video endpoint that always returned 404 for image tasks.
- **Task info for image generation.** The detail page displays the prompt, negative prompt, system
  prompt and the requested image size (e.g. `768x1344`), so a finished image can be traced back to
  the request that produced it.

### Bug Fixes

- Image generation tasks no longer borrow the creative-video stage list: the timeline shows the two
  real stages (submit, image generation) instead of unrelated stages such as scene config, story,
  script, audio, subtitle and concatenation.
- Finished image tasks report 100% progress and a completed status instead of staying at 0% with a
  "task starting" placeholder.
- Simple video and simple image tasks now mark their stages as done in the timeline once the task
  completes, instead of leaving every stage pending.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place.
