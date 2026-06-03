"""
Unit tests for app/utils/validation.py (Layer 2 semantic validation).

These are pure unit tests with no database, HTTP client, or mocks.
They directly test the is_valid_log() function.

Coverage:
    - Valid messages return (True, None)
    - Fewer than 3 words returns (False, reason)
    - Purely numeric string returns (False, reason)
    - Symbols/numbers only (no letters) returns (False, reason)
    - Mixed content with numbers and letters passes
    - Multi-line messages with 3+ words pass
    - Leading/trailing whitespace is handled
"""

import pytest

from app.utils.validation import is_valid_log


class TestIsValidLog:
    """Tests for the Layer 2 semantic validation utility."""

    # ------------------------------------------------------------------
    # Valid messages — should pass all rules
    # ------------------------------------------------------------------

    def test_valid_standard_log_passes(self):
        valid, reason = is_valid_log("Database connection pool exhausted after 30 seconds")
        assert valid is True
        assert reason is None

    def test_valid_three_word_message_passes(self):
        valid, reason = is_valid_log("disk read error")
        assert valid is True
        assert reason is None

    def test_valid_mixed_alphanumeric_passes(self):
        """Messages with numbers and letters together are valid."""
        valid, reason = is_valid_log("error code 500 in payment service")
        assert valid is True
        assert reason is None

    def test_valid_message_with_special_chars_passes(self):
        """Messages containing special chars alongside words are valid."""
        valid, reason = is_valid_log("OOM error: java.lang.OutOfMemoryError at heap")
        assert valid is True
        assert reason is None

    def test_valid_message_with_leading_whitespace_passes(self):
        """Leading and trailing whitespace is stripped internally."""
        valid, reason = is_valid_log("  disk read error  ")
        assert valid is True

    def test_valid_multiline_message_passes(self):
        valid, reason = is_valid_log("disk read error\nfile not found\n")
        assert valid is True

    # ------------------------------------------------------------------
    # Fewer than 3 words — Rule 1
    # ------------------------------------------------------------------

    def test_single_word_fails(self):
        valid, reason = is_valid_log("error")
        assert valid is False
        assert reason is not None
        assert "3 words" in reason.lower() or "fewer" in reason.lower()

    def test_two_word_message_fails(self):
        valid, reason = is_valid_log("database timeout")
        assert valid is False
        assert reason is not None

    def test_empty_string_fails(self):
        """Empty string has zero words."""
        valid, reason = is_valid_log("   ")
        assert valid is False

    # ------------------------------------------------------------------
    # Purely numeric — Rule 2
    # ------------------------------------------------------------------

    def test_purely_numeric_string_fails(self):
        valid, reason = is_valid_log("12345678901234567890")
        # '12345678901234567890' is 1 word, so Rule 1 fires first
        assert valid is False
        assert reason is not None

    def test_all_digits_multi_word_fails(self):
        """Three-word all-digit string fails Rule 3 (no alphabetical characters)."""
        valid, reason = is_valid_log("123 456 789")
        # Should fail Rule 3 (no alphabetical characters)
        assert valid is False
        assert "alphabetical" in reason.lower() or reason is not None

    # ------------------------------------------------------------------
    # No alphabetical characters — Rule 3
    # ------------------------------------------------------------------

    def test_symbols_only_fails(self):
        valid, reason = is_valid_log("!!! @@@ ### $$$ %%% ^^^")
        assert valid is False
        assert "alphabetical" in reason.lower() or "no alphabetical" in reason.lower()

    def test_mixed_symbols_and_numbers_fails(self):
        valid, reason = is_valid_log("123 !@# 456 $%^")
        assert valid is False

    def test_punctuation_only_fails(self):
        valid, reason = is_valid_log("... --- +++")
        assert valid is False

    # ------------------------------------------------------------------
    # Return type contract
    # ------------------------------------------------------------------

    def test_valid_result_is_tuple_of_true_none(self):
        result = is_valid_log("valid log entry here")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result == (True, None)

    def test_invalid_result_is_tuple_of_false_string(self):
        valid, reason = is_valid_log("bad")
        assert valid is False
        assert isinstance(reason, str)
        assert len(reason) > 0
