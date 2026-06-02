from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.database.base import Base
from app.database.session import engine
from app.api import logs as logs_router

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

# Register routers
app.include_router(logs_router.router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict:
    """Simple liveness probe."""
    return {"status": "ok"}
