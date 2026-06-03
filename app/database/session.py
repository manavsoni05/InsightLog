import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./incidents.db")

# connect_args is SQLite-specific: allows the same connection to be used
# across multiple threads (needed for FastAPI's thread pool).
# check_same_thread is a SQLite-only connection argument that allows the same
# connection to be reused across multiple threads (required for FastAPI's thread
# pool). Passing it to any other driver (e.g. psycopg2 for PostgreSQL) raises a
# TypeError at startup. We detect the dialect from the URL and only apply it for
# SQLite so this module is safe to use with any DATABASE_URL value.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine_kwargs = {"connect_args": _connect_args}
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    """
    FastAPI dependency that provides a database session per request.
    Ensures the session is always closed after the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
