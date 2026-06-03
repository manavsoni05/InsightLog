"""
Semantic validation utilities.

Provides Layer 2 validation for incident logs, ensuring only
meaningful logs are passed to the database and LLM pipeline.
"""
import logging
import re

logger = logging.getLogger(__name__)


def is_valid_log(message: str) -> tuple[bool, str | None]:
    """
    Semantic validation (Layer 2) to reject garbage logs before DB insertion.

    Rejects:
    - Only numbers or symbols (no letters)
    - Less than 3 words
    - Matches regex for purely numeric or purely non-alphabetical

    Returns:
        (is_valid: bool, reason: str | None)
    """
    stripped = message.strip()

    # Rule 1: Must contain at least 3 words
    if len(stripped.split()) < 3:
        reason = "Log contains fewer than 3 words."
        logger.debug("Rejected log: %s | Payload: %r", reason, message)
        return False, reason

    # Rule 2: Cannot be purely numeric
    if re.match(r"^\d+$", stripped):
        reason = "Log is purely numeric."
        logger.debug("Rejected log: %s | Payload: %r", reason, message)
        return False, reason

    # Rule 3: Cannot be entirely devoid of alphabetical characters (only symbols/numbers)
    if re.match(r"^[^a-zA-Z]+$", stripped):
        reason = "Log contains no alphabetical characters (only symbols/numbers)."
        logger.debug("Rejected log: %s | Payload: %r", reason, message)
        return False, reason

    return True, None
