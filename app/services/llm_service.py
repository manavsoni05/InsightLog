"""
LLM service — isolated Gemini 2.5 Flash integration.

Responsibilities:
    - Configure the Gemini client from environment.
    - Build the structured classification prompt.
    - Call the Gemini API and receive a response.
    - Extract JSON from the response (handles markdown code fences).
    - Deserialise and validate the JSON against the TriageResult schema.
    - Raise LLMServiceError for any failure so triage_service can mark FAILED.

Design rules:
    - No database access. No FastAPI imports. No business workflow logic.
    - All Gemini-specific code is confined to this module.
    - Returns a fully validated TriageResult; callers never see raw Gemini output.
"""

import json
import logging
import os
import re
import time
import warnings

from pydantic import ValidationError

from app.schemas.log import TriageResult

# Suppress the FutureWarning from the deprecated google-generativeai package
# so it does not pollute production logs on every request.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import google.generativeai as genai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Model name is configurable via env so it can be updated without code change.
# Default: gemini-2.5-flash as required by INSTRUCTIONS.md.
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Lazy-initialised model instance — created on first call to analyze().
_model: genai.GenerativeModel | None = None  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class LLMServiceError(Exception):
    """
    Raised when the LLM service cannot produce a valid triage result.

    Covers: missing API key, network/API errors, malformed JSON,
    and Pydantic validation failures on the Gemini response.
    """


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are an expert site-reliability engineer performing automated incident triage.

Analyse the following application or server log message and classify it.

Log message:
\"\"\"
{message}
\"\"\"

You MUST return a single JSON object — no markdown, no explanation, no code fences.
The JSON object must have exactly these four fields:

{{
  "severity":    "<one of: LOW | MEDIUM | CRITICAL>",
  "category":   "<one of: DATABASE | NETWORK | APPLICATION | SECURITY>",
  "root_cause":  "<concise 1-3 sentence explanation of the most likely root cause>",
  "remediation": "<action steps as a single plain string, e.g. '1. Do X. 2. Do Y. 3. Do Z.'>"
}}

CRITICAL RULES:
  - All four values MUST be plain strings — NOT arrays, NOT nested objects.
  - remediation MUST be a single string, never a JSON array.
  - severity MUST be exactly one of: LOW, MEDIUM, CRITICAL
  - category MUST be exactly one of: DATABASE, NETWORK, APPLICATION, SECURITY

Severity definitions:
  LOW      — Informational event; no immediate action required.
  MEDIUM   — Degraded behaviour or warning; investigate within hours.
  CRITICAL — Active service impact; requires immediate action.

Category definitions:
  DATABASE    — Database connection, query, replication, or storage issues.
  NETWORK     — Connectivity, DNS, latency, firewall, or TLS issues.
  APPLICATION — Code errors, crashes, memory leaks, or unexpected behaviour.
  SECURITY    — Authentication failures, authorisation violations, or intrusion signals.

