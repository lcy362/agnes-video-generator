# Release v8.2.1 — Arabic Subtitle Rendering and Guide Corrections

> Release date: 2026-11-23

## Overview

v8.2.1 is a small maintenance release. It renders Arabic subtitles with HarfBuzz-based
**khatt** shaping so letters join correctly and read right-to-left on every Pillow build, keeps
tall multi-line subtitles inside the frame, and corrects the published API reference and guides.
Other scripts keep the existing moviepy text path, and no API or configuration changes are
required.

## Usage

Source:

```bash
git pull
pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:8.2.1` (then `docker compose up -d` to
recreate the container).

npm users: `npx free-short-video` or `npm install -g free-short-video`; the launcher reinstalls
dependencies when `requirements.txt` changes.

### Upgrading notes

- Source installs must reinstall dependencies: `khatt[video]>=0.10.0,<1.0.0` replaces
  `arabic-reshaper` + `python-bidi`, and the moviepy floor moves to 2.2.1. Docker and npm installs
  handle this automatically.
- If khatt cannot be installed, Arabic lines fall back to moviepy's TextClip with a single warning
  (letters may not join or may read in the wrong direction); other languages are unaffected.
- No API or configuration changes. Existing API keys, workspaces, task state files and checkpoints
  keep working, and unfinished tasks can resume.

## What's New

### Features & Improvements

#### Correct Arabic subtitle shaping

- Arabic lines are now drawn by `khatt.video.TextClip` (HarfBuzz shaping) instead of pre-shaped
  text passed to moviepy. Letters join and read right-to-left regardless of whether Pillow was
  built with Raqm, tashkeel (harakat) is preserved, bracket glyphs render instead of tofu, and the
  Pillow 11+ bottom-clipping issue is gone. Other scripts use the existing moviepy path unchanged.
- khatt is resolved lazily on the first Arabic line; if it is missing, the app logs one warning and
  falls back to moviepy instead of raising an ImportError for every subtitle line.

### Bug Fixes

- **Tall subtitles stay inside the frame.** Multi-line subtitles — especially two-line Arabic,
  which measured about 131 px — were clamped only by a fixed 100 px bottom margin, so the last
  lines were cut off. Vertical clamping now also accounts for the clip's own height; single-line
  clips keep their previous position, and the position-conflict fallback uses the same rule.
- **API reference corrected to the 2.5-series format.** Examples now use
  `model: agnes-video-2.5-flash`, `mode` (`text` / `keyframe` / `reference`), `seconds` (4–12),
  `size` (720P) and `aspect_ratio`, and polling passes `model_name`. Retired
  `agnes-video-v2.0` / `agnes-image-2.1-flash` examples were removed.
- **Local configuration example fixed.** `POST /api/config` takes form data
  (`-F 'api_key=...'`); the previous JSON-body example returned a validation error.
- **Task names and free-tier limits aligned with the UI.** Guides now say Single-shot clip /
  Multi-shot story, 4–12 s and 720P instead of the retired names and 20-second claims.
- **Broken documentation links repaired**, including the Chinese/English quick-start cross-links
  and the FAQ's README comparison link.

---

**Compatibility:** no API or configuration changes. The Arabic rendering path adds one optional
dependency and moves the moviepy floor to 2.2.1; source installs must reinstall dependencies, while
Docker and npm installs do it automatically. Without khatt, Arabic subtitles degrade to the
previous renderer and other languages are unaffected.
