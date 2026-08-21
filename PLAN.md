# search-agent — Design Plan

An Open WebUI-*style* chat application (concept only, no code reuse): a self-hosted web UI for talking to an agent that runs a proper tool-calling loop with a slim, purpose-built toolset.

## 1. Scope

**In scope (v1)**
- Chat UI with streaming responses, session list, shareable session links
- Proper agentic loop (model → tool calls → results → model, until done)
- Tools: `web_search` (Exa), `write_file` (downloadable md/txt artifacts), `trace_session` (inspect another session by link), `spawn_subagents`, `read_file` (uploaded files)
- Google Login via a pluggable auth-provider interface
- Pluggable LLM providers: Fireworks, OpenAI, Anthropic — with correct reasoning/thinking-token persistence per provider

**Explicitly deferred (but shaping the design)**
- `corpus_search`: single-shot hybrid (semantic + keyword) search over a named corpus. The tool registry, file storage, and DB schema below are designed so this drops in later without rework.

## 2. Architecture

```
frontend (React + Vite + TS)          backend (Python / FastAPI)
┌────────────────────────┐   SSE/REST ┌──────────────────────────────┐
│ chat view, session list│ ◄────────► │ auth (pluggable OIDC)        │
│ trace view, artifacts  │            │ agent runner (async loop)    │
│ file upload            │            │ provider adapters (FW/OAI/AN)│
└────────────────────────┘            │ tool registry                │
                                      └──────────────┬───────────────┘
                                          Postgres (sessions, messages,
                                          events, files, users)
                                          + object storage on disk (files)
```

- **Backend**: Python 3.12, FastAPI, SQLAlchemy (async), Postgres (SQLite for dev). Streaming to the client via SSE.
- **Frontend**: React + Vite + TypeScript, single-page app. No SSR needed.
- **One process** for v1; the agent loop runs as an asyncio task per active session. Subagents are additional tasks in the same process (bounded by a semaphore).

## 3. The Agentic Loop

Each user message starts a **run**. A run is a loop:

```
history = load_session_messages(session)
while steps < MAX_STEPS:
    resp = provider.generate(history, tools=tool_registry.schemas(), stream=True)
    persist assistant message (text + reasoning blocks + tool_calls)
    if no tool_calls: break            # final answer
    results = await gather(execute(tc) for tc in resp.tool_calls)
    persist tool-result messages
```

- Every step emits **events** on the SSE stream: `reasoning_delta`, `text_delta`, `tool_call_started`, `tool_result`, `artifact_created`, `subagent_started/finished`, `run_finished`, `error`.
- Events are also persisted (append-only `events` table) — this *is* the trace, powering both the trace view in the UI and the `trace_session` tool.
- Guardrails: max steps per run (configurable, e.g. 25), per-tool timeout, tool-result truncation with overflow saved as an artifact, cancel button (cooperative cancellation of the asyncio task).

## 4. Provider Abstraction & Reasoning Persistence (key design)

This is the part the default Chat Completions flow gets wrong, and each provider solves it differently. The design principle: **store provider-native, opaque reasoning blocks alongside each assistant message, and let each adapter serialize its own blocks back**.

### Canonical message model

```python
class AssistantMessage:
    text: str | None
    tool_calls: list[ToolCall]
    reasoning: list[ReasoningBlock]     # opaque, provider-tagged

class ReasoningBlock:
    provider: str        # "openai" | "anthropic" | "fireworks"
    payload: dict        # provider-native JSON, stored verbatim, never edited
    display_text: str | None   # human-readable thinking for the UI, if available
```

### Adapter interface

```python
class ProviderAdapter(Protocol):
    def build_request(self, history: list[Message], tools: list[ToolSchema]) -> dict
    async def stream(self, request) -> AsyncIterator[AgentEvent]   # normalizes deltas
    def parse_final(self, raw) -> AssistantMessage                 # captures reasoning verbatim
```

### Per-provider handling (verified against current docs)

| Provider | API | How reasoning round-trips |
|---|---|---|
| **OpenAI** | **Responses API** (not Chat Completions) | Run stateless: `store=false` + `include=["reasoning.encrypted_content"]`. Store the returned reasoning items (encrypted payload) verbatim; on the next step, replay all output items (reasoning + function_call + function_call_output) since the last user message in `input`. Stateless keeps all state in our DB, which matters for pluggability and self-hosting; we deliberately avoid `previous_response_id` server-side state. |
| **Anthropic** | Messages API with `thinking` enabled | `thinking`/`redacted_thinking` blocks carry cryptographic signatures and **must** be echoed back complete and unmodified in the assistant message when returning `tool_result`s — the API 400s otherwise. Store blocks verbatim; adapter prepends them to the assistant content on replay. |
| **Fireworks** | Chat Completions-compatible | Reasoning models return `reasoning_content` on the assistant message. For multi-turn tool calling you must pass `reasoning_content` back on prior assistant messages (interleaved thinking triggers when the last message is `role: "tool"`). Models that don't support it ignore the field, so the adapter always includes it. |

