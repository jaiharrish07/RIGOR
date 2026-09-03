"""RIGOR backend — FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload

Then visit:
    http://localhost:8000/docs      — auto-generated API documentation
    http://localhost:8000/health    — service health check
"""
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db.session import engine

# Version comes from package metadata rather than a hardcoded literal.
try:
    from importlib.metadata import version as _pkg_version
    APP_VERSION = _pkg_version("rigor")
except Exception:
    APP_VERSION = "0.1.0"

app = FastAPI(
    title="RIGOR",
    description="Reproducibility Inspector for Grounded Open Research",
    version=APP_VERSION,
)

# CORS — permissive during Week 1 dev. Locked down later.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Report the service's health and the status of each dependency.

    Always returns HTTP 200 — the field values, not the status code,
    tell you what's up. This is what Docker and monitoring check.
    """
    # Check Postgres by running a trivial query.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception as exc:
        database_status = f"unavailable: {type(exc).__name__}"

    # Check GROBID by pinging its /api/isalive endpoint.
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(f"{settings.grobid_url}/api/isalive")
        grobid_status = "connected" if response.text.strip() == "true" else "unhealthy"
    except Exception as exc:
        grobid_status = f"unavailable: {type(exc).__name__}"

    overall = (
        "ok"
        if database_status == "connected" and grobid_status == "connected"
        else "degraded"
    )

    return {
        "status": overall,
        "database": database_status,
        "grobid": grobid_status,
        "version": APP_VERSION,
        "environment": settings.app_env,
    }