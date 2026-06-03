"""
Alert service — handles outbound notifications to third-party platforms.

Responsibilities:
    - Format and send Slack messages for CRITICAL incidents.
    - Gracefully handle network timeouts and API errors.
    - Ensure alerting failures do not crash the caller.

Design note:
    Uses standard library urllib.request to avoid introducing new third-party
    dependencies just for a simple POST request. All exceptions are caught and
    logged internally to ensure failure isolation.
"""

import json
import logging
import os
import urllib.request
from urllib.error import URLError

from app.schemas.log import Severity, TriageResult

logger = logging.getLogger(__name__)


def send_slack_alert(incident_id: str, result: TriageResult, request_id: str | None = None) -> None:
    """
    Send a Slack webhook notification if the incident is CRITICAL.

    Args:
        incident_id: UUID of the incident.
        result: The validated triage classification result.
    """
    if result.severity != Severity.CRITICAL:
        return

    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url or "your/webhook/url" in webhook_url:
        logger.warning(
            "SLACK_WEBHOOK_URL is not configured. "
            "Skipping Slack alert for CRITICAL incident %s",
            incident_id,
        )
        return

    req_id_text = f"*Request ID:* `{request_id}`\n" if request_id and request_id != "no-request-id" else ""
    payload = {
        "text": (
            f"🚨 *CRITICAL Incident Detected* 🚨\n\n"
            f"*ID:* `{incident_id}`\n"
            f"{req_id_text}"
            f"*Category:* {result.category.value}\n\n"
            f"*Root Cause:*\n{result.root_cause}\n\n"
            f"*Remediation:*\n{result.remediation}"
        )
    }

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Timeout is short (5s) because this runs in a background thread pool,
        # but we still don't want to hang indefinitely on a bad network.
        with urllib.request.urlopen(req, timeout=5.0) as response:
            if response.status != 200:
                logger.error(
                    "Slack alert failed for incident %s: HTTP %s",
                    incident_id,
                    response.status,
                )
            else:
                logger.info("Slack alert sent for CRITICAL incident %s", incident_id)

    except URLError as exc:
        logger.error(
            "Network error sending Slack alert for incident %s: %s", incident_id, exc
        )
    except Exception as exc:
        logger.error(
            "Unexpected error sending Slack alert for incident %s: %s", incident_id, exc
        )
