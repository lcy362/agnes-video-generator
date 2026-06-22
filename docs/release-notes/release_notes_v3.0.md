# Release v3.0.0 — 字幕与旁白独立控制 + AI 智能字幕 + 数字人口播 + 图片生成

> Release date: 2026-06-21

## Overview

v3.0.0 is a major feature release that introduces **four significant capabilities**: independent subtitle/narrator control, AI-powered subtitle styling, a new "Digital Anchor" video task type, and simple image generation. This release also delivers extensive subtitle rendering improvements, system prompt support, and stability fixes.

---

## Phase 1: Subtitle & Narrator Independent Control

Subtitle and narrator (TTS) configurations are now fully decoupled:

- **New `SubtitleConfig`** — elevated to a peer-level config alongside `AudioConfig`, each with its own `enabled` toggle
- **Pipeline step split** — `_step_audio_subtitle` replaced by independent `_step_audio` + `_step_subtitle` steps in both creative and manuscript pipelines
- **Four combination modes** — narrator+subtitle, narrator-only, subtitle-only, and silent (no audio, no subtitle)
- **Backward compatibility** — `TaskManager.load()` auto-migrates legacy `audio_config.subtitle_style` to the new `SubtitleConfig`
- **API changes** — new `subtitle_enabled` parameter on creative and manuscript task endpoints

---

## Phase 2: AI-Powered Subtitle Styling (LLM Mode)

LLM decides per-subtitle position, color, and font size:

- **`style_mode`** — `"fixed"` (default, global style) or `"llm"` (AI-driven per-subtitle styling)
- **`style_hints`** — user-provided natural language guidance for LLM styling decisions (e.g., "emphasis in red, summaries in yellow")
- **`generate_subtitle_styles()`** — new Screenwriter method that sends all subtitle entries to LLM in a single call, returns position/color/fontsize JSON
- **Sidecar JSON format** — `subtitle_styles.json` with per-entry overrides, falling back to global `SubtitleStyle` defaults
- **Concatenator integration** — `_parse_srt_to_clips` reads styles JSON, applies per-subtitle TextClip rendering

### Subtitle Rendering Improvements

- **Multi-line display** — adjacent subtitle segments overlap by 0.3s for smoother reading flow
- **Overlap boost** — 0.8s subtitle overlap for better visibility during transitions
- **Two-pass `extend-end`** — refined subtitle timing extension algorithm
- **Overflow protection** — safe-margin clamping prevents subtitles from exceeding video bounds
- **Position diversity** — LLM prompt enforces vertical zone partitioning for varied placement
- **Smart mode refinement** — arbitrary positioning, scene-aware granular splitting, emphasis duration boost

---

## Phase 3: Digital Anchor (数字人口播)

New task type `anchor` — AI-generated digital presenter with TTS narration:

- **`AnchorVideoTask`** — new Pydantic model with 7-step pipeline
- **Two image generation paths** — text-to-image (t2i) or image-to-image (i2i) with user-uploaded reference photo
- **Segmented video generation (方案 B)** — manuscript text split into 5-12s paragraphs, each generating a unique i2v clip with different gestures/expressions
- **`generate_anchor_clip_prompt()`** — LLM generates per-paragraph English dynamic prompts with lip-sync and gesture descriptions
- **TTS + subtitle overlay** — unified audio generation with LLM-driven subtitle positioning optimized for anchor-person framing
- **API endpoint** — `POST /api/tasks/anchor` with 14 parameters including anchor prompt, reference image, script text, and audio/subtitle settings
- **Audio source options** — model-generated audio or post-concatenation audio attachment

---

## Simple Image Generation

New fifth tab for standalone image generation:

- **`SimpleImageTask`** — lightweight task model for single image generation via Agnes Image API
- **`/api/image/{id}`** endpoint — retrieve generated image results
- **System prompt support** — optional system prompt input for both simple video and image tasks, prepended to final prompt
- **Frontend** — dedicated tab with form controls and 7-language i18n

---

## Stability & Bug Fixes

| Fix | Description |
|-----|-------------|
| `subprocess.run` SIGTTIN | Added `stdin=DEVNULL` to prevent background process suspension |
| SilentTTS return type | Fixed `SilentTTSEngine.generate()` returning `None` instead of `{}` in subtitle-only mode |
| SRT timing accuracy | SRT timeline now based on actual audio duration instead of estimated video duration |
| Image error logging | Detailed error output (HTTP status + response body + traceback) on image generation failure |
| UTF-8 encoding | Defensive UTF-8 encoding fixes in anchor pipeline |
| TTS duration ordering | TTS now runs before clip generation to obtain actual audio duration |

---

## Documentation

- `docs/plans-v3.0/feature_plan.md` — comprehensive v3.0 feature plan (3 phases + implementation tracking)
- `README.md` / `README_ZH.md` — rewritten with updated feature highlights and quick-start guide
- `AGENTS.md` — synced anchor task type, regression test scenarios
- Plans directory restructured into versioned folders (`plans-v1.0/`, `plans-v2.0/`, `plans-v3.0/`)

---

## Stats

```
35 files changed, 4,398 insertions(+), 1,157 deletions(-)
```

### Key New/Modified Files

| File | Description |
|------|-------------|
| `core/pipelines/anchor_video.py` | **New** — 7-step Anchor Pipeline with segmented i2v generation |
| `models/task.py` | SubtitleConfig, AnchorVideoTask, SimpleImageTask, style_mode/style_hints |
| `core/screenwriter.py` | generate_subtitle_styles, generate_anchor_clip_prompt, common subtitle generation |
| `core/compositor/concatenator.py` | Per-subtitle styling, anchor composite, overlap improvements |
| `core/audio/subtitle.py` | Multi-line rendering, overlap timing, overflow protection |
| `core/pipelines/creative_video.py` | Step split (audio + subtitle), LLM style integration |
| `core/pipelines/manuscript_video.py` | Step split, LLM style integration |
| `server.py` | Anchor endpoint, image endpoint, subtitle_enabled param, system prompt |
| `static/index.html` | 5th tab (image), anchor tab, subtitle/audio independent controls, i18n |
| `scripts/regression_runner.py` | Streamlined scenarios + anchor regression tests |

---

## Upgrade Notes

From v2.2:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

**Breaking change**: `AudioConfig.subtitle_style` has been removed. Legacy task states are auto-migrated on load. No manual intervention required.
