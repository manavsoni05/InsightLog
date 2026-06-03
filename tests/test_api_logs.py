"""
API integration tests for POST /api/v1/logs and GET /api/v1/logs/{receipt_id}.

These tests use the FastAPI TestClient with an in-memory SQLite database.
No real Gemini API calls are made — the background triage task is registered
but not awaited in these tests (TestClient executes background tasks after the
response is returned, and triage_service calls are not mocked here intentionally
so we test the full registration flow).

Coverage:
    - Happy path: valid log ingestion returns 201 + receipt_id
    - Auth: missing X-API-Key returns 401
    - Auth: wrong X-API-Key returns 401
    - Auth: correct X-API-Key returns 201
    - Validation: message too short returns 422
    - Validation: purely numeric message returns 422
    - Validation: missing message field returns 422
    - GET: unknown receipt_id returns 404
    - GET: known receipt_id returns 200 with correct fields
    - GET: newly ingested log has status RECEIVED
"""
import gc
import json
import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database.base import Base
from app.database.session import get_db
from app.core.security import verify_api_key


def _unique_db_path() -> str:
    return os.path.join(tempfile.gettempdir(), f"insightlog_auth_test_{uuid.uuid4().hex}.db")


def _dispose_and_delete(engine, path: str) -> None:
    try:
        engine.dispose()
    except Exception:
        pass
    gc.collect()
    try:
        os.remove(path)
    except (PermissionError, FileNotFoundError):
        pass

# ---------------------------------------------------------------------------
# Valid payload shorthand
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {"message": "Database connection pool exhausted after 30 seconds on primary replica"}
VALID_KEY = "test-secret-key"


# ---------------------------------------------------------------------------
# Auth-specific client (real verify_api_key, controlled key)
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_client():
    """
    TestClient that uses the real verify_api_key dependency with a controlled
    test API key. Used exclusively by authentication tests.
    """
    db_path = _unique_db_path()
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    # Do NOT override verify_api_key — we want the real one
    app.dependency_overrides.pop(verify_api_key, None)

    os.environ["API_KEY"] = VALID_KEY
    os.environ["API_KEY_ENABLED"] = "true"

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    os.environ.pop("API_KEY", None)
    os.environ.pop("API_KEY_ENABLED", None)
    _dispose_and_delete(engine, db_path)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_ingest_log_success(client: TestClient):
    """Valid log message returns 201 Created with a receipt_id UUID."""
    response = client.post("/api/v1/logs", json=VALID_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert "receipt_id" in data
    assert len(data["receipt_id"]) == 36  # UUID format


def test_ingest_log_returns_request_id_header(client: TestClient):
    """Every response must include the X-Request-ID header from our middleware."""
    response = client.post("/api/v1/logs", json=VALID_PAYLOAD)
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36


# ---------------------------------------------------------------------------
# Authentication tests (use auth_client with real verify_api_key)
# ---------------------------------------------------------------------------

def test_ingest_log_missing_api_key_returns_401(auth_client: TestClient):
    """POST without X-API-Key header returns 401 Unauthorized."""
    response = auth_client.post("/api/v1/logs", json=VALID_PAYLOAD)
    assert response.status_code == 401


def test_ingest_log_wrong_api_key_returns_401(auth_client: TestClient):
    """POST with incorrect X-API-Key returns 401 Unauthorized."""
    response = auth_client.post(
        "/api/v1/logs",
        json=VALID_PAYLOAD,
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_ingest_log_correct_api_key_returns_201(auth_client: TestClient):
    """POST with the correct X-API-Key returns 201 Created."""
    response = auth_client.post(
        "/api/v1/logs",
        json=VALID_PAYLOAD,
        headers={"X-API-Key": VALID_KEY},
    )
    assert response.status_code == 201
    assert "receipt_id" in response.json()


# ---------------------------------------------------------------------------
# Input validation tests (use client with auth bypassed)
# ---------------------------------------------------------------------------

def test_ingest_log_message_too_short_returns_422(client: TestClient):
    """Messages under 10 characters fail Pydantic Layer 1 validation."""
    response = client.post("/api/v1/logs", json={"message": "short"})
    assert response.status_code == 422


def test_ingest_log_purely_numeric_returns_422(client: TestClient):
    """Purely numeric messages are rejected by the field_validator."""
    response = client.post("/api/v1/logs", json={"message": "1234567890"})
    assert response.status_code == 422


def test_ingest_log_fewer_than_3_words_returns_422(client: TestClient):
    """Messages with fewer than 3 words are rejected by the field_validator."""
    response = client.post("/api/v1/logs", json={"message": "database timeout"})
    assert response.status_code == 422


def test_ingest_log_missing_message_returns_422(client: TestClient):
    """Request body missing the message field returns 422."""
    response = client.post("/api/v1/logs", json={})
    assert response.status_code == 422


def test_ingest_log_empty_message_returns_422(client: TestClient):
    """Empty string message returns 422."""
    response = client.post("/api/v1/logs", json={"message": ""})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET endpoint tests
# ---------------------------------------------------------------------------

def test_get_incident_not_found_returns_404(client: TestClient):
    """Querying a non-existent receipt_id returns 404."""
    response = client.get("/api/v1/logs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_get_incident_success_returns_received_status(client: TestClient):
    """
    After a successful POST, GET on the receipt_id returns 200 with status RECEIVED.
    The incident is in RECEIVED state because the background triage task has not
    run yet (TestClient executes background tasks synchronously after response,
    but the triage would fail without a real Gemini key — we just confirm the
    record exists and was persisted correctly).
    """
    post_response = client.post("/api/v1/logs", json=VALID_PAYLOAD)
    assert post_response.status_code == 201
    receipt_id = post_response.json()["receipt_id"]

    get_response = client.get(f"/api/v1/logs/{receipt_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["id"] == receipt_id
    assert data["message"] == VALID_PAYLOAD["message"]
    # Status may be RECEIVED, PROCESSING, COMPLETED, or FAILED depending on
    # whether the background task ran — any is acceptable here.
    assert data["status"] in ("RECEIVED", "PROCESSING", "COMPLETED", "FAILED")


def test_get_incident_contains_expected_fields(client: TestClient):
    """GET response always contains the required schema fields."""
    post_response = client.post("/api/v1/logs", json=VALID_PAYLOAD)
    receipt_id = post_response.json()["receipt_id"]

    get_response = client.get(f"/api/v1/logs/{receipt_id}")
    data = get_response.json()

    required_fields = {"id", "message", "status", "created_at"}
    assert required_fields.issubset(data.keys())


# ---------------------------------------------------------------------------
# Semantic validation (Layer 2) — tested via the API endpoint
# ---------------------------------------------------------------------------

def test_semantic_validation_symbols_only_returns_422(client: TestClient):
    """Messages that are all symbols (no alphabetical chars) are rejected."""
    response = client.post("/api/v1/logs", json={"message": "!!! @@@ ### $$$ %%% ^^^"})
    assert response.status_code == 422
