"""FastAPI application.

Minimal by design. This file was committed empty; only `/health` is implemented
here, because the database work and its tests need something importable to run
against. The /papers endpoints belong to the parsing pipeline and are NOT
implemented here.

`/health` follows docs/api_contract.md, which declares itself the source of
truth ("If backend and frontend disagree on a field, this doc wins").
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db.session import engine

# Version comes from package metadata rather than a hardcoded literal.
try:  # pragma: no cover - trivial fallback
    from importlib.metadata import version as _pkg_version

    APP_VERSION = _pkg_version("rigor")
except Exception:  # pragma: no cover
    APP_VERSION = "0.0.0"

app = FastAPI(title="RIGOR", version=APP_VERSION)

# CORS open during Week 1 development, per the API contract.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _database_status() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "unavailable"


def _grobid_status() -> str:
    """Probe GROBID's liveness endpoint.

    NOTE: the API contract names the field but specifies no probe, timeout, or
    success condition (gap C2). This uses GROBID's documented /api/isalive with
    a short timeout; confirm before relying on it.
    """
    import httpx

    try:
        r = httpx.get(f"{settings.grobid_url}/api/isalive", timeout=2.0)
        return "connected" if r.status_code == 200 else "unavailable"
    except Exception:
        return "unavailable"


@app.get("/health")
def health() -> dict:
    database = _database_status()
    grobid = _grobid_status()
    degraded = "unavailable" in (database, grobid)
    return {
        "status": "degraded" if degraded else "ok",
        "database": database,
        "grobid": grobid,
        "version": APP_VERSION,
    }
