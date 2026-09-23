"""Pure daily-ingest window, selection, lateness and batch-record logic."""

from __future__ import annotations

import pytest

from research_agent.ingest.arxiv import ArxivListing, ArxivVersion
from research_agent.ingest.daily import (
    DailyWindow,
    batch_record,
    eligible_families,
    lateness_records,
    next_window,
    parse_pages,
)


def _listing(
    family_id: str,
    *,
    submitted: str = "2025-05-01T00:00:00.000000Z",
    categories: tuple[str, ...] = ("cs.AI",),
    license_url: str | None = "http://creativecommons.org/licenses/by/4.0/",
) -> ArxivListing:
    return ArxivListing(
        family_id,
        "2025-05-01",
        categories,
        (ArxivVersion(1, submitted),),
        f"Paper {family_id}",
        "Abstract",
        license_url,
        None,
        "Author One",
    )


# --- next_window -------------------------------------------------------


def test_first_run_requires_an_explicit_since_date() -> None:
    with pytest.raises(ValueError):
        next_window(None, today="2026-01-05")


def test_first_run_starts_at_since() -> None:
    window = next_window(None, today="2026-01-05", since="2026-01-01")
    assert window == DailyWindow("2026-01-01", "2026-01-05")


def test_later_run_starts_the_day_after_the_watermark() -> None:
    window = next_window("2026-01-05", today="2026-01-08")
    assert window == DailyWindow("2026-01-06", "2026-01-08")


def test_watermark_not_before_today_is_refused() -> None:
    with pytest.raises(ValueError):
        next_window("2026-01-08", today="2026-01-08")
    with pytest.raises(ValueError):
        next_window("2026-01-09", today="2026-01-08")


def test_same_day_window_is_permitted_on_the_first_run() -> None:
    window = next_window(None, today="2026-01-01", since="2026-01-01")
    assert window == DailyWindow("2026-01-01", "2026-01-01")


# --- eligible_families ---------------------------------------------------


def test_out_of_category_and_legacy_records_are_excluded() -> None:
    out_of_category = _listing("2306.00001", categories=("cs.CV",))
    legacy = ArxivListing(
        "math/0510276",
        "2025-05-01",
        ("cs.AI",),
        (ArxivVersion(1, "2025-05-01T00:00:00.000000Z"),),
        "Legacy",
        "Abstract",
        None,
        None,
        "Author One",
    )
    in_category = _listing("2306.00002")
    families = eligible_families([out_of_category, legacy, in_category])
    assert [family.family_id for family in families] == ["2306.00002"]


def test_sorted_by_first_public_at_then_family_id() -> None:
    later = _listing("2306.00001", submitted="2025-05-02T00:00:00.000000Z")
    earlier_a = _listing("2306.00003", submitted="2025-05-01T00:00:00.000000Z")
    earlier_b = _listing("2306.00002", submitted="2025-05-01T00:00:00.000000Z")
    families = eligible_families([later, earlier_a, earlier_b])
    assert [family.family_id for family in families] == [
        "2306.00002",
        "2306.00003",
        "2306.00001",
    ]


def test_cross_listed_family_is_merged_once_with_union_categories() -> None:
    ai = _listing("2306.00001", categories=("cs.AI",), license_url=None)
    lg = _listing("2306.00001", categories=("cs.LG", "cs.CV"))
    families = eligible_families([ai, lg])
    assert len(families) == 1
    merged = families[0]
    assert merged.categories == ("cs.AI", "cs.CV", "cs.LG")
    # The first-seen record carried no license; the later record's is kept.
    assert merged.license_url == "http://creativecommons.org/licenses/by/4.0/"


def test_cross_listed_family_carries_its_primary_category() -> None:
    ai = _listing("2306.00001", categories=("cs.AI",))
    lg = _listing("2306.00001", categories=("cs.LG", "cs.CV"))
    families = eligible_families([ai, lg])
    assert len(families) == 1
    # arXiv lists a paper's own primary category first; the family keeps the
    # primary category of the record it was first admitted from.
    assert families[0].primary_category == "cs.AI"
    families_reversed = eligible_families([lg, ai])
    assert families_reversed[0].primary_category == "cs.LG"


def test_admission_widens_to_the_four_configured_categories() -> None:
    quant_ph = _listing("2306.00001", categories=("quant-ph",))
    q_bio = _listing("2306.00002", categories=("q-bio",))
    families = eligible_families([quant_ph, q_bio])
    assert [family.family_id for family in families] == ["2306.00001", "2306.00002"]
    assert families[0].primary_category == "quant-ph"
    assert families[1].primary_category == "q-bio"


def test_parse_pages_flattens_records_in_page_order() -> None:
    from research_agent.ingest.arxiv import parse_listing_page

    envelope = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><ListRecords>'
        b"<record><header><identifier>oai:arXiv.org:2306.00001</identifier>"
        b"<datestamp>2025-05-01</datestamp></header><metadata>"
        b'<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/"><id>2306.00001</id>'
        b'<version version="v1"><date>Thu, 01 May 2025 00:00:00 GMT</date></version>'
        b"<title>T</title><authors>A. Author</authors>"
        b"<categories>cs.AI</categories><abstract>A</abstract>"
        b"</arXivRaw></metadata></record></ListRecords></OAI-PMH>"
    )
    assert parse_listing_page(envelope).records  # sanity: fixture parses
    records = parse_pages([envelope, envelope])
    assert [record.family_id for record in records] == ["2306.00001", "2306.00001"]


# --- lateness_records ----------------------------------------------------


def test_lateness_is_observed_minus_first_public_at() -> None:
    family = eligible_families([_listing("2306.00001")])[0]
    records = lateness_records([family], observed_at="2025-05-02T00:00:00.000000Z")
    assert len(records) == 1
    assert records[0].family_id == "2306.00001"
    assert records[0].lateness_seconds == 86400.0


# --- batch_record ----------------------------------------------------


def test_batch_record_records_the_configured_category_list_and_sorted_families() -> (
    None
):
    families = eligible_families([_listing("2306.00002"), _listing("2306.00001")])
    lateness = lateness_records(families, observed_at="2025-05-02T00:00:00.000000Z")
    record = batch_record(
        day="2025-05-02",
        categories=("cs.LG", "cs.AI"),
        families=families,
        lateness=lateness,
        listing_report_manifests=("b" * 64, "a" * 64),
    )
    assert record["day"] == "2025-05-02"
    assert record["categories"] == ["cs.AI", "cs.LG"]
    assert record["listing_report_manifests"] == ["a" * 64, "b" * 64]
    assert [item["family_id"] for item in record["eligible_families"]] == [
        "2306.00001",
        "2306.00002",
    ]
    assert len(record["lateness"]) == 2


def test_batch_record_is_deterministic_for_identical_inputs() -> None:
    families = eligible_families([_listing("2306.00001")])
    lateness = lateness_records(families, observed_at="2025-05-02T00:00:00.000000Z")
    first = batch_record(
        day="2025-05-02",
        categories=("cs.AI", "cs.LG"),
        families=families,
        lateness=lateness,
        listing_report_manifests=("a" * 64,),
    )
    second = batch_record(
        day="2025-05-02",
        categories=("cs.AI", "cs.LG"),
        families=families,
        lateness=lateness,
        listing_report_manifests=("a" * 64,),
    )
    assert first == second
