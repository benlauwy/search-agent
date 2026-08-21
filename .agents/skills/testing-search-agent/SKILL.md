---
name: testing-search-agent
description: How to run and end-to-end test the search-agent app (FastAPI + React agentic chat) locally, including auth, provider keys, streaming, files, and known pitfalls.
---

# Testing search-agent locally

## Services
1. Postgres: docker container `search-agent-pg` (image `pgvector/pgvector:pg16`, user/pass/db all `searchagent`, port 5432). `docker start search-agent-pg` if it exists; the backend's default DB URL points at it.
2. Backend: `cd backend && uv run uvicorn app.main:app --port 8000`
3. Frontend: `cd frontend && npm run dev` → http://localhost:5173 (proxies /api to :8000). If Vite prints port 5174, another instance already owns 5173 — kill stale node/uvicorn processes first (`ss -tlnp | grep -E ':(8000|5173)'`).

## Auth & settings
- Default auth provider is "dev": the Sign in button logs in instantly as Dev User, no credentials.
- Fireworks API key goes in the Settings modal (sidebar footer → Settings). After save it reads back masked as `********`. Model `accounts/fireworks/models/deepseek-v4-pro` works.
- Without an Exa key, web_search tool returns "Exa API key not configured. Set it in Settings." as a tool error; the run should still finish gracefully.

## Useful test techniques
- Upload dialog: use Ctrl+L in the GTK file chooser to type a path directly; this also bypasses the extension filter, letting you force-select a .png to test the API's 415 rejection (UI surfaces "Unsupported file type…").
- Events/state inspection: `docker exec search-agent-pg psql -U searchagent -d searchagent -c "select ... from events/sessions/messages/files"`. Table names: `sessions` (not chat_sessions), `messages`, `events`, `files`, `users`, `app_settings`.
- Artifacts are stored under `backend/data/files/` — check disk to verify write_file / delete-cleanup behavior.

## Milestone 3–4 features (requires PR #4 / the milestones 3–4 code)
- Exa key field is Settings → Tools → "Exa API key (web search)" (app setting key `exa_api_key`; the key value comes from Devin secret `exa_key_debug`).
- Subagent parallelism is best verified via `select type, created_at from events where type like 'subagent%'` in psql.
- Subagent sessions are invisible in the sidebar by design — inspect them via the parent's Trace modal "Open subagent trace" button.

## Milestone 5 features (sharing, versions, cancel UX, rate limits, Docker)
- Second dev user for sharing tests: the dev provider always logs in the same "Dev User", so insert a second user row and forge its cookie: `cd backend && uv run python -c "...create User(provider='dev', subject='dev-user-2', ...) via app.db.SessionLocal, then URLSafeTimedSerializer('dev-secret-change-me', salt='session').dumps({'uid': u.id})"`. Set it as `sa_session` in an incognito window (document.cookie works; reload the page afterwards — the auth check runs on load). Verify with GET /api/auth/me.
- Share flow: header Share button → "Shared ✓" + "Copy link"; link is `/#/sessions/<id>`. Non-owner sees "Shared with you · read-only" badge, no composer/provider controls/upload. Unshared sessions return 404 for other users.
- Rate limits: runs 10/user/min, uploads 30/user/min (SA_RATE_LIMIT_RUNS_PER_MINUTE etc.; 0 disables). Cheap way to hit the runs limit without burning LLM calls: start one run, then rapid-fire POSTs to the same session — the limiter counts each attempt before the 409 "run in progress" check, so the 11th returns 429 with Retry-After.
- Cancel UX: the "Stopping…" label is transient and usually resolves in <1s locally — hard to capture on screen; the durable evidence is the "Run cancelled." notice and the composer returning to Send.
- Docker: `docker compose up --build -d` serves frontend+API on :8000 (SA_STATIC_DIR points at the built frontend inside the image). Stop the local uvicorn AND vite first (port clash on 8000; stray vite keeps 5173). The compose stack uses its own db volume — settings/API keys from local testing are absent there.

## Model capability (smart/fast) features
- Model settings keys are `<provider>_smart_model` / `<provider>_fast_model` (defaults in `backend/app/settings_store.py DEFAULT_MODELS`); Settings UI shows "Smart model"/"Fast model" per provider.
- Session capability lives in `sessions.settings_json ->> 'capability'` (chat default "smart", subagent default "fast"); the header Smart/Fast `<select>` is owned-sessions-only and disabled while a run is active.
- Verify effective model per run via `select payload_json->>'model', payload_json->>'capability' from events where type='run_started'` (column is `payload_json`, not `payload`).
- Mixed subagent tiers: an explicit prompt like "one FAST subagent (capability 'fast') to X and one SMART subagent (capability 'smart') to Y, use spawn_subagents with those capabilities" reliably makes the parent pass per-task capability; verify via child sessions' settings_json + their run_started events.
- Mid-run PATCH guard: `{shared}` toggles are allowed during a run (200), `{provider|model|capability}` return 409.

## Backend settings via environment
- Pydantic settings use `env_prefix="SA_"` (backend/app/config.py). To override a setting via env you MUST prefix it: e.g. `SA_SUBAGENT_TIMEOUT_SECONDS=20 uv run uvicorn app.main:app --port 8000`. An unprefixed var (e.g. `SUBAGENT_TIMEOUT_SECONDS`) is silently ignored and the default applies — verify the override took effect (e.g. check `/proc/<pid>/environ` and observe the behavior) before trusting a test run.

## Pitfalls
- If you restart the backend while the frontend page is open, the EventSource (SSE) dies permanently (browser EventSource stops retrying after a failed reconnect) — the UI gets stuck "running" and misses run events. Reload the page (F5) after any backend restart before judging streaming/cancel behavior.
- Cancel semantics: POST /api/sessions/{id}/cancel returns 200 and the runner emits `run_finished {"cancelled": true}`; the UI only reflects it via the SSE stream.

## Devin Secrets Needed
- `FW_KEY` — Fireworks API key, typed into Settings → Fireworks → API key (use `${FW_KEY}` substitution, never print it).
