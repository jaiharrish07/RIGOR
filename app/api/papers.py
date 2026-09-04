"""Papers API endpoints — upload, fetch, list.

Implements the contract defined in docs/api_contract.md:

    POST /papers         -- upload a PDF, parse via GROBID, save to DB
    GET  /papers/{id}    -- fetch one paper by UUID
    GET  /papers         -- paginated list of papers for dashboard

All endpoints return JSON. Errors follow the {"error": {code, message, details}}
envelope defined in the contract, NOT FastAPI's default {"detail": ...}.
"""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Paper
from app.db.session import get_db
from app.ingest.pdf_parser import (
    compute_file_metadata,
    extract_metadata,
    parse_pdf,
)

router = APIRouter(prefix="/papers", tags=["papers"])


# ─────────────────────────────────────────────────────────────────────────────
# Response builders  --  same shape used by POST and GET-by-id
# ─────────────────────────────────────────────────────────────────────────────

def build_paper_response(paper: Paper) -> dict[str, Any]:
    """Build the full 17-field paper response matching api_contract.md.

    Retraction fields deliberately omitted per Week 1 scope; Week 4 will add.
    """
    return {
        "id": str(paper.id),
        "filename": paper.filename,
        "file_size_bytes": paper.file_size_bytes,
        "sha256_hash": paper.sha256_hash,
        "page_count": paper.page_count,
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "keywords": paper.keywords,
        "doi": paper.doi,
        "publication_year": paper.publication_year,
        "venue": paper.venue,
        "journal_ref": paper.journal_ref,
        "status": paper.status,
        "error_message": paper.error_message,
        "uploaded_at": paper.uploaded_at.isoformat(),
        "parsed_at": paper.parsed_at.isoformat() if paper.parsed_at else None,
    }


def build_paper_summary(paper: Paper) -> dict[str, Any]:
    """Build the 9-field compact summary for GET /papers list.

    Smaller payload than the full paper -- suitable for the dashboard grid.
    """
    return {
        "id": str(paper.id),
        "filename": paper.filename,
        "title": paper.title,
        "authors_summary": _authors_summary(paper.authors),
        "publication_year": paper.publication_year,
        "venue": paper.venue,
        "status": paper.status,
        "page_count": paper.page_count,
        "uploaded_at": paper.uploaded_at.isoformat(),
    }


