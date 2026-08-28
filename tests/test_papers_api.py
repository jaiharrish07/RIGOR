"""Tests for the /papers endpoints.

STATUS: the /papers tests below are SKIPPED because the endpoints do not
exist yet -- app/main.py was committed empty and none of POST /papers,
GET /papers/{id} or GET /papers have been written. Drop the `@blocked`
decorator from a test once its endpoint lands; the assertions are written to
docs/api_contract.md and should pass as-is.

Coverage maps to the contract's four Week 1 endpoints:
  GET  /health       -- live, NOT skipped
  POST /papers       -- blocked, and also needs the demo PDF fixture
  GET  /papers/{id}  -- blocked, and also needs the demo PDF fixture
  GET  /papers       -- blocked, but needs no fixture: it seeds rows directly

Every blocked test here was checked by running it un-skipped and confirming it
fails because the route 404s, not because the fixtures or factories are wrong.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.factories import make_paper

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


# --- GET /papers (list) -------------------------------------------------------
# The dashboard list endpoint. week1_lokesh.md omits it entirely, but
# docs/api_contract.md names it as one of the four Week 1 endpoints, and it is
# the only source of `authors_summary` -- a field the contract explicitly says
# the frontend "does not have to compute". Pinning the shape here so the
# endpoint is written against it rather than the other way round.
#
# NOTE ON TIMESTAMPS: `uploaded_at` defaults to `func.now()`, which in Postgres
# is *transaction* start time -- every row inserted inside one test would share
# an identical value and make ordering assertions meaningless. The ordering and
# pagination tests below therefore set `uploaded_at` explicitly.

LIST_ITEM_FIELDS = {
    "id", "filename", "title", "authors_summary", "publication_year",
    "venue", "status", "page_count", "uploaded_at",
}

BASE_TIME = datetime(2026, 8, 26, 10, 30, tzinfo=timezone.utc)


def _seed(db_session, count, **kw):
    """Insert `count` papers, newest last, one minute apart."""
    papers = [
        make_paper(uploaded_at=BASE_TIME + timedelta(minutes=i), **kw)
        for i in range(count)
    ]
    db_session.add_all(papers)
    db_session.flush()
    return papers


@blocked
def test_list_papers_returns_contract_envelope(client, db_session):
    """The list response uses the four-field envelope from the contract."""
    _seed(db_session, 1)

    response = client.get("/papers")
    assert response.status_code == 200

    data = response.json()
    assert set(data) == {"total", "limit", "offset", "items"}
    assert isinstance(data["items"], list)
    assert data["limit"] == 20, "contract default limit"
    assert data["offset"] == 0, "contract default offset"


@blocked
def test_list_papers_item_has_exactly_the_contract_fields(client, db_session):
    """Each item is the compact summary -- not the full paper."""
    _seed(db_session, 1, title="Attention Is All You Need", venue="NeurIPS",
          publication_year=2017, page_count=15)

    item = client.get("/papers").json()["items"][0]
    assert set(item) == LIST_ITEM_FIELDS, (
        "list items must match the contract's PaperSummary exactly -- extra "
        "fields bloat the dashboard payload, missing ones break the cards"
    )


@blocked
def test_list_papers_never_leaks_heavy_fields(client, db_session):
    """raw_tei_xml and abstract must never appear in the list payload."""
    _seed(db_session, 1, raw_tei_xml="<TEI>" + "x" * 10_000 + "</TEI>",
          abstract="The dominant sequence transduction models...")

    response = client.get("/papers")
    # Assert success first: an absence-only test passes against a 404 body too,
    # which would keep it green even if the endpoint were deleted.
    assert response.status_code == 200
    assert response.json()["items"], "need a returned item for this to mean anything"

    body = response.text
    assert "raw_tei_xml" not in body
    assert "<TEI>" not in body
    assert "abstract" not in body


@blocked
def test_list_papers_is_newest_first(client, db_session):
    """Contract: 'a paginated list of all uploaded papers, newest first'."""
    _seed(db_session, 3)

    stamps = [item["uploaded_at"] for item in client.get("/papers").json()["items"]]
    assert stamps == sorted(stamps, reverse=True)


@blocked
def test_list_papers_respects_limit_and_offset(client, db_session):
    """Pagination slices the result and echoes the applied values back."""
    _seed(db_session, 5)

    page = client.get("/papers?limit=2&offset=0").json()
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert len(page["items"]) == 2

    next_page = client.get("/papers?limit=2&offset=2").json()
    assert next_page["offset"] == 2
    assert len(next_page["items"]) == 2

    first_ids = {i["id"] for i in page["items"]}
    second_ids = {i["id"] for i in next_page["items"]}
    assert not (first_ids & second_ids), "pages must not overlap"


@blocked
def test_list_papers_total_ignores_pagination(client, db_session):
    """`total` is the count across all pages, not the size of this one."""
    _seed(db_session, 5)

    data = client.get("/papers?limit=2").json()
    assert len(data["items"]) == 2
    assert data["total"] == 5, "total counts every matching paper, not the page"


@blocked
def test_list_papers_filters_by_status(client, db_session):
    """The optional `status` query parameter narrows the result and the total."""
    _seed(db_session, 3, status="parsed")
    _seed(db_session, 2, status="parsing_failed")

    data = client.get("/papers?status=parsing_failed").json()
    assert data["total"] == 2
    assert {i["status"] for i in data["items"]} == {"parsing_failed"}


@blocked
def test_list_papers_caps_limit_at_100(client, db_session):
    """Contract: 'Number of results to return (max 100)'."""
    _seed(db_session, 3)

    response = client.get("/papers?limit=500")
    # Either reject the over-large limit or clamp it -- but never honour it.
    if response.status_code == 200:
        assert response.json()["limit"] <= 100
    else:
        assert response.status_code == 400
        assert "error" in response.json()


@blocked
def test_list_papers_authors_summary_is_compact(client, db_session):
    """`authors_summary` collapses the author list to 'Surname et al.'.

    Only the multi-author case is asserted: the contract's single example is
    "Vaswani et al." from a multi-author paper, and it does not define the
    one-author or zero-author forms. Those are an open question for the
    contract, not something to guess at here.
    """
    _seed(db_session, 1, authors=[
        {"full_name": "Ashish Vaswani", "affiliation": "Google Brain",
         "email": "avaswani@google.com", "orcid": None},
        {"full_name": "Noam Shazeer", "affiliation": "Google Brain",
         "email": None, "orcid": None},
        {"full_name": "Niki Parmar", "affiliation": "Google Research",
         "email": None, "orcid": None},
    ])

    summary = client.get("/papers").json()["items"][0]["authors_summary"]
    assert summary == "Vaswani et al.", (
        "the contract says the frontend does not have to compute this"
    )


@blocked
def test_list_papers_on_empty_database(client):
    """No papers is a valid, non-error state -- an empty page, not a 404."""
    data = client.get("/papers").json()
    assert data == {"total": 0, "limit": 20, "offset": 0, "items": []}