### Provider switching mid-session
Reasoning blocks are provider-opaque, so each adapter includes **only its own provider's blocks** and drops foreign ones. Switching providers is allowed **between runs** (never mid-tool-loop): within a tool loop the reasoning chain must stay intact for correctness (hard requirement for Anthropic/OpenAI), but across user turns all three providers tolerate absent prior reasoning.

Provider + model + reasoning effort/budget are per-session settings (with org-level defaults) stored in the DB; API keys come from server env/config, never the browser.

## 5. Tools

Registry pattern — each tool declares a JSON-schema signature, an async `execute(args, ctx) -> ToolResult`, and per-tool config. `ctx` carries session, user, uploaded files, and an event emitter.

| Tool | Behavior |
|---|---|
| `web_search(query, num_results?)` | Exa `/search` with `contents` (text summaries/highlights). Returns titles, URLs, snippets. Config: Exa API key, default result count, optional domain filters. |
| `write_file(filename, content)` | Writes a Markdown/text **artifact**: stored server-side (files table + disk), surfaced in the UI as a downloadable card, download via authenticated `/api/files/{id}`. Repeated writes to the same name create versions. |
| `read_file(file_id \| filename)` | Reads a file the user uploaded to the session (or a previously written artifact). Text extracted at upload time (v1: txt/md/pdf/docx via lightweight extractors); large files are chunk-paginated (`offset`/`limit`). |
| `trace_session(url_or_id)` | Resolves a link to *another session in this app*, checks the caller owns it (or it's shared), and returns a structured transcript from the events log: messages, tool calls + truncated results, subagent runs, artifacts. Enables "look at what happened in session X and continue/critique it." |
| `spawn_subagents(tasks: [{task, context?}])` | Runs N child agents **in parallel**, each its own run with the same provider/adapter and a restricted toolset (no `spawn_subagents` — depth 1). Each child is a real (hidden-by-default) session, so it's traceable via `trace_session` and the trace UI. Returns each child's final answer as the tool result. Bounded concurrency + step budget. |
| *(future)* `corpus_search(corpus_id, query)` | Single-shot hybrid retrieval: pgvector embeddings (semantic) + Postgres FTS (keyword), rank-fused (RRF). See §8. |

## 6. Auth (pluggable, Google first)

- `AuthProvider` interface: `authorize_url()`, `exchange_code(code) -> Identity{provider, subject, email, name, picture}`. Implemented once as **generic OIDC** (via `authlib`); Google is just an OIDC config entry, so Okta/Entra/GitHub later are config, not code.
- Users keyed by `(provider, subject)`. Server-side session cookie (signed, httpOnly). Optional allowlist by email domain.
- All API routes and file downloads require auth; sessions are owner-scoped with an optional share flag (needed for `trace_session` across users later).

## 7. Data Model

```
users(id, provider, subject, email, name, created_at)
sessions(id, user_id, title, provider, model, settings_json, parent_session_id?, kind[chat|subagent], created_at)
messages(id, session_id, idx, role, text, reasoning_json, tool_calls_json, tool_call_id?, created_at)
events(id, session_id, run_id, idx, type, payload_json, created_at)      -- append-only trace
files(id, session_id, user_id, kind[upload|artifact], filename, mime, size, version, path, extracted_text?, created_at)
-- future: corpora(id, name, config), corpus_documents(corpus_id, file_id, ...), chunks(document_id, text, embedding vector, tsv tsvector)
```

`reasoning_json` stores the provider-native blocks verbatim (encrypted OpenAI items, signed Anthropic blocks, Fireworks `reasoning_content`) — this is what makes correct replay possible.

## 8. Future: Corpora (design constraints honored now)

- **Files are first-class rows** (not blobs inside messages), so corpus ingestion can point at existing uploads/artifacts or external sources.
- **Tool registry is config-driven**, so `corpus_search` registers per-corpus without core changes.
- **Postgres from day one** so pgvector + FTS need no new infra: ingestion = chunk → embed (provider-pluggable embedding model) → store `embedding` + `tsvector`; query = single-shot semantic + keyword search fused with RRF, returning chunks with citations back to source files.
- Corpus management UI/API (create corpus, attach files/folders, reindex) is a later milestone.

## 9. Milestones

1. **Skeleton** — FastAPI + Postgres + React app; Google OIDC login; create/list sessions; plain streaming chat against one provider (Fireworks).
2. **Agent loop + tools** — tool registry; `web_search`, `write_file`, `read_file` + uploads; event log + SSE event stream; run guardrails.
3. **All three providers** — adapter layer with reasoning persistence (Responses API w/ encrypted reasoning, Anthropic thinking blocks, Fireworks `reasoning_content`); per-session provider settings UI.
4. **Traces + subagents** — trace view UI, `trace_session` tool, `spawn_subagents` with parallel child runs.
5. **Polish** — session sharing, artifact versioning/downloads UX, cancellation, rate limits, deployment (single Docker Compose: app + Postgres).

Roughly: milestones 1–2 in one session, 3–4 in a second, 5 as follow-up.

## 10. Learnings from Milestones 1–2 (things that give pause)

Design notes from execution and review that should shape milestones 3–5:

1. **The single-process assumption is now load-bearing, not just convenient.** Three separate mechanisms rely on in-process state: the atomic run-slot reservation (prevents duplicate concurrent runs per session), the `file_version_lock` (serializes filename version allocation across uploads and artifacts), and the in-memory SSE event bus. Running multiple uvicorn workers silently breaks all three. Milestone 4's subagents multiply in-process concurrency but stay correct; **scale-out beyond one process** would need Postgres advisory locks (run slots, file versions) and LISTEN/NOTIFY or Redis pub/sub (events). Keep v1 single-process and document it loudly in deployment (§9 M5).
2. **Cancellation corrupts provider history unless reconciled.** A run cancelled between persisting an assistant message with `tool_calls` and persisting the tool results leaves unanswered `tool_calls` in history — all three providers 400 on this, permanently bricking the session. The loader now inserts placeholder tool results (`_reconcile_history`). Subagent runs (M4) must reuse the same loader; any new persistence path must keep the assistant-message-then-results ordering.
3. **Reasoning replay must be scoped to the active tool loop.** Replaying reasoning blocks from all prior completed turns bloats requests and is unnecessary: providers only *require* reasoning continuity within the current tool loop (assistant turns after the latest user message). The Fireworks adapter now replays only those; the OpenAI/Anthropic adapters (M3) should follow the same rule — it also matches OpenAI's "replay output items since the last user message" guidance in §4.
4. **SQLite is dev-only in practice.** Parallel tool execution + event persistence opens several concurrent write sessions; SQLite's single-writer model produces `database is locked` under exactly the workloads M4 makes common. A busy-timeout is configured as a mitigation, but treat Postgres as required for anything beyond single-user dev.
5. **Live SSE deltas are lossy by design; the events table is the trace.** Per-subscriber queues are bounded (evict-oldest on overflow), so token deltas can drop under backpressure while persisted events/messages remain complete. Consequence for M4: the parent's trace view and `trace_session` must read from the events table, never from the live bus.
6. **Provider model names churn.** The originally chosen Fireworks default 404'd mid-build (model deprecated). Also, saving Settings persists the then-current defaults as explicit DB rows, so code-default changes only affect fresh installs. Expect to re-verify model IDs each milestone; consider a "model unavailable" health check surfaced in Settings rather than failing mid-run.
7. **Uploads and artifacts share one filename/version namespace.** `read_file` resolves the highest version regardless of kind, so an artifact can shadow a same-named upload (and vice-versa). Acceptable for v1, but revisit before corpus ingestion (§8) keys anything on filename — an explicit `kind` disambiguator or separate namespaces may be needed.
8. **Disk + DB writes are not transactional.** Files are written to disk before their DB row commits; on commit failure the file is unlinked (best-effort). There's no true atomicity — a crash between write and commit still orphans a file. Fine at this scale; a startup sweep of unreferenced files is the cheap fix if it ever matters.

## 11. Open Questions

1. Frontend preference — plain React+Vite SPA (proposed) vs Next.js?
2. Should subagent sessions appear in the user's session list, or only inside the parent's trace view (proposed)?
3. Default models per provider (e.g. Fireworks: DeepSeek/GLM/Kimi reasoning model; OpenAI: GPT-5.x; Anthropic: Claude Sonnet 4.x)?
4. Single-user/small-team deployment assumption OK (no orgs/roles in v1)?
