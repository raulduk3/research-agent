from dataclasses import replace
from pathlib import Path

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta, sha256_hex
from research_agent.contracts.papers import SourceAccess
from research_agent.ingest.openalex import parse_retained_works_page
from research_agent.storage.errors import IntegrityFailure, UnavailableInput

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources"


def source_access(payload: bytes, *, live: bool = False) -> SourceAccess:
    target = "W2741809807" if live else "W100|W200"
    return SourceAccess(
        schema_version=1,
        input_hashes=(),
        producer_version=ProducerVersion("1" * 64, "2" * 40, 1),
        config_hash="3" * 64,
        created_at="2026-09-21T05:00:01.000000Z",
        source="openalex",
        requested_url=(
            "https://api.openalex.org/works?"
            f"filter=cites:{target}&"
            "select=id,ids,doi,publication_date,primary_topic,referenced_works&"
            f"per_page={'1' if live else '4'}&cursor=*"
        ),
        request_parameters_hash="4" * 64,
        adapter_version="openalex-works-v1",
        capture_started_at="2026-09-21T05:00:00.000000Z",
        capture_completed_at="2026-09-21T05:00:01.000000Z",
        http_status=200,
        retained_payload_hash=sha256_hex(payload),
        retention_policy_hash="5" * 64,
        license_expression="CC0-1.0",
        permission_evidence_hash="6" * 64,
        failure=None,
    )


def meta(payload: bytes) -> RecordMeta:
    return RecordMeta(
        1,
        (sha256_hex(payload),),
        ProducerVersion("7" * 64, "8" * 40, 1),
        "9" * 64,
        "2026-09-21T05:00:02.000000Z",
    )


def test_parse_retained_page_groups_only_exact_identifiers_and_preserves_uncertainty() -> (
    None
):
    payload = (FIXTURES / "openalex-synthetic-page.json").read_bytes()
    parsed = parse_retained_works_page(
        source_access(payload),
        payload,
        page_index=0,
        cursor_in=None,
        target_provider_ids=("W100", "W200"),
        meta=meta(payload),
    )

    assert parsed.page.cursor_in is None
    assert parsed.page.cursor_out == "next-page"
    assert parsed.page.returned_count == 4
    assert len(parsed.families) == 3
    alias = parsed.families[0]
    assert alias.canonical_family_id == "doi:10.1000/alias"
    assert alias.provider_work_ids == ("W10", "W20")
    assert alias.target_link_work_ids == ("W100", "W200")
    assert alias.date_state == "conflicting"
    assert tuple(
        item.start[:10] for item in alias.alternative_publication_intervals
    ) == (
        "2021-03-12",
        "2021-03-13",
    )
    assert alias.subfield_state == "conflicting"
    assert alias.alternative_subfield_ids == (
        "https://openalex.org/subfields/1702",
        "https://openalex.org/subfields/1703",
    )
    # Identical titles without an exact shared identifier remain distinct families.
    assert {item.canonical_family_id for item in parsed.families[1:]} == {
        "openalex:W30",
        "openalex:W40",
    }
    assert all(item.date_state == "missing" for item in parsed.families[1:])


def test_parser_is_hash_bound_closed_to_network_and_all_or_nothing() -> None:
    payload = (FIXTURES / "openalex-synthetic-page.json").read_bytes()
    access = source_access(payload)
    kwargs = {
        "page_index": 0,
        "cursor_in": None,
        "target_provider_ids": ("W100", "W200"),
        "meta": meta(payload),
    }
    with pytest.raises(IntegrityFailure, match="bytes"):
        parse_retained_works_page(access, payload + b" ", **kwargs)
    with pytest.raises(UnavailableInput, match="CC0"):
        parse_retained_works_page(
            replace(access, license_expression="proprietary"), payload, **kwargs
        )
    with pytest.raises(UnavailableInput, match="successful"):
        parse_retained_works_page(replace(access, http_status=206), payload, **kwargs)
    with pytest.raises(IntegrityFailure, match="cursor"):
        parse_retained_works_page(
            replace(
                access,
                requested_url=access.requested_url.replace("cursor=*", "cursor=wrong"),
            ),
            payload,
            **kwargs,
        )
    with pytest.raises(IntegrityFailure, match="bind parser inputs"):
        parse_retained_works_page(
            replace(
                access,
                requested_url=access.requested_url.replace("W100|W200", "W100"),
            ),
            payload,
            **kwargs,
        )

    malformed = payload.replace(
        b'"id":"https://openalex.org/W30"',
        b'"id":"https://openalex.org/not-an-id"',
        1,
    )
    with pytest.raises(IntegrityFailure, match="work id"):
        parse_retained_works_page(
            replace(access, retained_payload_hash=sha256_hex(malformed)),
            malformed,
            **{**kwargs, "meta": meta(malformed)},
        )


def test_exact_alias_with_missing_evidence_cannot_become_definitely_known() -> None:
    payload = (FIXTURES / "openalex-synthetic-page.json").read_bytes()
    payload = payload.replace(
        b'"primary_topic":{"subfield":{"id":"https://openalex.org/subfields/1703"}},',
        b'"primary_topic":null,',
        1,
    ).replace(b'"publication_date":"2021-03-13"', b'"publication_date":null', 1)
    access = source_access(payload)
    parsed = parse_retained_works_page(
        access,
        payload,
        page_index=0,
        cursor_in=None,
        target_provider_ids=("W100", "W200"),
        meta=meta(payload),
    )
    alias = parsed.families[0]
    assert alias.canonical_family_id == "doi:10.1000/alias"
    assert alias.date_state == "missing"
    assert alias.publication_interval is None
    assert alias.alternative_publication_intervals == ()
    assert alias.subfield_state == "missing"
    assert alias.primary_subfield_id is None


def test_preserved_anonymous_openalex_fixture_matches_documented_wire_shape() -> None:
    payload = (FIXTURES / "openalex-live-one.json").read_bytes()
    parsed = parse_retained_works_page(
        source_access(payload, live=True),
        payload,
        page_index=0,
        cursor_in=None,
        target_provider_ids=("W2741809807",),
        meta=meta(payload),
    )
    assert parsed.page.returned_count == 1
    assert parsed.page.cursor_out is not None
    assert len(parsed.families) == 1
    record = parsed.families[0]
    assert record.provider_work_ids == ("W3137875885",)
    assert record.target_link_work_ids == ("W2741809807",)
    assert record.publication_interval is not None
    assert record.publication_interval.start == "2021-03-12T00:00:00.000000Z"
    assert record.primary_subfield_id == "https://openalex.org/subfields/1804"


def test_missing_cursor_cannot_be_interpreted_as_complete_capture() -> None:
    import json
    from research_agent.contracts import canonical_json

    value = json.loads((FIXTURES / "openalex-synthetic-page.json").read_bytes())
    del value["meta"]["next_cursor"]
    payload = canonical_json(value)
    with pytest.raises(IntegrityFailure, match="continuation"):
        parse_retained_works_page(
            source_access(payload),
            payload,
            page_index=0,
            cursor_in=None,
            target_provider_ids=("W100", "W200"),
            meta=meta(payload),
        )
