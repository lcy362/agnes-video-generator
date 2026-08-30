# 🚀 Quick Start

## Prerequisites

- Python 3.10+
- ffmpeg — required only for **manual setup** (Option A); the Docker (Option B) and npm (Option C) options bundle ffmpeg automatically, so no system ffmpeg install is needed there.

That's it. No GPU, no large RAM, a regular laptop is all you need.

## Option A: Manual Setup

**Step 1 — Clone & Launch**

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
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

> **💡 Prefer a config file?** Copy the bundled template [`.env.example`](../../.env.example) to `.env` in the project root and fill in your key. It documents every supported variable with its default — multi-key rotation, rate limits, port, model overrides:
>
> ```bash
> cp .env.example .env    # then edit AGNES_API_KEY inside
> ```
>
> **Using several API keys?** Name them `AGNES_API_KEY`, `AGNES_API_KEY_2`, `AGNES_API_KEY_3` … (numbering must be contiguous). Rate-limit quotas scale with the number of keys, and a `429` automatically rotates to the next key.

**Step 3 — Create Your First Video**

Open `http://localhost:8765`, choose a video mode (Simple / Creative / Manuscript / Anchor), enter your idea, and click "Start Generating".

## Option B: Docker (No Python/FFmpeg Required)

Pre-built multi-arch images (`linux/amd64`, `linux/arm64`) are published to both **GitHub Container Registry (GHCR)** and **Docker Hub** on every release.

**Pull & Run**

```bash
# GHCR
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=<your-key> \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  ghcr.io/lcy362/free-short-video:latest

# Docker Hub
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=<your-key> \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  lcy362/free-short-video:latest
```

Then open `http://localhost:8765`.

**Data Persistence:** The app writes videos, uploads, and settings inside the container (`/app/.working_dir`, `/app/.agnes_config`). Mount them to your host so outputs survive container recreation and are accessible from your local filesystem. Your generated videos will be at `~/agnes-data/working/` on your machine.

Or use `docker compose` with the included `docker-compose.yml`:

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
AGNES_API_KEY=<your-key> docker compose up -d
```

## Option C: npm (One Command)

If you have **Node.js 18+** and **Python 3.10+** installed, the whole service ships as an npm package — no cloning, no manual venv:

```bash
# Run directly without installing
npx free-short-video

# Or install globally, then run
npm install -g free-short-video
free-short-video          # short alias: fsv
```

On first run the launcher automatically creates a local virtual environment, installs Python dependencies, wires up a bundled `ffmpeg` (via `imageio-ffmpeg`, so no system ffmpeg needed), starts the server on `http://localhost:8765`, and opens your browser. Pass your key through the environment or set it later in the Web UI:

```bash
AGNES_API_KEY=<your-key> npx free-short-video
```

Options: `--port <n>`, `--host <h>` (use `0.0.0.0` for LAN access), `--no-open`.

### ffmpeg: bundled by default, or install your own

With the npm package you normally **don't need to install ffmpeg yourself** — the launcher (`bin/cli.js`) automatically installs `imageio-ffmpeg` (a static ffmpeg binary, now an explicit dependency in `requirements.txt`) into the local venv and prepends its directory to `PATH`, so every `ffmpeg` call inside the Python service resolves to the bundled binary. This works out of the box on macOS, Linux, and Windows.

**If you prefer to install ffmpeg on your system** (recommended for production / maximum stability — your system ffmpeg takes precedence over the bundled one because it appears earlier on `PATH`):

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg

# CentOS / RHEL (requires RPM Fusion)
sudo dnf install ffmpeg

# Windows (Chocolatey)
choco install ffmpeg

# Windows (Scoop)
scoop install ffmpeg
```

Or download a build from <https://ffmpeg.org/download.html> and add it to your `PATH`. Verify with:

```bash
ffmpeg -version
```

**Risks if you do NOT install a system ffmpeg (i.e. rely solely on the bundled `imageio-ffmpeg`):**

- **Platform / architecture support** — `imageio-ffmpeg` ships pre-built binaries only for common platforms (macOS x86_64/arm64, Linux x86_64/arm64, Windows x64). On niche or very old architectures a matching wheel may not exist, and the bundled binary would be missing.
- **Single source of truth** — all ffmpeg capability comes from that one static binary. If its install/extract fails (disk permissions, corruption), the failure only surfaces **when you generate a video**, not at server startup — the error is a low-level `FileNotFoundError: 'ffmpeg'`, which is harder to diagnose than a startup check.
- **Pinned version** — the bundled ffmpeg is locked to whatever version `imageio-ffmpeg` ships (e.g. ffmpeg 7.1); you can't easily upgrade it on your own.
- **Mitigation** — for production or stability-critical use, install a system ffmpeg as shown above; the bundled one then acts only as a fallback.

## Option D: AI Agent Assisted Setup

This project is designed for AI coding assistants. First, download the code and prepare your API key:

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
```

Then tell your agent:

> "Read the AGENTS.md in this project, install dependencies, configure the API key `<your-key>`, and start the server."

The agent will read `AGENTS.md` (a comprehensive deployment guide) and handle: environment checks (Python 3.10+, ffmpeg), `pip install`, server launch, and API key configuration. After startup, you can also ask the agent to verify the deployment:

> "Run the deployment verification checks."

The agent will execute the 4-layer checklist from `AGENTS.md` (connectivity → static analysis → endpoint testing → subtitle feature) and report results.
