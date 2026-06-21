# Mechanics Sidekick

A diagnostic copilot for mechanics. Add a vehicle, upload its service manuals, open a job, and chat with an **agent** that grounds its answers in your manuals, reads the live car over OBD‑II, and searches the web — in a browser, with the answer streaming back as it's written. Beyond chat, it streams a **live telemetry dashboard** and runs a **guided diagnostic session** that walks you through a health test and produces a grounded vehicle health report.

It started as a local CLI; it's now a web app with an agentic, tool‑using assistant, a real‑time OBD dashboard, and a proactive diagnostic copilot. The CLI still works against the same database.

---

## What it does

Workflow: **Vehicle → Documents → Job → Chat**

1. **Add a vehicle.**
2. **Upload PDF service manuals.** Each is extracted page‑by‑page, split into overlapping chunks, given an LLM‑generated context summary, embedded, and stored — ingestion runs in the background and the UI shows each document go `pending → ready`.
3. **Open a job** (e.g. *"P0301 misfire"*).
4. **Chat.** The assistant is **agentic** — it decides which tools to call as it reasons, and can chain them (read a code → look it up in the manual) in a single turn:
   - **📖 `search_manuals`** — semantic search over *this vehicle's* uploaded manuals, cited by filename + page.
   - **🔧 OBD tools** — read live data, trouble codes (DTCs), freeze frames, readiness monitors, and vehicle info straight from the connected car, via the separate [obd‑mcp](https://github.com/mbohaychuk/OBD-II-MCP-Server) server. **Read‑only** — the destructive clear‑codes tool is filtered out of the toolset entirely.
   - **🔎 `web_search`** — the public web (recalls, TSBs, common failure patterns) when the manuals don't cover it.

Answers stream token‑by‑token over SSE; tool activity appears as live chips; manual citations show the source filename and page.

### Live telemetry dashboard

Open a vehicle's **Live** view to stream its sensor data (PIDs — RPM, coolant temp, fuel trims, O2, …) in real time: a dense vitals list with per‑row sparklines, a larger focus chart, a supported‑PID picker, and a VIN safety check. One shared async sampler reads the car **once** and fans the data out over SSE — extra tabs don't double the bus load — and every session is recorded to SQLite and replayable. Read‑only, no LLM.

### Diagnostic copilot session

Open a vehicle's **Diagnostic** view to run a guided health test. The copilot walks you through a protocol (idle → warm‑up → rev to ~2500 → return to idle), detecting each step from the live telemetry; it narrates the data with periodic LLM commentary, flags anomalies with deterministic rules, and at the end generates a **structured health report** — per‑system findings (severity, observation, recommendation) grounded in your manuals (and the web where they fall short), saved and reviewable. The LLM's autonomy is deliberately bounded: it interprets and may adapt a step within a fixed, validated vocabulary, but the protocol detection and anomaly rules are deterministic. The chat agent can then **reference past health reports** when you ask about the vehicle's condition or history.

---

## Architecture

Two processes, one experience:

- **Backend — FastAPI.** Wraps the existing service/repository layer, hosts a thin provider‑portable tool‑calling loop, connects to `obd‑mcp` over stdio as a standard MCP host, runs the RAG retrieval, and streams chat over Server‑Sent Events. OpenAI for chat **and** embeddings.
- **Frontend — Vue 3 + TypeScript SPA.** In development the Vite dev server proxies `/api` to the backend; in production the backend serves the built SPA via `StaticFiles`, so it's a single command on a single port. ECharts is code‑split into the lazy Live + Diagnostic routes, so it never weighs down the rest of the app.
- **Live telemetry + diagnostic copilot.** Because an ELM327 is a single, serialized resource, one shared **async sampler** reads the union of subscribed PIDs over the one `obd‑mcp` connection and fans them out latest‑wins to SSE subscribers (recording each tick to SQLite, off the hot path). A stateful **diagnostic runner** subscribes to that same stream as the one active session, drives a guided protocol over it, layers on LLM commentary + deterministic anomaly rules, and produces a persisted health report — each delivered over its own SSE endpoint.

`obd‑mcp` is a separate, generic MCP server; Sidekick is just one MCP host that consumes it — it stays oblivious to who calls it. If it isn't configured or a scanner isn't connected, chat degrades gracefully to manuals + web only, and the Live / Diagnostic views show a "connect a scanner" state.

```
Browser (Vue SPA) ──/api──▶ FastAPI ──┬─ agent loop (OpenAI tool-calling)
                                       │    ├─ search_manuals          → RAG over SQLite
                                       │    ├─ obd-mcp (stdio)          → live OBD-II data
                                       │    ├─ web_search               → Tavily
                                       │    └─ get_diagnostic_reports   → past health reports
                                       ├─ telemetry sampler ──SSE──▶ Live dashboard  (recorded to SQLite)
                                       └─ diagnostic runner ──SSE──▶ Diagnostic copilot
                                            protocol · commentary · anomaly · health report
```

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3 + TypeScript, Vite, Tailwind CSS v4, Pinia, vue‑router, Vitest |
| Backend | FastAPI + Uvicorn (SSE streaming) |
| Agent | Custom tool‑calling loop over the OpenAI SDK + the official MCP Python SDK (the `obd‑mcp` client) |
| LLM & embeddings | OpenAI (`gpt-4.1-mini`, `text-embedding-3-small`) — Ollama retained behind a provider seam for a future local option |
| Web search | Tavily |
| Live vehicle data | `obd‑mcp` (separate project) over MCP / stdio |
| PDF extraction | PyMuPDF |
| Database | SQLite via SQLAlchemy 2.0 |
| CLI | Typer + Rich |
| Tests | pytest (backend) · Vitest + @vue/test-utils (frontend) |

---

## Prerequisites

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/)
- **Node 20.19+** (or 22.12+) for the frontend
- An **OpenAI API key** (chat + embeddings)
- *Optional:* a **Tavily API key** for web search
- *Optional:* the [obd‑mcp](https://github.com/mbohaychuk/OBD-II-MCP-Server) project + an ELM327 scanner (or its simulator) for the live OBD tools

> **Note on privacy:** v1 uses OpenAI for generation and embeddings, so questions, retrieved manual excerpts, and (when OBD tools are used) vehicle data are sent to the cloud. The original fully‑local Ollama path is retained behind the provider seam but is not the default.

---

## Run it

### 1. Install
```bash
git clone https://github.com/mbohaychuk/Mechanics-Sidekick.git
cd Mechanics-Sidekick
uv sync --group dev            # backend deps (incl. tests)
cd frontend && npm install     # frontend deps
```

### 2. Configure
Copy `.env.example` to `.env` and set at least your OpenAI key:
```bash
OPENAI_API_KEY=sk-...
# optional — web search:
TAVILY_API_KEY=tvly-...
# optional — live OBD tools:
OBD_MCP_ENABLED=true
OBD_MCP_DIR=/home/you/repos/OBD-II-MCP-Server
OBD_PORT=socket://localhost:35000
```

### 3a. Develop (two processes)
```bash
uv run mechanic-sidekick-api           # backend on http://127.0.0.1:8000
cd frontend && npm run dev             # SPA on http://localhost:5173 (proxies /api → :8000)
```
Open **http://localhost:5173**.

### 3b. Single port (production‑style)
```bash
cd frontend && npm run build           # emits frontend/dist
cd .. && uv run mechanic-sidekick-api  # serves the SPA + API together
```
Open **http://127.0.0.1:8000**.

### CLI (optional — same database)
```bash
uv run mechanic-sidekick vehicle add
uv run mechanic-sidekick document add <vehicle_id> path/to/manual.pdf
uv run mechanic-sidekick job add <vehicle_id>
uv run mechanic-sidekick chat start <job_id>
```

---

## Configuration

Defaults work out of the box once `OPENAI_API_KEY` is set. Override anything via `.env` or environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI key for chat + embeddings |
| `OPENAI_CHAT_MODEL` | `gpt-4.1-mini` | Tool‑capable chat model |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | Embedding model (1536‑dim) |
| `LLM_PROVIDER` / `EMBED_PROVIDER` | `openai` | Provider behind the seam (`openai` or `ollama`) |
| `MAX_AGENT_ITERS` | `6` | Cap on tool‑calling loop iterations per turn |
| `OBD_MCP_ENABLED` | `false` | Spawn and connect to `obd‑mcp` for live OBD tools |
| `OBD_MCP_DIR` | — | Path to the `obd‑mcp` repo (run via `uv --directory`) |
| `OBD_PORT` | `socket://localhost:35000` | ELM327 transport (simulator default; WiFi unit e.g. `socket://192.168.0.10:35000`) |
| `OBD_TOOL_DENYLIST` | `ping,record_session` | Tools excluded from the model's set (destructive tools are always filtered) |
| `WEB_SEARCH_ENABLED` | `true` | Enable the `web_search` tool (needs `TAVILY_API_KEY`) |
| `TAVILY_API_KEY` | — | Tavily key for web search |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `500` / `100` | Words per chunk / overlap |
| `TOP_K_CHUNKS` | `5` | Chunks retrieved per `search_manuals` call |
| `RERANK_PROVIDER` | `none` | Cross-encoder reranker over the dense top‑N (`local` = FlashRank; needs `uv sync --group rerank`) |
| `RERANK_CANDIDATES` | `40` | Dense pool reranked, then truncated to `TOP_K_CHUNKS` |
| `HYBRID_SEARCH` | `false` | Fuse BM25 (SQLite FTS5) keyword ranks with cosine via Reciprocal Rank Fusion |
| `RECENT_MESSAGES` | `6` | Chat history window sent to the LLM |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | Backend bind address |
| `CORS_ORIGIN` | `http://localhost:5173` | Allowed dev origin |
| `DB_PATH` / `DOCS_DIR` | `./data/app.db` / `./data/documents` | SQLite + PDF storage |

---

## Tests

Both suites are hermetic — no network, no scanner, no OpenAI calls.

```bash
uv run pytest tests/ -v        # backend: OpenAI + MCP mocked, in-memory SQLite
cd frontend && npm test        # frontend: fetch / API client mocked (Vitest + jsdom)
```

---

## Design note — contextual retrieval

The initial implementation embedded raw text chunks directly. Tested against a real vehicle with both 4.2L and 6.0L engine manuals loaded, the retriever kept returning chunks from both variants for any engine‑related question — the embeddings couldn't tell them apart because the chunk text was often identical (*"tighten head bolts in sequence"*) regardless of engine size.

The fix is **contextual retrieval**: before embedding each chunk, a lightweight LLM call generates a 1–2 sentence summary situating the chunk in its document — which engine variant, which system, what it covers — and that summary plus a metadata header is prepended to the chunk text before embedding.

```
Document: 10-ENGINE ASSEMBLY 4.2L.pdf | Page: 45
This excerpt covers cylinder head bolt torque specifications and tightening
sequence for the 4.2L V8 engine during reassembly.

[original chunk text...]
```

The original chunk text is stored separately for citation display; the *enriched* version is what gets embedded. As a result, 4.2L and 6.0L content now point in meaningfully different directions in vector space, and retrieval precision improves with no change to the ranking logic. The tradeoff is ingestion time — one LLM call per chunk.

---

## Measuring retrieval — an eval harness, not a hunch

Retrieval changes are easy to *assert* and hard to *prove*. `evals/` is a small, dependency‑light harness that scores retrieval through the real `RetrievalService.retrieve()` against a set of **labeled questions whose answer pages are verified against the actual manual** (DTC codes, torque/spec values, repair procedures), reporting **hit@1 / hit@5 / MRR** per question type. It captures a dense‑only **baseline** so every change is judged on a measured delta — `uv run python -m evals.run_eval --vehicle-id N --label baseline`. Full method + results: [`evals/README.md`](evals/README.md).

Running it on a real **264 MB / 13k‑page Ford F‑150 manual** (~11k chunks) was clarifying, and overturned an assumption:

- **Dense retrieval already finds exact tokens.** It lands a relevant chunk in the top‑5 for *every* literal‑code query — so the headroom was **ranking** (hit@1 was only 0.40), not exact‑token recall.
- **A cross‑encoder reranker** (`RERANK_PROVIDER=local`) over the dense top‑40 lifts **hit@5 0.84 → 0.96** and recovers chunks dense missed entirely.
- **BM25 hybrid** (`HYBRID_SEARCH=true`, SQLite FTS5 + Reciprocal Rank Fusion) gives the best **hit@1 (0.56)** — *after* the harness caught a real bug: OR‑ing stopwords into the FTS query flooded BM25 with common‑word matches and pushed the right DTC chunk out of the candidate pool. The FTS tokenizer also preserves `.`, `-`, `/` so `P0420` / `M12x1.5` index as whole tokens.

Both are **off by default** and opt‑in; the harness is what decides whether each earns being enabled.

---

## Roadmap → v2: phone‑only, in the garage

The browser app is feature‑complete across its three designed phases — agentic chat, the live telemetry dashboard, and the diagnostic copilot. The next direction is a different shape entirely.

v1 assumes a laptop in the garage. **v2 drops the laptop — you walk up to the car with just your phone.**

In v2 the phone becomes a thin **relay** between the OBD adapter and a **cloud backend** that does the real work (runs `obd‑mcp`, the agent, and the RAG over your manuals). Two connection modes cover any garage:

- **Bluetooth + WiFi** — the phone talks to a **Bluetooth (BLE) OBD adapter** and reaches the cloud over **WiFi**.
- **WiFi + cellular** — the phone talks to a **WiFi OBD adapter** and reaches the cloud over **phone data**.

Either way the phone does only two things: (1) move OBD bytes to/from the adapter, and (2) relay them over a secure WebSocket to the cloud. On the server, python‑OBD opens that tunnel as if it were a local serial port — it sends `010C`, the bytes ride the socket to the car and back — so **`obd‑mcp` runs unchanged**, just with a WebSocket transport instead of a local one. The cloud agent connects to `obd‑mcp` as an MCP host exactly like the v1 backend; it never knows the car is remote.

**Why this shape** (rather than a fully in‑browser app): a browser can't open a raw TCP socket to a WiFi scanner, and Web Bluetooth is Android‑only — so the phone path implies a small **native app** (one screen; works on iOS too) that stays a trivial relay, while all the brains — `obd‑mcp`, the agent loop, the manuals — are reused wholesale from v1. The same transport seam that lets the v1 backend swap a local serial port for the simulator is exactly what a WebSocket transport plugs into.

**Tradeoffs being weighed:** added latency (phone → cloud → phone on every OBD query, on top of the already‑slow ELM327 — so live dashboards sample slower and reads get batched), more failure points (BLE / WiFi / WebSocket drops), and privacy (car data goes to the cloud — the same trade v1 already makes for cloud generation). Secured with `wss://` + per‑session auth.

Full exploration in [`docs/v2-ideas.md`](docs/v2-ideas.md).

---

## Known limitations & future work

Deliberate v1 tradeoffs in the RAG layer, each a clear next step:

- **Brute‑force vector search.** All of a vehicle's chunk embeddings are loaded from SQLite and scored in Python per query. Fine for a typical corpus; a vector store ([Chroma](https://www.trychroma.com/) / [Qdrant](https://qdrant.tech/)) would make retrieval instant at scale.
- **Embeddings stored as JSON strings** (not binary), paying a `json.loads` per chunk per query — ripe for numpy‑matrix caching.
- **Fixed word‑count chunking** ignores document structure; structure‑aware or parent‑child chunking would produce more coherent chunks for spec tables and multi‑step procedures.
- **No reranking.** A cross‑encoder reranker after initial retrieval would improve answers on ambiguous, multi‑part questions.
- **Vehicle‑scoped retrieval, not job‑scoped** — every question searches all of a vehicle's manuals.
