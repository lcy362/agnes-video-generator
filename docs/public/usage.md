# 📖 Usage

## 1. Configure API Key

Enter your free [Agnes AI](https://platform.agnes-ai.com) API key at the top of the page and save it. Or set it via environment variable:

```bash
export AGNES_API_KEY="your-api-key"
```

## 2. Choose a Video Mode

### Simple Video

Quick single-clip generation with full parameter control:

| Field | Description |
|-------|-------------|
| Prompt | Describe the AI video scene in natural language |
| Generation Mode | Text-to-Video / Image-to-Video / Text+Image / Keyframes |
| Resolution | Portrait 9:16 / Landscape 16:9 / Square 1:1 |
| Duration | 5s / 10s / 15s / 18s / 20s |
| Reference Image | Optional upload for image-to-video modes |
| End Frame Image | Optional end frame for keyframes mode |

### Creative Video

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

### Manuscript Video

Long-form text to narrated video:

| Field | Description | Required |
|-------|-------------|----------|
| Manuscript Text | Paste your full article, script, or narration | Yes |
| Resolution | Portrait / Landscape / Square | - |
| Narration | Voice role and speech rate | - |
| Subtitle Style | Full subtitle customization | - |

> **Note**: Segment duration is auto-calculated based on text length (~4 chars/sec, 5–12s per segment) — no manual setting needed.

### Digital Anchor

| Field | Description | Required |
|-------|-------------|----------|
| Anchor Script | Enter the text the anchor will say | Yes |
| Anchor Image | AI-generated or upload custom reference image | - |
| Resolution | Portrait / Landscape / Square | - |
| Narration | Voice role and speech rate | - |
| Subtitle Style | Full subtitle customization | - |

## 3. Click "Start Generating"

The progress panel shows real-time generation status for each step. For Creative Video: Init → Image Analysis → Story → Script → Narration → Character Reference → End Frame Prompts → End Frame Generation → Video Generation → Audio & Subtitles → Concatenation.

## 4. Checkpoint Resume & Task Management

If the server is interrupted, restart it and find the incomplete task in the "Task List" tab. Click "Resume" to continue from the last checkpoint. Running tasks can also be stopped and resumed later.

## 5. Manual Mode (v6.0)

> Full guide: [`manual_mode_guide.md`](./manual_mode_guide.md)

Manual mode pauses the pipeline at checkpoints so you can review or refine artifacts before continuing:

```
scenes → references → videos → audio → subtitle → final
```

- **Create**: choose "✋ Manual" at the top of the create panel and tick the pause points (defaults pre-filled per task type).
- **Switch anytime**: the "切回自动 / 切为手动" toggle on the task card. Auto→Manual suspends at the next safe point; Manual→Auto clears pause points and runs to completion immediately.
- **Three ways to handle artifacts** at a paused checkpoint:
  - 🤖 **AI Modify**: type a request, the system rewrites the artifact (text via chat / image via i2i / video via ffmpeg command).
  - ✏️ **Edit yourself**: copy the artifact path, edit locally, then click "I've modified, continue".
  - 🤝 **External Agent**: copy `cd <dir> && traework` (or another local agent, e.g. opencode) + prompt template, process, then confirm.
- **Change anything**: artifacts **and** task params (resolution / voice / duration / scene count) can be edited while paused. The system previews which artifacts will be deleted & re-run vs kept before you confirm (dependency graph).
- Not supported: simple / simple-image types (read-only artifact list after completion).

## ⚠️ Important Notes

This project is in early stage — corner cases may not be fully handled. Recommended workflow:

1. Fill in your idea on the page and submit an AI video task
2. Watch the **console logs** (the terminal running `server.py`) and be patient
3. All key operations are logged for easy debugging

### Upstream limits you should know (v7.0)

- **Free queue saturation**: Agnes can reject submissions for 10+ minutes with `video_queue_full`. The app keeps retrying on a dedicated track (up to 15 retries by default, `AGNES_VIDEO_BUSY_RETRY_ATTEMPTS`; the first retry fires immediately and later ones every 30–60s) and shows in the progress panel: `Agnes 视频队列已满（HTTP 503 · video_queue_full），正在排队重试（第 N 次 / 已等 X 分钟）。建议错峰重试或稍后再试。` Nothing is consumed by a rejected submit — just retry off-peak, or switch to another video model.
- **~15-minute inference hard cut-off**: if upstream aborts a job, the failure message contains the upstream wording (e.g. `inference not finished after 15 minutes (code=500)`) — waiting longer will not produce a video.
- **Video 2.5 Flash portrait (9:16) rotation defect**: upstream returns sideways frames for this one combination. The UI warns you when you pick it; use `16:9` / `3:4` / Video 2.0 portrait, or opt into automatic correction with `AGNES_FIX_V25_PORTRAIT_ROTATION=1`.
- **Model capabilities ship with releases**: a model listed in the dropdown but marked `⚠` is not adapted by your current version — upgrade to use it. The running version is shown in the page footer.

### Log Reference

All important operations are logged to the server console:

| Prefix | Module |
|--------|--------|
| `[Startup]` | Server startup, stale task reset |
| `[Workspace]` / `[Concurrency]` | Workspace switch & concurrent-task limits |
| `[Resume]` / `[Stop]` | Task resume/stop |
| `[Pipeline]` / `[Simple]` / `[Manuscript]` | Pipeline step execution |
| `[TTS]` / `[Subtitle]` | Audio and subtitle generation |
| `[Compositor]` | Video concatenation and processing |
| `[AgnesImage]` / `[AgnesVideo]` / `[AgnesChat]` | AI API calls |
| `[UpstreamRotate]` | 2.5-series portrait rotation correction (opt-in, v7.0) |
| `[KeyRotation]` | Swapping API keys on HTTP 429 |
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
