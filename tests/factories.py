"""Small builders so tests state only the field under test."""
import uuid

from app.db.models import Audit, Finding, Paper, Reference, Section


def make_paper(**kw) -> Paper:
    defaults = dict(
        sha256_hash=uuid.uuid4().hex * 2,  # 64 hex chars, unique per call
        filename="demo.pdf",
        file_size_bytes=1234,
        status="parsed",
    )
    return Paper(**{**defaults, **kw})


def make_section(paper, **kw) -> Section:
    defaults = dict(
        paper=paper, heading="3.2 Training Details", body_text="We used Adam.",
        level=2, order_index=3, word_count=3, char_count=13,
    )
    return Section(**{**defaults, **kw})


def make_reference(paper, **kw) -> Reference:
    defaults = dict(paper=paper, order_index=1, raw_text="Bahdanau et al. 2015.")
    return Reference(**{**defaults, **kw})


def make_audit(paper, **kw) -> Audit:
    defaults = dict(
        paper=paper, checklist_version="1.0",
        llm_provider="groq", llm_model="llama-3.3-70b-versatile",
    )
    return Audit(**{**defaults, **kw})


def make_finding(audit, **kw) -> Finding:
    defaults = dict(
        audit=audit, item_id="hyperparameter.learning_rate",
        category="hyperparameter", present="true",
    )
    return Finding(**{**defaults, **kw})
