"""GROBID-based PDF parser for RIGOR.

Turns raw PDF bytes into the structured metadata Lokesh's `papers` table
and the `POST /papers` API contract require.

Three public functions:

    compute_file_metadata(file_bytes)  -- pure Python: sha256, size, pages.
    parse_pdf(file_bytes)              -- HTTP call to GROBID: bytes -> TEI-XML.
    extract_metadata(tei_xml)          -- lxml parse: TEI-XML -> metadata dict.

Day 4's endpoint composes them roughly like this:

    file_meta = compute_file_metadata(contents)
    tei_xml   = await asyncio.to_thread(parse_pdf, contents)
    grobid    = extract_metadata(tei_xml)
    paper_row = Paper(**file_meta, **grobid, raw_tei_xml=tei_xml, ...)

All three functions are SYNC. GROBID takes 5-60 seconds per paper, so the
endpoint MUST wrap `parse_pdf` in `asyncio.to_thread(...)` to keep the
FastAPI event loop free for other incoming requests.
"""

import hashlib
import io
import logging
from typing import Any

import httpx
from lxml import etree
from pypdf import PdfReader

from app.config import settings

logger = logging.getLogger(__name__)

# GROBID's TEI-XML output declares xmlns="http://www.tei-c.org/ns/1.0".
# lxml requires this map to resolve the `tei:` prefix in every XPath below.
# Without it, .//tei:title would raise; .//title would silently match nothing.
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# GROBID full-text endpoint. Returns TEI with header, abstract, body, and
# references. Lighter endpoints (processHeaderDocument) skip the body but
# we need everything for Week 2's section extraction.
GROBID_ENDPOINT = "/api/processFulltextDocument"

# First GROBID call after container start can take 30-60s (JVM warmup +
# model load). 120s is a safety margin. On timeout, httpx raises.
GROBID_TIMEOUT_SECONDS = 120


# ─────────────────────────────────────────────────────────────────────────────
# 1. FILE METADATA  --  pure Python, no network, no XML
# ─────────────────────────────────────────────────────────────────────────────

