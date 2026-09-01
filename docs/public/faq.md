# ❓ FAQ

### Is Agnes Video Generator really free? Are there any hidden costs?

Yes, it is **completely free**. All AI model calls (Agnes Chat, Agnes Image, Agnes Video) are free of charge with no trial period, no watermarks, and no usage limits. The only TTS integration (Microsoft Edge TTS) is also free and requires no extra API key. You only need a free API key from [Agnes AI](https://platform.agnes-ai.com) to get started.

### Do I need a GPU to run this AI video generator?

No. All AI compute runs in the cloud via Agnes AI's free API. You just need a regular laptop or desktop computer that can run Python 3.10+ and ffmpeg. No GPU, no high RAM, no special hardware required.

### How is this different from Runway, Pika, or Sora?

Unlike commercial AI video tools that charge $10–$95/month, Agnes Video Generator is completely free and open-source (MIT). It offers built-in multi-scene pipelines, AI narration, auto subtitles, and digital anchor — features that require third-party tools or manual editing elsewhere. See the [comparison table](../README.md#comparison-agnes-vs-commercial-ai-video-tools) in the README for details.

### What video generation modes are supported?

Four modes: **Simple Video** (single prompt, full parameter control), **Creative Video** (AI story → multi-scene video with narration), **Manuscript Video** (long text → auto-split → narrated video), and **Digital Anchor** (AI anchor with TTS). Additional options include text-to-video, image-to-video, keyframes animation, and image-to-image end frame generation.

### Can I use my own images as references?

Yes. You can upload reference images for character or scene consistency across scenes, use custom end frames for precise visual transitions, or choose img2img to auto-generate end frames from your reference. Reference images are supported in both Creative Video and Digital Anchor modes.

### What languages does the UI support?

The Web UI supports 13 languages: 中文, English, Deutsch, Français, Nederlands, Español, Português, Italiano, Русский, 日本語, 한국어, Bahasa Melayu, and Bahasa Indonesia. Subtitles are generated in the source text language with CJK font support built-in.

### Can I run this with Docker?

Yes. Pre-built images are published to both [GHCR](https://github.com/lcy362/agnes-video-generator/pkgs/container/free-short-video) and [Docker Hub](https://hub.docker.com/r/lcy362/free-short-video). Just pull the `latest` tag and run — no Python or ffmpeg installation needed. See **[Option B: Docker](./getting-started.md#option-b-docker-no-pythonffmpeg-required)** in Getting Started for the full command and volume mount instructions.

### Can I host this on my own server?

Absolutely. The project is designed for self-hosting. Just clone the repo, run `./start.sh`, and the server starts on `http://localhost:8765`. No external dependencies, no cloud lock-in. See the [Quick Start](./getting-started.md) section.

### What should I do when generation fails?

Most failures are caused by **transient factors** such as model service fluctuations, network timeouts, or rate limiting. In the in-app **failure panel**, click **Retry Task** first — the task resumes from the failed step (checkpoint-based), and most cases recover on their own without resubmitting.

If it still fails after several retries (≥ 2), the feedback area **auto-expands**, letting you copy the diagnostic info in one click and jump to a pre-filled GitHub Issue — no need to describe your environment manually.

### Why do I get `401` / "invalid token" errors even though my API key looks correct?

A `401 Unauthorized` or "无效的令牌 / invalid token" response usually means the **API Key does not match the domain** it is being sent to — for example, a key issued on the global site being used against the China-domestic endpoint `api.agnes-ai.cn` (or the reverse). Different keys are issued for different sites, so the wrong domain rejects the token.

As of **v6.4.2**, each key can be bound to its own access domain, and a one-click **Auto-detect domains** button probes each key across `com` / `cn` / `cn_bak` and fills in the matching domain. In the API Key panel, pick the domain that matches your key, or just run auto-detect. Keys issued on the global site should use `apihub.agnes-ai.com`, or the `cn_bak` fallback (`apihub.agnes-ai.cn`), which accepts both domestic and global keys.

### How do I get help or report issues?

Feedback is available both in-app and on the official site:

- **In-app one-click reporting**: when a task fails, the failure panel offers **Copy Diagnostic Info** and **Open a GitHub Issue** buttons, automatically attaching the app version, task type, failed step, error message, and retry count to help maintainers pinpoint the problem.
- **Official site / GitHub**: you can also visit the [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) page to check existing reports or open a new one. The project also includes a comprehensive `AGENTS.md` for AI-agent-assisted debugging.

> 💡 Tip: before submitting an issue, try retrying as described in "What should I do when generation fails?" to reduce duplicate reports of transient failures.
