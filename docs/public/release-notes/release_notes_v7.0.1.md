# Release v7.0.1 — Fully Localized Backend Messages and Provider Setup Guidance

> Release date: 2026-09-24

## Overview

v7.0.1 is a patch release that completes the interface-language localization started in
v7.0.0: every remaining back-end-generated message — pipeline progress steps, parameter
validation errors, voice/language compatibility warnings, workspace and gallery errors — now
follows the UI language instead of being hard-coded Chinese. Non-Chinese users no longer see
Chinese strings mid-run in creative, manuscript, anchor or poetry video workflows. It also adds
third-party text provider setup guidance (a recommended provider with a step-by-step
free-token guide link) to the configuration panel, in all 22 interface languages. No breaking
changes.

## Usage

From v7.0.0, source install:

```bash
git pull
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.0.1`.

npm users: `npx free-short-video`.

Upgrade notes:

- No breaking changes and no data migration.
- Messages of tasks created before the upgrade keep the language snapshot taken at creation
  time, so in-flight or historical tasks may still show Chinese progress text.
- Chinese and English are fully covered; the other 20 languages fall back to Chinese until
  their catalogs are filled in.

## What's New

### Features & Improvements

- **Provider setup guidance in Settings.** When adding a third-party text model provider, the
  configuration panel now shows practical notes with a recommended provider (AMD Radeon
  Cloud) and its OpenAI-compatible endpoint, plus a link to a step-by-step guide for
  collecting free tokens. Available in all 22 UI languages.
- **Localized backend messages everywhere.** The localization framework shipped in v7.0.0 has
  been extended from high-impact messages to the complete set: ~120 remaining strings across
  all six task types — progress updates for every pipeline step, task-creation and preview
  validation errors, config/provider validation, voice-compatibility warnings and cleanup
  tooling messages — are rendered in the task's UI language.

### Refactoring & Optimizations

- **Single bilingual message catalog for the backend.** All user-facing backend strings now
  live in one translation catalog (~200 keys) with CI-enforced Chinese/English parity and a
  documented contributor convention (domain-based key naming, keyword placeholders, per-request
  vs per-task language sources), making the interface-language behavior a maintained invariant
  rather than an ad-hoc practice.

### Bug Fixes

- English-interface users no longer receive Chinese progress messages and validation errors
  in simple, creative, manuscript, anchor and poetry video tasks (follow-up to issue #64).
- Reference-image analysis failures ("image analysis failed (Start Frame)") are reported in
  the task's UI language instead of hard-coded Chinese (issue #65 follow-up).

---

No action is required after upgrading.
