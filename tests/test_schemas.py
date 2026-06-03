"""
Unit tests for Pydantic v2 schemas in app/schemas/log.py.

These tests are pure unit tests — no database, no HTTP client, no mocking.
They verify the validation rules defined on LogCreate and TriageResult directly.

Coverage:
    LogCreate:
        - valid message passes
        - message below min_length (10) fails
        - message above max_length (5000) fails
        - purely numeric message fails field_validator
        - fewer than 3 words fails field_validator
        - leading/trailing whitespace is stripped (str_strip_whitespace=True)

    TriageResult:
        - valid structured output passes
        - invalid severity enum value fails
        - invalid category enum value fails
        - missing required field fails
        - root_cause empty string fails (min_length=1)
"""

import pytest
from pydantic import ValidationError

from app.schemas.log import (
    LogCreate,
    TriageResult,
    Severity,
    Category,
)

# ---------------------------------------------------------------------------
# LogCreate — Layer 1 Pydantic validation
# ---------------------------------------------------------------------------


class TestLogCreate:
    """Tests for the LogCreate request schema."""

    def test_valid_message_passes(self):
        log = LogCreate(message="Database connection timeout after 30 seconds")
        assert log.message == "Database connection timeout after 30 seconds"

    def test_whitespace_is_stripped(self):
        log = LogCreate(message="  Database connection timed out  ")
        assert log.message == "Database connection timed out"

    def test_message_at_minimum_length_passes(self):
        """A message with 3 words that is exactly 10 characters long passes both rules."""
        # 'err or now' = 10 chars, 3 words — satisfies min_length=10 and 3-word rule
        log = LogCreate(message="err or now")
        assert log.message == "err or now"

    def test_message_too_short_fails(self):
        """Messages under 10 characters raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            LogCreate(message="short")
        assert "min_length" in str(exc_info.value).lower() or "10" in str(exc_info.value)

    def test_message_too_long_fails(self):
        """Messages over 5000 characters raise ValidationError."""
        with pytest.raises(ValidationError):
            LogCreate(message="x " * 2501)  # 5002 chars

    def test_purely_numeric_message_fails(self):
        """Digit-only strings are rejected by the field_validator."""
        with pytest.raises(ValidationError) as exc_info:
            LogCreate(message="1234567890")
        assert "numeric" in str(exc_info.value).lower()

    def test_fewer_than_3_words_fails(self):
        """Messages with 1 or 2 words are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            LogCreate(message="database timeout")
        assert "3 words" in str(exc_info.value).lower() or "meaningful" in str(exc_info.value).lower()

    def test_empty_message_fails(self):
        """Empty string is rejected (fails min_length and blank check)."""
        with pytest.raises(ValidationError):
            LogCreate(message="")

    def test_whitespace_only_message_fails(self):
        """Whitespace-only messages are stripped to empty and then rejected."""
        with pytest.raises(ValidationError):
            LogCreate(message="      ")

    def test_exactly_3_words_passes(self):
        """Messages with exactly 3 meaningful words should pass."""
        log = LogCreate(message="disk full error")
        assert log.message == "disk full error"


# ---------------------------------------------------------------------------
# TriageResult — LLM output schema validation
# ---------------------------------------------------------------------------


class TestTriageResult:
    """Tests for the TriageResult schema that validates LLM output."""

    def test_valid_triage_result_passes(self):
        result = TriageResult(
            severity=Severity.CRITICAL,
            category=Category.DATABASE,
            root_cause="Connection pool exhausted by long-running queries.",
            remediation="1. Terminate stale queries. 2. Increase pool size. 3. Add query timeout.",
        )
        assert result.severity == Severity.CRITICAL
        assert result.category == Category.DATABASE

    def test_all_severity_values_are_accepted(self):
        for sev in ("LOW", "MEDIUM", "CRITICAL"):
            result = TriageResult(
                severity=sev,
                category=Category.NETWORK,
                root_cause="Some root cause.",
                remediation="Some remediation.",
            )
            assert result.severity.value == sev

    def test_all_category_values_are_accepted(self):
        for cat in ("DATABASE", "NETWORK", "APPLICATION", "SECURITY"):
            result = TriageResult(
                severity=Severity.LOW,
                category=cat,
                root_cause="Some root cause.",
                remediation="Some remediation.",
            )
            assert result.category.value == cat

    def test_invalid_severity_fails(self):
        """Unrecognised severity value raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TriageResult(
                severity="UNKNOWN",
                category=Category.APPLICATION,
                root_cause="Something.",
                remediation="Do something.",
            )
        assert "severity" in str(exc_info.value).lower() or "unknown" in str(exc_info.value).lower()

    def test_invalid_category_fails(self):
        """Unrecognised category value raises ValidationError."""
        with pytest.raises(ValidationError):
            TriageResult(
                severity=Severity.LOW,
                category="STORAGE",  # not a valid Category
                root_cause="Something.",
                remediation="Do something.",
            )

    def test_missing_severity_fails(self):
        with pytest.raises(ValidationError):
            TriageResult(
                category=Category.NETWORK,
                root_cause="Something.",
                remediation="Do something.",
            )

    def test_missing_root_cause_fails(self):
        with pytest.raises(ValidationError):
            TriageResult(
                severity=Severity.MEDIUM,
                category=Category.APPLICATION,
                remediation="Do something.",
            )

    def test_empty_root_cause_fails(self):
        """root_cause has min_length=1 so empty string is rejected."""
        with pytest.raises(ValidationError):
            TriageResult(
                severity=Severity.LOW,
                category=Category.SECURITY,
                root_cause="",
                remediation="Do something.",
            )

    def test_empty_remediation_fails(self):
        """remediation has min_length=1 so empty string is rejected."""
        with pytest.raises(ValidationError):
            TriageResult(
                severity=Severity.LOW,
                category=Category.SECURITY,
                root_cause="Something.",
                remediation="",
            )
