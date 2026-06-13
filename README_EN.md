# 🎬 Agnes Video Generator — ✨ Completely Free AI Video Generation Tool

> 🆓 A completely free AI video generator powered by Agnes AI. Turn text ideas into multi-scene AI videos automatically. Supports text-to-video, image-to-video, and keyframes video generation.

Built upon [ViMax](https://github.com/HKUDS/ViMax) and [vimax-agnes](https://github.com/easyeye163/vimax-agnes), this project upgrades the command-line AI video generation tool into an all-in-one video generator with a Web UI.

## 🎥 Demo

> A dark-twist fairytale — *The Frog Prince*, 5 scenes, keyframes chaining, fully auto-generated.

[![The Frog Prince — Demo Video](https://img.shields.io/badge/▶%20Watch%20Demo-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/L4F6KdGnD6U/)

<sub>Click to watch on Douyin</sub>

## ✨ Features

- **🌐 Web UI** — One-click launch, operate entirely in the browser, no command line needed
- **🎥 AI-Powered Full Pipeline** — Idea → Story → Character Reference → Script → Per-Scene AI Video → Final Video
- **🖼️ Custom Reference Image** — Upload a character reference image for consistent character appearance across all scenes
- **🎯 Custom End Frames** — Specify end frame images for each scene to precisely control AI video output
- **🔄 Image-to-Image End Frames** — Auto-generate scene end frames via img2img based on reference image
- **🔗 Three Video Chaining Modes** — `keyframes` (recommended) / `ti2vid` (transition frames) / `none` (independent scenes)
- **💾 Checkpoint Resume** — Auto-resume interrupted AI video tasks from the last checkpoint, no duplicate uploads or generation
- **🔑 In-Page API Key Config** — Configure your Agnes API key directly in the Web UI
- **📡 Real-Time Progress** — WebSocket-powered live progress updates for every step of AI video generation

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- ffmpeg (for AI video concatenation)

### One-Click Launch

```bash
git clone https://github.com/your-org/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

Your browser will automatically open `http://localhost:8765`.

### Manual Launch

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Then visit `http://localhost:8765`.

## 📖 Usage

### 1. Configure API Key

Enter your [Agnes AI](https://platform.agnes-ai.com) API key at the top of the page and save it.

Alternatively, set it via environment variable:

```bash
export AGNES_API_KEY="your-api-key"
```

### 2. Create an AI Video Task

Fill in the following fields:

| Field | Description | Required |
|-------|-------------|----------|
| Idea | Describe your AI video idea in natural language | ✅ |
| Requirements | Scene count, duration, etc. (e.g., "3 scenes, 10s each, cinematic quality") | - |
| Visual Style | Cinematic realism, anime, cyberpunk, etc. | - |
| Chaining Mode | keyframes (recommended) / ti2vid / none | - |
| Video Size | Default 768×1152 portrait | - |
| Duration per Scene | 5s / 6s / 7s / 8s / 9s / 10s | - |

### 3. Optional: Reference Image & End Frames

- **Reference Image**: Upload a character image as a visual anchor. If not provided, one will be auto-generated from the story.
- **Custom End Frames**: Specify end frame images for each scene.
- **Generate End Frames from Reference**: Enable to auto-generate end frames via img2img based on the reference image.

### 4. Click "Start Generating"

The progress panel shows real-time AI video generation status: Init → Image Analysis → Story → Character Reference → Script → End Frame Prompts → End Frame Generation → Video Generation → Concatenation.

### 5. Checkpoint Resume

If the server is interrupted, restart it and find the incomplete task in the "Task List" tab. Click "Resume" to continue from the last checkpoint.

## 🏗️ Project Structure

```
agnes-video-generator/
├── start.sh                    # One-click launch script
├── requirements.txt            # Python dependencies
├── server.py                   # FastAPI server (REST + WebSocket)
├── static/
│   └── index.html              # Frontend SPA (Tailwind CSS)
├── core/
│   ├── config.py               # API key persistence
│   ├── screenwriter.py         # Screenwriter Agent (LLM calls)
│   ├── image_generator.py      # AI image generation (t2i / i2i)
│   ├── video_generator.py      # AI video generation (t2v / ti2vid / keyframes)
│   ├── pipeline.py             # AI video generation pipeline
│   └── task_manager.py         # Task management & checkpoint resume
├── models/
│   └── task.py                 # Data models
└── utils/
    ├── image.py                # Image download / base64 conversion
    └── video.py                # Video download
```

## 🔧 Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Backend | Python FastAPI | Async + WebSocket |
| Frontend | HTML/CSS/JS + Tailwind CSS CDN | Zero build steps |
| AI Models | Agnes AI API | agnes-2.0-flash / agnes-image-2.1-flash / agnes-video-v2.0 (all free) |
| Video Concatenation | moviepy | Same as upstream project |

## 🎬 Three AI Video Chaining Modes

| Mode | How It Works | Best For |
|------|-------------|----------|
| **keyframes** | Specify first + last frame per scene; server auto-interpolates transitions | Smooth transitions (recommended) |
| **ti2vid** | Last frame of previous scene → img2img transition → first frame of next scene | Visual continuity between scenes |
| **none** | All scenes share the same reference image, independent of each other | Fast output, independent scenes |

## 📋 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config` | Get API key (masked) |
| POST | `/api/config` | Save API key |
| POST | `/api/tasks` | Create an AI video generation task |
| GET | `/api/tasks` | List all tasks |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/tasks/{id}/resume` | Resume an interrupted task |
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

- `[Startup]` — Reset stale running tasks on startup
- `[WS]` — WebSocket client connect/disconnect
- `[Resume]` — Resume task start, prints current step statuses
- `[Pipeline]` — Per-step execution status (SKIP / RUNNING)
- `[TaskManager]` — Task state loading
- `[EndFrame]` — End frame generation retry info
- `[Pipeline] Shutdown` — Task interrupted
- `[Pipeline] Completed / failed` — Task finished or failed

### Output Directory

All AI video task artifacts are stored under `.working_dir/{task_id}/`:

```
.working_dir/{task_id}/
├── task_state.json              # Task state (required for checkpoint resume)
├── final_video.mp4              # Final concatenated AI video
├── story.txt                    # AI-generated story text
├── script.json                  # Scene script (JSON)
├── image_analysis.txt           # Image analysis results
├── character_reference.png      # AI-generated character reference image
├── character_ref_prompt.txt     # Character reference generation prompt
├── end_frame_prompts.json       # End frame prompts (keyframes mode)
├── scene_0/
│   ├── video.mp4                # Scene 0 AI video
│   ├── end_frame.png            # Scene 0 end frame
│   ├── task.json                # Video task ID
│   └── curl.sh                  # Curl command to query video status
├── scene_1/
│   └── ...
└── scene_2/
    └── ...
```

## 🙏 Acknowledgments

This project is built upon the following open-source projects:

- [ViMax](https://github.com/HKUDS/ViMax) — AI video generation framework by HKU Data Science Lab
- [vimax-agnes](https://github.com/easyeye163/vimax-agnes) — Agnes AI adaptation based on ViMax

Huge thanks to the original authors!

Special thanks to [Agnes AI](https://platform.agnes-ai.com) for providing free, high-quality AI model APIs (text, image, video generation) — this project is able to run at zero cost thanks to their generosity.

## Feedback & Contributing

This project is in early stage. Bug reports and feature suggestions are welcome via [GitHub Issues](../../issues).

## 📄 License

MIT
