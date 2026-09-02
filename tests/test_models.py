"""Tests for the five tables in docs/database_schema.md.

These check the guarantees the schema document actually promises: cascade
behaviour, the SET NULL rule, duplicate detection, and the JSONB columns.
"""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Audit, Finding, Paper, Reference, Section
from tests.factories import (
    make_audit,
    make_finding,
    make_paper,
    make_reference,
    make_section,
)


def _count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_paper_round_trips(db_session):
    """A paper can be inserted and read back."""
    paper = make_paper(title="Attention Is All You Need", doi="10.48550/arXiv.1706.03762")
    db_session.add(paper)
    db_session.flush()

    fetched = db_session.get(Paper, paper.id)
    assert fetched.title == "Attention Is All You Need"
    assert fetched.filename == "demo.pdf"
    assert fetched.id is not None


def test_server_defaults_populate(db_session):
    """NOT NULL columns with no caller-supplied value get their defaults."""
    paper = make_paper()
    db_session.add(paper)
    db_session.flush()
    db_session.refresh(paper)

    # PROVISIONAL (S4/S5): these defaults are our reading, not the doc's.
    assert paper.retraction_status == "unchecked"
    assert paper.authors == []
    assert paper.keywords == []
    assert paper.uploaded_at is not None
    assert paper.updated_at is not None


def test_sha256_hash_is_unique(db_session):
    """Duplicate-upload detection depends on this constraint."""
    shared = "a" * 64
    db_session.add(make_paper(sha256_hash=shared))
    db_session.flush()

    db_session.add(make_paper(sha256_hash=shared, filename="other.pdf"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_authors_jsonb_round_trips_objects(db_session):
    """authors is a list of objects, not a list of strings."""
    authors = [
        {"full_name": "Ashish Vaswani", "affiliation": "Google Brain",
         "email": "avaswani@google.com", "orcid": None},
        {"full_name": "Noam Shazeer", "affiliation": "Google Brain",
         "email": None, "orcid": None},
    ]
    paper = make_paper(authors=authors, keywords=["attention", "transformer"])
    db_session.add(paper)
    db_session.flush()
    db_session.expire(paper)

    fetched = db_session.get(Paper, paper.id)
    assert fetched.authors[0]["full_name"] == "Ashish Vaswani"
    assert fetched.authors[1]["email"] is None
    assert fetched.keywords == ["attention", "transformer"]


def test_deleting_paper_cascades_everything(db_session):
    """Deleting a Paper leaves no orphaned rows in any table."""
    paper = make_paper()
    section = make_section(paper)
    reference = make_reference(paper)
    audit = make_audit(paper)
    db_session.add_all([paper, section, reference, audit])
    db_session.flush()
    finding = make_finding(audit, section=section)
    db_session.add(finding)
    db_session.flush()

    assert (_count(db_session, Section), _count(db_session, Reference),
            _count(db_session, Audit), _count(db_session, Finding)) == (1, 1, 1, 1)

    db_session.delete(paper)
    db_session.flush()
    db_session.expire_all()

    assert _count(db_session, Paper) == 0
    assert _count(db_session, Section) == 0
    assert _count(db_session, Reference) == 0
    assert _count(db_session, Audit) == 0
    assert _count(db_session, Finding) == 0, "findings must cascade via audits"


def test_deleting_audit_cascades_findings_only(db_session):
    """Deleting an Audit removes its Findings but leaves the Paper."""
    paper = make_paper()
    audit = make_audit(paper)
    db_session.add_all([paper, audit])
    db_session.flush()
    db_session.add(make_finding(audit))
    db_session.flush()

    db_session.delete(audit)
    db_session.flush()
    db_session.expire_all()

    assert _count(db_session, Finding) == 0
    assert _count(db_session, Paper) == 1


def test_deleting_section_nulls_finding_section_id(db_session):
    """SET NULL: a finding survives its section being re-parsed away."""
    paper = make_paper()
    section = make_section(paper)
    audit = make_audit(paper)
    db_session.add_all([paper, section, audit])
    db_session.flush()
    finding = make_finding(audit, section=section, evidence_quote="We used Adam.")
    db_session.add(finding)
    db_session.flush()
    assert finding.section_id == section.id

    db_session.delete(section)
    db_session.flush()
    db_session.expire_all()

    survivor = db_session.get(Finding, finding.id)
    assert survivor is not None, "the finding must survive"
    assert survivor.section_id is None, "but its section link must be cleared"
    assert survivor.evidence_quote == "We used Adam."


def test_relationships_navigate_both_ways(db_session):
    """paper.sections / paper.references / paper.audits back-populate."""
    paper = make_paper()
    db_session.add_all([paper, make_section(paper), make_reference(paper), make_audit(paper)])
    db_session.flush()
    db_session.expire_all()

    fetched = db_session.get(Paper, paper.id)
    assert len(fetched.sections) == 1
    assert len(fetched.references) == 1
    assert len(fetched.audits) == 1
    assert fetched.sections[0].paper.id == paper.id


def test_not_null_columns_are_enforced(db_session):
    """A Paper without its required file-identity fields is rejected."""
    db_session.add(Paper(filename="x.pdf", status="parsed"))  # no hash, no size
    with pytest.raises(IntegrityError):
        db_session.flush()
