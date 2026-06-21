# app/db.py
import sqlite3

from sqlalchemy import create_engine, event, inspect, text, Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Additive columns introduced after first release. `create_all` never ALTERs an existing
# table, so without a migration framework an older on-disk DB is missing these and every
# query against the table errors. This lightweight, idempotent migration adds them.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "documents": [("chunks_total", "INTEGER"), ("chunks_done", "INTEGER")],
}


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    # SQLite defaults foreign-key enforcement OFF; enable it per connection so declared
    # ForeignKey constraints (and any future ON DELETE rules) are actually enforced.
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, connect_args={"check_same_thread": False})


def get_session_factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def ensure_runtime_columns(engine: Engine) -> None:
    """Idempotently add post-release additive columns missing from an older DB. Call after
    create_all on any persistent (on-disk) engine. No-op when the table/columns already exist."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for table, columns in _ADDITIVE_COLUMNS.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        missing = [(name, ddl) for name, ddl in columns if name not in existing]
        if missing:
            with engine.begin() as conn:
                for name, ddl in missing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
