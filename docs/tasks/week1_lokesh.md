# Week 1 — Lokesh's Tasks (Database, Models & Retraction Lookup)

**Your job this week:** Build the database — the tables where all data lives. Also build the module that checks if a paper has been retracted. Also write basic tests so we catch bugs early.

**By Friday night:** The database has tables for papers, sections, audits, and findings. There's a Python function that takes a DOI and returns "retracted" or "not retracted". Tests exist that check Jai's API endpoints work correctly.

**Total time:** About 6-8 hours across the week.

---

## Before you start — Setup checklist (do this Sunday or Monday morning)

- [ ] Python 3.11 installed. Check with `python --version`.
- [ ] Docker Desktop installed and running.
- [ ] `psql` (PostgreSQL client) installed. On Mac: `brew install postgresql`. On Ubuntu: `sudo apt install postgresql-client`.
- [ ] Cloned the RIGOR repo: `git clone <repo-url>`
- [ ] Signed up for Groq (not needed for your Week 1 work, but needed later)

---

## Day 1 (Monday) — Joint team call

**What happens:** 90-minute video call with Jai and Mohandoss.

**Your job in the call:**
1. **Present the database schema.** You'll show what tables and fields exist. Use the schema below as your starting point:

```python
# Paper — one row per uploaded PDF
class Paper:
    id: UUID (primary key)
    filename: str
    title: str | None
    authors: list[str]  # stored as JSON
    abstract: str | None
    doi: str | None
    status: str  # 'parsed' | 'parsing_failed' | 'unsupported_pdf'
    raw_tei_xml: str | None  # so downstream code doesn't re-parse
    uploaded_at: datetime

# Section — one row per section of a parsed paper (populated in Week 2)
class Section:
    id: UUID
    paper_id: UUID (foreign key to Paper)
    heading: str
    level: int  # 1 = main section, 2 = subsection, 3 = sub-subsection
    body_text: str
    page_start: int
    page_end: int
    order_index: int  # position in the paper

# Audit — one row per audit run
class Audit:
    id: UUID
    paper_id: UUID (foreign key to Paper)
    status: str  # 'pending' | 'running' | 'completed' | 'failed'
    progress: float  # 0.0 to 1.0
    created_at: datetime
    completed_at: datetime | None

# Finding — one row per finding produced by the audit
class Finding:
    id: UUID
    audit_id: UUID (foreign key to Audit)
    item_id: str  # e.g., 'hyperparameter.learning_rate'
    present: str  # 'true' | 'false' | 'cannot_determine'
    evidence_quote: str | None
    location: str | None  # e.g., "page 4, section 3.2"
    confidence: float | None
    verified: bool  # did the grounding verifier confirm the quote?
```

Ask Jai: "Does your `POST /papers` endpoint need any other fields on `Paper`?"
Ask Mohandoss: "Does anything in your LLM checklist need a field I'm missing on `Finding`?"

Adjust based on their answers.

2. Confirm your files will live in:
   - `backend/app/db/models.py`
   - `backend/app/db/session.py`
   - `backend/alembic/` (migration files)
   - `backend/app/external/crossref.py`
   - `backend/tests/test_papers_api.py`

**End of Monday:** No coding yet. Schema agreed on.

---

## Day 2 (Tuesday) — Build the database models

**Time:** 3 hours.

**Wait for:** Jai's FastAPI skeleton PR to be merged (so folder structure exists and `app/config.py` has database URL).

### Task 1: Set up your Python environment (15 min)

```bash
cd backend
source .venv/bin/activate    # Windows: .venv\Scripts\activate
```

