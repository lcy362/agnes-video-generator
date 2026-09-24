# Release v7.0.0 — Pluggable Text Model Providers and Localized Backend Messages

> Release date: 2026-09-23

## Overview

v7.0.0 is a **major release** that opens the text-model layer to any OpenAI-compatible or
Anthropic-compatible LLM provider. You can now add your own provider (base URL + API key),
fetch or hand-write its model list, and switch the model used by script writing, scene
planning, poetry segmentation and prompt rewriting — while the built-in Agnes model stays as
the zero-config default. It also localizes backend-generated user-facing messages (task
progress, failure panels, HTTP errors and diagnostics) to the interface language, so English
users no longer receive Chinese-only error reports. No breaking changes: existing tasks,
checkpoints and configurations keep working.

## Usage

From v6.5.x, source install:

```bash
git pull
.venv/bin/pip install -r requirements.txt
./start.sh
```

Docker users: `docker pull ghcr.io/lcy362/free-short-video:7.0.0`.

npm users: `npx free-short-video`.

Upgrade notes:

- No breaking changes and no data migration. Existing tasks, checkpoints and `config.json`
  files are read as-is; the built-in `agnes` provider remains the default until you switch.
- Custom provider API keys are stored in the local `config.json` (file mode `0600`) and are
  only ever returned to the UI in masked form.
- Anthropic-compatible providers cover text generation; multimodal (image input) calls fall
  back to text-only in this release.

## What's New

### Features & Improvements

- **Custom text model providers (OpenAI-compatible / Anthropic-compatible).** Configure any
  LLM endpoint with `base URL + API key` and two supported wire protocols
  (`openai-completions`, `anthropic-messages`). Once selected, every text call — screenplay
  breakdown, scene planning, poetry segmentation, image-prompt rewriting — is routed to your
  provider automatically. The built-in Agnes provider is always available, cannot be deleted,
  and keeps the previous behaviour when no custom provider is selected.
- **Provider management panel.** A dedicated settings section lists all text providers, lets
  you add, edit and delete them, and keeps the Agnes key/domain editing inside the provider
  modal. Keys are masked in the UI, and the provider's model list is a single editable list:
  fetch it from the endpoint or type model ids by hand. Model selection is a two-level
  provider → model picker that merges the models of all providers.
- **Interface-language aware backend messages.** Task progress messages, failure panels, HTTP
  error details and the diagnostics report are now localized according to the UI language
  instead of being hard-coded Chinese. The UI language travels with every request
  (`X-Agnes-UI-Lang`, falling back to `Accept-Language`), is snapshotted into each task at
  creation time, and therefore does not drift if the user switches language later. Chinese and
  English are covered; the remaining languages fall back to the existing behaviour.
- **Clearer network failure diagnosis.** TLS handshake resets (`connection reset`) are now
  attributed to local-connection problems, and the diagnostics report shows the interface
  language of the reporting user, making failure reports easier to triage.

### Refactoring & Optimizations

- **Decoupled text-generation layer.** A new protocol-client layer
  (`core/api/providers/` → base / OpenAI / Anthropic) plus a provider factory replaces the two
  hard-coded Agnes chat client constructions, so pipelines and the screenwriter are untouched
  while the underlying model source becomes pluggable. Custom providers reuse the existing
  shared rate limiter and exponential-backoff retry policy, and failures are recorded in the
  same error log as before.
- **Backend i18n runtime.** A new translation runtime plus request-scoped language middleware
  gives the FastAPI side the same localization guarantees the frontend already had, with a
  safe fallback chain that never turns a missing translation into a request failure.

### Bug Fixes

- Model pulling for an already saved provider now reuses its stored credentials instead of
  falling back to the Agnes key.
- The built-in Agnes provider no longer appears twice in the provider picker and is now
  labelled as text-only.
- Non-Chinese interfaces no longer receive hard-coded Chinese network-diagnosis and task
  messages (issue #64).

---

No action is required after upgrading.
