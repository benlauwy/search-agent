# search-agent

An Open WebUI-style (concept only) chat application: a web UI for an agent that runs a
proper tool-calling loop with a slim, purpose-built toolset. See [PLAN.md](PLAN.md) for
the full design.

## Current status (milestones 1–2)

- Streaming chat UI (React + Vite SPA) with session list, live reasoning display,
  tool-call cards, file uploads, and downloadable artifacts
- Agentic loop with guardrails (max steps, tool timeouts, result truncation, cancel)
- Tools: `web_search` (Exa), `write_file` (Markdown/text artifacts), `read_file`
  (uploaded files, paginated)
- Pluggable auth: Google OIDC or a dev-login provider for local development
- Fireworks provider with `reasoning_content` persistence across tool-calling turns
  (OpenAI Responses API and Anthropic adapters land in milestone 3)
- Provider/tool API keys and models configurable in the Settings UI (encrypted at rest)

## Running locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, Postgres
(a `pgvector/pgvector:pg16` Docker container works; SQLite also works via
`SA_DATABASE_URL=sqlite+aiosqlite:///./dev.db`).

```bash
# Postgres
docker run -d --name search-agent-pg \
  -e POSTGRES_USER=searchagent -e POSTGRES_PASSWORD=searchagent \
  -e POSTGRES_DB=searchagent -p 5432:5432 pgvector/pgvector:pg16

# Backend (http://localhost:8000)
cd backend
uv sync
uv run uvicorn app.main:app --port 8000

# Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Sign in (dev provider logs you in instantly), open Settings, and paste your
Fireworks/OpenAI/Anthropic API keys plus an Exa API key for web search.

## Configuration

Environment variables (prefix `SA_`, or a `backend/.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `SA_DATABASE_URL` | local Postgres | SQLAlchemy async database URL |
| `SA_SECRET_KEY` | dev value | Signs session cookies and encrypts stored API keys — set a strong value |
| `SA_AUTH_PROVIDER` | `dev` | `google` for Google Login, `dev` for local development |
| `SA_GOOGLE_CLIENT_ID` / `SA_GOOGLE_CLIENT_SECRET` | — | Google OAuth client (redirect URI: `{SA_API_URL}/api/auth/callback`) |
| `SA_ALLOWED_EMAIL_DOMAINS` | empty (allow all) | Comma-separated email-domain allowlist |
| `SA_APP_URL` / `SA_API_URL` | localhost dev URLs | Frontend origin / backend base URL |
| `SA_DATA_DIR` | `./data` | Where uploads and artifacts are stored |

Provider API keys and model choices are managed in the Settings UI and stored in the
database (secrets encrypted with a key derived from `SA_SECRET_KEY`).

## Development

```bash
cd backend && uv run ruff check .   # lint
cd frontend && npm run build        # typecheck + build
```
