# Simple Video Maker

A single, simple page for generating Arabic/English YouTube Shorts, built on top
of Agnes Video Generator.

## How to run

**Easiest — no Terminal needed:** in Finder, double-click
**`Launch Simple Video Maker.command`**. A small window pops up briefly while
it starts everything, then your browser opens automatically at
`http://localhost:8787`. You can close that window once the page has opened.

**Alternative (Terminal):**
1. Open Terminal.
2. Run:
   ```
   ./run.sh
   ```
3. Wait a few seconds — your browser opens automatically at
   `http://localhost:8787`.

Either way: fill in the form and click **Generate Video**. The launcher starts
the video-generation engine in the background if it isn't already running, so
you don't need to do anything else.

## One-time prerequisite (already done)

The video engine (Agnes) needs an API key configured once. This has already
been set up on this computer — you don't need to do anything for this.

## Using the page

1. **Language** — pick Arabic or English. This decides which voices are shown
   and which language you should type your topic/script in.
2. **Content**:
   - *"I have a script"* — paste your full narration text, click **Preview
     Split** to see how it breaks into scenes, then **Generate Video**.
   - *"Just a topic"* — type a short topic, set the number of scenes and
     total duration, click **Preview Script** to see what will be generated,
     then **Generate Video**.
3. **Voice** — pick a voice and click ▶ to hear a sample before generating.
4. **Subtitles** — toggle on/off; if on, pick a color/position/size.
5. Click **Generate Video** and wait — you'll see a progress bar, then a
   narration-only audio preview, and finally the finished video with a
   download link.
6. **Cover image** — separately, describe a background image and type a
   title; it generates an image and burns the title onto it automatically.

## Troubleshooting

- If the page doesn't open, check `/tmp/simple-ui.log` and
  `/tmp/agnes-backend.log` for errors.
- If port 8787 or 8765 is already used by something else, set
  `SIMPLE_UI_PORT` / `AGNES_PORT` environment variables before running
  `./run.sh`.
