# 🏗️ Project Structure

```
agnes-video-generator/
├── start.sh                          # One-click launch script
├── requirements.txt                  # Python dependencies
├── Dockerfile                        # Multi-arch Docker image (Python 3.11 + ffmpeg via imageio)
├── docker-compose.yml                # Docker Compose with persisted volumes
├── docker-run.sh                     # One-command Docker launch (wrapper with bind mounts)
├── server.py                         # FastAPI server (REST + WebSocket)
├── static/                           # Frontend build artifacts (committed to git)
│   ├── index.html                    # Built SPA entry (Vite output, base=/static/)
│   └── assets/                       # Hashed JS/CSS bundles
├── frontend/                         # Frontend source (Vue 3 + Vite + TypeScript)
│   ├── vite.config.ts                # outDir=../static, base=/static/, emptyOutDir=false
│   └── src/                          # Components / composables / i18n / api
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
    ├── plans/                         # Plan docs (versioned + optimization research)
    ├── public/                        # User-facing docs (README-linked)
    └── dev/                           # Internal architecture / QA docs
```

# 🔧 Tech Stack

| Layer            | Choice                                         | Notes                                                                |
| ---------------- | ---------------------------------------------- | -------------------------------------------------------------------- |
| Backend          | Python FastAPI                                 | Async + WebSocket                                                    |
| Frontend         | Vue 3 + Vite + TypeScript + Tailwind (PostCSS) | Build output committed to `static/`; zero runtime deps for end users |
| LLM              | Agnes Chat (`agnes-2.5-flash`)                 | Free — story, script, narration generation                           |
| Image AI         | `agnes-image-2.5-flash` (t2i / i2i)            | Free — reference images, end frames, standalone image generation     |
| Video AI         | `agnes-video-v2.0`                             | Free — text-to-video, image-to-video, keyframes                      |
| TTS              | Edge TTS (Microsoft)                           | Free — 4 Chinese voices, no extra API key needed                     |
| Subtitles        | moviepy + srt                                  | Fine-grained word-level SRT, multi-line wrapping                     |
| Video Processing | moviepy + ffmpeg                               | Concatenation, subtitle overlay, audio mixing                        |