def _authors_summary(authors: list[dict] | None) -> str | None:
    """'Vaswani et al.' style compact string. None if no authors.

    Uses the LAST word of the first author's full_name as the surname
    (works for 'Ashish Vaswani' → 'Vaswani'). For non-Western name orders
    this is wrong; Week 5's ML improvements will address it.
    """
    if not authors:
        return None
    first = authors[0]
    full_name = (first.get("full_name") or "").strip()
    if not full_name:
        return None
    surname = full_name.split()[-1]
    return f"{surname} et al." if len(authors) > 1 else surname


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    """Return a JSONResponse matching the contract's error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /papers  --  upload, parse, save
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def upload_paper(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a PDF, parse via GROBID, save to DB, return the parsed paper.

    Sync path: waits for GROBID to finish (5-60 sec) before responding.
    Week 3+ will queue this async.

    Returns 201 for new papers, 200 when returning an already-uploaded
    paper (deduplication by sha256).
    """
    # STEP 1: Read file bytes
    contents = await file.read()

    # STEP 2: Size check (fast)
    if len(contents) > settings.max_upload_size_bytes:
        return _error(
            413, "file_too_large",
            f"File exceeds {settings.max_upload_size_mb} MB limit.",
            {
                "max_size_bytes": settings.max_upload_size_bytes,
                "actual_size_bytes": len(contents),
            },
        )

    # STEP 3: Magic-bytes check (fast, no false positives on real PDFs)
    if not contents.startswith(b"%PDF"):
        return _error(400, "not_a_pdf", "File does not appear to be a PDF.")

    # STEP 4: Compute file metadata (hash, size, page count)
    file_meta = compute_file_metadata(contents)

    # STEP 5: Duplicate short-circuit  --  optimization, saves GROBID work
    existing = (
        db.query(Paper)
        .filter(Paper.sha256_hash == file_meta["sha256_hash"])
        .first()
    )
    if existing is not None:
        return JSONResponse(status_code=200, content=build_paper_response(existing))

    # STEP 6: Parse via GROBID (SLOW, 5-60 sec)  --  offload to worker thread
    # so the event loop can serve other requests during the wait.
    tei_xml: str | None = None
    grobid_metadata: dict[str, Any] = {}
    status = "parsed"
    error_message: str | None = None

    try:
        tei_xml = await asyncio.to_thread(parse_pdf, contents)
        grobid_metadata = extract_metadata(tei_xml)
    except Exception as exc:
        # Per contract: still create the row with status=parsing_failed
        # so the frontend can display "we tried but couldn't parse this".
        status = "parsing_failed"
        error_message = f"{type(exc).__name__}: {exc}"

    # STEP 7: Build Paper object
    paper = Paper(
        sha256_hash=file_meta["sha256_hash"],
        filename=file.filename or "unknown.pdf",
        file_size_bytes=file_meta["file_size_bytes"],
        page_count=file_meta["page_count"],
        title=grobid_metadata.get("title"),
        authors=grobid_metadata.get("authors", []),
        abstract=grobid_metadata.get("abstract"),
        keywords=grobid_metadata.get("keywords", []),
        doi=grobid_metadata.get("doi"),
        publication_year=grobid_metadata.get("publication_year"),
        venue=grobid_metadata.get("venue"),
        journal_ref=grobid_metadata.get("journal_ref"),
        status=status,
        error_message=error_message,
        raw_tei_xml=tei_xml,
    )

    # Successful parsing gets a parsed_at timestamp.
    if status == "parsed":
        from datetime import datetime, timezone
        paper.parsed_at = datetime.now(timezone.utc)

    # STEP 8: Save. Handle race condition where another request inserted
    # the same hash while we were parsing (30+ sec window is real).
    db.add(paper)
    try:
        db.commit()
        db.refresh(paper)  # populate id, uploaded_at, updated_at from DB defaults
    except IntegrityError:
        db.rollback()
        # Race lost. Fetch the winner and return it -- same result to the user.
        existing = (
            db.query(Paper)
            .filter(Paper.sha256_hash == file_meta["sha256_hash"])
            .first()
        )
        if existing is not None:
            return JSONResponse(status_code=200, content=build_paper_response(existing))
        # Should never happen -- IntegrityError but no row exists.
        return _error(500, "internal_error", "Database integrity error but no matching row found.")

    return build_paper_response(paper)


# ─────────────────────────────────────────────────────────────────────────────
# GET /papers/{paper_id}  --  fetch one paper
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{paper_id}")
def get_paper(paper_id: str, db: Session = Depends(get_db)):
    """Fetch a single paper by UUID."""
    # STEP 1-2: Validate UUID format
    try:
        paper_uuid = uuid.UUID(paper_id)
    except ValueError:
        return _error(
            400, "invalid_uuid",
            "Provided ID is not a valid UUID.",
            {"provided_id": paper_id},
        )

    # STEP 3-4: Query DB
    paper = db.query(Paper).filter(Paper.id == paper_uuid).first()
    if paper is None:
        return _error(
            404, "not_found",
            "Paper does not exist for the given ID.",
            {"paper_id": paper_id},
        )

    # STEP 5-6: Build and return
    return build_paper_response(paper)


# ─────────────────────────────────────────────────────────────────────────────
# GET /papers  --  paginated list
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_papers(
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
):
    """Paginated list of papers, newest first. Optional status filter.

    Response shape:
        {"total": <int>, "limit": <int>, "offset": <int>, "items": [<summary>...]}
    """
    # STEP 1-2: FastAPI handled parsing + validation via Query(...)

    # STEP 3-4: Build base query, apply filter
    query = db.query(Paper)
    if status is not None:
        query = query.filter(Paper.status == status)

    # STEP 5: Count total BEFORE applying offset/limit
    total = query.count()

    # STEP 6-7: Order, offset, limit
    papers = (
        query.order_by(Paper.uploaded_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # STEP 8-9: Build summaries and return
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [build_paper_summary(p) for p in papers],
    }