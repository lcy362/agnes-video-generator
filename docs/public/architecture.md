# 🏗️ Project Structure

```
agnes-video-generator/
├── start.sh                          # One-click launch script
├── requirements.txt                  # Python dependencies
├── Dockerfile                        # Multi-arch Docker image (Python 3.11 + ffmpeg via imageio)
├── docker-compose.yml                # Docker Compose with persisted volumes
├── docker-run.sh                     # One-command Docker launch (wrapper with bind mounts)
├── server.py                         # FastAPI server (REST only; progress via task-state polling, no WebSocket)
├── web/                              # Web layer: routers / shared deps / middleware
│   ├── middleware.py                 # LangContextMiddleware — per-request UI language (v7.0)
│   └── routes/                       # APIRouter modules (config/workspace/voice/image/video/task/creation/utility/preview)
├── static/                           # Frontend build artifacts (committed to git)
│   ├── index.html                    # Built SPA entry (Vite output, base=/static/)
│   └── assets/                       # Hashed JS/CSS bundles
├── frontend/                         # Frontend source (Vue 3 + Vite + TypeScript)
│   ├── vite.config.ts                # outDir=../static, base=/static/, emptyOutDir=false
│   └── src/                          # Components / composables / i18n / api
├── core/
│   ├── config.py                     # API key, fonts, defaults, text-provider settings
│   ├── i18n_backend.py               # Backend i18n runtime: language parsing + message catalog (v7.0)
│   ├── screenwriter.py               # Screenwriter Agent (LLM-powered story/script/narration)
│   ├── task_manager.py               # Task state persistence & checkpoint resume
│   ├── api/
│   │   ├── agnes_chat.py             # Built-in LLM Chat API (agnes-3.0-flash)
│   │   ├── chat_providers.py         # Text-client factory: built-in Agnes or a custom provider
│   │   ├── providers/                # Wire-protocol clients: base / openai-completions / anthropic-messages
│   │   ├── agnes_image.py            # Image generation API (agnes-image-2.5-flash; 2.1 / 2.0-flash selectable)
│   │   ├── agnes_video.py            # Video generation API (agnes-video-v2.0)
│   │   └── rate_limiter.py           # Dual token buckets (shared 20 × keys × 0.8/min + video-submit bucket)
│   ├── audio/
│   │   ├── tts.py                    # Edge TTS engine + silent fallback engine
│   │   └── subtitle.py               # SRT generation (fine-grained word-level) + overlay
│   ├── compositor/
│   │   ├── concatenator.py           # Video concatenation + audio/subtitle overlay
│   │   └── processor.py              # Video resize, frame extraction, freeze, silence gen
│   └── pipelines/
│       ├── multi_scene.py            # Template-method base class for multi-scene pipelines
│       ├── simple_video.py           # Pipeline: Simple Video
│       ├── creative/                 # Pipeline: Creative Video (script → frames → video → narration → stitch)
│       ├── manuscript_video.py       # Pipeline: Manuscript Video
│       ├── anchor_video.py           # Pipeline: Digital Anchor
│       └── poetry_video.py           # Pipeline: Poetry Recitation
├── models/
│   └── task.py                       # Data models (6 task types, configs, requests)
├── resource/
│   └── fonts/                        # Built-in CJK fonts for subtitle rendering
├── utils/
│   ├── image.py                      # Image download / base64 conversion
│   └── video.py                      # Video download
├── scripts/
│   └── regression_runner.py          # 14-scenario regression test suite
└── docs/
    ├── plans/                         # Plan docs (versioned + optimization research)
    ├── public/                        # User-facing docs (README-linked)
    └── dev/                           # Internal architecture / QA docs
```

# 🔧 Tech Stack

| Layer            | Choice                                         | Notes                                                                |
| ---------------- | ---------------------------------------------- | -------------------------------------------------------------------- |
| Backend          | Python FastAPI                                 | REST only; progress via task-state polling (**no WebSocket**)         |
| Backend i18n     | Request-scoped language context                | `X-Agnes-UI-Lang` > `Accept-Language` > `zh`; localizes task messages, HTTP errors, diagnostics |
| Frontend         | Vue 3 + Vite + TypeScript + Tailwind (PostCSS) | Build output committed to `static/`; zero runtime deps for end users |
| LLM              | Pluggable text providers                       | Built-in Agnes Chat (`agnes-3.0-flash`) by default; bring your own OpenAI-compatible / Anthropic-compatible endpoint (base URL + key) for story / script / narration |
| Image AI         | `agnes-image-2.5-flash` (t2i / i2i)            | Free — reference images, end frames, standalone image generation     |
| Video AI         | `agnes-video-v2.0`                             | Free — text-to-video, image-to-video, keyframes                      |
| TTS              | Edge TTS (Microsoft)                           | Free — dynamic voice catalog grouped by 22 UI languages, no extra key |
| Subtitles        | moviepy + srt                                  | Fine-grained word-level SRT, multi-line wrapping                     |
| Video Processing | moviepy + ffmpeg                               | Concatenation, subtitle overlay, audio mixing                        |

