# 🎬 Agnes Video Generator — Completely Free AI Video Generator

[![中文](https://img.shields.io/badge/CN-中文-red)](/README_ZH.md)
[![GitHub Stars](https://img.shields.io/github/stars/lcy362/agnes-video-generator?style=social)](https://github.com/lcy362/agnes-video-generator)
[![License](https://img.shields.io/github/license/lcy362/agnes-video-generator)](https://github.com/lcy362/agnes-video-generator/blob/HEAD/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![Website](https://img.shields.io/badge/website-video.lichuanyang.top-8A2BE2)](https://video.lichuanyang.top)
[![Docker Hub](https://img.shields.io/docker/pulls/lcy362/free-short-video?label=docker%20pulls)](https://hub.docker.com/r/lcy362/free-short-video)
[![npm](https://img.shields.io/npm/v/free-short-video?label=npm)](https://www.npmjs.com/package/free-short-video)
[![Sonar Quality Gate](https://img.shields.io/sonar/quality_gate/lcy362_agnes-video-generator?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge)](https://sonarcloud.io/project/overview?id=lcy362_agnes-video-generator)
[![Sonar Coverage](https://img.shields.io/sonar/coverage/lcy362_agnes-video-generator?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge)](https://sonarcloud.io/project/overview?id=lcy362_agnes-video-generator)

<p align="center">
  <img src="images/home.png" alt="Agnes Video Generator — Free AI Video Generator" width="720">
</p>

<!--
schema.org structured data for SEO/GEO indexing. GitHub does not execute this script, but the raw JSON-LD is visible to search engines and AI engines that scan repository READMEs.
-->
<!--
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Agnes Video Generator",
  "alternateName": "Free AI Video Generator",
  "applicationCategory": "MultimediaApplication",
  "operatingSystem": "Linux, macOS, Windows",
  "description": "A completely free, open-source AI video generator. No subscription, no high-end GPU, no usage limits — type a text idea and get narrated, auto-subtitled multi-scene AI videos. Supports text-to-video, image-to-video, keyframes animation, digital anchor and manuscript-to-video.",
  "url": "https://github.com/lcy362/agnes-video-generator",
  "downloadUrl": "https://github.com/lcy362/agnes-video-generator",
  "softwareVersion": "1.0.0",
  "license": "https://opensource.org/licenses/MIT",
  "keywords": "free AI video generator, AI video generation, text to video, AI video creator, open source video generator, AI narration, auto subtitles, multi-scene video, Runway alternative, Pika alternative",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  },
  "author": {
    "@type": "Person",
    "@id": "https://lichuanyang.top/#author",
    "name": "SandGrid",
    "alternateName": "lcy362",
    "url": "https://lichuanyang.top/",
    "sameAs": [
      "https://github.com/lcy362",
      "https://gitee.com/sandgrid/agnes-video-generator",
      "https://video.lichuanyang.top/"
    ]
  }
}
</script>
-->

> **🌏 Mirror Notice / 镜像说明**
> This project is also mirrored on [Gitee](https://gitee.com/sandgrid/agnes-video-generator) for faster access in mainland China. The **GitHub repository is the primary home** of this project — issues, PRs, and stars are managed there.
> 本项目在国内 Gitee 设有镜像仓库，便于国内访问加速；**GitHub 为项目主仓库**，Issue / PR / Star 均在 GitHub 提交。

> **Completely free AI video generator** — Built on Agnes AI's free models, no subscription, no high-end GPU, no usage limits. Type in a text idea and automatically generate multi-scene AI videos with narration and subtitles. Supports text-to-video, image-to-video, keyframes animation, digital anchor, and more. All AI compute runs in the cloud — a regular laptop is all you need. **[Try it online →](https://video.lichuanyang.top)**

> "The solution is not to suppress AI, but to make it a more equitable capability, so that everyone knows how to create more with AI. This is a very important vision for our company — to make world-class AI belong to everyone. What we can do may be insignificant, but this vision is very long-term and enduring."
>
> — Bruce Yang, Founder of Agnes AI

**[🌐 Official Website](https://video.lichuanyang.top)** | **[📝 Blog (中文)](https://lichuanyang.top/posts/22470/)** | **[📝 Blog (English)](https://lichuanyang.top/en/posts/22470/)**

> **🖥️ Try it now — no install needed:** Visit [video.lichuanyang.top](https://video.lichuanyang.top) and experience **Simple Video** mode directly in your browser. Just enter a prompt and generate a free AI video instantly.

## 🚀 Three Ways to Use — All Completely Free

| Project | Run Where | Features | Link |
|---------|-----------|----------|------|
| **[Agnes Video Generator](https://github.com/lcy362/agnes-video-generator)** (this project) | **Download & run locally** | **More powerful** — TTS narration, auto subtitles, digital anchor, image-to-video, keyframes animation, manuscript-to-video, checkpoint resume & more | [GitHub](https://github.com/lcy362/agnes-video-generator) |
| **[FreeShortVideoStudio](https://github.com/lcy362/free-short-video-studio)** | **Fully online, in the browser** | Lightweight, zero install — no setup at all, **features under active construction** | [video.lichuanyang.top/studio](https://video.lichuanyang.top/studio) · [GitHub](https://github.com/lcy362/free-short-video-studio) |
| **[Agnes Video Generator](https://github.com/lcy362/agnes-video-generator)** — **agent-ready** | **Driven by an AI coding agent** | **Least effort** — install the standalone `agnes-video` skill: it installs the service, generates the video, delivers the file, debugs failures and can open a PR for a real defect | [Skill repository](https://github.com/lcy362/agnes-video-generator-skills) · [Flint](https://github.com/lcy362/flint) |

## 🤖 Or Let an AI Agent Drive It

Install **one skill**, then describe the result you want. The `agnes-video` skill installs the
service, makes the video, delivers the file and diagnoses failures — **you never clone this
repository**, and the skill is useful on its own, not just as an add-on to this project.

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub     # Sources → add the cloned directory (flint reads its skills/ subdirectory)
```

[**flint**](https://github.com/lcy362/flint) is a local-first, open-source skills manager: it deploys
the skill into any agent directory (Claude Code, Cursor, Codex, TRAE and more) by symlink or copy,
with no cloud, no account and no telemetry. It works on local sources only — it never clones anything
for you — so you register the directory you just cloned.

**Or copy it in by hand** — no flint required, but you repeat it for every project and every new agent:

```bash
cp -R agnes-video-generator-skills/skills/agnes-video <project>/.agents/skills/   # any agent that reads .agents/skills
```

**The skill installs the service too.** It runs `scripts/bootstrap.py install`, which puts the
service under `~/.agnes-video` (override with `AGNES_HOME`), keeps its own virtualenv there, starts it
on `localhost:8765`, and re-runs nothing on the next use. Config, workspace, outputs and logs live in
that same data root.

**Then ask for outcomes** — no commands, no flags:

> "Make a creative long video about the Voyager probes, with narration and subtitles."

> "My task `4de1bcd26fda` failed — find out why and tell me if it is worth fixing."

> "Take my finished task, improve the storyboard prompts, and regenerate only the affected scenes."

One loop, five stages — and it stays in the same skill, so nothing is lost between them:

| Stage | What it does |
|-------|--------------|
| Install | Bootstrap the service under `~/.agnes-video` and verify it through the real endpoints |
| Create | Pick the pipeline, take the key safely, submit the task, report progress |
| Deliver | Copy the file to `$AGNES_HOME/outputs/<task_id>/` and report path, duration, resolution |
| Diagnose | Classify a failure as configuration, upstream capacity, or a genuine defect |
| Fix | After you agree: fork, fix a small defect, run pre-flight, open a PR |

Full guide: **[Let an AI Agent Operate This Project](docs/public/agent-operations.md)**.

## ⭐ Support & Contribute

If you find this project useful, please **star the [GitHub repository](https://github.com/lcy362/agnes-video-generator)** ⭐ — your support helps more people discover this free and open-source AI video generator.

Bug reports and feature suggestions are welcome via [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues).

### 💝 Support the Developer

Agnes Video Generator is and will always remain completely free and open-source. There will be **no paid plans, no premium features, and no subscription services** — now or in the future.

If you find this project helpful, here are a few ways to support its continued development:

- **⭐ Star on GitHub** — Star the [repository](https://github.com/lcy362/agnes-video-generator) to help others discover this project.
- **🪨 Star the author's new project [Flint](https://github.com/lcy362/flint)** — a local-first AI skills manager for your Claude Code / Cursor / other agents. Centralize, tag and reuse the skills you keep building.
- **🌐 Whitelist the official website** — Turn off your ad blocker on [video.lichuanyang.top](https://video.lichuanyang.top) and click on an ad if something catches your eye. A small gesture that makes a real difference.
- **📢 Share your creations** — Post videos made with Agnes Video Generator on social media (Douyin, YouTube, Xiaohongshu, etc.) and tag the project. More exposure means more users, more feedback, and a better tool for everyone.

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

### Comparison: Agnes vs. Commercial AI Video Tools

| Feature | Agnes Video Generator | Runway Gen-3 | Pika 2.0 | OpenAI Sora | Kling 1.6 |
|---------|:---:|:---:|:---:|:---:|:---:|
| **Price** | Free | $15–$95/month | $10–$95/month | $20+/month (limited) | Free quota, then pay-per-second |
| **Open Source** | ✅ Yes (MIT) | ❌ No | ❌ No | ❌ No | ❌ No |
| **Self-Hosted** | ✅ Yes | ❌ No | ❌ No | ❌ No | ❌ No |
| **Max Video Length** | 20s per clip, unlimited scenes | 10s per clip | 10s per clip | 20s per clip | 10s per clip |
| **Multi-Scene Pipeline** | ✅ Built-in (Creative/Manuscript) | ❌ Manual editing | ❌ Manual editing | ❌ Manual editing | ❌ Manual editing |
| **AI Narration (TTS)** | ✅ Free, built-in | ❌ Third-party | ❌ Third-party | ❌ Not available | ❌ Not available |
| **Auto Subtitles** | ✅ Word-level SRT | ❌ Not available | ❌ Not available | ❌ Not available | ❌ Not available |
| **Digital Anchor** | ✅ Built-in | ❌ No | ❌ No | ❌ No | ❌ No |
| **Resolution Options** | 9:16 / 16:9 / 1:1 | Multiple | Multiple | Multiple | Multiple |
| **Image-to-Video** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Image inputs | ✅ Yes |
| **Keyframes Animation** | ✅ Yes | ✅ Yes | ✅ Yes | ❌ Not available | ❌ Not available |
| **Local GPU Required** | ❌ No (cloud API) | ❌ No (cloud) | ❌ No (cloud) | ❌ No (cloud) | ❌ No (cloud) |
| **Watermark** | No watermark | Built-in watermark | Built-in watermark | C2PA metadata | Built-in watermark |
| **Usage Limit** | No limit (16 req/min rate limit) | Billed by compute | Billed by generation | Billed by generation | Billed by generation |

## ⚙️ Configuration

Everything is configured through environment variables — no config file is required. To start from a documented template:

```bash
cp .env.example .env    # then edit AGNES_API_KEY inside
```

[`.env.example`](.env.example) lists every supported variable with its default value: API key, multi-key rotation, rate limits, port, model overrides, and maintenance options.

> **Have more than one API key?** Set `AGNES_API_KEY`, `AGNES_API_KEY_2`, `AGNES_API_KEY_3` … (numbering must be contiguous). Rate-limit quotas scale with your key count, a `429` automatically rotates to the next key, and the concurrency limit scales along with it.

Full walkthrough: [Getting Started → Configure API Key](docs/public/getting-started.md).

## 📚 Documentation

- **[Features](docs/public/features.md)** — Creation modes, the completely free AI model chain, AI narration & smart subtitles, flexible creative controls, production-grade reliability, and the multilingual Web UI.
- **[Getting Started](docs/public/getting-started.md)** — Install and deploy in 4 ways: Manual (`start.sh`), Docker, npm (`npx free-short-video`), or AI-Agent assisted.
- **[AI Agent Operations](docs/public/agent-operations.md)** — How to drive this project with a coding agent: install the standalone `agnes-video` skill once, then ask for outcomes — it installs the service, generates videos, diagnoses failures and can open a PR for a real defect.
- **[Usage Guide](docs/public/usage.md)** — Configure your API key, pick a video mode, resume from checkpoints, the three chaining modes, and logs & output layout.
- **[Architecture](docs/public/architecture.md)** — Project structure and tech stack.
- **[API Reference](docs/public/api.md)** — Full REST endpoint list (progress via polling, no WebSocket).
- **[FAQ](docs/public/faq.md)** — Frequently asked questions.
- **[About & License](docs/public/about.md)** — Acknowledgments and the MIT license.

## 🌐 Related Projects

More projects by the same author:

- **[Agnes Video Generator](https://github.com/lcy362/agnes-video-generator)** — Completely free AI video generator (this project).
- **[FreeShortVideoStudio](https://github.com/lcy362/free-short-video-studio)** — Fully online, in-browser video studio.
- **[Flint](https://github.com/lcy362/flint)** — Local-first AI skills manager: centralize, tag, deduplicate and deploy your Skills into any agent or project directory. If it helps you, a star is very welcome! ⭐

**Keywords**: free AI video generator, AI video generation tool, text to video AI, free AI video maker, AI video creator, open source video generator, Agnes AI, text-to-video, image-to-video, keyframes video, AI narration, auto subtitles, multi-scene video, zero cost AI video, no subscription AI video tool, digital anchor, self-hosted AI video generator, open source alternative to Runway

---

## 🛠️ Gujarati AI News Anchor — Development Progress

> Progress log for the Gujarati female news-anchor workflow. This section records only verified repository/deployment findings; a successful website build does **not** mean that audio or a talking-anchor video has been tested successfully.

### Latest verified status — 25 October 2026

- **Deployment:** Vercel deployment is `READY`; build logs report `Build Completed` and `Deployment completed`.
- **Gujarati text-to-speech:** The repository declares `edge-tts` in `requirements.txt`. Actual Gujarati audio generation and playback have **not yet been verified**.
- **Anchor lip-sync:** A successful end-to-end lip-sync test has **not yet been verified**.
- **Video export/download:** A complete generated anchor video and its download have **not yet been verified**.

### Next work

1. Trace the existing voice-generation path and confirm it selects a Gujarati female voice for Gujarati scripts.
2. Run a real Gujarati text-to-speech test and verify that audio is produced and playable.
3. Connect the generated audio to the existing anchor-video workflow and test lip-sync.
4. Verify the finished video and download path; record actual test results here.

**Important:** This log is a progress record, not a claim that the unfinished tests have passed. It will be updated when a concrete code change or test result is confirmed.


### Investigation update — 25 October 2026, 17:32 IST

- **Code path inspected:** `core/pipelines/anchor_video.py` and `core/audio/tts.py`.
- **Confirmed behavior:** the anchor pipeline generates Edge-TTS narration only when `audio_source=post_stitch`; `audio_source=model` intentionally skips the project's TTS step. A Gujarati script switches from the default Chinese voice to `gu-IN-DhwaniNeural`, while an explicitly chosen voice is preserved.
- **Not yet verified:** the deployed service has not been run with a real Gujarati script/audio request, so voice availability, playable audio, lip-sync, and final video download remain unproven.
- **Next engineering step:** verify the actual voice catalog and request/config path, then run a real Gujarati TTS smoke test before changing the lip-sync pipeline. No mock audio or demo result will be used.

- **Code fix committed:** `core/audio/tts.py` now rejects an empty Edge-TTS audio stream before replacing the output file, and logs the saved audio byte count. This prevents a zero-byte MP3 from being mistaken for successful speech generation. Commit: `19c3535234d575dd7069b35c7ce9a8eef0ad05c2`.
- **Test status:** source change committed; automated tests and a live Gujarati audio request have not been run in this environment. Do not treat this as proof that Gujarati speech generation works end-to-end.


- **Gujarati TTS cache fix committed:** voice selection now happens before the cached-audio check. Gujarati scripts using the default voice select `gu-IN-DhwaniNeural` and use a voice-specific output filename, preventing an existing default-voice narration from being reused accidentally. Commit: `fdee3b5456b4f5d3033e41fb4ec508a40d93f9c4`.
- **Verification status:** source re-read after commit and the expected change is present. No live Gujarati TTS request or end-to-end video test has run yet; deployment and real audio playback remain unverified.


## Gujarati anchor lip-sync — current engineering status (2026-10-25)

- Confirmed: `post_stitch` currently generates a short five-second image-to-video anchor clip, then loops it and overlays a separate TTS narration. This synchronizes the audio track with the video duration, but it does **not** synchronize mouth shapes to Gujarati phonemes.
- Confirmed: repository code search did not find an existing Wav2Lip/lip-sync implementation or dedicated lip-sync provider integration.
- The Gujarati TTS voice/cache fix is present on `feature/gujarati-news-anchor-lipsync`.
- No new lip-sync implementation has been committed yet. A genuine solution needs a supported lip-sync model/service or an available model endpoint; simply changing FFmpeg timing cannot create accurate mouth movement. Do not mark a render as lip-synced unless that stage actually ran successfully.
- Verification still required: generate a real Gujarati narration, run the selected lip-sync stage, inspect the output video/audio streams and playback, and then verify the deployed build. Vercel's deployment being READY only confirms deployment readiness, not that a real AI render works.
