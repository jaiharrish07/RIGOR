"""SQLAlchemy models — the five tables described in docs/database_schema.md.

Implements the schema document as written: 78 columns across papers, sections,
references, audits and findings, with the cascade rules and indexes it lists.

PROVISIONAL DECISIONS — three points are not settled by the schema document.
Each is implemented with the reading noted below so the schema is runnable, and
each needs confirmation before this migration is considered final:

  S4  `papers.retraction_status` is NOT NULL but is only written at the Week-4
      retraction check, and no DEFAULT is stated. Implemented as
      server_default='unchecked' — the only enum value meaning "not yet checked".

  S5  `references.verified_via_crossref` / `is_retracted` are NOT NULL but are
      likewise Week-4-populated with no stated DEFAULT. Implemented as
      server_default=false. NOTE the schema uses `verified_via_crossref = False`
      to mean both "not yet checked" and "checked, not found" — those are
      different facts and a third state may be needed.

  S7  The table is named `references`, a RESERVED KEYWORD in PostgreSQL.
      SQLAlchemy quotes identifiers automatically so this works, but any
      hand-written SQL must spell it "references" with double quotes.
"""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)


class Paper(Base):
    """One row per uploaded PDF. The anchor row every other table connects to."""

    __tablename__ = "papers"

    id: Mapped[UUID] = _pk()

    # --- File identity ---
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Bibliographic metadata (populated after GROBID) ---
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    journal_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # --- Parsing state ---
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_tei_xml: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Retraction (Week 4) ---
    # PROVISIONAL (S4): NOT NULL with no default stated in the schema doc.
    retraction_status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'unchecked'")
    )
    retraction_source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retraction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retraction_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Timestamps ---
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships (passive_deletes lets the DB-level CASCADE do the work) ---
    sections: Mapped[list["Section"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", passive_deletes=True
    )
    references: Mapped[list["Reference"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", passive_deletes=True
    )
    audits: Mapped[list["Audit"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Paper {self.id} {self.filename!r} status={self.status!r}>"


class Section(Base):
    """One row per section of a parsed paper. The raw material the LLM reads."""

    __tablename__ = "sections"

    id: Mapped[UUID] = _pk()
    paper_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    heading: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    section_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_appendix: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    paper: Mapped["Paper"] = relationship(back_populates="sections")

    def __repr__(self) -> str:
        return f"<Section {self.id} {self.heading!r} type={self.section_type!r}>"


class Reference(Base):
    """One row per bibliography entry. NOT the same as a Paper row.

    PROVISIONAL (S7): `references` is a reserved keyword in PostgreSQL.
    SQLAlchemy quotes it automatically; raw SQL must use "references".
    """

    __tablename__ = "references"

    id: Mapped[UUID] = _pk()
    paper_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # PROVISIONAL (S5): NOT NULL with no default stated in the schema doc.
    verified_via_crossref: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_retracted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    crossref_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    paper: Mapped["Paper"] = relationship(back_populates="references")

    def __repr__(self) -> str:
        return f"<Reference {self.id} [{self.order_index}] doi={self.doi!r}>"


class Audit(Base):
    """One row per audit run. The coordinator that ties Findings together."""

    __tablename__ = "audits"

    id: Mapped[UUID] = _pk()
    paper_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default=text("'pending'"), index=True
    )
    progress: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0.0")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    checklist_version: Mapped[str] = mapped_column(String(20), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    paper: Mapped["Paper"] = relationship(back_populates="audits")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Audit {self.id} status={self.status!r} progress={self.progress}>"


class Finding(Base):
    """One row per checklist item verdict. The output of the whole system."""

    __tablename__ = "findings"

    id: Mapped[UUID] = _pk()
    audit_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )

    item_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    present: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Evidence & location ---
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SET NULL so findings survive section re-parsing.
    section_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    location_hint: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Grounding verification ---
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )
    verification_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fuzzy_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    audit: Mapped["Audit"] = relationship(back_populates="findings")
    section: Mapped["Section | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Finding {self.id} {self.item_id!r} present={self.present!r} verified={self.verified}>"