# 🔌 Text Model Providers (v7.0)

Text generation is pluggable. Every text call — screenplay breakdown, scene planning, poetry
segmentation, image-prompt rewriting — goes through one factory that dispatches on the currently
selected provider:

```
pipelines / screenwriter / video_routes
  └─ get_or_build_text_chat_client()          # core/api/chat_providers.py
       ├─ "" or "agnes" → AgnesChatAPI        # built-in, behaviour unchanged
       └─ <custom>      → OpenAIChatClient | AnthropicChatClient   # core/api/providers/
```

- **Provider record** (`config.json` → `text_providers[]`): `provider` (unique route key),
  `display_name`, `api`, `base_url`, `api_key`, `models[]`. The active route is stored in
  `models.text_provider` (empty = built-in Agnes), the model id in `models.text`.
- **Wire protocols**:
  - `openai-completions` — `{base}/chat/completions` + `{base}/models`, `Authorization: Bearer`
  - `anthropic-messages` — `{base}/v1/messages` + `{base}/v1/models`, `x-api-key` +
    `anthropic-version`
- **Fallback**: a missing or unknown `text_provider` resolves back to Agnes with a warning, so
  existing `config.json` files keep working without migration.
- **Credentials**: custom-provider keys live in the local `config.json` (file mode `0600`) and
  are only ever returned to the UI masked.
- **Retry & rate limiting**: custom providers reuse the shared token bucket plus a fixed
  exponential backoff (3 attempts, 15s base) and never rotate Agnes keys.
- **Multimodal**: OpenAI-compatible providers accept image input; Anthropic-compatible
  providers currently ignore images and fall back to text-only.
- **UI**: provider management (add / edit / delete, fetch or hand-write the model list, switch
  the active route) lives in `frontend/src/components/ConfigPanel.vue`.

# 🌐 Backend Localization (v7.0)

The frontend already localizes static UI text; v7.0 extends the same guarantee to messages the
**backend** generates and the user reads verbatim — task progress lines, failure-panel text,
`HTTPException` details and the diagnostics report (hard-coded Chinese before v7.0).

- **Language resolution** (`web/middleware.py::LangContextMiddleware`, mounted in `server.py`):
  every request resolves the UI language as `X-Agnes-UI-Lang` > `Accept-Language` > `zh` and
  stores it in a `ContextVar` (`core/i18n_backend.current_lang`), reset in `finally` so nothing
  leaks across coroutines.
- **Runtime** (`core/i18n_backend.py`): `SUPPORTED_UI_LANGS` (the 22 UI languages),
  `normalize_lang` (`en-US` / `zh_Hans_CN` → 2-letter code), `parse_accept_language` (RFC 7231
  q-weights), `CATALOG` (`{key: {lang: template}}`, currently `zh` + `en`) and
  `translate(key, lang, **params)` with a three-level fallback (target → zh → en → key name)
  that never raises — an i18n gap must not turn into a request failure.
- **Async pipelines do not use the request context**: the language is snapshotted into
  `BaseTaskState.ui_language` at task creation and read back via `BasePipeline._t()` /
  `_ui_lang()`, so a task keeps one language for its whole lifetime even if the user switches
  the UI language mid-run.
- **Frontend injection**: `installFetchLangHeader()` (`frontend/src/api/fetchPatch.ts`) patches
  `window.fetch` once at startup and adds `X-Agnes-UI-Lang` to every request; `apiFetch` in
  `frontend/src/api/index.ts` sets it explicitly as a second layer.
- **Coverage & rules**: `zh` + `en` are complete (CI-enforced parity); other languages fall
  back to `zh`. New user-visible backend messages must go through `translate()`, use
  `<domain>.<meaning>` keys and keyword placeholders — see `docs/plans/v7.0/backend_i18n_plan.md`.