def compute_file_metadata(file_bytes: bytes) -> dict[str, Any]:
    """Compute file-level metadata from raw PDF bytes.

    Returns the three fields `papers` requires at insert-time,
    before GROBID is called:

        sha256_hash       str        64 hex chars, never null
        file_size_bytes   int        byte count, never null
        page_count        int|None   null if pypdf could not read the PDF

    This function NEVER validates input. The endpoint decides whether to
    accept the file (magic bytes, size). This function measures whatever
    bytes it is handed.
    """
    # hashlib on any bytes always succeeds. Empty bytes hash to the well-
    # known e3b0c442... digest -- same value everywhere, useful for
    # detecting duplicate uploads regardless of filename.
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    # len(bytes) is O(1) -- bytes stores its length internally.
    file_size_bytes = len(file_bytes)

    # pypdf needs a file-like object, not raw bytes. BytesIO wraps bytes
    # to look like a file. Fails on malformed / encrypted / truncated PDFs;
    # we swallow, log with hash prefix for debuggability, and let
    # page_count fall through as None (schema allows null).
    page_count: int | None
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001 -- pypdf raises varied types
        logger.warning(
            "pypdf failed to count pages (sha256=%s...): %s",
            sha256_hash[:12], exc,
        )
        page_count = None

    return {
        "sha256_hash": sha256_hash,
        "file_size_bytes": file_size_bytes,
        "page_count": page_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. GROBID CALL  --  synchronous HTTP; endpoint offloads with to_thread
# ─────────────────────────────────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes) -> str:
    """POST the PDF to GROBID, return the TEI-XML response body as a string.

    Synchronous by design. Endpoint wraps it:

        tei_xml = await asyncio.to_thread(parse_pdf, contents)

    Raises:
        httpx.TimeoutException  -- GROBID did not respond in 120s
        httpx.HTTPStatusError   -- GROBID returned non-2xx
    """
    url = f"{settings.grobid_url}{GROBID_ENDPOINT}"

    # files={"input": (filename, bytes, content_type)} triggers a
    # multipart/form-data request. GROBID ignores the filename; the tuple
    # exists to satisfy the multipart spec. The field name MUST be "input".
    response = httpx.post(
        url,
        files={"input": ("paper.pdf", file_bytes, "application/pdf")},
        timeout=GROBID_TIMEOUT_SECONDS,
    )
    # 4xx = we sent bad input; 5xx = GROBID crashed. Either way, do not
    # try to parse the error body as TEI-XML -- the endpoint will catch
    # the exception and set status="parsing_failed".
    response.raise_for_status()

    # response.text is str (httpx decoded using the response's charset).
    # extract_metadata will re-encode to UTF-8 bytes for lxml.
    return response.text


# ─────────────────────────────────────────────────────────────────────────────
# 3. TEI-XML METADATA EXTRACTION  --  where the parser earns its keep
# ─────────────────────────────────────────────────────────────────────────────

def extract_metadata(tei_xml: str) -> dict[str, Any]:
    """Parse GROBID TEI-XML into the metadata dict the API contract needs.

    Returns exactly these keys (matches papers schema + POST /papers response):

        title              str | None
        authors            list[dict]      -- see _extract_authors
        abstract           str | None
        keywords           list[str]
        doi                str | None
        publication_year   int | None
        venue              str | None
        journal_ref        str | None

    Never raises for missing fields -- a mostly-empty TEI returns a valid
    dict with mostly Nones and empty lists. Only raises if the XML itself
    is malformed (lxml XMLSyntaxError).
    """
    # etree.fromstring requires BYTES when the XML has an <?xml encoding=...?>
    # declaration -- lxml refuses str input in that case because the two
    # sources of encoding info would conflict. We re-encode to UTF-8.
    root = etree.fromstring(tei_xml.encode("utf-8"))

    return {
        "title": _extract_title(root),
        "authors": _extract_authors(root),
        "abstract": _extract_abstract(root),
        "keywords": _extract_keywords(root),
        "doi": _extract_doi(root),
        "publication_year": _extract_publication_year(root),
        "venue": _extract_venue(root),
        "journal_ref": _extract_journal_ref(root),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Private extraction helpers  --  one per field
# Every helper: try XPath, guard for None, return value or empty marker.
# ─────────────────────────────────────────────────────────────────────────────

def _text_or_none(element) -> str | None:
    """Stripped text of an lxml element, or None if missing/empty."""
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped if stripped else None


def _extract_title(root) -> str | None:
    # teiHeader/fileDesc/titleStmt/title. The main paper title lives here.
    # Body sections also have <title>, so scoping to teiHeader//titleStmt
    # avoids grabbing a section heading by accident.
    el = root.find(".//tei:teiHeader//tei:titleStmt/tei:title", TEI_NS)
    return _text_or_none(el)


def _extract_abstract(root) -> str | None:
    # profileDesc/abstract. Abstract contains nested <p> tags; we want
    # every scrap of inner text, joined. itertext() walks the subtree.
    el = root.find(".//tei:profileDesc/tei:abstract", TEI_NS)
    if el is None:
        return None
    parts = [t.strip() for t in el.itertext() if t and t.strip()]
    joined = " ".join(parts)
    return joined if joined else None


def _extract_doi(root) -> str | None:
    # DOIs appear as <idno type="DOI">10.xxxx/yyyy</idno>. Multiple idno
    # tags may coexist (arXiv id, ISBN, DOI) -- filter by @type='DOI'.
    el = root.find(".//tei:idno[@type='DOI']", TEI_NS)
    return _text_or_none(el)


def _extract_publication_year(root) -> int | None:
    # GROBID stores dates as <date when="2017-06-12"/>. @when may be full
    # date, year-month, or just year. Take the first 4 chars if digits.
    # Try publicationStmt first (paper-level), then monogr (venue-level).
    for xpath in (
        ".//tei:teiHeader//tei:publicationStmt/tei:date",
        ".//tei:teiHeader//tei:monogr/tei:imprint/tei:date",
    ):
        el = root.find(xpath, TEI_NS)
        if el is not None:
            when = el.get("when", "")
            if len(when) >= 4 and when[:4].isdigit():
                return int(when[:4])
    return None


def _extract_venue(root) -> str | None:
    # Venue = journal or conference. Under monogr:
    #   <title level="j">Nature</title>       -- journal
    #   <title level="m">NeurIPS 2017</title>  -- conference / book
    # Prefer journal, fall back to monograph.
    for level in ("j", "m"):
        el = root.find(
            f".//tei:teiHeader//tei:monogr/tei:title[@level='{level}']",
            TEI_NS,
        )
        text = _text_or_none(el)
        if text:
            return text
    return None


def _extract_journal_ref(root) -> str | None:
    # GROBID does NOT emit a single "full citation" string. We assemble
    # one: "<venue>, vol. X, no. Y, pp. Z-Z". If no venue, return None
    # rather than a meaningless fragment.
    venue = _extract_venue(root)
    if not venue:
        return None
    parts = [venue]

    imprint = root.find(".//tei:teiHeader//tei:monogr/tei:imprint", TEI_NS)
    if imprint is not None:
        # Volume, issue as <biblScope unit="volume">42</biblScope>.
        for unit, prefix in (("volume", "vol. "), ("issue", "no. ")):
            el = imprint.find(f"tei:biblScope[@unit='{unit}']", TEI_NS)
            text = _text_or_none(el)
            if text:
                parts.append(f"{prefix}{text}")

        # Pages: <biblScope unit="page" from="5998" to="6008"/>.
        pages = imprint.find("tei:biblScope[@unit='page']", TEI_NS)
        if pages is not None:
            page_from, page_to = pages.get("from"), pages.get("to")
            if page_from and page_to:
                parts.append(f"pp. {page_from}-{page_to}")
            elif page_from:
                parts.append(f"p. {page_from}")

    return ", ".join(parts)


def _extract_keywords(root) -> list[str]:
    # Under profileDesc/textClass/keywords. GROBID may emit <term> children
    # (structured) OR one big text block (unstructured). Handle both.
    kw_root = root.find(
        ".//tei:profileDesc/tei:textClass/tei:keywords", TEI_NS,
    )
    if kw_root is None:
        return []

    terms = kw_root.findall(".//tei:term", TEI_NS)
    if terms:
        return [t.text.strip() for t in terms if t.text and t.text.strip()]

    # Fallback: one flat text block, split on common separators.
    flat = "".join(kw_root.itertext()).strip()
    if not flat:
        return []
    for sep in (";", ","):
        if sep in flat:
            return [k.strip() for k in flat.split(sep) if k.strip()]
    return [flat]


def _extract_authors(root) -> list[dict[str, str | None]]:
    """Extract the paper's own authors as a list of dicts.

    Contract shape (each author):
        {"full_name": str, "affiliation": str|None,
         "email": str|None, "orcid": str|None}

    CRITICAL scoping: only authors under sourceDesc/biblStruct/analytic
    are the PAPER's authors. Authors inside <listBibl> are cited-work
    authors and must NOT appear here -- they belong on Reference rows.
    """
    authors_out: list[dict[str, str | None]] = []

    author_els = root.findall(
        ".//tei:sourceDesc//tei:analytic/tei:author", TEI_NS,
    )

    for author_el in author_els:
        # NAME: forename(s) + surname under persName. A person can have
        # multiple forenames (first + middle); we keep them all in order.
        forenames = author_el.findall(".//tei:persName/tei:forename", TEI_NS)
        surname_el = author_el.find(".//tei:persName/tei:surname", TEI_NS)

        name_parts: list[str] = []
        for f in forenames:
            if f.text and f.text.strip():
                name_parts.append(f.text.strip())
        if surname_el is not None and surname_el.text and surname_el.text.strip():
            name_parts.append(surname_el.text.strip())

        full_name = " ".join(name_parts) if name_parts else None
        if not full_name:
            # A nameless author row is useless -- skip it.
            continue

        # EMAIL: direct child <email>. Usually only the corresponding
        # author has one; the rest are None.
        email = _text_or_none(author_el.find("tei:email", TEI_NS))

        # ORCID: <idno type="ORCID">nnnn-nnnn-nnnn-nnnn</idno>.
        orcid = _text_or_none(
            author_el.find(".//tei:idno[@type='ORCID']", TEI_NS),
        )

        # AFFILIATION: v1 stores only the FIRST affiliation (multi-
        # affiliated authors are rare and complicate the schema). Prefer
        # <orgName type="institution">; fall back to any orgName; fall
        # back to raw text inside <affiliation>.
        affiliation: str | None = None
        affiliation_el = author_el.find("tei:affiliation", TEI_NS)
        if affiliation_el is not None:
            org_el = affiliation_el.find(
                "tei:orgName[@type='institution']", TEI_NS,
            )
            if org_el is None:
                org_el = affiliation_el.find("tei:orgName", TEI_NS)
            if org_el is not None and org_el.text and org_el.text.strip():
                affiliation = org_el.text.strip()
            else:
                text = "".join(affiliation_el.itertext()).strip()
                affiliation = text if text else None

        authors_out.append({
            "full_name": full_name,
            "affiliation": affiliation,
            "email": email,
            "orcid": orcid,
        })

    return authors_out