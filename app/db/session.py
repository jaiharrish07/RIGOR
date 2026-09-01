"""SQLAlchemy engine and session management.

This module is the ONLY place in the app that creates a database engine.
Every other module gets a session via ``get_db`` (a FastAPI dependency)
or ``session_scope`` (a context manager for scripts and tests).
"""
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# The engine is a connection pool, not a single connection.
# pool_pre_ping=True: verify connections are alive before using — cheap
# insurance against stale connections after Postgres restarts.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,  # Set True to log every SQL statement (noisy — use only for debugging).
    future=True,
)

# SessionLocal is a factory that creates new Session objects.
# We create one Session per HTTP request, not one per process.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session per request.

    Usage in an endpoint:

        @router.get("/papers/{id}")
        def read_paper(id: UUID, db: Session = Depends(get_db)):
            return db.query(Paper).get(id)

    The session is closed automatically after the request completes,
    even if the endpoint raises an exception.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for use outside FastAPI (scripts, tests, CLI tools).

    Commits on success, rolls back on exception, always closes.

    Usage:

        with session_scope() as db:
            db.add(paper)
            # auto-commits here if no exception
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()