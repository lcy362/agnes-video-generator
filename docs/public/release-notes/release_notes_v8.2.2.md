# Release v8.2.2 — Model Catalog Follows the Retired 2.5 Flash Text Model

> Release date: 2026-11-24

## Overview

v8.2.2 is a small maintenance release that aligns the built-in model catalog with Agnes AI's
retirement of the **`agnes-2.5-flash` chat model on 2026-11-30**. The app already defaulted to
`agnes-3.0-flash`, but the retired id could still be picked in the text-model list or stay pinned in
an existing `config.json`. Both paths are now handled, the decision model is no longer offered as a
chat model, and paid-model labels cover every Pro variant. Video and image models are unchanged, and
there are no API or configuration changes.

## Usage

Source:

```bash
git pull
pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.2.2` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`; the launcher reinstalls
dependencies when `requirements.txt` changes.

### Upgrading notes

- No action required. Nothing to reinstall, no configuration to edit, no task state or checkpoint to
  reset.
- If `config.json` still pins `agnes-2.5-flash` (or the older `agnes-2.0-flash`), the text model is
  normalized to `agnes-3.0-flash` when it is read and persisted on the next save, so script writing,
  scene prompts and other chat calls keep working after the shutdown date.
- The default video model (`agnes-video-2.5-flash`, free tier) and image model
  (`agnes-image-2.5-flash`) are untouched; the paid `agnes-video-2.5` option keeps working.

## What's New

### Bug Fixes

- **Retired chat model removed from the model picker.** `agnes-2.5-flash` retires on 2026-11-30 and no
  longer appears in the text-model list, nor in the offline fallback list used when `/v1/models` is
  unreachable — a failed catalog request can no longer recommend a model that will reject calls.
- **Existing configurations migrate automatically.** A saved text model that points at a retired id
  falls back to `agnes-3.0-flash` on read and on save, so upgrades do not need a manual edit and do
  not start failing once the model is switched off upstream.
- **Decision model is no longer offered as a chat model.** `agnes-sys1-1.0` only serves
  `POST /v1/systemone` and rejects Chat Completions with HTTP 400; it used to be classified as a text
  model and could break every call when selected. It is now filtered out of the catalog.
- **Paid-model labels cover every Pro variant.** The settings page recognizes the new `agnes-3.0-pro`
  and `agnes-2.5-pro-beta` / `-theta` entries as paid instead of matching only 2.5 Pro by name.
- **Beta hint no longer names a specific model.** The hint now describes the selected model in all 22
  UI languages instead of claiming that `agnes-2.5-flash` is the beta model.

---

**Compatibility:** no API or configuration changes. Text-model selections that point at a retired id
are migrated to `agnes-3.0-flash`; video and image models, task state files and checkpoints are
unaffected, and unfinished tasks can resume.