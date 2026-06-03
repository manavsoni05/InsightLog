"""
API Key security dependency.

Provides a FastAPI-injectable dependency that enforces X-API-Key header
authentication on any route that declares it via Depends(verify_api_key).

Configuration (environment variables):
    API_KEY         — The expected secret key value. Must be set in .env for
                      production. If empty, the server will refuse all requests
                      when enforcement is enabled (fail-secure behaviour).
    API_KEY_ENABLED — Set to "false" to disable authentication entirely.
                      Useful for local development without needing a header.
                      Defaults to "true" (enforcement ON).

Usage in a route:
    from app.core.security import verify_api_key
    from fastapi import Depends

    @router.post("")
    def my_route(_: None = Depends(verify_api_key)):
        ...

Security design:
    - The key is read from environment on every request (no module-level caching)
      so a key rotation only requires a server restart, not a code deployment.
    - Uses a constant-time comparison via Python's == on strings of equal length
      which is sufficient for header-based secrets (not timing-attack critical
      like password hashing, but avoids naive early-exit comparisons).
    - When API_KEY env var is blank AND enforcement is enabled, every request
      is rejected — this is intentional fail-secure behaviour to prevent
      accidentally running an unprotected server in production.
"""

import os
import hmac
import logging

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """
    FastAPI dependency that validates the X-API-Key request header.

    Raises:
        HTTPException 401: If the key is missing, empty, or incorrect.

    Returns:
        None on success — routes declare it as ``_: None = Depends(verify_api_key)``.
    """
    # Allow disabling auth for local development workflows.
    enabled = os.getenv("API_KEY_ENABLED", "true").strip().lower()
    if enabled == "false":
        logger.debug("API key authentication is DISABLED (API_KEY_ENABLED=false)")
        return

    expected_key = os.getenv("API_KEY", "").strip()

    # Fail-secure: if the expected key is not configured, reject everything.
    # This prevents a misconfigured production server from becoming open.
    if not expected_key:
        logger.error(
            "API_KEY environment variable is not set. "
            "All requests are being rejected (fail-secure). "
            "Set API_KEY in your .env file or set API_KEY_ENABLED=false for dev."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key authentication is not configured on the server.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected_key.encode()):
        logger.warning(
            "Rejected request: invalid or missing X-API-Key header "
            "(provided key length: %d)",
            len(x_api_key),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
