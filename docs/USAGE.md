# Using Mechanics-Sidekick

## What this is

The CLI for Mechanics-Sidekick. The web app (see the [README](../README.md)) is the
primary interface; the CLI shares the same SQLite database. You load PDFs against a
vehicle, open a job, and ask questions — every answer is grounded in your own
documents with page citations.

**Privacy:** by default the app uses **OpenAI** for chat and embeddings, so questions
and retrieved manual excerpts are sent to the cloud (the README has the full privacy
note). For a **fully-local** setup, set `EMBED_PROVIDER=ollama` and `LLM_PROVIDER=ollama`
in `.env` — then the LLM and embeddings run via Ollama on localhost and nothing leaves
your machine.

## Prerequisites

- `uv` (Python package manager) — Python 3.11+
- **Default (OpenAI):** an `OPENAI_API_KEY` set in `.env`.
- **Local option (instead of OpenAI):** Ollama reachable at `http://localhost:11434`
  with `llama3.2:3b` (chat + per-chunk context summaries) and `nomic-embed-text`
  (embeddings) pulled, plus `EMBED_PROVIDER=ollama` / `LLM_PROVIDER=ollama` in `.env`.
- Linux/macOS shell. Tested on Ubuntu.

## First-time setup

From the repo root (`~/repos/Mechanics-Sidekick`):

```bash
uv sync --group dev                       # installs runtime + test deps
cp .env.example .env                      # then set OPENAI_API_KEY (or switch providers to ollama)
```

For the local Ollama option, start Ollama and pull the models:

```bash
ollama serve                              # or: docker start ollama-portfolio
ollama pull llama3.2:3b
ollama pull nomic-embed-text
curl -s http://localhost:11434/api/tags   # confirm Ollama is up + models present
```

Verify the install:

```bash
uv run pytest tests/ -v          # full suite, all offline (OpenAI, Ollama, and MCP are mocked)
uv run mechanic-sidekick --help
```

## Run it

The CLI is a Typer app with five command groups: `vehicle`, `document`, `job`,
`chat`, `db`. Every command opens its own SQLite session against
`./data/app.db`, which is created on first use.

Quick reachability check before ingesting or chatting:

```bash
curl -s http://localhost:11434/api/tags | grep -E 'llama3.2:3b|nomic-embed-text'
```

## Try it out

Full happy path (commands prompt for fields where shown):

```bash
# 1. Add a vehicle (interactive prompts: year, make, model, engine, VIN, notes)
uv run mechanic-sidekick vehicle add
# -> prints assigned vehicle ID, e.g. "Created vehicle #1"

# 2. Ingest a small PDF (large manuals take many minutes on CPU — keep it small)
uv run mechanic-sidekick document add 1 path/to/manual.pdf
# Each page is extracted, chunked (500 words, 100 overlap), each chunk gets a
# context summary via llama3.2:3b, then embedded via nomic-embed-text.
# Document is marked 'ready' on success, 'failed' on error.

# 3. Open a job against the vehicle
uv run mechanic-sidekick job add 1
# -> prints assigned job ID, e.g. "Created job #1"

# 4. Ask a question (single-shot)
uv run mechanic-sidekick chat ask 1 "What is the valve clearance spec?"
#    or interactive:
uv run mechanic-sidekick chat start 1
```

Verified end-to-end on the existing 2004 Audi A8 fixture (vehicle 1, job 1,
ingested `15-CYLINDER_HEAD_VALVETRAIN_4.2L.pdf`) — `chat ask 1 "..."` returned
a cited answer in under two minutes with five source rows (filename + page).

## Known issues / gotchas

- **DANGER — `mechanic-sidekick db reset` is destructive.** It deletes
  `data/app.db` **and** wipes everything under `data/documents/` (every
  subdirectory, including PDFs you copied in yourself — not just ingested
  copies). It does prompt for confirmation interactively, but `--yes`/`-y`
  skips the prompt entirely. **Do not run it if you have PDFs in
  `data/documents/` that aren't backed up elsewhere.** There is no
  "delete just the DB" option.
- Ingestion is slow on CPU. Every chunk costs one LLM call (context summary) +
  one embedding call. A small synthetic PDF (a few KB, ~5 chunks) takes seconds;
  a full service manual takes many minutes.
- `chat ask` / `chat start` load **all** chunks for the vehicle into memory and
  score them in Python (brute-force cosine). Fine for a handful of manuals,
  slow once you cross thousands of chunks per vehicle.
- All retrieval is **vehicle-scoped, not job-scoped** — every job on the same
  vehicle sees every document on that vehicle.
- The project's `CLAUDE.md` lists stale model names (`gpt-oss:20b`,
  `qwen3-embedding:4b`). The README, `app/config.py`, and `.env` are the
  source of truth: `llama3.2:3b` + `nomic-embed-text`.

## Stop / cleanup

Nothing to stop — each CLI invocation is a one-shot process that closes its
session on exit. To shut down Ollama:

```bash
docker stop ollama-portfolio   # if you started it just for this
```

Persistent state lives in:
- `data/app.db` — SQLite database (vehicles, documents, chunks, jobs, messages)
- `data/documents/<vehicle_id>/...` — copies of ingested PDFs

Both persist across runs by design. Delete them manually (or run `db reset`
**knowing what it nukes**) to start fresh.
