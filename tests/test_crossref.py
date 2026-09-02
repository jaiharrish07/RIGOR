"""Tests for the Crossref retraction lookup.

Fully mocked with respx: the suite must not depend on Crossref being up.
"""
import httpx
import pytest
import respx

from app.external.crossref import CROSSREF_BASE, check_retraction, normalise_doi

DOI = "10.1234/example"
URL = f"{CROSSREF_BASE}/{DOI}"


def _work(update_type: str, label: str = "Retraction") -> dict:
    return {
        "message": {
            "update-to": [
                {
                    "type": update_type,
                    "label": label,
                    "updated": {"date-time": "2020-06-05T00:00:00Z"},
                }
            ]
        }
    }


@pytest.mark.parametrize(
    "update_type,expected",
    [
        ("retraction", "retracted"),
        ("partial_retraction", "retracted"),
        ("withdrawal", "retracted"),
        ("expression_of_concern", "expression_of_concern"),
        ("correction", "corrected"),
        ("corrigendum", "corrected"),
        ("erratum", "corrected"),
        ("new_edition", "none"),
    ],
)
@respx.mock
def test_update_types_map_to_statuses(update_type, expected):
    respx.get(URL).mock(return_value=httpx.Response(200, json=_work(update_type)))
    assert check_retraction(DOI).status == expected


@respx.mock
def test_no_updates_means_clean():
    respx.get(URL).mock(return_value=httpx.Response(200, json={"message": {}}))
    result = check_retraction(DOI)
    assert result.status == "none"
    assert result.source_url is None


@respx.mock
def test_most_severe_update_wins():
    """A work with both a correction and a retraction is retracted."""
    payload = {
        "message": {
            "update-to": [
                {"type": "correction", "label": "Correction",
                 "updated": {"date-time": "2019-01-01T00:00:00Z"}},
                {"type": "retraction", "label": "Retraction",
                 "updated": {"date-time": "2020-06-05T00:00:00Z"}},
            ]
        }
    }
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    result = check_retraction(DOI)
    assert result.status == "retracted"
    assert result.reason == "Retraction"


@respx.mock
def test_retracted_carries_metadata():
    respx.get(URL).mock(return_value=httpx.Response(200, json=_work("retraction")))
    result = check_retraction(DOI)
    assert result.source_url == f"https://doi.org/{DOI}"
    assert result.reason == "Retraction"
    assert result.updated_date == "2020-06-05T00:00:00Z"


@respx.mock
def test_404_is_unavailable_not_clean():
    """An unknown DOI is 'we do not know', never 'we checked and it is fine'."""
    respx.get(URL).mock(return_value=httpx.Response(404))
    assert check_retraction(DOI).status == "unavailable"


@pytest.mark.parametrize("doi", ["", "   ", None])
def test_blank_doi_is_unavailable(doi):
    assert check_retraction(doi).status == "unavailable"


@respx.mock
def test_retries_then_succeeds():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json=_work("retraction")),
        ]
    )
    assert check_retraction(DOI).status == "retracted"
    assert route.call_count == 2


@respx.mock
def test_all_retries_fail_is_unavailable():
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    assert check_retraction(DOI).status == "unavailable"
    assert route.call_count == 3


@respx.mock
def test_rate_limit_is_retried():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"message": {}}),
        ]
    )
    assert check_retraction(DOI).status == "none"
    assert route.call_count == 2


@respx.mock
def test_server_error_is_retried_then_unavailable():
    route = respx.get(URL).mock(return_value=httpx.Response(500))
    assert check_retraction(DOI).status == "unavailable"
    assert route.call_count == 3


@respx.mock
def test_malformed_json_is_unavailable():
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"not json"))
    assert check_retraction(DOI).status == "unavailable"


@pytest.mark.parametrize(
    "raw",
    [
        "10.1234/example",
        "https://doi.org/10.1234/example",
        "http://dx.doi.org/10.1234/example",
        "doi:10.1234/example",
        "  10.1234/example  ",
    ],
)
@respx.mock
def test_doi_prefixes_are_normalised(raw):
    """The task doc names this failure mode but its draft did not handle it."""
    respx.get(URL).mock(return_value=httpx.Response(200, json={"message": {}}))
    assert check_retraction(raw).status == "none"
    assert normalise_doi(raw) == DOI


@respx.mock
def test_doi_is_url_encoded():
    """DOIs legally contain characters that must not leak into the path."""
    weird = "10.1234/a<b>c"
    route = respx.get(f"{CROSSREF_BASE}/10.1234%2Fa%3Cb%3Ec").mock(
        return_value=httpx.Response(200, json={"message": {}})
    )
    assert check_retraction(weird).status == "none"
    assert route.called
