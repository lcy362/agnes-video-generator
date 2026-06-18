# 🎬 Agnes Video Generator — Completely Free AI Video Generator

[![中文](https://img.shields.io/badge/CN-中文-red)](/README_ZH.md)

> **100% free AI video generator** — no subscription, no credit card, no usage limits. Powered by Agnes AI's free models, this open-source tool turns text ideas into narrated, subtitled multi-scene AI videos with a single click. Supports text-to-video, image-to-video, and keyframes generation.

Built upon [ViMax](https://github.com/HKUDS/ViMax) and [vimax-agnes](https://github.com/easyeye163/vimax-agnes), this project transforms command-line AI video generation into an all-in-one free video creation platform with a modern Web UI.

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

Every AI video tool on the market charges per second of generated video. Agnes Video Generator is different — it is **completely free to use**, from text generation to image synthesis to video rendering. The only thing you need is a free API key from [Agnes AI](https://platform.agnes-ai.com), and you can generate unlimited AI videos at zero cost.

This makes it ideal for creators, educators, marketers, and developers who want to experiment with AI video generation without worrying about billing.

## ✨ Features

### 🆓 Zero-Cost AI Video Generation

All four core AI capabilities are **completely free** — no trial period, no watermarks, no token limits:

| Capability | Model | Cost |
|-----------|-------|------|
| Text / Script Generation | `agnes-2.0-flash` | Free |
| Image Generation | `agnes-image-2.1-flash` | Free |
| Video Generation | `agnes-video-v2.0` | Free |
| Text-to-Speech Narration | Edge TTS (Microsoft) | Free |

### 🎬 Three Video Creation Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **Simple Video** | Single prompt → single AI video. Full control over all parameters (mode, duration, resolution, seed, negative prompt). | Quick one-shot AI video clips |
| **Creative Video** | AI-driven full pipeline: idea → story → script → character reference → multi-scene video → narration → subtitles → final output | Storytelling, short films |
| **Manuscript Video** | Paste a long article or script → auto-split into segments → per-segment AI video → unified TTS narration + subtitle overlay → final video | Explainers, course content, vlogs |

### 🎙️ AI Narration & Subtitles

- **Free TTS narration** via Microsoft Edge TTS — 4 Chinese voice roles (gentle female, steady male, lively female, young male) with adjustable speech rate (-30% to +30%)
- **Auto-generated subtitles** with fine-grained word-level timestamps (every 2-3 seconds) for perfect sync
- **Multi-line subtitle wrapping** — long subtitle text automatically splits into two lines with smart punctuation-aware break points, preventing screen overflow
- **Fully configurable subtitle style** — font, color, size, position (top/bottom), stroke, and semi-transparent background

### 🌐 Multilingual Web UI

One-click launch, operate entirely in the browser. Available in **7 languages**: Chinese, English, Russian, Japanese, Korean, Malay, and Indonesian.

### 🎨 Advanced Creative Controls

- **Custom Reference Image** — Upload a character reference image for consistent appearance across all scenes
- **Custom End Frames** — Specify end frame images per scene for precise visual control
- **Image-to-Image End Frames** — Auto-generate scene end frames via img2img from your reference image
- **Three Video Chaining Modes** — `keyframes` (recommended) / `ti2vid` (transition frames) / `none` (independent scenes)
- **Multiple Resolutions** — Portrait 9:16 (768×1152), Landscape 16:9 (1152×768), Square 1:1 (1024×1024)
- **Flexible Durations** — 5s, 10s, 15s, 18s, or 20s per scene

### 🔧 Production Features

- **Checkpoint Resume** — Interrupted tasks auto-resume from the last checkpoint, no duplicate API calls
- **Task Management** — Create, view, resume, and stop tasks from the Web UI
- **Real-Time Progress** — WebSocket-powered live progress updates for every generation step
- **In-Page API Key Config** — Configure your Agnes API key directly in the browser, no config files
- **AI Agent Friendly** — Designed for easy setup and operation by AI coding assistants

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- ffmpeg (for video concatenation and audio processing)

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

Open `http://localhost:8765`, choose a video mode (Simple / Creative / Manuscript), enter your idea, and click "Start Generating".

### Option B: AI Agent Assisted Setup

This project is designed for easy deployment by AI coding assistants (Claude, Cursor, QoderWork, etc.). First, download the code and prepare your API key:

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
```

Then tell your agent:

> "Read the AGENTS.md in this project, install dependencies, configure the API key `<your-key>`, and start the server."

The agent will read `AGENTS.md` — a comprehensive deployment guide — and handle: environment checks (Python 3.10+, ffmpeg), `pip install`, server launch, and API key configuration. After startup, you can also ask the agent to verify the deployment:

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
| Mode | Text-to-Video / Image-to-Video / Text+Image / Keyframes |
| Resolution | Portrait 9:16 / Landscape 16:9 / Square 1:1 |
| Duration | 5s / 10s / 15s / 18s / 20s |
| Reference Image | Optional upload for image-to-video modes |
| End Frame Image | Optional end frame for keyframes mode |

#### Creative Video

AI-driven multi-scene storytelling:

| Field | Description | Required |
|-------|-------------|----------|
| Idea | Describe your AI video concept | Yes |
| Requirements | Scene count, duration, style constraints | - |
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
│   └── index.html                    # Frontend SPA — 3 task tabs, 7 languages (Tailwind CSS)
├── core/
│   ├── config.py                     # API key, font resolution, default configs
│   ├── screenwriter.py               # Screenwriter Agent (LLM-powered story/script/narration)
│   ├── task_manager.py               # Task state persistence & checkpoint resume
│   ├── api/
│   │   ├── agnes_chat.py             # LLM Chat API (agnes-2.0-flash)
│   │   ├── agnes_image.py            # Image generation API (agnes-image-2.1-flash)
│   │   └── agnes_video.py            # Video generation API (agnes-video-v2.0)
│   ├── audio/
│   │   ├── tts.py                    # Edge TTS engine + silent fallback engine
│   │   └── subtitle.py               # SRT generation (fine-grained word-level) + overlay
│   ├── compositor/
│   │   ├── concatenator.py           # Video concatenation + audio/subtitle overlay
│   │   └── processor.py              # Video resize, frame extraction, freeze, silence gen
│   └── pipelines/
│       ├── simple_video.py           # Pipeline: Simple Video
│       ├── creative_video.py         # Pipeline: Creative Video (10-step)
│       └── manuscript_video.py       # Pipeline: Manuscript Video (5-step)
├── models/
│   └── task.py                       # Data models (3 task types, configs, requests)
├── resource/
│   └── fonts/                        # Built-in CJK fonts for subtitle rendering
├── utils/
│   ├── image.py                      # Image download / base64 conversion
│   └── video.py                      # Video download
├── scripts/
│   └── regression_runner.py          # 9-scenario regression test suite
└── docs/
    ├── system_design.md              # Architecture documentation
    ├── regression_test_plan.md       # Regression test plan
    └── *.mermaid                     # UML diagrams
```

## 🔧 Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend | Python FastAPI | Async + WebSocket |
| Frontend | HTML/CSS/JS + Tailwind CSS CDN | Zero build steps, single-file SPA |
| LLM | Agnes Chat (`agnes-2.0-flash`) | Free — story, script, narration generation |
| Image AI | `agnes-image-2.1-flash` (t2i) / `agnes-image-2.0-flash` (i2i) | Free — reference images, end frames |
| Video AI | `agnes-video-v2.0` | Free — text-to-video, image-to-video, keyframes |
| TTS | Edge TTS (Microsoft) | Free — 4 Chinese voices, no API key needed |
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
| GET | `/api/voices` | List available TTS voices |
| POST | `/api/tasks/simple` | Create simple video task |
| POST | `/api/tasks/creative` | Create creative video task |
| POST | `/api/tasks/manuscript` | Create manuscript video task |
| GET | `/api/tasks` | List all tasks (with type badges) |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/tasks/{id}/resume` | Resume an interrupted task |
| POST | `/api/tasks/{id}/stop` | Stop a running task |
| GET | `/api/video/{id}` | Download/stream final video |
| WS | `/ws/{id}` | WebSocket real-time progress |

## ⚠️ Important Notes

This project is in early stage — corner cases may not be fully handled. Recommended workflow:

1. Fill in your idea on the page and submit the AI video task
2. Watch the **console logs** (the terminal running `server.py`) and be patient
3. All key operations are logged for easy debugging

### Known Limitations

- Network instability may cause retry failures in some steps
- Large AI videos (>20s) take longer to generate — please be patient
- Behavior is undefined when custom end frame count doesn't match scene count
- Concurrent AI video tasks may cause resource contention

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
| `[TaskManager]` | Task state persistence |

### Output Directory

All AI video task artifacts are stored under `.working_dir/{timestamp}_{task_id}/`:

```
.working_dir/{timestamp}_{task_id}/
├── task_state.json              # Task state (required for checkpoint resume)
├── final_video.mp4              # Final AI video with narration + subtitles
├── story.txt                    # AI-generated story (creative mode)
├── script.json                  # Scene script (JSON)
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

**Keywords**: free AI video generator, AI video generation tool, text to video AI, free AI video maker, AI video creator, open source video generator, Agnes AI, text-to-video, image-to-video, keyframes video, AI narration, auto subtitles, multi-scene video, zero cost AI video, no subscription AI video tool
