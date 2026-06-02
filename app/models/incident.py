import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, Enum as SAEnum
from app.database.base import Base


class StatusEnum(str, enum.Enum):
    """Tracks the lifecycle of an incident through the triage pipeline."""
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SeverityEnum(str, enum.Enum):
    """Severity level assigned by the LLM triage."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    CRITICAL = "CRITICAL"


class CategoryEnum(str, enum.Enum):
    """Category of the incident assigned by the LLM triage."""
    DATABASE = "DATABASE"
    NETWORK = "NETWORK"
    APPLICATION = "APPLICATION"
    SECURITY = "SECURITY"


class IncidentLog(Base):
    """
    ORM model representing a single ingested log entry and its triage results.

    Columns:
        id          - UUID primary key (string representation for SQLite compat)
        message     - Original raw log message
        status      - Lifecycle status (RECEIVED → PROCESSING → COMPLETED/FAILED)
        severity    - LLM-assigned severity; nullable until triage completes
        category    - LLM-assigned category; nullable until triage completes
        root_cause  - Short explanation from LLM; nullable until triage completes
        remediation - Suggested action steps from LLM; nullable until triage completes
        error_detail- Stored if triage fails; helps debugging
        created_at  - UTC timestamp of ingestion
    """
    __tablename__ = "incident_logs"

    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    message: str = Column(Text, nullable=False)
    status: str = Column(
        SAEnum(StatusEnum),
        nullable=False,
        default=StatusEnum.RECEIVED,
    )
    severity: str | None = Column(SAEnum(SeverityEnum), nullable=True)
    category: str | None = Column(SAEnum(CategoryEnum), nullable=True)
    root_cause: str | None = Column(Text, nullable=True)
    remediation: str | None = Column(Text, nullable=True)
    error_detail: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
