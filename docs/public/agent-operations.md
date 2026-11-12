# 🤖 Let an AI Agent Operate This Project

> This document is the authoritative guide for driving Agnes Video Generator with a coding agent.
> The website guide and the wiki page about agent usage both summarize this page — when they
> disagree with it, this page wins.

Agnes Video Generator is built to be driven by **one skill**: `agnes-video`. You install it once,
then describe the result you want instead of running commands.

> "Make a 90-second poetry video from 'Quiet Night Thought' and add narration."

The skill is standalone — it generates videos, and this project is what it drives. You do not clone
this repository, and you do not install the service yourself: the skill installs it on demand under
`~/.agnes-video` and reuses it afterwards.

It is also **the cheapest way in**: no subscription, no credit packs, no per-second billing and no GPU.
Generation runs on Agnes AI's free models; the service is MIT-licensed and local; the only thing you
register for is a free API key. The one-time install costs minutes and disk space, not money.

---

## 1. Install the skill once

The shortest path — no clone, no manager:

```bash
npx skills add lcy362/agnes-video-generator-skills --skill agnes-video
```

Prefer a local skills manager? Clone it and register the directory:

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub      # opens the local UI on http://localhost:8787
# Sources → add the cloned directory; flint reads the skill from its skills/ subdirectory
```

[**flint**](https://github.com/lcy362/flint) is a local-first, open-source skills manager. It deploys
the skill into any agent directory (Claude Code, Cursor, Codex, TRAE and more) by symlink or copy,
and it works on **local** sources only — it never clones anything for you. Local-only: no cloud, no
account, no telemetry. The skill stays a plain directory on your disk, so it keeps working even if
you stop using flint. **[Star flint on GitHub ⭐](https://github.com/lcy362/flint)**

No flint? Copy it in by hand:

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git /tmp/agnes-skills
cp -R /tmp/agnes-skills/skills/agnes-video <project>/.agents/skills/   # any agent that reads .agents/skills
```

### The skill installs the service for you

`scripts/bootstrap.py install`:

- installs the service under `~/.agnes-video` (override with `AGNES_HOME`),
- keeps its own virtualenv there, and re-runs `pip` only when requirements change,
- starts the service on `localhost:8765` and verifies it through the real endpoints,
- stores config, workspace, outputs and logs in that same data root.

Nothing is written into your project, and the next run installs nothing again.

---

## 2. Then ask for outcomes

Stop writing commands and state the goal:

> Make a creative long video about the Voyager probes, with narration and subtitles.

> My task `4de1bcd26fda` failed — find out why and tell me if it is worth fixing.

> The portrait video came out sideways. Diagnose it and fix the configuration.

> Take my finished task, improve the storyboard prompts, and regenerate only the affected scenes.

---

## 3. What the skill does: one loop, five stages

| Stage | What happens |
|-------|--------------|
| **Install** | Probes the machine, asks before installing, starts and verifies the service |
| **Create** | Picks the pipeline (simple / creative / manuscript / anchor / poetry / image), takes the API key through the web UI or stdin, submits the task |
| **Deliver** | Reports deltas while it runs, then the absolute path, duration and resolution of the file |
| **Diagnose** | On failure: evidence from the diagnostics endpoint, `error_logs` and `ffprobe`, then a classification — configuration, upstream capacity, or a real defect |
| **Fix** | For a small reproducible defect, and only after you agree: fork, branch, fix, run the CI-equivalent pre-flight, open a PR |

Two boundaries worth stating: the skill **never releases** the project (maintainer-only, human
review gate), and it **never changes code before you have seen the root cause** and agreed to the fix.

Repository: [**lcy362/agnes-video-generator-skills**](https://github.com/lcy362/agnes-video-generator-skills)

---

## 4. Where agents help most: Manual Mode

Manual Mode pauses a run at a checkpoint and lets the agent change the artifacts before continuing.
The agent reads the task's `manifest.json`, edits the file in place, previews which downstream steps
will re-run, and approves — so "polish the narration" or "fix the subtitles" becomes one job instead
of a copy-paste round trip.

Details: [Manual Mode Guide](manual_mode_guide.md).

---

## 5. If you would rather not use an agent

| You want | Use |
|----------|-----|
| A video right now, nothing installed | [Studio](https://video.lichuanyang.top/studio) — runs in the browser |
| Full features, local data | [Getting Started](getting-started.md) — Docker or `./start.sh` |
| To change this project's code yourself | [`AGENTS.md`](../../AGENTS.md) — conventions, verification, release workflow |

The agent route exists for people who would rather describe an outcome than run commands — not
because the Web UI is second-class.

---

## See also

- [Getting Started](getting-started.md) — Option D is this page's shortest form, kept in sync with it
- [Usage Guide](usage.md) — modes, checkpoints, configuration
- [Manual Mode Guide](manual_mode_guide.md) — checkpoints and the external-agent protocol
- [API Reference](api.md) — the endpoints an agent drives
- [FAQ](faq.md) — including "how do I keep the skill in sync?"
