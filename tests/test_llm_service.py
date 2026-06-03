"""
Unit tests for app/services/llm_service.py.

All Gemini API calls are mocked — no real API key required. Tests run fully
offline and verify the internal logic of the llm_service module:
    - Successful analysis returns a validated TriageResult
    - None response.text raises LLMServiceError (Issue 5 fix)
    - Invalid JSON raises LLMServiceError
    - Pydantic validation failure on LLM output raises LLMServiceError
    - Retry logic fires on failure and eventually raises after max_attempts
    - _extract_json handles markdown fences and bare JSON correctly
    - _coerce_response converts list fields to strings

Testing strategy:
    - mock the GenerativeModel.generate_content() method at the module level
    - reset the module-level _model cache before each test to allow
      _get_model() to be short-circuited by patching it directly
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.integrations.llm_service import (
    LLMServiceError,
    _extract_json,
    _coerce_response,
    _build_prompt,
)
from app.schemas.log import Severity, Category


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_LLM_RESPONSE = json.dumps({
    "severity": "CRITICAL",
    "category": "DATABASE",
    "root_cause": "Connection pool exhausted by long-running query.",
    "remediation": "1. Kill stale queries. 2. Increase pool size.",
})


def _mock_response(text: str | None) -> MagicMock:
    """Create a mock Gemini response object with the given text."""
    mock = MagicMock()
    mock.text = text
    return mock


# ---------------------------------------------------------------------------
# _build_prompt — safe concatenation (Issue 4 fix)
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_prompt_contains_message(self):
        msg = "Database connection timed out after 30 seconds"
        prompt = _build_prompt(msg)
        assert msg in prompt

    def test_prompt_with_curly_braces_does_not_crash(self):
        """
        The old .format() implementation would raise KeyError for messages
        containing { or } characters. Safe concatenation must not raise.
        """
        msg = "{evil injection} some log message with braces {}"
        prompt = _build_prompt(msg)  # must not raise
        assert msg in prompt

    def test_prompt_uses_xml_delimiters(self):
        """Message must be enclosed in <log_message> XML tags."""
        prompt = _build_prompt("test message for triage")
        assert "<log_message>" in prompt
        assert "</log_message>" in prompt

    def test_prompt_contains_json_schema(self):
        """Static prompt sections must reference the four required fields."""
        prompt = _build_prompt("some log")
        for field in ("severity", "category", "root_cause", "remediation"):
            assert field in prompt


# ---------------------------------------------------------------------------
# _extract_json — JSON extraction from raw Gemini output
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_bare_json_returned_directly(self):
        raw = '{"severity": "LOW", "category": "NETWORK"}'
        assert _extract_json(raw) == raw

    def test_markdown_json_fence_stripped(self):
        raw = '```json\n{"severity": "LOW"}\n```'
        result = _extract_json(raw)
        assert result == '{"severity": "LOW"}'

    def test_markdown_fence_without_language_tag_stripped(self):
        raw = '```\n{"severity": "MEDIUM"}\n```'
        result = _extract_json(raw)
        assert result == '{"severity": "MEDIUM"}'

    def test_empty_string_raises_llm_service_error(self):
        with pytest.raises(LLMServiceError, match="empty"):
            _extract_json("")

    def test_plain_text_raises_llm_service_error(self):
        with pytest.raises(LLMServiceError):
            _extract_json("Here is my explanation without any JSON object.")


# ---------------------------------------------------------------------------
# _coerce_response — list-to-string field coercion
# ---------------------------------------------------------------------------

class TestCoerceResponse:
    def test_string_fields_unchanged(self):
        parsed = {
            "severity": "LOW",
            "category": "NETWORK",
            "root_cause": "A string.",
            "remediation": "Another string.",
        }
        result = _coerce_response(parsed)
        assert result["root_cause"] == "A string."
        assert result["remediation"] == "Another string."

    def test_list_root_cause_coerced_to_string(self):
        parsed = {"root_cause": ["Step A", "Step B"], "remediation": "Fixed."}
        result = _coerce_response(parsed)
        assert isinstance(result["root_cause"], str)
        assert "1." in result["root_cause"]
        assert "Step A" in result["root_cause"]

    def test_list_remediation_coerced_to_string(self):
        parsed = {"root_cause": "Something.", "remediation": ["Do X", "Do Y", "Do Z"]}
        result = _coerce_response(parsed)
        assert isinstance(result["remediation"], str)
        assert "1." in result["remediation"]
        assert "3." in result["remediation"]

    def test_severity_and_category_not_coerced(self):
        """Only root_cause and remediation are coerced. Severity/category must stay as-is."""
        parsed = {
            "severity": "CRITICAL",
            "category": "DATABASE",
            "root_cause": "Root.",
            "remediation": "Fix.",
        }
        result = _coerce_response(parsed)
        assert result["severity"] == "CRITICAL"
        assert result["category"] == "DATABASE"


# ---------------------------------------------------------------------------
# analyze() — full integration with mocked Gemini model
# ---------------------------------------------------------------------------

class TestAnalyze:
    """Tests for the public analyze() function with mocked Gemini."""

    @patch("app.integrations.llm_service._get_model")
    def test_analyze_success_returns_triage_result(self, mock_get_model):
        """Valid Gemini response is parsed and returned as TriageResult."""
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _mock_response(VALID_LLM_RESPONSE)
        mock_get_model.return_value = mock_model

        from app.integrations.llm_service import analyze
        result = analyze("Database connection pool exhausted after 30 seconds")

        assert result.severity == Severity.CRITICAL
        assert result.category == Category.DATABASE
        assert len(result.root_cause) > 0
        assert len(result.remediation) > 0

    @patch("app.integrations.llm_service._get_model")
    def test_analyze_none_response_text_raises_llm_service_error(self, mock_get_model):
        """
        Issue 5 fix: None response.text must raise LLMServiceError (not AttributeError)
        so the retry loop catches it correctly.
        """
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _mock_response(None)
        mock_get_model.return_value = mock_model

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError, match="None/empty"):
            analyze("Some log message that triggers a None response")

    @patch("app.integrations.llm_service._get_model")
    def test_analyze_invalid_json_raises_llm_service_error(self, mock_get_model):
        """Malformed JSON in Gemini response raises LLMServiceError."""
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _mock_response("{broken json: }")
        mock_get_model.return_value = mock_model

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError):
            analyze("Some valid log message for testing purposes")

    @patch("app.integrations.llm_service._get_model")
    def test_analyze_invalid_schema_raises_llm_service_error(self, mock_get_model):
        """JSON with wrong enum values fails Pydantic validation."""
        mock_model = MagicMock()
        bad_response = json.dumps({
            "severity": "SUPER_CRITICAL",   # not a valid enum
            "category": "STORAGE",           # not a valid enum
            "root_cause": "Some cause.",
            "remediation": "Some fix.",
        })
        mock_model.generate_content.return_value = _mock_response(bad_response)
        mock_get_model.return_value = mock_model

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError, match="schema validation"):
            analyze("Some valid log message for testing purposes")

    @patch("app.integrations.llm_service.time")
    @patch("app.integrations.llm_service._get_model")
    def test_analyze_retries_three_times_before_failing(self, mock_get_model, mock_time):
        """
        When Gemini consistently returns invalid data, analyze() must retry
        exactly 3 times before raising LLMServiceError.
        """
        mock_model = MagicMock()
        # Always return None response to trigger retry
        mock_model.generate_content.return_value = _mock_response(None)
        mock_get_model.return_value = mock_model
        mock_time.sleep = MagicMock()  # prevent actual sleeping in tests

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError):
            analyze("Some log message to trigger retry behaviour")

        # generate_content should be called exactly 3 times (max_attempts=3)
        assert mock_model.generate_content.call_count == 3

    @patch("app.integrations.llm_service.time")
    @patch("app.integrations.llm_service._get_model")
    def test_analyze_sleeps_between_retries(self, mock_get_model, mock_time):
        """
        Exponential backoff: attempt 1 → immediate, attempt 2 → sleep(1),
        attempt 3 → sleep(2). We verify time.sleep is called with the right values.
        """
        mock_model = MagicMock()
        mock_model.generate_content.return_value = _mock_response(None)
        mock_get_model.return_value = mock_model
        mock_time.sleep = MagicMock()

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError):
            analyze("Log message triggering retry with sleep verification")

        # sleep should be called twice: after attempt 1 (sleep 1), after attempt 2 (sleep 2)
        sleep_calls = [call.args[0] for call in mock_time.sleep.call_args_list]
        assert sleep_calls == [1, 2]


# ---------------------------------------------------------------------------
# FAILURE TEST A — Missing GEMINI_API_KEY
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    """
    Failure scenario: GEMINI_API_KEY environment variable is not configured.

    Real-world impact: A misconfigured deployment (missing secret in CI/CD,
    rotated key not yet redeployed) would cause every triage job to fail.
    This test verifies that the failure is caught cleanly as LLMServiceError
    (not a bare KeyError or AttributeError) so triage_service can mark the
    incident FAILED with a human-readable error_detail message.

    Implementation note: _get_model() is NOT mocked here — we let it run
    for real against a blank API key so the guard code path is exercised.
    The module-level _model cache is cleared before the test to ensure
    _get_model() actually runs (not returning the cached real model from
    a previous test session).
    """

    def test_missing_api_key_raises_llm_service_error(self, monkeypatch):
        """
        When GEMINI_API_KEY is blank, _get_model() must raise LLMServiceError
        with a clear message — not crash with AttributeError or KeyError.
        """
        import app.integrations.llm_service as llm_mod

        # Clear the module-level cache so _get_model() re-runs the key check
        original_model = llm_mod._model
        llm_mod._model = None

        # Blank out the API key
        monkeypatch.setenv("GEMINI_API_KEY", "")

        try:
            with pytest.raises(LLMServiceError) as exc_info:
                llm_mod.analyze("Database connection pool exhausted after 30 seconds")

            error_msg = str(exc_info.value).lower()
            # Must mention the key configuration, not a bare Python exception
            assert "gemini_api_key" in error_msg or "api key" in error_msg or "not configured" in error_msg
        finally:
            # Restore the original model state so other tests are unaffected
            llm_mod._model = original_model

    def test_placeholder_api_key_raises_llm_service_error(self, monkeypatch):
        """
        When GEMINI_API_KEY is set to the placeholder value from .env.example,
        the fail-secure check must catch it and raise LLMServiceError.
        This prevents accidentally running with an unconfigured key.
        """
        import app.integrations.llm_service as llm_mod

        original_model = llm_mod._model
        llm_mod._model = None

        monkeypatch.setenv("GEMINI_API_KEY", "your-gemini-api-key-here")

        try:
            with pytest.raises(LLMServiceError):
                llm_mod.analyze("Some log message for placeholder key test here")
        finally:
            llm_mod._model = original_model


# ---------------------------------------------------------------------------
# FAILURE TEST B — Network exception wrapped as LLMServiceError
# ---------------------------------------------------------------------------

class TestNetworkFailure:
    """
    Failure scenario: Gemini API is unreachable (network partition, DNS failure,
    or service outage). The raw network exception (ConnectionError, TimeoutError)
    must be wrapped into LLMServiceError so the retry loop handles it — not
    surface as an unhandled exception that bypasses retry and crashes the thread.

    Real-world impact: Without this wrapping, a 5-second network timeout on
    attempt 1 would jump directly to the outer except block in process_triage(),
    marking the incident FAILED with error_detail='ConnectionError: ...' instead
    of giving the retry system a chance to succeed on attempt 2 or 3.
    """

    @patch("app.integrations.llm_service.time")
    @patch("app.integrations.llm_service._get_model")
    def test_network_exception_is_wrapped_as_llm_service_error(
        self, mock_get_model, mock_time
    ):
        """
        When generate_content() raises a raw network exception (simulated as
        ConnectionError here), analyze() must wrap it in LLMServiceError so
        the retry loop catches it on all 3 attempts.
        """
        mock_model = MagicMock()
        # Simulate a network error on every attempt
        mock_model.generate_content.side_effect = ConnectionError("Network unreachable")
        mock_get_model.return_value = mock_model
        mock_time.sleep = MagicMock()

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError) as exc_info:
            analyze("Primary database replica is unreachable all writes failing now")

        # Must be LLMServiceError, not the raw ConnectionError
        assert "Gemini API call failed" in str(exc_info.value)
        # Must have retried all 3 times — not bailed on the first exception
        assert mock_model.generate_content.call_count == 3

    @patch("app.integrations.llm_service.time")
    @patch("app.integrations.llm_service._get_model")
    def test_network_exception_triggers_exponential_backoff(
        self, mock_get_model, mock_time
    ):
        """
        Network failures must trigger the same exponential backoff as LLM errors:
        sleep(1) after attempt 1, sleep(2) after attempt 2, raise after attempt 3.
        """
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = OSError("Connection timed out")
        mock_get_model.return_value = mock_model
        mock_time.sleep = MagicMock()

        from app.integrations.llm_service import analyze
        with pytest.raises(LLMServiceError):
            analyze("Disk IO error causing application to crash and burn severely")

        sleep_calls = [call.args[0] for call in mock_time.sleep.call_args_list]
        # Backoff: sleep(1) after attempt 1, sleep(2) after attempt 2
        assert sleep_calls == [1, 2]