(The virtual env should already exist from Jai's Tuesday work. If not, run `python -m venv .venv` first.)

### Task 2: Create the models file (1 hour)

Create `backend/app/db/__init__.py` (empty file).

Create `backend/app/db/models.py`:

```python
"""SQLAlchemy models — the database tables."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    filename: Mapped[str] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    authors: Mapped[list] = mapped_column(JSONB, default=list)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50))
    raw_tei_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    sections: Mapped[list["Section"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    audits: Mapped[list["Audit"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("papers.id"))
    heading: Mapped[str] = mapped_column(String(500))
    level: Mapped[int] = mapped_column(Integer)
    body_text: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer)

    paper: Mapped["Paper"] = relationship(back_populates="sections")


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("papers.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    paper: Mapped["Paper"] = relationship(back_populates="audits")
    findings: Mapped[list["Finding"]] = relationship(back_populates="audit", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    audit_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("audits.id"))
    item_id: Mapped[str] = mapped_column(String(200))  # e.g. 'hyperparameter.learning_rate'
    present: Mapped[str] = mapped_column(String(50))  # 'true' | 'false' | 'cannot_determine'
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    audit: Mapped["Audit"] = relationship(back_populates="findings")
```

### Task 3: Create the session helper (30 min)

Create `backend/app/db/session.py`:

```python
"""Database session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency to get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### Task 4: Set up Alembic migrations (1 hour 15 min)

Alembic is the tool that creates and updates database tables based on your models.

From the `backend/` folder:

```bash
alembic init alembic
```

This creates a folder `backend/alembic/` and a file `backend/alembic.ini`.

Edit `backend/alembic.ini`:
- Find the line `sqlalchemy.url = driver://user:pass@localhost/dbname`
- Change it to: `sqlalchemy.url = postgresql://rigor:rigor_dev_password@localhost:5432/rigor`

Edit `backend/alembic/env.py`:
- Near the top, add:
  ```python
  from app.db.models import Base
  ```
- Find the line `target_metadata = None`
- Change it to: `target_metadata = Base.metadata`

Generate the first migration:

```bash
alembic revision --autogenerate -m "Create initial tables"
```

This creates a file in `backend/alembic/versions/` with your table definitions.

Apply the migration to actually create the tables in Postgres:

```bash
alembic upgrade head
```

**Verify the tables exist:**

```bash
psql -h localhost -U rigor -d rigor -c "\dt"
# Password: rigor_dev_password
```

You should see:
```
              List of relations
 Schema |      Name       | Type  | Owner
--------+-----------------+-------+-------
 public | alembic_version | table | rigor
 public | audits          | table | rigor
 public | findings        | table | rigor
 public | papers          | table | rigor
 public | sections        | table | rigor
```

If you see those 5 tables, you're done.

**Commit:**

```bash
git checkout -b feat/database-models
git add backend/app/db/ backend/alembic/ backend/alembic.ini
git commit -m "Add SQLAlchemy models and Alembic migrations"
git push -u origin feat/database-models
```

Open PR. Ask Jai to review — he needs this before he can build his endpoints on Wednesday.

**End-of-Tuesday check-in:**
```
Yesterday: Team call, agreed on schema
Today: Database models, session helper, Alembic migration all done. Tables exist in Postgres. PR opened.
Blocked on: nothing
```

---

## Day 3 (Wednesday) — Build the retraction lookup

**Time:** 2 hours.

### Task: Create the Crossref client

Create `backend/app/external/__init__.py` (empty).

Create `backend/app/external/crossref.py`:

```python
"""Retraction lookup via Crossref REST API.

Since 2023, Crossref hosts the Retraction Watch dataset. We query
the Crossref work record and check the update-to and relation fields
to determine retraction status.
"""
from typing import Literal
from dataclasses import dataclass
import httpx
import time

CROSSREF_BASE = "https://api.crossref.org/works"

Status = Literal["none", "corrected", "retracted", "expression_of_concern", "unavailable"]


@dataclass
class RetractionStatus:
    status: Status
    source_url: str | None = None
    reason: str | None = None
    updated_date: str | None = None


def check_retraction(doi: str) -> RetractionStatus:
    """Check retraction status for a DOI. Handles retries."""
    if not doi or not doi.strip():
        return RetractionStatus(status="unavailable")

    doi = doi.strip()
    url = f"{CROSSREF_BASE}/{doi}"

    # Try up to 3 times with exponential backoff
    for attempt in range(3):
        try:
            response = httpx.get(url, timeout=15, headers={
                "User-Agent": "RIGOR/1.0 (research reproducibility auditing tool)",
            })
            if response.status_code == 404:
                return RetractionStatus(status="unavailable")
            response.raise_for_status()
            break
        except httpx.HTTPError as e:
            if attempt == 2:
                return RetractionStatus(status="unavailable")
            time.sleep(2 ** attempt)  # 1s, 2s, then give up

    data = response.json()
    message = data.get("message", {})

    # Check the 'update-to' field — if this work was updated by another,
    # inspect the relationship type
    updates = message.get("update-to", [])
    for update in updates:
        update_type = update.get("type", "").lower()
        if "retraction" in update_type:
            return RetractionStatus(
                status="retracted",
                source_url=f"https://doi.org/{doi}",
                reason=update.get("label"),
                updated_date=update.get("updated", {}).get("date-time"),
            )
        elif "correction" in update_type:
            return RetractionStatus(
                status="corrected",
                source_url=f"https://doi.org/{doi}",
                updated_date=update.get("updated", {}).get("date-time"),
            )
        elif "expression_of_concern" in update_type or "expression of concern" in update_type:
            return RetractionStatus(
                status="expression_of_concern",
                source_url=f"https://doi.org/{doi}",
                updated_date=update.get("updated", {}).get("date-time"),
            )

    return RetractionStatus(status="none")
```

**Test it works:**

Create `backend/scripts/test_retraction.py`:

```python
from app.external.crossref import check_retraction

# A known-retracted paper (from Retraction Watch)
doi_retracted = "10.1038/s41586-019-1666-5"  # Example — verify with a real one

# A known-clean paper (Attention Is All You Need)
doi_clean = "10.48550/arXiv.1706.03762"

for label, doi in [("retracted example", doi_retracted), ("clean example", doi_clean)]:
    status = check_retraction(doi)
    print(f"{label}: {status}")
```

Run it:

```bash
cd backend
python -m scripts.test_retraction
```

**Note:** The retracted example DOI above is a placeholder — find a real retracted ML paper DOI from [retractionwatch.com](https://retractionwatch.com) before your final test.

**Commit:**

```bash
git checkout -b feat/crossref-retraction
git add backend/app/external/ backend/scripts/test_retraction.py
git commit -m "Add Crossref retraction lookup module"
git push -u origin feat/crossref-retraction
```

Open PR. Ask Jai to review.

---

## Day 4 (Thursday) — Write tests

**Time:** 2-3 hours.

**Wait for:** Jai's `POST /papers` and `GET /papers/{id}` endpoints PR to be merged.

### Task: Write pytest tests for the endpoints

Create `backend/tests/__init__.py` (empty).
Create `backend/tests/conftest.py`:

```python
"""Shared test fixtures."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.models import Base
from app.db.session import get_db

# Use a separate test database
TEST_DATABASE_URL = "postgresql://rigor:rigor_dev_password@localhost:5432/rigor_test"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_engine):
    """Fresh session per test, rolled back at the end."""
    SessionLocal = sessionmaker(bind=test_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client with the test DB session."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
```

Create the test database first (one-time setup):

```bash
psql -h localhost -U rigor -d postgres -c "CREATE DATABASE rigor_test;"
# Password: rigor_dev_password
```

Create `backend/tests/test_papers_api.py`:

```python
"""Tests for the /papers endpoints."""
from pathlib import Path

DEMO_PAPER = Path(__file__).parent.parent.parent / "demo_papers" / "demo_01_gold_transformer.pdf"


def test_health(client):
    """Health endpoint returns ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_paper_returns_correct_shape(client):
    """Uploading a valid PDF returns the expected response shape."""
    with open(DEMO_PAPER, "rb") as f:
        response = client.post(
            "/papers",
            files={"file": ("demo.pdf", f, "application/pdf")},
        )

    assert response.status_code == 201
    data = response.json()

    # Check all expected fields exist
    assert "id" in data
    assert "title" in data
    assert "authors" in data
    assert "abstract" in data
    assert "doi" in data
    assert "status" in data
    assert "uploaded_at" in data

    # Basic sanity
    assert isinstance(data["authors"], list)
    assert data["status"] in ["parsed", "parsing_failed", "unsupported_pdf"]


def test_upload_non_pdf_returns_400(client):
    """Uploading a non-PDF file returns 400."""
    response = client.post(
        "/papers",
        files={"file": ("notpdf.txt", b"This is not a PDF", "text/plain")},
    )
    assert response.status_code == 400


def test_get_paper_returns_the_saved_paper(client):
    """After uploading, we can retrieve the paper by ID."""
    with open(DEMO_PAPER, "rb") as f:
        upload_response = client.post(
            "/papers",
            files={"file": ("demo.pdf", f, "application/pdf")},
        )
    paper_id = upload_response.json()["id"]

    get_response = client.get(f"/papers/{paper_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == paper_id


def test_get_nonexistent_paper_returns_404(client):
    """Fetching a nonexistent ID returns 404."""
    response = client.get("/papers/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
```

Install pytest:

```bash
pip install pytest
```

Run the tests:

```bash
cd backend
pytest tests/ -v
```

You should see all tests pass. If some fail, that's actually valuable information — it means something's not right between Jai's endpoint code and your models. Fix together in the group chat.

**Commit:**

```bash
git checkout -b feat/api-tests
git add backend/tests/
git commit -m "Add pytest tests for /papers endpoints"
git push -u origin feat/api-tests
```

Open PR. Ask Jai to review.

---

## Day 5 (Friday) — Integration Day

**Morning: 30-min group video call at 10 AM.**

**Your job during integration:**
1. Run the full test suite: `pytest tests/ -v` — do all tests pass on the merged main branch?
2. Test the retraction lookup on Jai's uploaded papers:

```bash
# After Jai uploads a paper via curl, run:
python -c "
from app.db.session import SessionLocal
from app.db.models import Paper
from app.external.crossref import check_retraction

with SessionLocal() as db:
    papers = db.query(Paper).all()
    for p in papers:
        if p.doi:
            status = check_retraction(p.doi)
            print(f'{p.title[:50]}... → {status.status}')
        else:
            print(f'{p.title[:50]}... → no DOI')
"
```

3. Help debug any Friday integration bugs.

**End-of-Friday check-in:**
```
Yesterday: Tests written, retraction lookup ready
Today: All tests pass on main, retraction lookup verified on demo papers
Blocked on: nothing
```

---

## Sunday — Weekly meeting

**8 PM IST, 45 min video call.**

**Your job:**
1. Screen-share and walk through your code (5 min):
   - `models.py` — the four tables and why each field exists
   - `crossref.py` — how retraction lookup works
   - `test_papers_api.py` — run the tests live so everyone sees them pass
2. Say what you're committing to for Week 2 (helping extend the parser for section extraction, or first drafts of frontend based on what the group decides)
3. Raise any blockers

---

## What to do if you get stuck

1. **First 30 minutes:** re-read error, check Postgres is running
2. **Next 30 minutes:** Google the error
3. **After 1 hour:** post in group chat
4. **After 2 hours:** ask AI to explain the problem, not solve it

---

## Common problems and fixes

**Alembic says "target database is not up to date".** Run `alembic upgrade head`.

**Alembic autogenerate creates an empty migration.** Your `env.py` doesn't have `target_metadata = Base.metadata`, or `from app.db.models import Base` is missing. Check `env.py`.

**"UUID type not supported".** Make sure you're using `PgUUID` from `sqlalchemy.dialects.postgresql`, not the plain SQLAlchemy `Uuid`.

**Tests fail with "role rigor does not exist".** The test database wasn't created. Run:
```bash
psql -h localhost -U rigor -d postgres -c "CREATE DATABASE rigor_test;"
```

**Crossref returns 404 for a DOI you're sure exists.** DOIs are case-sensitive and must be the full DOI (like `10.1038/nature25988`), not the URL. Strip `https://doi.org/` if present.

**Rate limited by Crossref.** You're calling too fast. Add a `time.sleep(0.1)` between calls if bulk-testing.

---

That's it. Message the group chat when you're ready to start.
