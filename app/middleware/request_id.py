"""
Request ID middleware for end-to-end distributed tracing.

Problem this solves:
    Without a shared identifier, the log output for concurrent requests is an
    interleaved stream of disconnected lines. When triage for 50 incidents runs
    simultaneously, it is impossible to tell which LLM call, DB write, or Slack
    alert belongs to which HTTP request.

Solution:
    This middleware generates a UUID4 for every incoming HTTP request and stores
    it in a contextvars.ContextVar. Because ContextVar is task-local (each
    asyncio task and thread-pool worker gets its own copy), services can read
    the ID at any point in the call chain without it being passed as a parameter.

    The ID is also returned to the caller as the ``X-Request-ID`` response header
    so clients can correlate their requests with server-side log entries.

Usage:
    In main.py:
        from app.middleware.request_id import RequestIDMiddleware
        app.add_middleware(RequestIDMiddleware)

    In any service module:
        from app.middleware.request_id import get_request_id
        logger.info("[%s] Processing ...", get_request_id())

    The BackgroundTask thread inherits the ContextVar value that was set during
    the HTTP request because FastAPI copies the context when scheduling background
    tasks — so the same request_id is visible inside process_triage().
"""

import uuid
import logging
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Module-level ContextVar — safe to read from any service without imports
# creating circular dependencies. The default value appears in logs for code
# paths that run outside of a request context (e.g. startup, tests).
_request_id_var: ContextVar[str] = ContextVar("request_id", default="no-request-id")


def get_request_id() -> str:
    """
    Return the request ID for the current task/thread context.

    Returns "no-request-id" when called outside of a live HTTP request
    (e.g. during server startup or in unit tests that do not set it).
    """
    return _request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that attaches a unique UUID to every HTTP request.

    Lifecycle per request:
        1. Generate uuid4 string.
        2. Store it in the ContextVar (propagates automatically to background tasks).
        3. Add it as ``X-Request-ID`` header on the response.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        _request_id_var.set(request_id)

        logger.debug("→ [%s] %s %s", request_id, request.method, request.url.path)

        response: Response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        logger.debug("← [%s] HTTP %s", request_id, response.status_code)

        return response
