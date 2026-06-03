import logging
import sys

# Configure root logger for live terminal updates and raw log storage
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app_runtime.log", encoding="utf-8", mode="a")
    ]
)

# Load environment variables FIRST — before any module reads os.environ.
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.database.base import Base
from app.database.session import engine
from app.api import logs as logs_router
from app.middleware.request_id import RequestIDMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from app.core.rate_limit import limiter

# Import all models here so Base.metadata knows about them
# before create_all is called.
import app.models.incident  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create all database tables on startup if they don't already exist."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI Incident Triage Service",
    description="Receives application logs, classifies them with Gemini, and alerts on critical incidents.",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware — registered before routers so every request is intercepted.
# RequestIDMiddleware generates a UUID4 per request, stores it in a ContextVar
# that is readable by all service-layer code, and injects X-Request-ID into
# every response header for client-side correlation.
app.add_middleware(RequestIDMiddleware)

# Register routers
app.include_router(logs_router.router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict:
    """Simple liveness probe."""
    return {"status": "ok"}
