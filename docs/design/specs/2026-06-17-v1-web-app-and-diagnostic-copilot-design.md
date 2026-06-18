# Mechanics Sidekick v1 — Web App + Live Diagnostic Copilot

**Date:** 2026-06-17
**Status:** Approved design. Phase 1 is specified for implementation; Phases 2–3 are roadmap sketches that exist to keep Phase 1's seams future-proof. Each phase gets its own detailed spec → plan → build cycle before it is built.

## Context

Mechanics Sidekick today is a local Typer CLI: a vehicle → documents (PDFs) → job → chat RAG flow, Ollama for chat + embeddings, SQLite via SQLAlchemy, brute-force cosine retrieval. This design moves it to a browser app and turns the chat into an **agentic, tool-using assistant** that can read the car live through the separate `obd-mcp` project, ground answers in the uploaded manuals, and search the web.

`obd-mcp` (`~/repos/OBD-II-MCP-Server`, v0.1.0, 117 tests) is a generic MCP server exposing live OBD-II data (DTCs, PIDs, freeze frames, NHTSA recalls) as tools. It is consumed by *any* MCP host. **Sidekick becomes one such host** — it connects to `obd-mcp` over stdio the same way any standard MCP host would. `obd-mcp` stays oblivious to who calls it. (`obd-mcp`'s optional `SIDEKICK_URL`/`repair-lookup` reverse path is explicitly out of scope here.)

## The three-phase vision

1. **Phase 1 — Foundation: web app + agentic Q&A chat.** The browser app (vehicles/documents/jobs management + a smart chat) on OpenAI for chat *and* embeddings, with three agent tools: `search_manuals`, read-only `obd-mcp` tools, and `web_search`. Shippable on its own. **Fully specified below.**
2. **Phase 2 — Live telemetry dashboard.** Scanner ↔ vehicle association, per-vehicle connection status, a live gauge/chart dashboard streaming PIDs (RPM, O2, etc.). Read-only, no LLM. **Sketched below.**
3. **Phase 3 — Live diagnostic copilot.** A proactive session mode on top of 1+2: streaming LLM commentary over live data, guided user actions ("rev it", "drive it"), manual-grounded interpretation of readings, automatic problem diagnosis against the manuals, and a generated vehicle health report. **Sketched below.**

Q&A chat (request/response) and a live diagnostic session (continuous, proactive, time-series, report-producing) are genuinely different interaction models, which is why they are separate phases rather than one build.

---

## Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | **Vite + Vue 3 SPA frontend + FastAPI (Python) backend, two processes.** | Frontend dev already knows Vue/Nuxt, so NiceGUI's "Python devs avoid JS" value is nil; a real Vue UI is more polished and portfolio-worthy. Backend must stay Python to reuse the whole service layer + run the Python MCP client. SSR unneeded for a localhost single-user tool. **Supersedes the stale `docs/v2-ideas.md` NiceGUI note.** |
| D2 | **OpenAI for chat *and* embeddings; Ollama removed from the default runtime.** | "Makes setup easier" — one provider, no local model server. Embeddings, chat, and per-chunk context summaries all run on OpenAI. |
| D3 | **Minimal provider seam, OpenAI the only v1 implementation.** | Plugin system is wanted, but "abstract crazy later." A thin `ChatProvider` / embedding seam keeps Ollama re-addable without building it now. |
| D4 | **RAG exposed as a `search_manuals` tool**, peer to the OBD and web tools — not injected as upfront context. | Agentic model decides when/what to search, can refine and re-search, and can chain "read DTC → look it up in the manual" in one turn. |
| D5 | **Custom, thin agent loop using the official `mcp` SDK as the client** (not OpenAI Agents SDK / LangChain). | Keeps provider portability and the clean service layer; avoids framework lock-in and heavy deps. |
| D6 | **`obd-mcp` hard-wired as the single MCP server; read-only tools only.** Destructive `clear_dtcs` filtered out of the toolset. | YAGNI on a multi-server manager until a second server exists. Filtering the one destructive, elicitation-gated tool removes all elicitation plumbing from v1 and bounds blast radius. |
| D7 | **Typer CLI retained; localhost single-user, no auth.** | The CLI still works against the same DB — no reason to delete working code. No external surface (reverse endpoint deferred), so no auth needed. |

---

## Phase 1 — Foundation: web app + agentic Q&A chat (FULL SPEC)

### 1.1 Scope

**In:** FastAPI backend wrapping existing services; Vue 3 SPA; vehicle/document/job management; browser upload + background ingestion; OpenAI chat + embeddings + contextualization; agentic chat with `search_manuals` + read-only `obd-mcp` tools + `web_search`; SSE streaming of tokens and tool activity; a single global "scanner reachable?" indicator.

**Out (later phases):** per-vehicle scanner association and status (Phase 2), live telemetry dashboard (Phase 2), proactive commentary / guided actions / health report (Phase 3), `OllamaProvider` implementation, generic multi-MCP-server manager, persisting the tool trace, the reverse `repair-lookup` endpoint.

### 1.2 Architecture

Two processes:
- **FastAPI backend** — reuses `app/services`, `app/repositories`, `app/rag` untouched in behavior; adds REST + SSE endpoints, the agent loop, the MCP host, and background ingestion.
- **Vite + Vue 3 SPA** — the UI.

**Dev:** Vite dev server proxies `/api` → FastAPI (two processes). **Local run:** FastAPI serves the built SPA via `StaticFiles`, so it's a single command on a single port — preserving the "open a browser" experience.

New backend layout (existing packages unchanged):
```
app/
  api/
    main.py        # FastAPI app, CORS, lifespan (init engine + MCP host), mount SPA
    deps.py        # per-request DB session dependency; service factories mirroring CLI _make_* fns
    routers/
      vehicles.py
      documents.py
      jobs.py
      chat.py
      scanner.py
  agent/
    provider.py    # ChatProvider protocol + OpenAIProvider (chat). Embedding seam likewise.
    mcp_client.py  # spawn obd-mcp over stdio, list/call read-only tools, schema translation
    tools.py       # search_manuals (wraps RetrievalService) + web_search + MCP tool pass-through
    orchestrator.py# the tool-calling loop; yields stream events
```

### 1.3 Components

**Provider seam (`provider.py`).** `ChatProvider.run_turn(messages, tools) -> ProviderTurn{text | tool_calls}`, streaming. One impl: `OpenAIProvider` (chat completions, `tools=`, `tool_choice="auto"`, streamed deltas; assembles `tool_calls` from streamed fragments). A parallel embedding seam wraps OpenAI embeddings. The existing `OllamaService` stays in-tree but unused by default, behind the seam, for a future local option.

**MCP client (`mcp_client.py`).** At backend startup (FastAPI lifespan), spawn `uv --directory $OBD_MCP_DIR run obd-mcp` with env `OBD_PORT` (default simulator `socket://localhost:35000`), connect via the `mcp` client SDK over stdio, `initialize`, `list_tools` once, keep the session warm. Translate MCP tool JSON Schemas → OpenAI function-tool format. Expose `call(name, args)`. **Filter out `clear_dtcs`** (and any tool annotated destructive). If startup/connection fails, the host degrades gracefully — chat runs with `search_manuals` + `web_search` only, and any attempted OBD call returns "scanner not connected."

**Tools (`tools.py`).**
- `search_manuals(query)` — wraps `RetrievalService.retrieve(vehicle_id, query)`; `vehicle_id` is bound from the current job at orchestration time, not exposed to the model. Returns ranked excerpts with `{filename, page, excerpt}`.
- read-only `obd-mcp` tools — `read_dtcs`, `read_live_data`, `read_freeze_frame`, `read_readiness_monitors`, `get_vehicle_info`, `list_supported_pids`, `lookup_recalls_and_complaints`, etc.
- `web_search(query)` — function tool backed by a provider-agnostic search API (Tavily/Brave) so it isn't tied to OpenAI's hosted tool; exact backend chosen in the plan.

**Orchestrator (`orchestrator.py`).** `async run(job_id, user_message)` → async generator of stream events:
1. Load job + vehicle + recent history (`recent_messages` limit); persist the user message.
2. Build system prompt (mechanic's assistant; ground answers in manuals via `search_manuals`; read the car via OBD tools; cite sources) + history + user message.
3. Loop, capped at `MAX_AGENT_ITERS` (default 6): ask provider with the tool list; if it returns tool calls, emit `tool_call` events, execute each (local `search_manuals`/`web_search` or `mcp.call`), emit `tool_result` events, append results to messages, loop; else stream the final answer tokens and break.
4. Collect sources from `search_manuals` results during the turn; persist the final assistant message + `sources_json`.

**SSE event types:** `token`, `tool_call`, `tool_result`, `sources`, `done`, `error`.

### 1.4 Data flow (one chat message)

```
Vue → POST /api/jobs/{id}/messages {content}
    → orchestrator.run(...)  (async)
    → text/event-stream: token* (tool_call → tool_result)* token* sources done
```

### 1.5 Data model & persistence

- **No schema migration in Phase 1.** Reuse `chat_message` (`role`, `content`, `sources_json`) exactly as today. Persist the user message and the final assistant message + sources. **Tool activity is streamed live but not persisted** — on history reload the UI shows messages + citations, not the tool trace. (Persisting the trace is a deferred enhancement requiring an additive column.)
- DB sessions: engine created once at startup (reuse `app/db.py`); a per-request session dependency that commits/rolls back. Sync services run in FastAPI's threadpool; the async agent loop invokes them via threadpool. `check_same_thread=False` is already set on the engine.

### 1.6 Embeddings change (D2) — consequence

OpenAI embeddings (`text-embedding-3-small`, 1536-dim) are **incompatible** with existing `nomic-embed-text` chunks (768-dim) — cosine ranking requires the same model for query and corpus. **All previously ingested documents must be re-ingested** under OpenAI embeddings. This is a one-time re-run (pre-production data only). Ingestion now also runs the per-chunk context summary on OpenAI, so ingestion cost shifts from local compute to OpenAI tokens.

### 1.7 Config additions (`Settings`)

`LLM_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL` (default tool-capable, e.g. `gpt-4.1-mini`; `gpt-4.1`/`gpt-4o` as upgrades), `EMBED_PROVIDER=openai`, `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`), `OBD_MCP_DIR`, `OBD_PORT` (default `socket://localhost:35000`), `WEB_SEARCH_API_KEY` (+ provider), `API_PORT`, `CORS_ORIGIN` (Vite dev origin), `MAX_AGENT_ITERS`. Existing chunking/top-k/recent-messages config unchanged. Ollama config retained but unused by default.

### 1.8 Error handling

- OpenAI auth/rate-limit → `error` SSE event surfaced in chat.
- `obd-mcp` down → manuals-only chat; OBD tool calls return a clear "scanner not connected."
- Ingestion failure → document marked `failed`, error shown in UI (existing pattern).
- Agent hits `MAX_AGENT_ITERS` → emit a graceful "couldn't complete" message.
- SSE disconnect → frontend shows error/retry.

### 1.9 Safety

- Every agent tool is **read-only**: destructive `clear_dtcs` filtered out, no filesystem-write tool. So a prompt-injection arriving via `web_search` (untrusted content) or a manipulated manual/web result cannot damage the car or local data — the blast radius is bounded to "the model says something wrong," not "the model does something destructive."
- Single-user localhost; no external network surface.

### 1.10 Frontend (Vue 3 SPA)

- **Vehicles** — list/add/select; global "scanner reachable?" badge.
- **Vehicle detail** — documents (drag-drop upload, live `processing_status`), jobs (list/create).
- **Chat** — streaming answers, tool-activity chips ("🔧 read_dtcs", "📖 search_manuals", "🔎 web_search"), source citations (filename + page), input box.
- **Settings** — OpenAI key present?, `obd-mcp` status, `OBD_PORT`.
- State via Pinia; chat stream consumed with a fetch-based SSE reader.

### 1.11 API surface (Phase 1)

`GET/POST /api/vehicles`, `GET /api/vehicles/{id}`, `GET/POST /api/vehicles/{id}/documents`, `GET /api/documents/{id}`, `GET/POST /api/vehicles/{id}/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/messages`, `POST /api/jobs/{id}/messages` (SSE), `GET /api/scanner/status`, `GET /api/health`.

### 1.12 Testing

- **Backend (pytest, existing in-memory-SQLite fixtures):** orchestrator loop driven by a **fake provider returning scripted tool calls** — assert tools fire, sources collected, messages persisted (confirmed-red TDD on this core logic). MCP client and OpenAI mocked. Routers via FastAPI `TestClient`. `search_manuals` tested against the real `RetrievalService` with a mocked embedder.
- **Frontend (Vitest):** chat rendering/streaming components. Playwright e2e deferred past Phase 1 core.

### 1.13 Reuse (existing code leveraged, not rebuilt)

Reused as-is: `VehicleService`, `JobService`, `DocumentService`, `RetrievalService`, `ChatRepository`/`JobRepository`/`VehicleRepository`/`DocumentRepository`/`ChunkRepository`, `app/rag/similarity.py`, `app/db.py`. Extended: `EmbeddingService` and `ContextualizationService` gain an OpenAI backend behind the seam. **Not reused for the agentic path:** `app/rag/prompt_builder.py`'s `build_messages` injects retrieved chunks upfront, which contradicts RAG-as-a-tool (D4); the orchestrator assembles its own messages and tool list instead. Its system-prompt scaffolding may be lifted into the orchestrator's prompt; `build_messages` itself stays only for the CLI's existing non-agentic chat. New only: `app/api/*`, `app/agent/*`, `frontend/*`.

### 1.14 Build order (Phase 1 internal slices)

1. FastAPI skeleton: lifespan engine, session dependency, CORS, SPA static mount, health endpoint.
2. REST CRUD: vehicles, jobs, documents (list/get).
3. Background ingestion: upload endpoint + `DocumentService` background task + OpenAI embeddings/contextualization swap + status.
4. Provider seam (OpenAI chat) + `search_manuals` + agent orchestrator (manuals-only) + SSE chat endpoint + message persistence.
5. MCP host (`obd-mcp` stdio) + read-only OBD tools in the loop + `GET /api/scanner/status`.
6. `web_search` tool.
7. Frontend: management views (vehicles, documents w/ upload + status, jobs).
8. Frontend: chat view (streaming, tool chips, sources).
9. Frontend: settings + scanner indicator.

---

## Phase 2 — Live telemetry dashboard (SKETCH)

Detailed spec deferred. Seams Phase 1 must leave room for:

- **Scanner ↔ vehicle association.** Recommended: auto-match the connected ELM327's VIN (via `obd-mcp` `get_vehicle_info`) to a `vehicle.vin`; manual override when no VIN/no match. Likely a small additive model (e.g., an `active_scanner_session` concept or a `vehicle.last_seen_vin`); designed-for in Phase 2, not built in Phase 1.
- **Per-vehicle connection status** in the vehicle list (replaces Phase 1's single global indicator).
- **Live PID streaming.** A backend polling loop calling `obd-mcp` `read_live_data` for supported PIDs on an interval, streamed to the SPA over SSE; the SPA renders gauges/charts (RPM, coolant temp, O2, etc.). Read-only, no LLM.

## Phase 3 — Live diagnostic copilot (SKETCH)

Detailed spec deferred. Builds on Phases 1+2:

- **Session mode** — a stateful live diagnostic session distinct from request/response chat, consuming the Phase 2 telemetry stream.
- **Streaming commentary** — the LLM narrates the live data as it changes.
- **Guided actions** — the LLM prompts the user ("rev to 2500 RPM", "drive at steady 60 km/h") and reacts to the resulting data.
- **Manual-grounded interpretation** — raw RPM/O2 values are correlated against manual specs via `search_manuals` to judge "normal vs abnormal for *this* engine."
- **Health report** — a generated vehicle health summary from the session.
- **Automatic diagnosis** — detected anomalies are diagnosed against the uploaded manuals (and `web_search` when uncovered).

Open questions for Phase 3's own spec: how live time-series + commentary are persisted; report format/storage; sampling/latency strategy for commentary over a fast PID stream.

---

## Deferred / open items

- `OllamaProvider` (local generation) implementation behind the seam.
- Persisting the agent tool trace (additive `chat_message` column).
- Generic multi-MCP-server manager (when a second server is added).
- Reverse `repair-lookup` endpoint for external `obd-mcp` hosts.
- `web_search` backend choice (Tavily/Brave) — pinned in the Phase 1 plan.
- Final OpenAI chat/embedding model defaults — pinned in the Phase 1 plan.
