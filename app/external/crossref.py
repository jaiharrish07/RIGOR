"""Retraction lookup via the Crossref REST API.

Since 2023 Crossref hosts the Retraction Watch dataset. We fetch the work
record and inspect its `update-to` relationships to determine whether the
work has been retracted, corrected, or had an expression of concern issued.

Returned statuses line up with `papers.retraction_status` in
docs/database_schema.md. `unchecked` is that column's default and is never
returned here — this function always performs a check.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

CROSSREF_BASE = "https://api.crossref.org/works"
USER_AGENT = "RIGOR/1.0 (research reproducibility auditing tool)"

MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 15.0

Status = Literal["none", "corrected", "retracted", "expression_of_concern", "unavailable"]

# A work can carry several updates at once (e.g. a correction and then a
# retraction). Rank them so the most serious wins, rather than whichever
# happens to appear first in the list.
_SEVERITY: dict[Status, int] = {
    "none": 0,
    "corrected": 1,
    "expression_of_concern": 2,
    "retracted": 3,
}

_RETRACTION_TYPES = {"retraction", "partial_retraction", "withdrawal", "removal"}
_CONCERN_TYPES = {"expression_of_concern", "expression of concern"}
_CORRECTION_TYPES = {"correction", "corrigendum", "erratum"}


@dataclass
class RetractionStatus:
    status: Status
    source_url: str | None = None
    reason: str | None = None
    updated_date: str | None = None


def normalise_doi(doi: str) -> str:
    """Strip the prefixes users and parsers commonly leave attached.

    Crossref wants a bare DOI (`10.1038/nature25988`), not a URL. GROBID and
    copy-paste both routinely produce the URL form, which 404s otherwise.
    """
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    return doi.strip().rstrip("/")


def _classify(update_type: str) -> Status | None:
    t = update_type.strip().lower().replace("-", "_")
    if t in _RETRACTION_TYPES or "retract" in t:
        return "retracted"
    if t in _CONCERN_TYPES or "concern" in t:
        return "expression_of_concern"
    if t in _CORRECTION_TYPES or "correct" in t:
        return "corrected"
    return None


def _fetch(url: str) -> httpx.Response | None:
    """GET with retries. Returns None if the work is absent or unreachable."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = httpx.get(url, timeout=TIMEOUT_SECONDS, headers=headers)
            if response.status_code == 404:
                return None
            if response.status_code == 429:
                # Rate limited: honour Retry-After when Crossref supplies it.
                if attempt == MAX_ATTEMPTS - 1:
                    return None
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt == MAX_ATTEMPTS - 1:
                return None
            time.sleep(2**attempt)
    return None


def check_retraction(doi: str) -> RetractionStatus:
    """Check retraction status for a DOI.

    Returns `unavailable` when the DOI is blank, unknown to Crossref, or the
    API could not be reached — those are all "we do not know", as distinct
    from `none`, which means "we checked and it is clean".
    """
    if not doi or not doi.strip():
        return RetractionStatus(status="unavailable")

    doi = normalise_doi(doi)
    if not doi:
        return RetractionStatus(status="unavailable")

    response = _fetch(f"{CROSSREF_BASE}/{quote(doi, safe='')}")
    if response is None:
        return RetractionStatus(status="unavailable")

    try:
        message = response.json().get("message", {})
    except ValueError:
        return RetractionStatus(status="unavailable")

    best = RetractionStatus(status="none")
    for update in message.get("update-to", []) or []:
        classified = _classify(str(update.get("type", "")))
        if classified is None:
            continue
        if _SEVERITY[classified] <= _SEVERITY[best.status]:
            continue
        best = RetractionStatus(
            status=classified,
            source_url=f"https://doi.org/{doi}",
            reason=update.get("label"),
            updated_date=(update.get("updated") or {}).get("date-time"),
        )

    return best
