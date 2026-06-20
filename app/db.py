# app/db.py
import sqlite3

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


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