Return ONLY the JSON object. Any response that is not valid JSON will be rejected.
"""


def _build_prompt(message: str) -> str:
    """Inject the log message into the classification prompt template."""
    return _PROMPT_TEMPLATE.format(message=message)


# ---------------------------------------------------------------------------
# Gemini client (lazy initialisation)
# ---------------------------------------------------------------------------


def _get_model() -> "genai.GenerativeModel":  # type: ignore[name-defined]
    """
    Return the cached Gemini GenerativeModel, initialising it on first call.

    Lazy initialisation means a missing API key only fails when analyze()
    is actually called, not at import time — allowing tests that mock
    llm_service to import cleanly without a real API key.
    """
    global _model
    if _model is not None:
        return _model

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your-gemini-api-key-here":
        raise LLMServiceError(
            "GEMINI_API_KEY is not configured. "
            "Set a valid API key in the .env file."
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        genai.configure(api_key=api_key)

        _model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            generation_config=genai.GenerationConfig(
                # Instructs Gemini to return JSON only — primary enforcement.
                # The prompt itself is the secondary enforcement.
                response_mime_type="application/json",
                temperature=0.1,  # low temperature for consistent structured output
            ),
        )

    logger.info("Gemini model initialised: %s", GEMINI_MODEL)
    return _model


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """
    Extract a raw JSON string from Gemini's response text.

    Handles three response formats:
      1. Pure JSON  — returned directly.
      2. ```json ... ```  — markdown code fence with language tag.
      3. ``` ... ```      — markdown code fence without language tag.

    Args:
        text: Raw text returned by the Gemini API.

    Returns:
        The JSON string ready for json.loads().

    Raises:
        LLMServiceError: If no JSON-like content can be found.
    """
    text = text.strip()

    if not text:
        raise LLMServiceError("Gemini returned an empty response.")

    # Strip markdown code fences if present (common even with response_mime_type set)
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # If it starts with { it is likely already raw JSON
    if text.startswith("{"):
        return text

    raise LLMServiceError(
        f"Gemini response does not contain a JSON object. "
        f"Raw response (first 300 chars): {text[:300]!r}"
    )


def _coerce_response(parsed: dict) -> dict:
    """
    Defensively coerce Gemini output fields to the types TriageResult expects.

    Despite explicit prompt instructions, Gemini occasionally returns
    ``remediation`` or ``root_cause`` as a JSON array instead of a string.
    This function converts any list value to a numbered plain-text string
    so that Pydantic validation does not fail on a correctable format issue.

    Only ``root_cause`` and ``remediation`` are coerced — ``severity`` and
    ``category`` must remain as-is so that invalid enum values still fail
    Pydantic validation as expected.

    Args:
        parsed: The raw dict from json.loads().

    Returns:
        The same dict with list fields converted to numbered strings.
    """
    for field in ("root_cause", "remediation"):
        value = parsed.get(field)
        if isinstance(value, list):
            # Convert ["Step A", "Step B"] → "1. Step A 2. Step B"
            parsed[field] = " ".join(
                f"{i}. {item}" for i, item in enumerate(value, start=1)
            )
            logger.debug(
                "Coerced '%s' from list to string (%d items)", field, len(value)
            )
    return parsed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(message: str) -> TriageResult:
    """
    Classify a log message using Gemini 2.5 Flash.

    Args:
        message: The raw log message to analyse.

    Returns:
        A fully validated TriageResult containing severity, category,
        root_cause, and remediation.

    Raises:
        LLMServiceError: For any failure: API error, malformed JSON,
                         or Pydantic validation failure.
    """
    model = _get_model()
    prompt = _build_prompt(message)

    logger.info("Calling Gemini (%s) for triage analysis", GEMINI_MODEL)

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            # --- API call ---
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", FutureWarning)
                    response = model.generate_content(prompt)
                raw_text: str = response.text
            except Exception as exc:
                raise LLMServiceError(
                    f"Gemini API call failed: {type(exc).__name__}: {exc}"
                ) from exc

            logger.debug("Gemini raw response: %s", raw_text[:500])

            # --- JSON extraction ---
            json_str = _extract_json(raw_text)

            # --- Deserialisation ---
            try:
                parsed: dict = json.loads(json_str)
            except json.JSONDecodeError as exc:
                raise LLMServiceError(
                    f"Gemini response is not valid JSON: {exc}. "
                    f"Raw JSON string: {json_str[:300]!r}"
                ) from exc

            # --- Coerce before validation (handles list fields from Gemini) ---
            parsed = _coerce_response(parsed)

            # --- Pydantic validation ---
            try:
                result = TriageResult.model_validate(parsed)
            except ValidationError as exc:
                raise LLMServiceError(
                    f"Gemini response failed schema validation: {exc}. "
                    f"Parsed dict: {parsed}"
                ) from exc

            logger.info(
                "Gemini triage complete: severity=%s category=%s",
                result.severity.value,
                result.category.value,
            )
            return result
            
        except LLMServiceError as exc:
            if attempt >= max_attempts:
                logger.error("Gemini analysis completely failed after %d attempts.", max_attempts)
                raise
                
            wait_time = attempt
            logger.warning(
                "Gemini analysis attempt %d failed: %s. Retrying in %ds...",
                attempt, str(exc).splitlines()[0], wait_time
            )
            time.sleep(wait_time)
