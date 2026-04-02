# app/db.py
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    pass


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, connect_args={"check_same_thread": False})


def get_session_factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
