"""
pytest configuration and shared fixtures for the InsightLog test suite.

Design decisions:
    - Uses a unique file-based SQLite database per test (uuid4 in filename)
      because:
        1. SQLite :memory: databases are connection-scoped — each connection
           sees a separate empty database, breaking route handlers in TestClient.
        2. Windows locks SQLite files while connections are open; using a unique
           file per test avoids teardown PermissionErrors from concurrently open
           connections (e.g. from BackgroundTask threads).
    - Each test gets a fresh DB file created in the system temp directory.
    - Teardown disposes of all SQLAlchemy connection pools and forces GC before
      attempting to delete the file, which releases Windows file locks.
    - The FastAPI app's get_db dependency is overridden with a factory that
      opens sessions on the same per-test DB file.
    - API key authentication is bypassed for all non-auth tests.
"""

import gc
import os
import uuid
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.core.security import verify_api_key


def _make_engine(db_path: str):
    """Create a SQLAlchemy engine for a SQLite file at db_path."""
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def _unique_db_path() -> str:
    """Return a path to a unique SQLite file in the system temp dir."""
    return os.path.join(tempfile.gettempdir(), f"insightlog_test_{uuid.uuid4().hex}.db")


def _dispose_and_delete(engine, path: str) -> None:
    """Dispose all connections in the pool and attempt to delete the DB file."""
    try:
        engine.dispose()
    except Exception:
        pass
    gc.collect()  # release any remaining Python references to connections
    try:
        os.remove(path)
    except (PermissionError, FileNotFoundError):
        pass  # Windows may still hold the file; leave it in temp — OS cleans up


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function", autouse=False)
def db():
    """
    Provide a fresh database session backed by a unique SQLite file.

    Tables are created before the test and the file is deleted (best-effort)
    after the test to keep temp dirs tidy.
    """
    db_path = _unique_db_path()
    engine = _make_engine(db_path)
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    _dispose_and_delete(engine, db_path)


@pytest.fixture(scope="function")
def client(db: Session):
    """
    Provide a FastAPI TestClient wired to the same unique test DB as the db fixture.

    The DB URL is extracted from the engine bound to the session so both the
    session fixture and the route handler's overridden get_db open connections
    to the same file.
    """
    # Extract the DB URL from the session's bound engine
    db_url = str(db.bind.url)
    db_path = db_url.replace("sqlite:///", "")

    test_engine = _make_engine(db_path)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def _override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    def _override_verify_api_key():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_api_key] = _override_verify_api_key

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    _dispose_and_delete(test_engine, db_path)
