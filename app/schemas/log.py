"""
Pydantic v2 schemas for the AI Incident Triage Service.

Separation of concerns:
    - These schemas define the API contract (what clients send and receive).
    - They are intentionally independent of the SQLAlchemy ORM models so that
      the database layer and the API layer can evolve without coupling.
"""

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (API layer — mirror ORM enums but belong to the schema contract)
# ---------------------------------------------------------------------------


class Severity(str, enum.Enum):
    """
    Severity level assigned by the LLM triage engine.

    LOW      — Informational; no immediate action required.
    MEDIUM   — Degraded behaviour; should be investigated soon.
    CRITICAL — Service-impacting; triggers an immediate Slack alert.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"


class Category(str, enum.Enum):
    """
    Functional category of the incident, determined by the LLM.

    DATABASE    — Storage, query, connection, or replication issues.
    NETWORK     — Connectivity, latency, DNS, or firewall issues.
    APPLICATION — Logic errors, crashes, or unexpected behaviour in code.
    SECURITY    — Auth failures, suspicious access patterns, or policy violations.
    """

    DATABASE = "DATABASE"
    NETWORK = "NETWORK"
    APPLICATION = "APPLICATION"
    SECURITY = "SECURITY"


class IncidentStatus(str, enum.Enum):
    """
    Lifecycle status of an ingested log entry.

    RECEIVED   — Log has been persisted; background triage not yet started.
    PROCESSING — LLM analysis is in progress.
    COMPLETED  — Triage finished successfully; results stored.
    FAILED     — All LLM retry attempts exhausted; error detail stored.
    """

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class LogCreate(BaseModel):
    """
    Request body for POST /api/v1/logs.

    The client supplies only the raw log message; all triage fields are
    populated asynchronously by the background processing pipeline.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,   # trims accidental leading/trailing spaces
        json_schema_extra={
            "example": {
                "message": "Database connection timeout after 30 seconds"
            }
        },
    )

    message: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description=(
            "The raw log message to be triaged. "
            "Must be between 10 and 5000 characters."
        ),
    )

    @field_validator("message")
    @classmethod
    def validate_message_content(cls, value: str) -> str:
        """Reject messages that are blank, purely numeric, or too short."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be blank or whitespace-only")
        if stripped.isdigit():
            raise ValueError("message must not be purely numeric")
        if len(stripped.split()) < 3:
            raise ValueError("message must contain at least 3 words to be meaningful")
        return value


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class LogReceiptResponse(BaseModel):
    """
    Immediate response returned by POST /api/v1/logs.

    The receipt_id can be used by the caller to query the triage result later.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "receipt_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
            }
        }
    )

    receipt_id: str = Field(
        ...,
        description="UUID of the newly created incident log entry.",
    )


class TriageResult(BaseModel):
    """
    Structured output produced by the LLM triage engine.

    This schema is used in two places:
      1. As the expected JSON structure returned by Gemini (validated on parse).
      2. As part of IncidentResponse when the client queries a completed incident.

    All fields are required because Gemini is prompted to always return them.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "severity": "CRITICAL",
                "category": "DATABASE",
                "root_cause": (
                    "The database connection pool was exhausted due to a "
                    "long-running query holding connections open."
                ),
                "remediation": (
                    "1. Identify and terminate the long-running query. "
                    "2. Increase the connection pool size. "
                    "3. Add query timeout limits."
                ),
            }
        }
    )

    severity: Severity = Field(
        ...,
        description="Severity level of the incident: LOW, MEDIUM, or CRITICAL.",
    )
    category: Category = Field(
        ...,
        description=(
            "Functional category of the incident: "
            "DATABASE, NETWORK, APPLICATION, or SECURITY."
        ),
    )
    root_cause: str = Field(
        ...,
        min_length=1,
        description="A concise explanation of the most likely root cause.",
    )
    remediation: str = Field(
        ...,
        min_length=1,
        description="Recommended action steps to resolve or mitigate the incident.",
    )


class IncidentResponse(BaseModel):
    """
    Full incident record returned when querying a specific log entry.

    Severity, category, root_cause, and remediation are None until the
    background triage pipeline sets status to COMPLETED.
    """

    model_config = ConfigDict(
        from_attributes=True,        # enables ORM-mode (replaces orm_mode in v1)
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "message": "Database connection timeout after 30 seconds",
                "status": "COMPLETED",
                "severity": "CRITICAL",
                "category": "DATABASE",
                "root_cause": "Connection pool exhausted by long-running queries.",
                "remediation": "Terminate stale queries and increase pool size.",
                "created_at": "2026-06-02T14:30:00Z",
            }
        },
    )

    id: str = Field(..., description="UUID of the incident log entry.")
    message: str = Field(..., description="Original raw log message.")
    status: IncidentStatus = Field(..., description="Current lifecycle status.")
    severity: Severity | None = Field(
        None,
        description="Severity level; None until triage completes.",
    )
    category: Category | None = Field(
        None,
        description="Functional category; None until triage completes.",
    )
    root_cause: str | None = Field(
        None,
        description="Root cause explanation; None until triage completes.",
    )
    remediation: str | None = Field(
        None,
        description="Remediation steps; None until triage completes.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp of when the log was ingested.",
    )
