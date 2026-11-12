# Release v8.1.1 — Cleaner Keyframe Uploads for Creative Video

> Release date: 2026-11-12

## Overview

v8.1.1 is a small maintenance release for creative long video. In keyframe mode the form no longer
offers reference-image uploads that never reached the model, so the scene start is unambiguous:
each scene begins from the character reference or from the previous scene's end frame. A side
benefit is one fewer image-generation call per task, and upload controls that do nothing are gone.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.1.1` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks and no required configuration changes. Existing API keys, workspaces, task state
  files and unfinished tasks keep working.
- The frontend in `static/` was rebuilt, so source installs should hard-refresh the page once.
- Keyframe tasks ignore the per-scene, style-plate and end-frame uploads described below when they
  do not apply to the selected chaining mode; previously such uploads were accepted but unused.
- Scene reference images and the style plate remain available in the `ti2vid` and `none` chaining
  modes, where they do reach the model.

## What's New

### Bug Fixes

- **Keyframe mode no longer offers uploads it does not use.** Three controls were shown and accepted
  in creative long video even though nothing consumed them:
  - *Per-scene reference images.* In keyframe mode an uploaded scene image used to override the
    scene's first frame, which silently discarded the previous scene's end frame — so the
    custom end frame you set no longer decided where the next scene started. Scene starts now come
    only from the character reference (first scene) and the previous scene's end frame; to control
    where a scene begins, change the previous scene's end frame. The uploader is hidden in keyframe
    mode and remains in `ti2vid` / `none`.
  - *Custom end frames in other modes.* The checkbox appeared in every chaining mode, but only
    keyframe mode reads end frames; elsewhere the images were only passed to prompt analysis. The
    block is now keyframe-only.
  - *Style plate.* Keyframe videos submit no reference images and their end-frame image-to-image
    step only reads the character plate plus the previous end frame, so the generated style plate
    was never used. It is no longer generated or accepted in keyframe mode, saving one image call
    per task. Style is still controlled by the style text, which feeds the storyboard prompt.
- **Switching chaining mode no longer carries hidden configuration.** Changing the mode now clears
  the fields the new mode ignores, so a task can never be submitted with settings the interface has
  already hidden.
- **Upload count logging is robust.** Routes that log how many uploads were skipped no longer fail
  when the handler is invoked directly (internal forwarding) rather than through the HTTP layer.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place; a hard refresh is recommended once because the frontend bundle changed.
