"""Pure daily-ingest window, selection, lateness and batch-record logic."""

from __future__ import annotations

from dataclasses import replace

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.primitives import ProducerVersion, RecordMeta
from research_agent.contracts.questions import validate_sheet_payload
from research_agent.environment.sealing import validate_horizon
from research_agent.ingest.arxiv import ArxivListing, ArxivVersion
from research_agent.ingest.daily import (
    DailyWindow,
    EligibleFamily,
    batch_record,
    day_heads,
    eligible_families,
    island_for_category,
    issue_questions,
    lateness_records,
    next_window,
    parse_pages,
    route_islands,
)
from research_agent.outcomes.targets import TARGET_ORDER
from research_agent.outcomes.targets import definitions as target_definitions


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


# --- island routing (AG-36, TDD-3.1.13) -----------------------------------


def test_island_for_category_routes_the_three_admitted_prefixes() -> None:
    assert island_for_category("cs.AI") == "cs"
    assert island_for_category("cs.LG") == "cs"
    assert island_for_category("quant-ph") == "quant-ph"
    assert island_for_category("q-bio.GN") == "q-bio"


def test_island_for_category_rejects_an_unmapped_category() -> None:
    with pytest.raises(ValueError):
        island_for_category("astro-ph")


def test_eligible_family_primary_category_is_fixed_from_the_first_record() -> None:
    # A later cross-listed record's categories are unioned in, but the
    # family's routed island must not depend on listing page order.
    first = _listing("2306.00001", categories=("cs.AI",))
    second = _listing("2306.00001", categories=("cs.LG", "quant-ph"))
    family = eligible_families([first, second])[0]
    assert family.primary_category == "cs.AI"
    assert family.island == "cs"


def _family(
    family_id: str, primary_category: str, *, first_public_at: str = "2025-05-01"
) -> EligibleFamily:
    return EligibleFamily(
        family_id, first_public_at, (primary_category,), None, primary_category
    )


def test_route_islands_groups_and_preserves_within_island_order() -> None:
    cs_early = _family("2306.00001", "cs.AI", first_public_at="2025-05-01")
    cs_late = _family("2306.00002", "cs.LG", first_public_at="2025-05-02")
    quant = _family("2306.00003", "quant-ph")
    routed = route_islands([cs_early, cs_late, quant])
    assert set(routed) == {"cs", "quant-ph"}
    assert [family.family_id for family in routed["cs"]] == [
        "2306.00001",
        "2306.00002",
    ]
    assert [family.family_id for family in routed["quant-ph"]] == ["2306.00003"]


def test_route_islands_never_mixes_two_islands_for_one_paper() -> None:
    routed = route_islands(
        [_family("2306.00001", "cs.AI"), _family("2306.00002", "quant-ph")]
    )
    all_ids = [family.family_id for members in routed.values() for family in members]
    assert sorted(all_ids) == ["2306.00001", "2306.00002"]
    assert len(all_ids) == len(set(all_ids))


# --- issue_questions -------------------------------------------------

TARGET_META = RecordMeta(
    1,
    (),
    ProducerVersion("a" * 64, "b" * 40, 1),
    "c" * 64,
    "2026-01-01T00:00:00.000000Z",
)
FIRST_PUBLIC = "2026-01-02T09:00:00.000000Z"


def _papers(count: int, category: str = "cs.AI") -> list[EligibleFamily]:
    return [
        _family(f"2601.{number:05d}", category, first_public_at=FIRST_PUBLIC)
        for number in range(1, count + 1)
    ]


def test_questions_are_one_per_target_per_paper_and_the_same_on_every_call() -> None:
    targets = target_definitions(TARGET_META)
    papers = _papers(2)
    sheets = issue_questions("2026-01-02", "cs", papers, targets=targets)
    assert sheets == issue_questions("2026-01-02", "cs", papers, targets=targets)
    (sheet,) = sheets
    assert [q["resolver_id"] for q in sheet] == list(TARGET_ORDER) * 2
    assert len({q["question_id"] for q in sheet}) == 6
    for question, definition in zip(sheet, targets * 2, strict=True):
        assert question["target_definition_hash"] == sha256_hex(
            definition.to_canonical_json()
        )
        assert question["resolver_version"] == definition.schema_version
        assert validate_horizon(FIRST_PUBLIC, question["horizon"], 365)
    # A sealed sheet accepts the questions exactly as issued.
    assert validate_sheet_payload("seal", {"questions": list(sheet)})
    # The id follows the family and the definition, not the call or the batch.
    alone = issue_questions("2026-01-02", "cs", papers[1:], targets=targets)
    assert alone[0] == sheet[3:]
    other_meta = replace(TARGET_META, created_at="2026-01-03T00:00:00.000000Z")
    moved = issue_questions(
        "2026-01-02", "cs", papers, targets=target_definitions(other_meta)
    )
    assert {q["question_id"] for q in moved[0]}.isdisjoint(
        q["question_id"] for q in sheet
    )


@pytest.mark.parametrize(("papers", "sizes"), [(0, []), (6, [18]), (7, [18, 3])])
def test_a_sheet_holds_whole_papers_and_at_most_twenty_questions(
    papers: int, sizes: list[int]
) -> None:
    sheets = issue_questions(
        "2026-01-02", "cs", _papers(papers), targets=target_definitions(TARGET_META)
    )
    assert [len(sheet) for sheet in sheets] == sizes


def test_questions_are_refused_for_a_foreign_island_or_a_later_paper() -> None:
    targets = target_definitions(TARGET_META)
    with pytest.raises(ValueError, match="not on island cs"):
        issue_questions("2026-01-02", "cs", _papers(1, "quant-ph"), targets=targets)
    with pytest.raises(ValueError, match="first public after"):
        issue_questions("2026-01-01", "cs", _papers(1), targets=targets)
    with pytest.raises(ValueError, match="targets"):
        issue_questions("2026-01-02", "cs", _papers(1), targets=())


def test_a_day_paper_is_eligible_with_its_horizon_and_no_borrowed_reason() -> None:
    heads = day_heads(FIRST_PUBLIC, target_definitions(TARGET_META))
    assert [head.target_id for head in heads] == list(TARGET_ORDER)
    for head in heads:
        assert head.forecast_eligibility == "eligible"
        assert head.availability == "unavailable"
        assert head.unavailable_reason == "no_active_bundle"
        assert head.horizon_end == "2027-01-02T09:00:00.000000Z"


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
