"""Tests for the /papers endpoints.

STATUS: the /papers tests below are SKIPPED because the endpoints do not
exist yet -- app/main.py was committed empty and POST /papers and
GET /papers/{id} have not been written. Remove the `pytestmark` line and the
DEMO_PAPER guard once that work lands; the assertions are already written to
docs/api_contract.md and should pass as-is.

`test_health` is NOT skipped -- /health exists and runs for real.
"""
from pathlib import Path

import pytest

# The task doc points at demo_papers/, which does not exist and which
# .gitignore would exclude anyway (*.pdf is ignored, and only
# tests/fixtures/**/*.pdf is whitelisted back in).
DEMO_PAPER = Path(__file__).parent / "fixtures" / "demo_01_gold_transformer.pdf"


def test_health(client):
    """Health endpoint reports its dependencies.

    NOTE: week1_lokesh.md asserts `response.json() == {"status": "ok"}`, but
    docs/api_contract.md defines four fields and declares itself the source of
    truth. The contract wins, so this asserts the contract's shape.
    """
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert set(data) == {"status", "database", "grobid", "version"}
    assert data["status"] in {"ok", "degraded"}
    assert data["database"] == "connected", "test database should be reachable"
    assert data["grobid"] in {"connected", "unavailable"}
    assert data["version"]


# --- Everything below is blocked on the /papers endpoints ---------------------
# Applied per-test, not via module-level `pytestmark`, which would also skip
# test_health above.

blocked = pytest.mark.skip(
    reason="Blocked: POST /papers and GET /papers/{id} are not implemented "
           "(app/main.py was committed empty). See week1_lokesh.md Day 4."
)


@blocked
def test_upload_paper_returns_correct_shape(client):
    """Uploading a valid PDF returns the shape in docs/api_contract.md."""
    with open(DEMO_PAPER, "rb") as f:
        response = client.post(
            "/papers", files={"file": ("demo.pdf", f, "application/pdf")}
        )

    assert response.status_code == 201
    data = response.json()

    for field in (
        "id", "filename", "file_size_bytes", "sha256_hash", "page_count",
        "title", "authors", "abstract", "keywords", "doi", "publication_year",
        "venue", "journal_ref", "status", "error_message", "uploaded_at",
        "parsed_at",
    ):
        assert field in data, f"missing contract field: {field}"

    assert isinstance(data["authors"], list)
    assert isinstance(data["keywords"], list)
    assert data["status"] in {
        "uploaded", "parsing", "parsed",
        "parsing_failed", "unsupported_pdf", "corrupted",
    }
    assert "raw_tei_xml" not in data, "raw_tei_xml must never be returned"


@blocked
def test_upload_non_pdf_returns_400(client):
    """Uploading a non-PDF returns 400 with the contract's error envelope."""
    response = client.post(
        "/papers", files={"file": ("notpdf.txt", b"This is not a PDF", "text/plain")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_a_pdf"


@blocked
def test_get_paper_returns_the_saved_paper(client):
    """After uploading, the paper can be retrieved by ID."""
    with open(DEMO_PAPER, "rb") as f:
        upload = client.post(
            "/papers", files={"file": ("demo.pdf", f, "application/pdf")}
        )
    paper_id = upload.json()["id"]

    response = client.get(f"/papers/{paper_id}")
    assert response.status_code == 200
    assert response.json()["id"] == paper_id


@blocked
def test_get_nonexistent_paper_returns_404(client):
    """Fetching an unknown ID returns 404 with the contract's error code."""
    response = client.get("/papers/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
