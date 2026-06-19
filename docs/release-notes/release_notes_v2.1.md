# Release v2.1 — Code Review Fixes + Regression Test Framework + Quality Improvements

> Release date: 2026-06-16

## Overview

v2.1 focuses on code quality and engineering robustness. All 24 issues from the full code review have been fixed, and an automated regression test framework has been introduced to ensure long-term stability.

---

## Code Review Fixes

Based on `docs/plans-v2.0/code_review_report.md`, all 24 issues resolved:

### High Severity (H1-H6)
- **H1** — API Key hardcoded in `agnes_chat.py` → unified read from `config.py`
- **H2** — Path traversal in `server.py` file upload → safe path join with `os.path.basename`
- **H3** — Missing font fallback in `concatenator.py` subtitle overlay → `resolve_font_path` CJK fallback
- **H4** — Shell injection in `processor.py` → list arguments instead of `shell=True`
- **H5** — moviepy `write_videofile` log leakage in `subtitle.py` → redirect to `devnull`
- **H6** — JSON parse failure in `screenwriter.py` → LLM retry with fallback parsing

### Medium Severity (M1-M10)
- Index / bounds safety (M1-M3)
- Overly broad exception handling → granular catch (M4-M5)
- Task directory path normalization (M6)
- Unified HTTP timeouts (M7)
- Task state race condition (M8)
- TTS file handle leak (M9)
- Frontend i18n variable shadowing (M10)

### Low Severity (L1-L8)
- Automated unit test framework (L1)
- Typo fixes (L2-L3)
- Redundant documentation cleanup (L4-L5)
- AGENTS.md alignment with code (L6)
- Dead file cleanup (L7-L8)

---

## Regression Test Framework

- **9 scenarios concurrent execution** (3 simple + 4 creative + 2 manuscript)
- Weighted semaphore for parallelism control (total weight ≤ 10, 50% API headroom)
- Incremental JSON report + Markdown readable report
- Resume / quick-verify modes
- `--cleanup` safe artifact removal

### Endpoint Verification (E1-E9)
All 9 endpoints auto-verified: homepage, config, three task creation endpoints, task query, resume, stop

### Artifact Verification (F1-F7, R1-R10)
- `final_video.mp4` existence + non-empty + duration + resolution
- Audio track + whisper ASR speech content matching
- SRT subtitle entry validation
- Resume checkpoint completeness

---

## Other Improvements

- **Subtitle multi-line wrapping** — dynamic `max_chars_per_line`, CJK punctuation break priority, `method="caption"` rendering
- **TTS** — auto 2.5x volume boost, edge case error handling
- **Concatenator** — single-video shortcut optimization, subtitle overlay failure degradation (non-blocking)
- **start.sh** — auto venv creation, dependency install, macOS browser auto-open
- **Requirements** — pinned `edge_tts>=7.0.0`, `srt>=3.5.0`, `moviepy>=2.0.0`
- **Config** — API Key clear functionality, enhanced font path fallback
- **Static analysis integration** — each `Taskfile` includes `ruff` + `mypy` checks

---

## Stats

```
26 files changed, 1,611 insertions(+), 235 deletions(-)
```

### New / Deleted Files
| File | Action | Description |
|------|--------|-------------|
| `docs/plans-v2.0/code_review_report.md` | +added | 24 code review issues documented |
| `docs/release-notes/release_notes_v2.0.md` | +added | v2.0 release notes |
| `docs/release-notes/release_notes_v2.1.md` | +added | v2.1 release notes |
| `tests/test_core.py` | +added | 428-line automated unit test suite |
| `test_ref.png` / `test_end.png` | +added | Regression test assets |
| `_test_reset.py` | -deleted | Deprecated test script |
| `start.sh` | refactored | One-click startup with auto venv + deps + browser |

---

## Upgrade Notes

From v2.0:
```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Run regression tests:
```bash
.venv/bin/python scripts/regression_runner.py --auto-start
```
