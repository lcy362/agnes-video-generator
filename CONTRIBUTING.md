# Contributing to Agnes Video Generator

Thanks for wanting to help. This guide covers where to file things, what reviewers look for, and the terms that apply to showcase submissions.

> For deployment and usage, see [`docs/public/getting-started.md`](docs/public/getting-started.md) and the [FAQ](https://video.lichuanyang.top/en/faq).

---

## 1. Pick the right channel

| I want to… | Go to |
|---|---|
| Report a bug, a failed render or a crash | **Issues** → `Bug report` template (the in-app "Report on GitHub" button pre-fills diagnostics) |
| Suggest a feature or ask how something works | **Discussions** → `Q&A` or `General` |
| Debug a self-hosted deployment | Check [`docs/public/getting-started.md`](docs/public/getting-started.md) and the [FAQ](https://video.lichuanyang.top/en/faq) first, then open a `Q&A` discussion |
| **Share something you made with this project, and the prompt behind it** | **Discussions** → `Show and tell` (there is a submission form — see section 3) |
| Change the code | Pull request (see section 2) |

> Just want to generate a video? Use the **[online demo](https://video.lichuanyang.top/en/demo)** — it runs in your browser with your own API key. Issues are not a generation entry point.

---

## 2. Code contributions

### 2.1 Local setup

```bash
python3 --version   # 3.10+
./start.sh          # creates a venv, installs dependencies, serves http://localhost:8765
```

Manual / Docker / npm options are documented in [`docs/public/getting-started.md`](docs/public/getting-started.md).

### 2.2 Checks that must pass (same as CI)

```bash
# 1) Static analysis (CI runs ruff; also py_compile the files you touched)
ruff check core/ web/ utils/ models/ scripts/
.venv/bin/python -m py_compile <files you changed>

# 2) Translation completeness (a missing `en` string fails with exit code 2)
python scripts/i18n_check.py

# 3) Unit tests (CI enforces a 55% coverage floor)
.venv/bin/python -m pytest tests/ -q

# 4) If you changed frontend sources, rebuild and commit the artifacts (CI verifies that
#    static/ matches frontend/ sources)
cd frontend && npm test && npm run build
```

### 2.3 Hard rules

1. **Every user-visible string must exist in all 22 language files** (`i18n/langs/*.json`). A missing `en` string is a hard CI failure.
2. **Frontend artifacts must match the sources**: after touching `frontend/`, run `npm run build` and commit the `static/` diff.
3. **Never commit secrets or private data**: API keys, tokens, private paths, email addresses or phone numbers must not appear in code, tests, docs or screenshots.
4. **Do not touch unrelated files** and do not refactor opportunistically. For large renames, open a discussion first.
5. **Before changing pipelines or upstream retry policy**, read [`docs/dev/agnes_video_upstream_behavior.md`](docs/dev/agnes_video_upstream_behavior.md) — it records how the upstream API actually behaves (failures returned as HTTP 200, queue saturation, the 15-minute inference ceiling, resolution snapping, and the 2.5-flash portrait rotation issue).

### 2.4 Pull requests

1. Fork, or branch in this repository (`fix/…`, `feat/…`, `docs/…`).
2. One concern per pull request. Describe *problem → change → how you verified it*, including the actual output of the four checks above.
3. Write commit messages in English, short and imperative (`Fix subtitle drift on long scenes`).
4. Link the issue with `Fixes #123`.
5. Merged once CI is green and a maintainer approves. Release rules live in [`docs/dev/release_process.md`](docs/dev/release_process.md).

---

## 3. Showcase

Built something good with this project? The official website has a showcase that presents the **video together with the prompt** that produced it.

### 3.1 How to submit

Post in **Discussions → `Show and tell`** using the submission form. It asks for:

- a publicly accessible video URL
- the title in its original language, plus an English title
- the **original prompt, pasted verbatim** (no translation, no shortening) and its language
- an optional English meaning note that readers of every language will see
- the task type (`simple`, `creative`, `manuscript`, `anchor`, `poetry`, `simple_image`)
- optional generation settings (model, duration, resolution, scene count)

### 3.2 What happens to a submission

| Destination | Notes |
|---|---|
| ✅ Your own account | The video stays on **your** channel or platform. Views and subscribers are yours. |
| ✅ Website showcase | If featured, it appears with the video, the verbatim prompt, the English meaning note and the settings, **credited with a link back to you**. |
| ✅ Official YouTube playlist | If featured, it may be added to the official playlist `Community Showcase`. YouTube allows any public video to be added to another channel's playlist — **no re-upload is involved**. |
| ❌ Official channel itself | We do **not** re-upload submissions to the project's own YouTube channel. This avoids copyright and account-liability problems. If you want a genuine joint production, open a `General` discussion and we will agree on terms separately. |

### 3.3 Licence you grant (important)

By submitting, you:

1. **Confirm you hold the rights**: the work is your own, or you have obtained every necessary permission. You are responsible for the audio it uses (TTS or music) and for any real person's likeness that appears in it.
2. **Grant a revocable, non-exclusive, royalty-free, worldwide licence** allowing this project to display the work and its prompt on the official website and to include the video in the official YouTube playlist `Community Showcase`, with attribution.
3. **Keep your copyright**: this licence does not transfer ownership of the work.
4. **May request removal at any time** by commenting on your post. The website is statically generated, so removal takes effect at the **next deployment** (usually within a day or two); removal from the playlist is immediate.
5. **Understand that selection is not guaranteed**: maintainers curate submissions by hand (complete render, reproducible prompt, no copyright or likeness risk) and may remove featured items at any time without giving a reason.

### 3.4 Common reasons a submission is not featured

- The render is incomplete, or is obviously a failed test artifact.
- The prompt is missing, or has been shortened so much that it cannot be reproduced.
- Third-party music, footage or a real person's likeness is used without permission.
- The content is unsuitable for an official product page (violence, sexual content, political advocacy, misleading medical or financial claims, and so on).

---

## 4. Code of conduct

All interactions in this project — issues, discussions, pull request reviews — must follow the [GitHub Community Guidelines](https://docs.github.com/articles/github-community-guidelines). Be respectful, avoid personal attacks, do not post spam, and do not spread infringing or misleading content. Maintainers may remove violating content and restrict participation.

---

## 5. Licence

- **Code** is licensed under the [MIT License](LICENSE). By submitting a pull request you agree that your contribution may be distributed under the same licence.
- **User-created content** (videos, prompts) remains the property of its author; this project only displays it under the terms in section 3.3.
