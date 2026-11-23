# ✨ Core Features

## 🎬 Multiple Creation Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Single-shot clip** (formerly Simple Video) | One prompt → one 4–12 s AI video. Full parameter control (model, generation mode, duration, aspect ratio, seed, negative prompt); supports text-to-video, image-to-video, first/last frames, reference images and reference audio. The one-click preset is free `agnes-video-2.5-flash` / 5 s / 16:9 / 720P. | Quick free AI clips |
| **Multi-shot story** (formerly Creative Video) | Full AI pipeline: idea → story → script → character reference → 1–30 shots → narration → subtitles → final video. | Storytelling, short films |
| **Manuscript video** | Paste a long article or script → auto-split by reading duration → per-segment AI video → unified TTS narration + subtitle overlay → final video. | Explainers, course content, vlogs |
| **Digital anchor** | AI-generated anchor (or your own image) → anchor clip → TTS narration → subtitles → looped concatenation, with `post_stitch` audio or model-native lip-sync audio. | Virtual anchors, product pitches, news |
| **Poetry video** | A poem → per-line scenes (the original verse becomes narration) → t2v clips + recitation + timed subtitles → final video. | Classical poetry, mood films |
| **Simple image** | One Agnes Image API call for text-to-image / image-to-image, including reference images. | Cover art, reference plates |

## 🆓 Completely Free AI Model Chain

All core AI capabilities are **completely free** — no trial period, no watermarks, no token limits:

| Capability | Model | Cost |
|-----------|-------|------|
| Text / Script Generation | `agnes-3.0-flash` | Free |
| Image Generation | `agnes-image-2.5-flash` | Free |
| Video Generation | `agnes-video-2.5-flash` | Free |
| Text-to-Speech Narration | Edge TTS (Microsoft) | Free, no extra API key needed |

All AI API calls share a token-bucket rate limiter (shared bucket defaults to 20 × number of keys × 0.8 requests/min, plus a separate bucket for video submissions), with automatic retries and exponential backoff to ensure stable operation.

## 🎙️ AI Narration & Smart Subtitles

Both Multi-shot story and Manuscript video support:

- **Free TTS narration**: Based on Microsoft Edge TTS, with a dynamic voice catalog grouped by the 22 UI languages (voice preview + cross-language compatibility checks) and adjustable speech rate
- **Word-level fine-grained subtitles**: SRT subtitles generated from TTS word-level timestamps, one entry every 2-3 seconds, with precise audio-video sync
- **Multi-line auto-wrapping**: Long subtitle text is intelligently split into two lines, preferring punctuation break points to prevent screen overflow
- **Fully configurable subtitle style**: Font, color, size, position (top/bottom), stroke, and semi-transparent background
- **Audio-video sync strategy**: All video clips are concatenated first, then audio and subtitles are overlaid as a whole, avoiding cumulative errors from per-segment overlay. TTS output is automatically amplified 1.5× to compensate for Edge TTS's low default volume

## 🎨 Flexible Creative Controls

- **Custom reference images** — Upload character or scene reference images to maintain visual consistency across scenes
- **Custom end frames** — Specify end frame images per scene for precise visual transition control
- **Image-to-image end frames** — Auto-generate scene end frames via img2img from your reference image
- **Three video chaining modes** — `keyframes` (first+last frame interpolation, recommended) / `ti2vid` (inter-scene transition frames) / `none` (independent scenes)
- **Aspect-ratio based output** — 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16 (default 16:9; 2.5 Flash renders at 720P)
- **One-click single-shot clip** — Type a prompt and go: free 2.5 Flash / 5s / 16:9 / 720P preset; paid tiers are labelled and require confirmation
- **Flexible duration** — Custom scene duration
- **Smart manuscript splitting** — Splits by period/question mark/exclamation mark, greedily merges into 5-12 second segments based on reading speed (~4 chars/sec), preserves long sentences, auto-merges short sentences forward

## 🆕 Recent capabilities (v7.6–v8.2)

- **Multi reference images** (v8.1): up to 5 images on Flash / 8 on 2.5, merged from the character plate, style plate, transition stills and per-scene images; per-scene top-ups are possible at the `references` checkpoint.
- **Native first/last frames and reference audio**: the 2.5-series API accepts `first_frame` / `last_frame`, `images[]` and public-URL `audios[]`.
- **Manual mode & external assets**: pause at checkpoints to edit artifacts, or import clips produced elsewhere (Jimeng workflow, experimental) with `concat_videos_keep_audio`.
- **Long task mode** (v8.2): a cumulative busy-queue wait budget (60 minutes by default, 5–480) instead of a fixed retry count; **fast retry** can chain rounds automatically, and provably fatal upstream errors are classified and fail fast.
- **AI agent skill**: one standalone skill installs the service, creates videos, delivers files, diagnoses failures and — with your agreement — fixes a real defect and opens a PR.

## 🔧 Production-Grade Reliability

- **Checkpoint resume** — Automatically resumes from the last checkpoint after interruption; state is persisted after each step, no duplicate API calls
- **Task management** — Create, view, resume, and stop tasks from the Web UI
- **Live progress** — Frontend polls task state (`GET /api/tasks/{id}`) for per-step generation progress (step name, status, percentage, current/total); no WebSocket needed
- **Built-in CJK fonts** — Project ships with Chinese fonts, no garbled characters in subtitle rendering

## 🤖 AI Agent Friendly

Designed specifically for AI coding assistants (Claude, Cursor, QoderWork, etc.), with a complete `AGENTS.md` deployment guide. AI Agents can automatically:

- Check environment (Python 3.10+, ffmpeg)
- Install dependencies and start the server
- Configure API key
- Run 4-layer deployment verification (connectivity → static analysis → endpoint testing → subtitle feature)
- Execute 14-scenario regression test suite

## 🌐 Multilingual Web UI

One-click launch, operate entirely in the browser. Interface available in **22 languages**: 中文, English, Deutsch, Français, Nederlands, Español, Português, Italiano, Русский, 日本語, 한국어, Bahasa Melayu, Bahasa Indonesia, العربية, Türkçe, Tiếng Việt, ไทย, Tagalog, हिन्दी, فارسی, বাংলা, اردو. The voice catalog and subtitle font fallback cover the same 22 languages (including Arabic / Persian / Urdu RTL ligature shaping and Thai / Devanagari / Bengali font fallback).

## 🎬 Three AI Video Chaining Modes

| Mode | How It Works | Best For |
|------|-------------|----------|
| **keyframes** | Specify first + last frame per scene; server auto-interpolates transitions | Smooth transitions (recommended) |
| **ti2vid** | Last frame of previous scene → img2img transition → first frame of next scene | Visual continuity between scenes |
| **none** | All scenes share the same reference image, independent of each other | Fast output, independent scenes |
