"""
Log service — business logic for incident log lifecycle.

Responsibilities:
    - Generate the UUID receipt for each ingested log.
    - Persist the initial record with status = RECEIVED.
    - Own the database transaction (commit / rollback).

This layer is intentionally framework-agnostic: it receives a plain
SQLAlchemy Session and returns domain objects, making it independently
testable without a running FastAPI app.
"""

import uuid
import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.incident import IncidentLog, StatusEnum

logger = logging.getLogger(__name__)


def create_incident_log(db: Session, message: str) -> IncidentLog:
    """
    Persist a new incident log entry with status RECEIVED.

    Args:
        db:      SQLAlchemy session provided via FastAPI dependency injection.
        message: Raw log message submitted by the caller.

    Returns:
        The newly created and committed IncidentLog ORM instance.

    Raises:
        RuntimeError: Wraps any SQLAlchemy error so the route layer receives
                      a clean exception without leaking DB internals.
    """
    receipt_id = str(uuid.uuid4())

    incident = IncidentLog(
        id=receipt_id,
        message=message,
        status=StatusEnum.RECEIVED,
    )

    try:
        db.add(incident)
        db.commit()
        db.refresh(incident)   # ensure all DB-generated defaults are loaded
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("Failed to persist incident log: %s", exc, exc_info=True)
        raise RuntimeError("Could not save the incident log.") from exc

    logger.info("Incident log created: id=%s status=%s", incident.id, incident.status)
    return incident
