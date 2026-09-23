"""Strict arXiv OAI-PMH listing parser and closed request paths."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from research_agent.ingest.arxiv import (
    ArxivFormatError,
    bucket_pdf_path,
    document_path,
    listing_path,
    listing_window,
    parse_listing_page,
    target_sets,
)
from research_agent.learning.corpus import mature_months

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sources" / "arxiv-oai-sample.xml"
_ENVELOPE = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">{body}</OAI-PMH>'
)


def _page(body: bytes) -> bytes:
    return _ENVELOPE.replace(b"{body}", body)


def _record(
    *,
    versions: bytes,
    title: bytes = b"<title>T</title>",
    authors: bytes = b"<authors>A. Author</authors>",
) -> bytes:
    return (
        b"<ListRecords><record><header><identifier>oai:arXiv.org:2305.01937"
        b"</identifier><datestamp>2025-05-01</datestamp></header><metadata>"
        b'<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>2305.01937</id>'
        + versions
        + title
        + authors
        + b"<categories>cs.LG</categories><abstract>A</abstract></arXivRaw>"
        b"</metadata></record></ListRecords>"
    )


_V1 = b'<version version="v1"><date>Wed, 03 May 2023 10:00:00 GMT</date></version>'


def test_real_page_parses_versions_categories_license_and_doi() -> None:
    page = parse_listing_page(FIXTURE.read_bytes())
    assert [record.family_id for record in page.records] == [
        "1909.01940",
        *[record.family_id for record in page.records[1:]],
    ]
    first = page.records[0]
    assert first.categories == ("eess.IV", "cs.AI", "cs.CV", "cs.LG", "stat.ML")
    assert first.first_public_at == "2019-09-03T14:03:55.000000Z"
    assert [version.number for version in first.versions] == [1, 2]
    assert first.license_url == "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
    assert first.doi == "10.1007/978-3-030-62469-9_7"
    assert first.in_target_categories
    assert all(record.in_target_categories for record in page.records)
    # An empty resumption token ends the list.
    assert page.resumption_token is None
    assert page.complete_list_size == 3


def test_author_count_splits_comma_and_and_joined_lists() -> None:
    # Pooch et al.: three names joined by ", " with no "and".
    # Tuttosi et al.: four names joined by ", " with no "and".
    # Orvalho et al.: three names joined entirely by " and ", no comma.
    page = parse_listing_page(FIXTURE.read_bytes())
    assert [record.author_count for record in page.records] == [3, 4, 3]


def test_cross_listed_paper_is_in_target_categories() -> None:
    page = parse_listing_page(FIXTURE.read_bytes())
    cross_listed = [
        r for r in page.records if r.categories[0] not in {"cs.AI", "cs.LG"}
    ]
    assert cross_listed and all(r.in_target_categories for r in cross_listed)


def test_no_records_match_is_an_empty_complete_page() -> None:
    page = parse_listing_page(_page(b'<error code="noRecordsMatch">none</error>'))
    assert page.records == () and page.resumption_token is None


@pytest.mark.parametrize(
    "raw",
    [
        _page(b'<error code="badResumptionToken">expired</error>'),
        _page(_record(versions=b"")),
        _page(
            _record(
                versions=_V1.replace(b'"v1"', b'"v2"'),
            )
        ),
        _page(_record(versions=_V1, title=b"")),
        _page(_record(versions=_V1, authors=b"<authors></authors>")),
        _page(_record(versions=_V1.replace(b"GMT", b""))),
        b'<!DOCTYPE x [<!ENTITY a "b">]>' + _page(_record(versions=_V1)),
        b"<not-xml",
    ],
)
def test_malformed_pages_are_rejected_whole(raw: bytes) -> None:
    with pytest.raises(ArxivFormatError):
        parse_listing_page(raw)


def test_pre_2007_identifiers_are_listed_but_marked_legacy() -> None:
    page = parse_listing_page(
        _page(_record(versions=_V1).replace(b"2305.01937", b"math/0510276"))
    )
    (record,) = page.records
    assert record.family_id == "math/0510276" and record.legacy_identifier
    for bad in (b"../etc", b"MATH/0510276", b"math/051027"):
        with pytest.raises(ArxivFormatError):
            parse_listing_page(_page(_record(versions=_V1).replace(b"2305.01937", bad)))


def test_deleted_records_are_skipped() -> None:
    deleted = (
        b'<ListRecords><record><header status="deleted"><identifier>x</identifier>'
        b"<datestamp>2025-05-01</datestamp></header></record></ListRecords>"
    )
    assert parse_listing_page(_page(deleted)).records == ()


def test_listing_path_is_closed() -> None:
    path = listing_path(
        set_spec="cs:cs:LG", from_date="2023-05-01", until_date="2026-09-21", token=None
    )
    assert parse_qs(urlsplit(path).query) == {
        "verb": ["ListRecords"],
        "metadataPrefix": ["arXivRaw"],
        "set": ["cs:cs:LG"],
        "from": ["2023-05-01"],
        "until": ["2026-09-21"],
    }
    continuation = listing_path(
        set_spec="cs:cs:LG", from_date="x", until_date="y", token="abc|123"
    )
    assert parse_qs(urlsplit(continuation).query) == {
        "verb": ["ListRecords"],
        "resumptionToken": ["abc|123"],
    }
    for bad in (
        {"set_spec": "cs:cs:CV", "from_date": "2023-05-01", "until_date": "2023-05-02"},
        {"set_spec": "cs:cs:AI", "from_date": "2023-5-1", "until_date": "2023-05-02"},
        {"set_spec": "cs:cs:AI", "from_date": "2023-05-03", "until_date": "2023-05-02"},
    ):
        with pytest.raises(ValueError):
            listing_path(token=None, **bad)
    with pytest.raises(ValueError):
        listing_path(set_spec="cs:cs:AI", from_date="", until_date="", token="a b")


def test_document_paths_request_only_the_original_version() -> None:
    assert document_path("2305.01937", "src") == "/src/2305.01937v1"
    assert document_path("2305.01937", "pdf") == "/pdf/2305.01937v1"
    for family, kind in (
        ("2305.01937v2", "pdf"),
        ("../x", "src"),
        ("2305.01937", "html"),
    ):
        with pytest.raises(ValueError):
            document_path(family, kind)


def test_bucket_pdf_path_names_the_same_original_version_by_submission_month() -> None:
    assert (
        bucket_pdf_path("2305.01937")
        == "/arxiv-dataset/arxiv/arxiv/pdf/2305/2305.01937v1.pdf"
    )
    for family in ("2305.01937v2", "../x", "2305.193"):
        with pytest.raises(ValueError):
            bucket_pdf_path(family)


def test_target_sets_derives_one_subject_set_per_category_deduplicated() -> None:
    assert target_sets(("cs.AI", "cs.LG")) == ("cs:cs:AI", "cs:cs:LG")
    assert target_sets(("cs.AI", "cs.LG", "quant-ph", "q-bio")) == (
        "cs:cs:AI",
        "cs:cs:LG",
        "physics:quant-ph",
        "q-bio",
    )
    # Repeats collapse without reordering the first occurrence.
    assert target_sets(("cs.LG", "cs.AI", "cs.LG")) == ("cs:cs:LG", "cs:cs:AI")
    with pytest.raises(ValueError, match="unsupported"):
        target_sets(("cs.CV",))


def test_listing_path_admits_every_derived_target_set() -> None:
    for set_spec in target_sets(("cs.AI", "cs.LG", "quant-ph", "q-bio")):
        listing_path(
            set_spec=set_spec,
            from_date="2023-05-01",
            until_date="2026-09-21",
            token=None,
        )
    with pytest.raises(ValueError):
        listing_path(
            set_spec="cs:cs:CV",
            from_date="2023-05-01",
            until_date="2026-09-21",
            token=None,
        )


def test_listing_window_covers_every_mature_month_through_the_freeze() -> None:
    frozen_at = "2026-09-21T00:00:00.000000Z"
    months = mature_months(frozen_at)
    assert (months[0], months[-1]) == ("2023-05", "2025-05")
    assert listing_window(months, frozen_at) == ("2023-05-01", "2026-09-21")
