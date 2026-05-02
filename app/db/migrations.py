# app/db/migrations.py
"""One-shot migration to the hybrid retrieval schema.

When the legacy `embedding_json` column is present, clears existing chunk rows
and drops that column. Adds the new metadata columns to document_chunks and
creates the FTS5 + sqlite-vec virtual tables that Plan 2's retrieval pipeline
reads.

Idempotent: running twice on the same engine is a no-op — the DELETE branch
only fires while `embedding_json` still exists (i.e., exactly once per DB).
"""
from sqlalchemy import Engine, inspect, text


_NEW_COLUMNS = (
    ("chunk_kind", "TEXT NOT NULL DEFAULT 'prose'"),
    ("engine_variant", "TEXT NULL"),
    ("table_type", "TEXT NULL"),
    ("table_id", "TEXT NULL"),
)


def apply_hybrid_retrieval_migration(engine: Engine, vec_dim: int) -> None:
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("document_chunks")}
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        # 1. One-time cutover from the legacy schema. Only runs when the
        # old `embedding_json` column is still present — after the first
        # migration on a given DB, this branch never fires again, so the
        # function is a true no-op on subsequent calls.
        if "embedding_json" in existing_cols:
            conn.execute(text("DELETE FROM document_chunks"))
            conn.execute(text("ALTER TABLE document_chunks DROP COLUMN embedding_json"))

        # 3. Add new metadata columns idempotently.
        for col_name, col_decl in _NEW_COLUMNS:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {col_name} {col_decl}"))

        # 4. Indexes for the engine_variant filter and table grouping.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_engine_variant ON document_chunks(engine_variant)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_table_id ON document_chunks(table_id)"
        ))

        # 5. FTS5 virtual table over the contextualized text (the same enriched
        # text that gets embedded). content='' = external content; we manage
        # rows manually from chunk_repository.
        if "document_chunks_fts" not in existing_tables:
            conn.execute(text(
                "CREATE VIRTUAL TABLE document_chunks_fts USING fts5("
                "  chunk_id UNINDEXED,"
                "  text,"
                "  content=''"
                ")"
            ))

        # 6. sqlite-vec virtual table for cosine similarity.
        if "document_chunks_vec" not in existing_tables:
            conn.execute(text(
                f"CREATE VIRTUAL TABLE document_chunks_vec USING vec0("
                f"  chunk_id INTEGER PRIMARY KEY,"
                f"  embedding FLOAT[{vec_dim}]"
                f")"
            ))
