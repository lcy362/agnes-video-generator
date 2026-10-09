# ❓ FAQ

### Is Agnes Video Generator really free? Are there any hidden costs?

Yes, it is **completely free**. All AI model calls (Agnes Chat, Agnes Image, Agnes Video) are free of charge with no trial period, no watermarks, and no usage limits. The only TTS integration (Microsoft Edge TTS) is also free and requires no extra API key. You only need a free API key from [Agnes AI](https://platform.agnes-ai.com) to get started.

### Do I need a GPU to run this AI video generator?

No. All AI compute runs in the cloud via Agnes AI's free API. You just need a regular laptop or desktop computer that can run Python 3.10+ and ffmpeg. No GPU, no high RAM, no special hardware required.

### How is this different from Runway, Pika, or Sora?

Unlike commercial AI video tools that charge $10–$95/month, Agnes Video Generator is completely free and open-source (MIT). It offers built-in multi-scene pipelines, AI narration, auto subtitles, and digital anchor — features that require third-party tools or manual editing elsewhere. See the [comparison table](../README.md#comparison-agnes-vs-commercial-ai-video-tools) in the README for details.

### What video generation modes are supported?

Six task types: **Simple Video** (single prompt, full parameter control), **Creative Video** (AI story → multi-scene video with narration), **Manuscript Video** (long text → auto-split → narrated video), **Digital Anchor** (AI anchor with lip-synced speech), **Poetry Video** (a poem → per-line scenes → recitation + timed subtitles), and **Simple Image** (text-to-image / image-to-image in one call). Additional options include text-to-video, image-to-video, keyframes animation, and image-to-image end frame generation.

### Can I use my own images as references?

Yes. You can upload reference images for character or scene consistency across scenes, use custom end frames for precise visual transitions, or choose img2img to auto-generate end frames from your reference. Reference images are supported in Creative Video, Manuscript Video (mapped per paragraph to guide i2v framing), and Digital Anchor modes.

### What languages does the UI support?

The Web UI supports 22 languages: 中文, English, Deutsch, Français, Nederlands, Español, Português, Italiano, Русский, 日本語, 한국어, Bahasa Melayu, Bahasa Indonesia, العربية, Türkçe, Tiếng Việt, ไทย, Tagalog, हिन्दी, فارسی, বাংলা, اردو. Subtitles are generated in the source text language, with built-in font fallback for CJK, Arabic / Persian / Urdu (RTL), Thai, Devanagari and Bengali scripts.

### Can I run this with Docker?

Yes. Pre-built images are published to both [GHCR](https://github.com/lcy362/agnes-video-generator/pkgs/container/free-short-video) and [Docker Hub](https://hub.docker.com/r/lcy362/free-short-video). Just pull the `latest` tag and run — no Python or ffmpeg installation needed. See **[Option B: Docker](./getting-started.md#option-b-docker-no-pythonffmpeg-required)** in Getting Started for the full command and volume mount instructions.

### Can I host this on my own server?

Absolutely. The project is designed for self-hosting. Just clone the repo, run `./start.sh`, and the server starts on `http://localhost:8765`. No external dependencies, no cloud lock-in. See the [Quick Start](./getting-started.md) section.

### What should I do when generation fails?

Most failures are caused by **transient factors** such as model service fluctuations, network timeouts, or rate limiting. In the in-app **failure panel**, click **Retry Task** first — the task resumes from the failed step (checkpoint-based), and most cases recover on their own without resubmitting.

If it still fails after several retries (≥ 2), the feedback area **auto-expands**, letting you copy the diagnostic info in one click and jump to a pre-filled GitHub Issue — no need to describe your environment manually.

### The task sits at 0% for a very long time, then fails. Is my setup broken?

Usually not. For free video models such as **Video 2.5 Flash, Agnes keeps a shared inference queue that can stay saturated for 10+ minutes** — during that window every submission is rejected with `503 video_queue_full` (the raw message is `video queue is full, please retry later (request id: …)`) and *no* job is created (nothing is consumed, nothing is lost). This is Agnes-side capacity, not your prompt or configuration.

As of **v7.0**, the app handles this explicitly:

- A queue-full rejection no longer counts against the normal retry budget. It moves to a **dedicated retry track** (up to 15 retries by default, configurable via `AGNES_VIDEO_BUSY_RETRY_ATTEMPTS`). The first retry fires immediately ("hug the rate limit": timing is handed to the token bucket, so the real interval is the bucket's own quota), and subsequent retries are spaced 30–60s apart.
- The progress panel names the cause and keeps the raw error visible, e.g. `Agnes 视频队列已满（HTTP 503 · video_queue_full），正在排队重试（第 3 次 / 已等 5 分钟）。建议错峰重试或稍后再试。` / `Agnes video queue is full (HTTP 503 · video_queue_full), retrying (attempt 3 / waited 5 min). Please retry later, ideally off-peak.`
- Only when those retries are exhausted do you get a failure — and the message names Agnes, quotes the raw `HTTP 503 · video_queue_full`, and tells you to **retry later / off-peak or switch model**, instead of a generic `HTTP 503: server error`.

**What you can do:** retry during off-peak hours, switch to another video model (Video 2.0 uses a separate queue and often still accepts jobs), or add more API keys (each key has its own quota).

### Generation timed out after ~15 minutes with "inference not finished after 15 minutes"

That message comes straight from the upstream inference backend. Agnes applies a **~15-minute hard cut-off per inference** — once a job trips it, the task is marked `failed` with that exact message and **waiting longer will not produce a video**. It is not a "needs more time" situation.

Since **v7.0**, self-hosted installs surface this verbatim instead of hiding it:

- The failure message keeps the upstream text and appends the upstream code, e.g. `Video generation failed: ComfyUI internal error: inference not finished after 15 minutes (code=500)`.
- `error_logs/*.json` stores `message` (readable text) plus the `code` — no more raw dict literals.

> **Why does self-hosting show a real error while the online demo just says "timed out"?** The demo applies its own client-side timeout earlier and rewrites the reason; self-hosting polls long enough (default 1800s, `AGNES_VIDEO_POLL_TIMEOUT`) to receive the genuine terminal state. A real error message is a *feature*: it tells you the difference between "not queued yet" and "queued but stuck". See `docs/dev/agnes_video_upstream_behavior.md` for the raw measurements.

### Why is my Video 2.5 Flash portrait (9:16) video lying on its side?

Known **upstream defect** (reported 2026-09): with `aspect_ratio=9:16` the API returns a portrait *container* (720×1280) but the pixels are a landscape composition rotated 90°, and there is no rotation metadata to correct it automatically. `16:9` and `3:4` are unaffected. Multi-scene pipelines carry the rotated frames into concatenation and subtitles, so the final video also looks sideways.

Two ways out:

1. **Avoid it (zero risk, default)**: pick `16:9` (or `3:4`), or use **Video 2.0** for portrait output. Since v7.0 the app shows an explicit hint when you select 9:16 on a 2.5-series model.
2. **Let the app fix it**: set `AGNES_FIX_V25_PORTRAIT_ROTATION=1` before starting. After download the app detects the signature (landscape inference size in a portrait container) and transposes the clip once (`ffmpeg transpose=2`), logging `[UpstreamRotate]`. This is opt-in because it would over-rotate the day upstream fixes the bug.

### The online demo offers a model or resolution that my local install doesn't have

The **model list** is fetched live from the API, so a newly released model shows up in your dropdown as soon as upstream publishes it. But the **capability table** (which resolutions, durations and modes that model accepts) is shipped with each release — an older install can therefore list a model it doesn't fully understand.

Since **v7.0**:

- Models that the current version has no capability entry for are marked with `⚠` in the dropdown plus an explicit notice: *"This model is not adapted in the current version; generation may misbehave. Please upgrade and retry."* They are no longer silently submitted with the old v2.0 pixel protocol.
- The app version is shown in the page footer and returned by `GET /api/models` (`app_version`), so you can tell at a glance whether you are on an old build.

Upgrade with either:

```bash
git pull && ./start.sh                                  # source install
docker compose pull && docker compose up -d             # Docker install
```

Quality differences between the demo and your install usually come from **model generation** itself (Video 2.5 Flash runs at roughly 4.1 Mb/s versus ~1.5 Mb/s for Video 2.0), not from a setting you missed. Pick `Video 2.5 Flash` in the model dropdown to match the demo.

### Generation worked for a long time, then failed at the last step with `getaddrinfo failed` / `[Errno 11004]`

This is a **local DNS problem on your machine**, not a generation failure. Prompts and jobs go to the API endpoint, but the finished media is served from a separate output domain (`cos-platform-outputs.agnes-ai.cn` for videos, `platform-outputs.agnes-ai.space` for images). If your resolver cannot resolve that output domain, the job is already done on the server side while your machine cannot pull the file back — so the run dies right at download time and every retry dies at the same place.

Check in this order:

1. Switch to a resolver that can reach the domain. In mainland China, `223.5.5.5` (AliDNS) or `119.29.29.29` (DNSPod) work; abroad, `1.1.1.1` or your ISP resolver is fine.
2. Turn off DNS hijacking from a VPN or proxy client, and check hosts-file entries or security software that blocks unfamiliar domains.
3. Flush the local resolver cache (`ipconfig /flushdns` on Windows, `sudo dscacheutil -flushcache` on macOS) and reload the page.
4. Click **Retry Task**. The generated video id is kept in the task directory, so the task resumes from the failed step and only re-fetches the file — no resubmission, no extra quota.

As of **v6.4.8**, the failure panel labels this class of error explicitly (a `网络诊断` / network-diagnosis message naming the domain that failed to resolve) instead of showing an opaque `RetryError[...]`, and the pre-filled Issue now reports the step that actually failed.

### Why do I get `401` / "invalid token" errors even though my API key looks correct?

A `401 Unauthorized` or "无效的令牌 / invalid token" response usually means the **API Key does not match the domain** it is being sent to — for example, a key issued on the global site being used against the China-domestic endpoint `api.agnes-ai.cn` (or the reverse). Different keys are issued for different sites, so the wrong domain rejects the token.

As of **v6.4.2**, each key can be bound to its own access domain, and a one-click **Auto-detect domains** button probes each key across `com` / `cn` / `cn_bak` and fills in the matching domain. In the API Key panel, pick the domain that matches your key, or just run auto-detect. Keys issued on the global site should use `apihub.agnes-ai.com`, or the `cn_bak` fallback (`apihub.agnes-ai.cn`), which accepts both domestic and global keys.

> **Note — env keys vs. Web-page keys.** Per-key domain binding and Auto-detect only apply to keys added in the **Web config page**. Keys supplied via `.env` / environment variables are *env* keys: they can't be bound individually and are skipped by auto-detect — they all use the single **global default domain** you pick on the Web page. So with a `.env` key, the fix for `401` is to set the global default domain to match that key's site (or move the key to the Web config page). Also, when rotating multiple keys, one mismatched/expired key causes intermittent `401` whenever it is the one picked.

### Can I get a video by posting my prompt in a GitHub Issue?

No. This project is a **self-hosted application**, not a hosted generation service — maintainers don't run jobs for you, so a prompt pasted into an Issue (or a comment) produces nothing and gets closed as invalid. Use one of the two real entry points instead:

- **Run it yourself**: `./start.sh` (or Docker / npm), then open `http://localhost:8765` and enter your prompt in the app. See [Getting Started](./getting-started.md).
- **Try it online, no install**: the free browser demo at [video.lichuanyang.top/demo](https://video.lichuanyang.top/demo) — it runs entirely in your browser with your own Agnes API key.

Please keep Issues for what they are for: **bug reports** (error message, task type, failed step — the in-app failure panel fills all of that in for you) and **feature requests**. If a prompt gives you poor results *inside the app*, that is a prompting/model question — include the prompt, mode, model and resolution you used and we'll take a look.

### How do I get help or report issues?

Feedback is available both in-app and on the official site:

- **In-app one-click reporting**: when a task fails, the failure panel offers **Copy Diagnostic Info** and **Open a GitHub Issue** buttons, automatically attaching the app version, task type, failed step, error message, and retry count to help maintainers pinpoint the problem.
- **Official site / GitHub**: you can also visit the [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) page to check existing reports or open a new one. The project also includes a comprehensive `AGENTS.md` for AI-agent-assisted debugging.

> 💡 Tip: before submitting an issue, try retrying as described in "What should I do when generation fails?" to reduce duplicate reports of transient failures.
