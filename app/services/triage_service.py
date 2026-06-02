"""
Triage service — asynchronous incident analysis workflow.

Responsibilities:
    - Manage the full status lifecycle: RECEIVED → PROCESSING → COMPLETED | FAILED.
    - Own a dedicated database session (the request-scoped session from get_db()
      is already closed by the time a BackgroundTask runs).
    - Delegate analysis to llm_service (Gemini 2.5 Flash).
    - Store triage results back to the database.

Design note:
    process_triage() is intentionally a plain function (not async) because
    FastAPI BackgroundTasks dispatches it in a thread pool, which is correct for
    blocking I/O work like database writes and HTTP calls to the Gemini API.
"""

import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import SessionLocal
from app.models.incident import IncidentLog, StatusEnum
from app.schemas.log import TriageResult
from app.services import llm_service, alert_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers — each owns exactly one commit (one atomic state transition)
# ---------------------------------------------------------------------------


def _set_status(db: Session, incident: IncidentLog, new_status: StatusEnum) -> None:
    """Update the status field and commit atomically."""
    incident.status = new_status
    db.commit()
    logger.debug("Incident %s → status=%s", incident.id, new_status.value)


def _apply_triage_result(
    db: Session,
    incident: IncidentLog,
    result: TriageResult,
) -> None:
    """
    Persist triage result fields and mark the incident as COMPLETED.

    Accepts a fully validated TriageResult (not a raw dict) so that
    type safety is preserved end-to-end from Gemini → DB.
    """
    incident.severity = result.severity
    incident.category = result.category
    incident.root_cause = result.root_cause
    incident.remediation = result.remediation
    incident.status = StatusEnum.COMPLETED
    db.commit()
    logger.info(
        "Incident %s triage completed: severity=%s category=%s",
        incident.id,
        result.severity.value,
        result.category.value,
    )


def _mark_failed(db: Session, incident: IncidentLog, error: Exception) -> None:
    """Store the error detail and mark the incident as FAILED."""
    incident.status = StatusEnum.FAILED
    incident.error_detail = f"{type(error).__name__}: {error}"
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "Could not persist FAILED status for incident %s", incident.id
        )


# ---------------------------------------------------------------------------
# Public entry point — registered as a BackgroundTask in the route layer
# ---------------------------------------------------------------------------


def process_triage(incident_id: str) -> None:
    """
    Full triage workflow executed asynchronously after the HTTP response is sent.

    Lifecycle:
        1. Open a fresh DB session (request session is already closed).
        2. Load the incident record.
        3. Transition: RECEIVED → PROCESSING  (committed to DB).
        4. Call llm_service.analyze() — Gemini 2.5 Flash classifies the log.
        5a. On success  → persist TriageResult, transition: PROCESSING → COMPLETED.
        5b. On any error → persist error detail, transition: PROCESSING → FAILED.
        6. Close the DB session.

    Args:
        incident_id: UUID of the IncidentLog row to process.
    """
    logger.info("Background triage started for incident_id=%s", incident_id)

    db: Session = SessionLocal()
    try:
        # Step 1: load the record
        incident: IncidentLog | None = db.get(IncidentLog, incident_id)
        if incident is None:
            logger.error(
                "Triage aborted: incident_id=%s not found in DB", incident_id
            )
            return

        # Step 2: commit PROCESSING before any LLM work begins
        _set_status(db, incident, StatusEnum.PROCESSING)

        # Step 3: classify with Gemini 2.5 Flash
        result: TriageResult = llm_service.analyze(incident.message)

        # Step 4: persist results and commit COMPLETED
        _apply_triage_result(db, incident, result)

        # Step 5: Slack notification for CRITICAL incidents (failure isolated)
        try:
            alert_service.send_slack_alert(incident_id, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error in alert service for incident %s", incident_id)

    except Exception as exc:  # noqa: BLE001  (intentional broad catch for background task)
        logger.exception(
            "Triage failed for incident_id=%s: %s", incident_id, exc
        )
        try:
            _mark_failed(db, incident, exc)  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not mark incident %s as FAILED", incident_id
            )
    finally:
        db.close()
        logger.info(
            "Background triage finished for incident_id=%s", incident_id
        )
