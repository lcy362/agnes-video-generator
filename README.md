# 🎬 Agnes Video Generator — Completely Free AI Video Generator

[![中文](https://img.shields.io/badge/CN-中文-red)](/README_ZH.md)

> **Completely free AI video generator** — Built on Agnes AI's free models, no subscription, no high-end GPU, no usage limits. Type in a text idea and automatically generate multi-scene AI videos with narration and subtitles. Supports text-to-video, image-to-video, keyframes animation, digital anchor, and more. All AI compute runs in the cloud — a regular laptop is all you need.

> "The solution is not to suppress AI, but to make it a more equitable capability, so that everyone knows how to create more with AI. This is a very important vision for our company — to make world-class AI belong to everyone. What we can do may be insignificant, but this vision is very long-term and enduring."
>
> — Bruce Yang, Founder of Agnes AI

**[🌐 Official Website](https://video.lichuanyang.top)** | **[📝 Blog (中文)](https://lichuanyang.top/posts/22470/)** | **[📝 Blog (English)](https://lichuanyang.top/en/posts/22470/)**

## 🎥 Demo

### 1. Creative Video — No Narration

> A dark-twist fairytale — *The Frog Prince*, 5 scenes, keyframes chaining, fully auto-generated.

[![The Frog Prince — Demo Video](https://img.shields.io/badge/▶%20Watch%20Demo-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/L4F6KdGnD6U/)

### 2. Creative Video — With TTS Narration

> Same *Frog Prince* story, now with AI-generated TTS narration and auto subtitles.

[![The Frog Prince with Narration — Demo](https://img.shields.io/badge/▶%20Watch%20Demo-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/l2FlbF1Jdz0/)

### 3. Manuscript Video — Text-to-Video

> Paste a long article or script → auto-split into segments → AI video per segment → unified TTS narration + subtitles → final video.

[![Manuscript Video Demo](https://img.shields.io/badge/▶%20Watch%20Demo-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/eSGE9KENWVU/)

<sub>Click to watch on Douyin</sub>

## Why Agnes Video Generator?

Making AI videos today has an absurdly high barrier. Overseas services like Runway and Pika charge monthly subscriptions of tens of dollars. Domestic platforms like Jimeng and Keling charge by the second once their free quotas run out. Want to run open-source models locally? A GPU capable of video generation easily costs over ten thousand RMB. For most people who want to try AI video creation, the door is essentially closed.

We believe what Bruce Yang said — AI should be a more equitable capability. World-class AI should belong to everyone, not just those who can afford the bill.

To be honest, Agnes's video model isn't perfect yet. The generated frames are sometimes unstable, and complex actions occasionally deform. But it is **completely free with no usage limits**, and it iterates fast. We choose to grow with it rather than wait for a "perfect" commercial solution. If you share this mindset, then this project is for you — all you need is a free [Agnes AI](https://platform.agnes-ai.com) API key and an ordinary computer that can run Python to start creating AI videos at zero cost.

## ✨ Core Features

### 🎬 Multiple Creation Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Simple Video** | Single prompt → single AI video. Full control over all parameters (generation mode, duration, resolution, seed, negative prompt). Also supports image-to-video and keyframes mode. | Quick single-clip AI video |
| **Creative Video** | Full AI pipeline: idea → story → script → character reference → multi-scene video → narration → subtitles → final output. 10-step pipeline, fully automated. | Storytelling, creative videos |
| **Manuscript Video** | Paste a long article or script → auto-split by reading duration → per-segment AI video → unified TTS narration + subtitle overlay → final output. 5-step pipeline. | Explainers, course content, vlogs |
| **Digital Anchor** | AI-generated digital anchor (or upload custom image) → dynamic anchor clip → TTS narration → subtitle positioning → looped concatenation. Optional reference image for appearance consistency. | Virtual anchors, product presentations, news broadcasts |

### 🆓 Completely Free AI Model Chain

All core AI capabilities are **completely free** — no trial period, no watermarks, no token limits:

| Capability | Model | Cost |
|-----------|-------|------|
| Text / Script Generation | `agnes-2.0-flash` | Free |
| Image Generation | `agnes-image-2.1-flash` | Free |
| Video Generation | `agnes-video-v2.0` | Free |
| Text-to-Speech Narration | Edge TTS (Microsoft) | Free, no extra API key needed |

All AI API calls share a global token bucket rate limiter (16 requests/min), with automatic retries and exponential backoff to ensure stable operation.

### 🎙️ AI Narration & Smart Subtitles

Both Creative Video and Manuscript Video support:

- **Free TTS narration**: Based on Microsoft Edge TTS, offering 4 Chinese voice roles (gentle female, steady male, lively female, young male) with adjustable speech rate (-30% to +30%)
- **Word-level fine-grained subtitles**: SRT subtitles generated from TTS word-level timestamps, one entry every 2-3 seconds, with precise audio-video sync
- **Multi-line auto-wrapping**: Long subtitle text is intelligently split into two lines, preferring punctuation break points to prevent screen overflow
- **Fully configurable subtitle style**: Font, color, size, position (top/bottom), stroke, and semi-transparent background
- **Audio-video sync strategy**: All video clips are concatenated first, then audio and subtitles are overlaid as a whole, avoiding cumulative errors from per-segment overlay. TTS output is automatically amplified 2.5× to compensate for Edge TTS's low default volume

### 🎨 Flexible Creative Controls

- **Custom reference images** — Upload character or scene reference images to maintain visual consistency across scenes
- **Custom end frames** — Specify end frame images per scene for precise visual transition control
- **Image-to-image end frames** — Auto-generate scene end frames via img2img from your reference image
- **Three video chaining modes** — `keyframes` (first+last frame interpolation, recommended) / `ti2vid` (inter-scene transition frames) / `none` (independent scenes)
- **Multiple resolutions** — Portrait 9:16 (768×1152), Landscape 16:9 (1152×768), Square 1:1 (1024×1024)
- **Flexible duration** — Custom scene duration
- **Smart manuscript splitting** — Splits by period/question mark/exclamation mark, greedily merges into 5-12 second segments based on reading speed (~4 chars/sec), preserves long sentences, auto-merges short sentences forward

### 🔧 Production-Grade Reliability

- **Checkpoint resume** — Automatically resumes from the last checkpoint after interruption; state is persisted after each step, no duplicate API calls
- **Task management** — Create, view, resume, and stop tasks from the Web UI
- **Real-time progress** — WebSocket pushes per-step generation progress (step name, status, percentage, current/total)
- **Built-in CJK fonts** — Project ships with Chinese fonts, no garbled characters in subtitle rendering

### 🤖 AI Agent Friendly

Designed specifically for AI coding assistants (Claude, Cursor, QoderWork, etc.), with a complete `AGENTS.md` deployment guide. AI Agents can automatically:

- Check environment (Python 3.10+, ffmpeg)
- Install dependencies and start the server
- Configure API key
- Run 4-layer deployment verification (connectivity → static analysis → endpoint testing → subtitle feature)
- Execute 10-scenario regression test suite

### 🌐 Multilingual Web UI

One-click launch, operate entirely in the browser. Interface available in **7 languages**: 中文, English, Русский, 日本語, 한국어, Bahasa Melayu, Bahasa Indonesia.

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- ffmpeg (for video concatenation and audio processing)

That's it. No GPU, no large RAM, a regular laptop is all you need.

### Option A: Manual Setup

**Step 1 — Clone & Launch**

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

The script automatically creates a virtual environment, installs dependencies, and opens `http://localhost:8765` in your browser. You can also start manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

**Step 2 — Configure API Key**

Get a free API key from [Agnes AI](https://platform.agnes-ai.com), then choose one of two ways:

```bash
# Way 1: Environment variable
export AGNES_API_KEY="your-api-key"

# Way 2: Via API (same as entering it in the Web UI)
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "your-api-key"}'
```

**Step 3 — Create Your First Video**

Open `http://localhost:8765`, choose a video mode (Simple / Creative / Manuscript / Anchor / Image), enter your idea, and click "Start Generating".

### Option B: AI Agent Assisted Setup

This project is designed for AI coding assistants. First, download the code and prepare your API key:

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
```

Then tell your agent:

> "Read the AGENTS.md in this project, install dependencies, configure the API key `<your-key>`, and start the server."

The agent will read `AGENTS.md` (a comprehensive deployment guide) and handle: environment checks (Python 3.10+, ffmpeg), `pip install`, server launch, and API key configuration. After startup, you can also ask the agent to verify the deployment:

> "Run the deployment verification checks."

The agent will execute the 4-layer checklist from `AGENTS.md` (connectivity → static analysis → endpoint testing → subtitle feature) and report results.

## 📖 Usage

### 1. Configure API Key

Enter your free [Agnes AI](https://platform.agnes-ai.com) API key at the top of the page and save it. Or set it via environment variable:

```bash
export AGNES_API_KEY="your-api-key"
```

### 2. Choose a Video Mode

#### Simple Video

Quick single-clip generation with full parameter control:

| Field | Description |
|-------|-------------|
| Prompt | Describe the AI video scene in natural language |
| Generation Mode | Text-to-Video / Image-to-Video / Text+Image / Keyframes |
| Resolution | Portrait 9:16 / Landscape 16:9 / Square 1:1 |
| Duration | 5s / 10s / 15s / 18s / 20s |
| Reference Image | Optional upload for image-to-video modes |
| End Frame Image | Optional end frame for keyframes mode |

#### Creative Video

AI-driven multi-scene storytelling:

| Field | Description | Required |
|-------|-------------|----------|
| Idea | Describe your AI video concept | Yes |
| User Requirements | Scene count, duration, and other constraints | - |
| Visual Style | Cinematic realism, anime, cyberpunk, etc. | - |
| Chaining Mode | keyframes (recommended) / ti2vid / none | - |
| Narration | Enable/disable TTS narration, choose voice and speed | - |
| Subtitle Style | Font, color, size, position, stroke, background | - |
| Reference Image | Optional character reference for visual consistency | - |
| End Frames | Custom or auto-generated per-scene end frames | - |

#### Manuscript Video

Long-form text to narrated video:

| Field | Description | Required |
|-------|-------------|----------|
| Manuscript Text | Paste your full article, script, or narration | Yes |
| Resolution | Portrait / Landscape / Square | - |
| Narration | Voice role and speech rate | - |
| Subtitle Style | Full subtitle customization | - |

> **Note**: Segment duration is auto-calculated based on text length (~4 chars/sec, 5–12s per segment) — no manual setting needed.

#### Digital Anchor

| Field | Description | Required |
|-------|-------------|----------|
| Anchor Script | Enter the text the anchor will say | Yes |
| Anchor Image | AI-generated or upload custom reference image | - |
| Resolution | Portrait / Landscape / Square | - |
| Narration | Voice role and speech rate | - |
| Subtitle Style | Full subtitle customization | - |

### 3. Click "Start Generating"

The progress panel shows real-time generation status for each step. For Creative Video: Init → Image Analysis → Story → Character Reference → Script → Narration → End Frame Prompts → End Frame Generation → Video Generation → Audio & Subtitles → Concatenation.

### 4. Checkpoint Resume & Task Management

If the server is interrupted, restart it and find the incomplete task in the "Task List" tab. Click "Resume" to continue from the last checkpoint. Running tasks can also be stopped and resumed later.

## 🏗️ Project Structure

```
agnes-video-generator/
├── start.sh                          # One-click launch script
├── requirements.txt                  # Python dependencies
├── server.py                         # FastAPI server (REST + WebSocket)
├── static/
│   └── index.html                    # Frontend SPA — 5 task tabs, 7 languages (Tailwind CSS)
├── core/
│   ├── config.py                     # API key, font resolution, default configs
│   ├── screenwriter.py               # Screenwriter Agent (LLM-powered story/script/narration)
│   ├── task_manager.py               # Task state persistence & checkpoint resume
│   ├── api/
│   │   ├── agnes_chat.py             # LLM Chat API (agnes-2.0-flash)
│   │   ├── agnes_image.py            # Image generation API (agnes-image-2.1-flash / 2.0-flash)
│   │   ├── agnes_video.py            # Video generation API (agnes-video-v2.0)
│   │   └── rate_limiter.py           # Global token bucket rate limiter (16 requests/min)
│   ├── audio/
│   │   ├── tts.py                    # Edge TTS engine + silent fallback engine
│   │   └── subtitle.py               # SRT generation (fine-grained word-level) + overlay
│   ├── compositor/
│   │   ├── concatenator.py           # Video concatenation + audio/subtitle overlay
│   │   └── processor.py              # Video resize, frame extraction, freeze, silence gen
│   └── pipelines/
│       ├── simple_video.py           # Pipeline: Simple Video
│       ├── creative_video.py         # Pipeline: Creative Video (10-step)
│       ├── manuscript_video.py       # Pipeline: Manuscript Video (5-step)
│       └── anchor_video.py           # Pipeline: Digital Anchor
├── models/
│   └── task.py                       # Data models (5 task types, configs, requests)
├── resource/
│   └── fonts/                        # Built-in CJK fonts for subtitle rendering
├── utils/
│   ├── image.py                      # Image download / base64 conversion
│   └── video.py                      # Video download
├── scripts/
│   └── regression_runner.py          # 10-scenario regression test suite
└── docs/
    ├── regression_test_plan.md       # Regression test plan
    ├── plans-v1.0/                   # v1.0 design & planning docs
    ├── plans-v2.0/                   # v2.0 review & optimization docs
    └── plans-v3.0/                   # v3.0 feature planning docs
```

## 🔧 Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend | Python FastAPI | Async + WebSocket |
| Frontend | HTML/CSS/JS + Tailwind CSS CDN | Zero build steps, single-file SPA |
| LLM | Agnes Chat (`agnes-2.0-flash`) | Free — story, script, narration generation |
| Image AI | `agnes-image-2.1-flash` (t2i) / `agnes-image-2.0-flash` (i2i) | Free — reference images, end frames, standalone image generation |
| Video AI | `agnes-video-v2.0` | Free — text-to-video, image-to-video, keyframes |
| TTS | Edge TTS (Microsoft) | Free — 4 Chinese voices, no extra API key needed |
| Subtitles | moviepy + srt | Fine-grained word-level SRT, multi-line wrapping |
| Video Processing | moviepy + ffmpeg | Concatenation, subtitle overlay, audio mixing |

## 🎬 Three AI Video Chaining Modes

| Mode | How It Works | Best For |
|------|-------------|----------|
| **keyframes** | Specify first + last frame per scene; server auto-interpolates transitions | Smooth transitions (recommended) |
| **ti2vid** | Last frame of previous scene → img2img transition → first frame of next scene | Visual continuity between scenes |
| **none** | All scenes share the same reference image, independent of each other | Fast output, independent scenes |

## 📋 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve Web UI |
| GET | `/api/config` | Get API key (masked) |
| POST | `/api/config` | Save API key |
| DELETE | `/api/config` | Delete API key |
| GET | `/api/voices` | List available TTS voices |
| POST | `/api/image/generate` | Image generation |
| GET | `/api/image/{task_id}` | Query image task status |
| POST | `/api/tasks/simple` | Create simple video task |
| POST | `/api/tasks/creative` | Create creative video task |
| POST | `/api/tasks/manuscript` | Create manuscript video task |
| POST | `/api/tasks/anchor` | Create digital anchor task |
| POST | `/api/tasks` | Generic task creation (backward-compatible) |
| GET | `/api/tasks` | List all tasks (with type badges) |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/tasks/{id}/resume` | Resume an interrupted task |
| POST | `/api/tasks/{id}/stop` | Stop a running task |
| GET | `/api/video/{id}` | Download/stream final video |
| WS | `/ws/{id}` | WebSocket real-time progress |

## ⚠️ Important Notes

This project is in early stage — corner cases may not be fully handled. Recommended workflow:

1. Fill in your idea on the page and submit an AI video task
2. Watch the **console logs** (the terminal running `server.py`) and be patient
3. All key operations are logged for easy debugging

### Log Reference

All important operations are logged to the server console:

| Prefix | Module |
|--------|--------|
| `[Startup]` | Server startup, stale task reset |
| `[WS]` | WebSocket connect/disconnect |
| `[Resume]` / `[Stop]` | Task resume/stop |
| `[Pipeline]` / `[Simple]` / `[Manuscript]` | Pipeline step execution |
| `[TTS]` / `[Subtitle]` | Audio and subtitle generation |
| `[Compositor]` | Video concatenation and processing |
| `[AgnesImage]` / `[AgnesVideo]` / `[AgnesChat]` | AI API calls |
| `[RateLimiter]` | Global rate limiter |
| `[TaskManager]` | Task state persistence |
| `[Screenwriter]` | Screenwriter Agent |

### Output Directory

All AI video task artifacts are stored under `.working_dir/{timestamp}_{task_id}/`:

```
.working_dir/{timestamp}_{task_id}/
├── task_state.json              # Task state (required for checkpoint resume)
├── final_video.mp4              # Final video with narration + subtitles
├── story.txt                    # AI-generated story (creative mode)
├── script.json                  # Scene script (JSON format)
├── narration.mp3                # Combined TTS narration audio
├── narration.srt                # Combined subtitle file
├── scene_0/
│   ├── video.mp4                # Scene 0 AI video
│   ├── end_frame.png            # Scene 0 end frame
│   └── task.json                # Video generation task ID
├── scene_1/
│   └── ...
└── scene_2/
    └── ...
```

## 🙏 Acknowledgments

This project is built upon the following open-source projects:

- [ViMax](https://github.com/HKUDS/ViMax) — AI video generation framework by HKU Data Science Lab
- [vimax-agnes](https://github.com/easyeye163/vimax-agnes) — Agnes AI adaptation based on ViMax

Special thanks to [Agnes AI](https://platform.agnes-ai.com) for providing **completely free**, high-quality AI model APIs (text, image, and video generation) — this project runs at absolute zero cost thanks to their generosity.

## Feedback & Contributing

Bug reports and feature suggestions are welcome via [GitHub Issues](../../issues).

## 📄 License

MIT

---

**Keywords**: free AI video generator, AI video generation tool, text to video AI, free AI video maker, AI video creator, open source video generator, Agnes AI, text-to-video, image-to-video, keyframes video, AI narration, auto subtitles, multi-scene video, zero cost AI video, no subscription AI video tool, digital anchor
