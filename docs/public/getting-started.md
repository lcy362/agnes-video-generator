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

# Way 2: Via API (same as entering it in the Web UI; the endpoint takes form data)
curl -X POST http://localhost:8765/api/config \
  -F 'api_key=your-api-key'
```

> **💡 Prefer a config file?** Copy the bundled template [`.env.example`](../../.env.example) to `.env` in the project root and fill in your key. It documents every supported variable with its default — multi-key rotation, rate limits, port, model overrides:
>
> ```bash
> cp .env.example .env    # then edit AGNES_API_KEY inside
> ```
>
> **Using several API keys?** Name them `AGNES_API_KEY`, `AGNES_API_KEY_2`, `AGNES_API_KEY_3` … (numbering must be contiguous). Rate-limit quotas scale with the number of keys, and a `429` automatically rotates to the next key.

> **⚠️ Match the key to the right site (avoid `401` / "invalid token").** Agnes has separate endpoints per site, and a `401` almost always means the key is being sent to the wrong one:
> - `apihub.agnes-ai.com` (Global) — keys from the global site.
> - `api.agnes-ai.cn` (China) — **China-domestic-only** keys.
> - `apihub.agnes-ai.cn` (fallback) — accepts both China and global keys.
>
> The domain is chosen in the **Web config page**, not via `.env`. Keys supplied through `.env` / environment variables are *env* keys: they **cannot be bound to a per-key domain and are skipped by "Auto-detect domains"** — they all use the single **global default domain** you set on the Web page. So:
> - **Single-site key:** just set the global default domain to match that key's site, and you're done.
> - **Keys from different sites mixed together:** add them on the Web config page instead (these are *config* keys). Each gets its own domain dropdown, or click **Auto-detect domains** to fill them in; they persist across restarts.
>
> With multiple keys rotating, a single mismatched or expired key makes tasks intermittently fail with `401` when that key is picked — fix or remove it.

**Step 3 — Create Your First Video**

Open `http://localhost:8765` and pick one of the six task types — **Single-shot clip** (formerly Simple Video), **Multi-shot story** (formerly Creative Video), Manuscript video, Digital anchor, Poetry video or Simple image — then enter your idea and click "Start Generating".

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

On first run the launcher automatically creates a virtual environment, installs Python dependencies, wires up a bundled `ffmpeg` (via `imageio-ffmpeg`, so no system ffmpeg needed), starts the server on `http://localhost:8765`, and opens your browser. Pass your key through the environment or set it later in the Web UI:

```bash
AGNES_API_KEY=<your-key> npx free-short-video
```

**Everything mutable lives in one data root** — `~/.agnes-video` by default, override with `AGNES_HOME`
(or `--home <dir>`): `venv/`, `config/`, `workspace/`, `logs/`. Keeping it out of the package directory
is what makes the install durable: `npx` unpacks into its own cache, so a cache clean or a version bump
would otherwise throw away the virtualenv and re-download every Python dependency. Later runs reuse it,
and `pip` only runs again when `requirements.txt` actually changed (sha256 fingerprint).

Options: `--port <n>`, `--host <h>` (use `0.0.0.0` for LAN access), `--no-open`,
`--detach` (start in the background, exit once the service answers), `--json` (machine-readable result,
implies `--detach`), `--print-paths` (show where the data root pieces live), `--home <dir>`.

```bash
# Script / agent friendly: start in the background and get a JSON result
npx free-short-video --detach --json --no-open
# {"ok":true,"ready":true,"pid":4242,"base":"http://127.0.0.1:8765","home":"/home/you/.agnes-video",...}
```

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

This project is built to be driven by an AI coding assistant through **one skill**. Install it once,
then describe the outcome you want instead of running commands. The authoritative description is
**[Let an AI Agent Operate This Project](agent-operations.md)**.

**Install the skill.** It is a plain directory plus small scripts — no service code, and no
credentials ever pass through it:

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub     # Sources → add the cloned directory (flint reads its skills/ subdirectory)
```

[**flint**](https://github.com/lcy362/flint) is a local-first, open-source skills manager: it deploys
the skill into any agent directory (Claude Code, Cursor, Codex, TRAE and more) by symlink or copy,
with no cloud, no account and no telemetry. It works on local sources only — it never clones anything
for you — so you register the directory you just cloned.

**Or copy it in by hand** if you would rather not use flint — the trade-off is that you repeat it
for every project and every new agent:

```bash
cp -R agnes-video-generator-skills/skills/agnes-video <project>/.agents/skills/   # any agent that reads .agents/skills
```

**The skill installs the service too.** You do not need this repository cloned first: the skill runs
`scripts/bootstrap.py install`, which puts the service under `~/.agnes-video` (override with
`AGNES_HOME`), keeps its own virtualenv there, starts it on `localhost:8765`, and re-runs nothing on
the next use. Config, workspace, outputs and logs live in that same data root.

**Then ask for outcomes.** The skill is one closed loop — install, create, deliver, diagnose, and
(with your agreement) fix a real defect and open a PR:

> "Make a creative long video about the Voyager probes, with narration and subtitles."

> "My task `4de1bcd26fda` failed — find out why and tell me if it is worth fixing."

**[Star flint on GitHub ⭐](https://github.com/lcy362/flint)**

