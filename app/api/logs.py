"""
API router for log ingestion.

Route contract:
    POST /api/v1/logs
        Request:  LogCreate           { "message": "..." }
        Response: LogReceiptResponse  { "receipt_id": "<uuid>" }

    GET /api/v1/logs/{receipt_id}
        Response: IncidentResponse    (full record including triage results)

Design rules followed:
    - Routes are thin: no business logic, no direct DB access.
    - All persistence is delegated to service layer functions.
    - Database session is injected via FastAPI's Depends().
    - HTTP status codes are explicit (201 Created for resource creation).
    - BackgroundTasks is injected by FastAPI — the route adds the task and
      returns immediately; processing runs after the response is sent.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.incident import IncidentLog
from app.schemas.log import IncidentResponse, LogCreate, LogReceiptResponse
from app.services import log_service, triage_service
from app.utils.validation import is_valid_log
from app.core.security import verify_api_key
from app.core.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/logs",
    tags=["Logs"],
)


@router.post(
    "",
    response_model=LogReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a log message",
    description=(
        "Accepts a raw log message, persists it immediately with status RECEIVED, "
        "and returns a receipt ID. Triage analysis runs asynchronously in the background "
        "and does NOT block this response."
    ),
)
@limiter.limit("30/minute")
def ingest_log(
    request: Request,
    payload: LogCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> LogReceiptResponse:
    """
    POST /api/v1/logs

    1. Save log → status = RECEIVED.
    2. Register background triage task.
    3. Return receipt_id immediately (before triage starts).
    """
    try:
        # --- Layer 2: Semantic validation ---
        is_valid, reason = is_valid_log(payload.message)
        if not is_valid:
            logger.warning("Log rejected by semantic validation: %s", reason)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Semantic validation failed: {reason}",
            )

        incident = log_service.create_incident_log(db=db, message=payload.message)
    except RuntimeError as exc:
        logger.error("Log ingestion failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store the log entry. Please try again.",
        ) from exc

    # Register the triage workflow to run after this response is sent.
    # triage_service opens its own DB session — it cannot reuse `db` here
    # because that session will be closed before the background task runs.
    background_tasks.add_task(triage_service.process_triage, incident.id)

    logger.info("⏳ [QUEUED] Background triage queued for Incident ID: %s", incident.id)
    return LogReceiptResponse(receipt_id=incident.id)


@router.get(
    "/{receipt_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get incident status and triage results",
    description=(
        "Returns the current status and triage results for a previously ingested log. "
        "Poll this endpoint to confirm background processing has completed."
    ),
)
def get_incident(
    receipt_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
) -> IncidentResponse:
    """
    GET /api/v1/logs/{receipt_id}

    Retrieves the full incident record. Triage fields (severity, category,
    root_cause, remediation) are None while status is RECEIVED or PROCESSING.
    """
    incident: IncidentLog | None = db.get(IncidentLog, receipt_id)

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No incident found with receipt_id '{receipt_id}'.",
        )

    return IncidentResponse.model_validate(incident)
