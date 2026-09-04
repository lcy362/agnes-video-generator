# ✨ Core Features

## 🎬 Multiple Creation Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Simple Video** | Single prompt → single AI video. Full control over all parameters (generation mode, duration, resolution, seed, negative prompt). Also supports image-to-video and keyframes mode. | Quick single-clip AI video |
| **Creative Video** | Full AI pipeline: idea → story → script → character reference → multi-scene video → narration → subtitles → final output. 10-step pipeline, fully automated. | Storytelling, creative videos |
| **Manuscript Video** | Paste a long article or script → auto-split by reading duration → per-segment AI video → unified TTS narration + subtitle overlay → final output. 5-step pipeline. | Explainers, course content, vlogs |
| **Digital Anchor** | AI-generated digital anchor (or upload custom image) → dynamic anchor clip → TTS narration → subtitle positioning → looped concatenation. Optional reference image for appearance consistency. | Virtual anchors, product presentations, news broadcasts |

## 🆓 Completely Free AI Model Chain

All core AI capabilities are **completely free** — no trial period, no watermarks, no token limits:

| Capability | Model | Cost |
|-----------|-------|------|
| Text / Script Generation | `agnes-2.5-flash` | Free |
| Image Generation | `agnes-image-2.5-flash` | Free |
| Video Generation | `agnes-video-v2.0` | Free |
| Text-to-Speech Narration | Edge TTS (Microsoft) | Free, no extra API key needed |

All AI API calls share a global token bucket rate limiter (16 requests/min), with automatic retries and exponential backoff to ensure stable operation.

## 🎙️ AI Narration & Smart Subtitles

Both Creative Video and Manuscript Video support:

- **Free TTS narration**: Based on Microsoft Edge TTS, offering 4 Chinese voice roles (gentle female, steady male, lively female, young male) with adjustable speech rate (-30% to +30%)
- **Word-level fine-grained subtitles**: SRT subtitles generated from TTS word-level timestamps, one entry every 2-3 seconds, with precise audio-video sync
- **Multi-line auto-wrapping**: Long subtitle text is intelligently split into two lines, preferring punctuation break points to prevent screen overflow
- **Fully configurable subtitle style**: Font, color, size, position (top/bottom), stroke, and semi-transparent background
- **Audio-video sync strategy**: All video clips are concatenated first, then audio and subtitles are overlaid as a whole, avoiding cumulative errors from per-segment overlay. TTS output is automatically amplified 2.5× to compensate for Edge TTS's low default volume

## 🎨 Flexible Creative Controls

- **Custom reference images** — Upload character or scene reference images to maintain visual consistency across scenes
- **Custom end frames** — Specify end frame images per scene for precise visual transition control
- **Image-to-image end frames** — Auto-generate scene end frames via img2img from your reference image
- **Three video chaining modes** — `keyframes` (first+last frame interpolation, recommended) / `ti2vid` (inter-scene transition frames) / `none` (independent scenes)
- **Multiple resolutions** — Portrait 9:16 (768×1152), Landscape 16:9 (1152×768), Square 1:1 (1024×1024)
- **Flexible duration** — Custom scene duration
- **Smart manuscript splitting** — Splits by period/question mark/exclamation mark, greedily merges into 5-12 second segments based on reading speed (~4 chars/sec), preserves long sentences, auto-merges short sentences forward

## 🔧 Production-Grade Reliability

- **Checkpoint resume** — Automatically resumes from the last checkpoint after interruption; state is persisted after each step, no duplicate API calls
- **Task management** — Create, view, resume, and stop tasks from the Web UI
- **Real-time progress** — WebSocket pushes per-step generation progress (step name, status, percentage, current/total)
- **Built-in CJK fonts** — Project ships with Chinese fonts, no garbled characters in subtitle rendering

## 🤖 AI Agent Friendly

Designed specifically for AI coding assistants (Claude, Cursor, QoderWork, etc.), with a complete `AGENTS.md` deployment guide. AI Agents can automatically:

- Check environment (Python 3.10+, ffmpeg)
- Install dependencies and start the server
- Configure API key
- Run 4-layer deployment verification (connectivity → static analysis → endpoint testing → subtitle feature)
- Execute 10-scenario regression test suite

## 🌐 Multilingual Web UI

One-click launch, operate entirely in the browser. Interface available in **13 languages**: 中文, English, Deutsch, Français, Nederlands, Español, Português, Italiano, Русский, 日本語, 한국어, Bahasa Melayu, Bahasa Indonesia.

## 🎬 Three AI Video Chaining Modes

| Mode | How It Works | Best For |
|------|-------------|----------|
| **keyframes** | Specify first + last frame per scene; server auto-interpolates transitions | Smooth transitions (recommended) |
| **ti2vid** | Last frame of previous scene → img2img transition → first frame of next scene | Visual continuity between scenes |
| **none** | All scenes share the same reference image, independent of each other | Fast output, independent scenes |
