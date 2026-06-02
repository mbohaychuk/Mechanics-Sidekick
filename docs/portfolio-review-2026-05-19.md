# Portfolio review notes — 2026-05-19

Notes collected while preparing this project for portfolio capture.

Severity legend:
- 🔴 **Blocker** — would prevent a recruiter from running or evaluating the project
- 🟠 **Embarrassing** — visible to anyone who clones the repo; should be fixed before sharing
- 🟡 **Polish** — minor UX, docs, or code quality
- 🟢 **Idea** — not a defect; potential improvement to discuss

## 🔴 Blockers

### 1. `db reset` destroys user-placed source files in `data/documents/`
`app/cli.py:db_reset` (the command added in commit `54966f5`) calls `shutil.rmtree` on every subdir of `DOCS_DIR`. Today (2026-05-19) the previous session moved the Audi A8 manuals to `data/documents/Audi_A8_2004-2009_Manuals/` per design intent (DOCS_DIR is the documented PDF storage root). Running `db reset --yes` immediately deleted those 84 PDFs (~116 MB) with no recovery path. The command's confirmation prompt does warn "data/documents/* (PDF files)" but the wording suggests "ingested PDFs", not "anything the user put here". Possible fixes (not applied — your call): (a) only delete files whose paths are recorded in the `documents` SQLite table; (b) move processed PDFs into a separate `DOCS_DIR/_ingested/` subdir and only clear that; (c) stronger wording on the prompt: "Delete EVERYTHING in data/documents/, including files you added manually".

## 🟠 Embarrassing

### 2. Default model names in `app/config.py:6-8` are not real Ollama models
`chat_model = "gemma4:26b"` and `context_model = "gemma4:e4b"` — Ollama has gemma, gemma2, gemma3 but no `gemma4`. The README was updated (commit `74c7155`) to reference these names too. Any clone-and-run user hits an immediate model-not-found error. Suggest aligning README + config defaults to real model names (`gemma2:9b`, `llama3.2:3b`, etc.) or document the expected pull list.

### 3. README's "Ollama must be running" implies it but doesn't show install
Mechanic-Sidekick depends entirely on Ollama; the README mentions it but doesn't link to install instructions or list the exact `ollama pull` commands needed. A recruiter or curious peer trying to follow the README will run `mechanic-sidekick chat ask` and get a confusing connection-refused error.

## 🟡 Polish

### 4. `vehicle add` doesn't show the Year/Make/Model labels before prompts
When you run `vehicle add`, all the prompts appear on one line (`Year: Make: Model: ...`) because typer's prompts are squashed. Each prompt should be on its own line. Visible in the demo recording.

### 5. `data/documents/.gitkeep` is at the top of an otherwise gitignored dir
Fine, but worth a note: the `.gitkeep` pattern works, but a stale `.gitkeep` in a deleted/recreated dir can mislead — `db reset` already preserves it (line "if child.name == '.gitkeep': continue"). That's correct behaviour but undocumented.

## 🟢 Ideas

### 6. Stashed work — hybrid retrieval CLI wiring
`stash@{0}` contains the WIP wiring for the agentic RAG loop design (per `docs/specs/2026-05-01-agentic-rag-loop-design.md`). The supporting modules (`app/db/migrations.py`, `app/services/table_chunker.py`, `app/services/metadata_extractor.py`) need to be written before that stash can land. Recruiters won't see this, but worth tracking in your own notes.

### 7. Consider adding `mechanic-sidekick db status` or `mechanic-sidekick doctor`
A single command that checks Ollama reachability + model availability + DB schema version would massively shorten the time-to-first-success for someone new to the project.
