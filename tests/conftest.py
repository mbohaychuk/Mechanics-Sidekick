# tests/conftest.py
import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_engine
from app.db.migrations import apply_hybrid_retrieval_migration
import app.models  # noqa: F401


@pytest.fixture(scope="function")
def db_engine():
    # In-memory engine — sqlite-vec already loaded by get_engine().
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    apply_hybrid_retrieval_migration(engine, vec_dim=4)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
