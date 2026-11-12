# Release v8.1.0 — Multi Reference Images for Every Video Type

> Release date: 2026-11-12

## Overview

v8.1.0 is a feature release for reference-image control. Creative long video, manuscript long video,
poetry video, digital-human talking head and simple image generation now share one reference model —
character plate, style plate, continuity still and per-scene content images — so you can upload
several images per task (or per scene) and have them actually reach the model. It also fixes
keyframe aspect-ratio distortion, adds a working retry path for failed image tasks, and keeps
external asset mode (Jimeng workflow) from calling the image model.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.1.0` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no required configuration changes. Existing API keys, workspaces, task state
  files and unfinished tasks keep working; older tasks read the new reference fields as empty.
- The frontend in `static/` was rebuilt, so source installs should hard-refresh the page once.
- New optional environment variables: `AGNES_IMAGE_MAX_REF_IMAGES` (reference limit for image
  generation, default 5) and `AGNES_UPLOAD_MAX_MB` (per-file upload cap, default 10).
- Uploading no images behaves exactly as before — no extra steps and no extra model calls.

## What's New

### Features & Improvements

#### Multi reference images for every task type

- Creative long video, manuscript long video, poetry video, digital-human talking head and simple
  image generation all accept multiple reference images now, from the form all the way to the model
  API.
- Images are organised into four slots — character plate, style plate, continuity still and
  per-scene content image — merged in that order, de-duplicated, then truncated to the model limit
  (video: 5 for `agnes-video-2.5-flash`, 8 for `agnes-video-2.5`; image: 5 by default). Prompts can
  address them as `<Picture N>`.
- A shared uploader replaces the old single-file inputs: thumbnails, `#N` order badges and
  reordering, in all 22 UI languages.
- Limits now have one source of truth (also exposed through `GET /api/models`), going over the limit
  returns a clear 422 instead of being silently truncated, uploads are capped at 10MB per file, and
  unsupported file extensions are rejected instead of being silently renamed.

#### Per-scene reference images and checkpoints

- Manuscript tasks can pause right before video submission and let you add or replace reference images
  scene by scene (`POST /api/tasks/{id}/scene-refs`), instead of squeezing one long script into a
  single look.
- Creative tasks accept multiple images per scene plus optional character / style plates, and an
  optional shot-linking mode that draws a still between scenes and submits it as the next keyframe.

#### Consistent characters in keyframe and talking-head tasks

- Creative keyframe mode now submits native first/last frames, and digital-human tasks persist the
  uploaded reference images and use image-to-image instead of a text-to-image placeholder, so the
  face stays consistent across shots.

### Refactoring & Optimizations

- Reference-image assembly moved into a single stateless module shared by every pipeline
  (character → style → continuity → scene content, with de-duplication and truncation reporting).
  Limits, ordering and de-duplication can no longer drift between task types, and per-scene
  extensions only need one hook.

### Bug Fixes

- **Keyframe aspect ratio is preserved.** First/last frames used to be hosted as square 1024×1024
  images, so 9:16 or 16:9 keyframe requests came back as 720×720. Frames are now hosted at the
  target ratio (for example 720×1280 → 720×1260 output) and stale square cache entries are
  refreshed automatically.
- **Failed image tasks can be retried.** Clicking "Retry task" on a failed image generation used to
  fail instantly at the init step with
  `"SimpleImageTask" object has no field "step_build_scenes"`. Image tasks now have their own retry
  path that reuses the saved prompt, system prompt, size, negative prompt and reference images.
- **External asset mode stays offline for image generation.** In the Jimeng workflow (external asset
  mode) the pipeline no longer calls the image model for character plates or continuity stills, and
  user-uploaded plates are kept as-is.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place; a hard refresh is recommended once because the frontend bundle changed.
