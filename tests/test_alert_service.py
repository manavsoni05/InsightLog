"""
Unit tests for app/services/alert_service.py.

All network calls are mocked — no real Slack webhooks are hit.
Tests run fully offline and verify the alerting behaviour:
    - Non-CRITICAL incidents: send_slack_alert returns without calling urlopen
    - Missing webhook URL: logs a warning, no crash, no network call
    - Placeholder webhook URL: treated the same as missing
    - CRITICAL incident with valid URL: urlopen called with correct JSON payload
    - Network error (URLError): caught and logged, no crash
    - Unexpected exception: caught and logged, no crash
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch, call

from app.integrations.alert_service import send_slack_alert
from app.schemas.log import TriageResult, Severity, Category


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

INCIDENT_ID = "test-incident-uuid-1234"

CRITICAL_RESULT = TriageResult(
    severity=Severity.CRITICAL,
    category=Category.DATABASE,
    root_cause="Connection pool exhausted.",
    remediation="1. Kill stale connections. 2. Increase pool size.",
)

LOW_RESULT = TriageResult(
    severity=Severity.LOW,
    category=Category.APPLICATION,
    root_cause="Minor log warning.",
    remediation="No action required.",
)

MEDIUM_RESULT = TriageResult(
    severity=Severity.MEDIUM,
    category=Category.NETWORK,
    root_cause="Elevated latency detected.",
    remediation="Investigate network path.",
)

VALID_WEBHOOK = "https://hooks.slack.com/services/T000/B000/testwebhooktoken"


# ---------------------------------------------------------------------------
# Non-critical incidents — no alert should be sent
# ---------------------------------------------------------------------------

class TestNonCriticalAlerts:

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_low_severity_does_not_call_urlopen(self, mock_urlopen):
        send_slack_alert(INCIDENT_ID, LOW_RESULT)
        mock_urlopen.assert_not_called()

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_medium_severity_does_not_call_urlopen(self, mock_urlopen):
        send_slack_alert(INCIDENT_ID, MEDIUM_RESULT)
        mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# Missing or unconfigured webhook URL
# ---------------------------------------------------------------------------

class TestUnconfiguredWebhook:

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_missing_webhook_url_does_not_crash(self, mock_urlopen, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)  # must not raise
        mock_urlopen.assert_not_called()

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_placeholder_webhook_url_does_not_crash(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/your/webhook/url")
        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)  # must not raise
        mock_urlopen.assert_not_called()

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_empty_webhook_url_does_not_crash(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)  # must not raise
        mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# CRITICAL incident with valid webhook — alert must be sent
# ---------------------------------------------------------------------------

class TestCriticalAlertSent:

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_critical_alert_calls_urlopen(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", VALID_WEBHOOK)
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)

        mock_urlopen.assert_called_once()

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_critical_alert_payload_contains_incident_id(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", VALID_WEBHOOK)
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)

        # Extract the request object passed to urlopen
        request_arg = mock_urlopen.call_args[0][0]
        payload_bytes = request_arg.data
        payload = json.loads(payload_bytes.decode("utf-8"))

        assert INCIDENT_ID in payload["text"]
        assert "CRITICAL" in payload["text"]

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_critical_alert_uses_json_content_type(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", VALID_WEBHOOK)
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)

        request_arg = mock_urlopen.call_args[0][0]
        assert request_arg.headers.get("Content-type") == "application/json"


# ---------------------------------------------------------------------------
# Error handling — network failures must not crash the caller
# ---------------------------------------------------------------------------

class TestAlertErrorHandling:

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_url_error_does_not_propagate(self, mock_urlopen, monkeypatch):
        """URLError during Slack POST must be caught — not crash the background task."""
        from urllib.error import URLError
        monkeypatch.setenv("SLACK_WEBHOOK_URL", VALID_WEBHOOK)
        mock_urlopen.side_effect = URLError("Connection refused")

        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)  # must not raise

    @patch("app.integrations.alert_service.urllib.request.urlopen")
    def test_unexpected_exception_does_not_propagate(self, mock_urlopen, monkeypatch):
        """Any unexpected exception must be swallowed to protect the background task."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", VALID_WEBHOOK)
        mock_urlopen.side_effect = RuntimeError("Unexpected error")

        send_slack_alert(INCIDENT_ID, CRITICAL_RESULT)  # must not raise
