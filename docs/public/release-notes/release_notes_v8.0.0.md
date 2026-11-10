# Release v8.0.0 — Redesigned Interface, Fast Retry Mode and One-Click Simple Video

> Release date: 2026-11-10

## Overview

v8.0.0 is a major release built around three themes: a completely rebuilt web interface, a fast
retry mode for saturated video queues, and a reworked simple video flow that turns a single prompt
into a usable clip. The whole app now shares one visual system and one navigation model on desktop
and mobile, queue-full waiting is no longer a fixed 30–60 second cadence, and simple video ships
with sane defaults plus native first/last frame, multi-image and audio references.

## Usage

Source:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.0.0` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`.

### Upgrading notes

- No API breaks. Existing API keys, workspaces, task state files and unfinished tasks keep working;
  tasks created before this release resume normally.
- The frontend in `static/` was rebuilt and the layout changed substantially, so source installs
  should hard-refresh the page once to drop the cached bundle.
- The system configuration moved from the top of the create page into a settings drawer: use
  **Settings** at the bottom of the left navigation on desktop, or the gear icon in the mobile top
  bar. An amber dot marks it while no API key is configured.
- Simple video now defaults to **16:9** instead of 9:16. The previous default produced
  upside-down-looking portrait clips on the 2.5-flash model; use the aspect selector if you really
  need vertical output.
- The app now opens on simple video by default and remembers the last task type you picked.

## What's New

### Features & Improvements

#### A completely redesigned interface

- **One visual system for the whole app.** Colours, spacing, radii, borders and motion now come from
  a single set of design tokens, with matching light and dark themes. Surfaces are separated by
  hairlines instead of shadows, one amber accent carries every primary action, and metadata uses a
  monospace face.
- **Left navigation instead of top tabs.** The four main views (create, simple video, task list,
  gallery) live in a fixed left rail with numbered entries and line icons; the system configuration
  moved into a right-side drawer. Below 1024px the rail collapses into a top bar plus a horizontally
  scrollable navigation strip.
- **Consistent component layer.** Panels, buttons, inputs, chips, segmented controls, timelines and
  progress meters are defined once and reused, so the create page, task list, gallery and progress
  page finally look like one product.
- **Mobile layout that holds up.** The progress page, task list and create forms were re-checked at
  390×844: no horizontal overflow, readable metrics, and touch-friendly controls.
- **Better with all 22 languages.** Long labels (German, Russian, Turkish) no longer wrap inside
  buttons or stretch the sidebar, decorative emoji were replaced by a consistent icon set, and
  over-long copy truncates with a full-text tooltip instead of breaking the layout.
- **Accessibility.** Visible keyboard focus rings, `aria-current` / `aria-expanded` on navigation and
  collapsible sections, labelled icon buttons, and respect for `prefers-reduced-motion`.

#### Fast retry mode for saturated video queues

- When the upstream video queue is full twice in a row (HTTP 503 · `video_queue_full`), the progress
  page offers a **fast retry** switch.
- You choose **attempts per minute (1–120)** and **duration (1–30 minutes)**; defaults are 30 per
  minute for 3 minutes. The panel shows the remaining time and a live **"sent N times"** counter.
- Fast retries run on their own cadence: they do not consume the regular busy-track budget and do not
  take tokens from the shared video submit bucket, so the chosen rate is actually delivered.
- The mode stops by itself when a submission is accepted, when the duration expires, or when you
  switch it off; the task then continues with the normal retry rhythm.
- The attempt counter keeps moving for every request that was really sent, including non-queue 5xx
  responses, key rotations on HTTP 429 and request timeouts.

#### One-click simple video

- **Defaults that just work.** Simple video now starts from free `agnes-video-2.5-flash`, text to
  video, 5 seconds, 16:9 and 720P: type a prompt, press generate, get a clip. Only the prompt is
  required, both in the UI and through the API.
- **Preset as the single source of truth.** All defaults come from the backend and are exposed via
  `GET /api/models`, so the UI, the API and resumed tasks can no longer disagree. The previous
  "15 / 18 / 20 second" fallbacks that the API rejected are gone.
- **Layered form.** The main area keeps only the prompt, a preset summary and the generate button;
  model, mode, duration, aspect ratio and resolution live under **modify settings**.
- **Native first and last frame.** Keyframe mode submits the frames as `first_frame` / `last_frame`
  instead of squeezing them into the reference-image list, which fixes the framing drift of the old
  fallback. Set `AGNES_KEYFRAME_NATIVE=0` to fall back to the previous behaviour.
- **Multiple reference images.** Reference mode accepts up to 5 images on Flash and up to 8 on 2.5,
  each removable, with `<Picture N>` hints so prompts can refer to a specific image.
- **Audio references.** Reference mode accepts up to 3 public http(s) URLs with `<Audio N>` hints.
- **Paid tiers are hard to pick by accident.** Models are sorted free-first, labelled
  `free` / `paid`, and selecting a paid model asks for confirmation before generating. **Restore
  defaults** always returns to the free tier.
- **Input validation before submit.** Keyframe mode needs at least one frame, reference mode needs at
  least one image or audio URL, and mixing keyframe with reference materials is rejected.

#### External asset mode (experimental)

- Tasks can now be split between this app and an external tool such as Jimeng: the external tool
  generates clips, you import them back, and the project handles concatenation (keeping the original
  audio track) and the final output. Marked as experimental in the UI.

### Refactoring & Optimizations

- Upstream retry behaviour is unified into a two-track model (busy track and fault track) with a
  single place that decides classification and intervals, replacing scattered per-provider retry
  code. Busy waits are capped by attempt count instead of a total time budget.
- Video polling is resilient to key drift: each task records a non-reversible fingerprint of the key
  that submitted it, resolves that key again after a restart, and falls back to a one-off ownership
  probe. Polling also picks between the legacy gateway endpoint and the `v1/videos` REST endpoint per
  key, since domestic and international sites answer on different ones.
- Simple video defaults are defined once on the backend and served to the frontend, removing three
  parallel sets of defaults and the mismatched duration whitelists.

### Bug Fixes

- Fixed the fast retry counter freezing at an old value when retries received non-queue errors or hit
  request timeouts.
- Fixed image-generation tasks showing the video pipeline stages, the wrong result player and 0%
  progress on their detail page.
- Fixed the settings drawer backdrop not darkening the page in the light theme.
- Fixed long localised labels and cached draft values breaking layouts or submitting options the API
  rejects.
- Fixed simple video tasks leaving every timeline stage pending after completion.

---

**Compatibility:** no API breaks and no required configuration changes. Source, Docker and npm
installs upgrade in place; a hard refresh is recommended once because the frontend bundle and layout
changed.
