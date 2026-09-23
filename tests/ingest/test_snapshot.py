from __future__ import annotations

import io
from dataclasses import replace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_agent.contracts import ProducerVersion, sha256_hex
from research_agent.contracts.papers import SourceAccess
from research_agent.ingest.fetch import FetchedSnapshotRange
from research_agent.ingest.snapshot import (
    ParsedSnapshotPart,
    build_snapshot_observation,
    parse_snapshot_identities,
    parse_snapshot_part,
    release_instant,
)
from research_agent.storage.errors import IntegrityFailure

_PRODUCER = ProducerVersion("1" * 64, "2" * 40, 1)
_CONFIG_HASH = "3" * 64


def _part_bytes(
    rows: list[dict[str, object]], *, columns: tuple[str, ...] | None = None
) -> bytes:
    names = columns or ("id", "referenced_works", "referenced_works_count")
    table = pa.table({name: [row[name] for row in rows] for name in names})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _access(payload: bytes, *, failure: str | None = None) -> SourceAccess:
    return SourceAccess(
        schema_version=1,
        input_hashes=(),
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
        created_at="2026-05-21T09:00:00.000000Z",
        source="openalex",
        requested_url="https://openalex.s3.amazonaws.com/data/parquet/works/part.parquet",
        request_parameters_hash="4" * 64,
        adapter_version="openalex-snapshot-range-v1",
        capture_started_at="2026-05-21T09:00:00.000000Z",
        capture_completed_at="2026-05-21T09:00:00.500000Z",
        http_status=None if failure else 206,
        retained_payload_hash=None if failure else sha256_hex(payload),
        retention_policy_hash="5" * 64,
        license_expression="CC0-1.0",
        permission_evidence_hash="6" * 64,
        failure=failure,
    )


def _fake_fetch(data: bytes, *, fail_after: int | None = None):
    calls = {"count": 0}

    def fetch(range_spec: str) -> FetchedSnapshotRange:
        calls["count"] += 1
        if fail_after is not None and calls["count"] > fail_after:
            return FetchedSnapshotRange(_access(b"", failure="timeout"), None, None)
        if range_spec.startswith("-"):
            length = int(range_spec[1:])
            start = max(0, len(data) - length)
            end = len(data) - 1
        else:
            start_text, end_text = range_spec.split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(data) - 1
        end = min(end, len(data) - 1)
        chunk = data[start : end + 1]
        return FetchedSnapshotRange(_access(chunk), chunk, (start, end, len(data)))

    return fetch, calls


def test_release_instant_is_release_midnight_utc() -> None:
    assert release_instant("2026-05-21") == "2026-05-21T00:00:00.000000Z"


@pytest.mark.parametrize("release", ["2026-5-21", "not-a-date", "2026-05-21T00:00:00Z"])
def test_release_instant_refuses_a_non_canonical_date(release: str) -> None:
    with pytest.raises(IntegrityFailure):
        release_instant(release)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "id": "https://openalex.org/W20",
            "referenced_works": ["https://openalex.org/W10"],
            "referenced_works_count": 1,
        },
        {
            "id": "https://openalex.org/W30",
            "referenced_works": [
                "https://openalex.org/W10",
                "https://openalex.org/W99",
            ],
            "referenced_works_count": 2,
        },
        {
            "id": "https://openalex.org/W40",
            "referenced_works": ["https://openalex.org/W99"],
            "referenced_works_count": 1,
        },
    ]


def test_parse_snapshot_part_keeps_only_edges_landing_on_the_target() -> None:
    data = _part_bytes(_rows())
    fetch, _ = _fake_fetch(data)

    parsed = parse_snapshot_part(
        fetch,
        key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
        part_index=0,
        cursor_in=None,
        next_key=None,
        target_provider_ids=("W10",),
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )

    assert parsed.page.status == "completed"
    assert parsed.page.failure is None
    assert parsed.page.returned_count == 2
    assert {family.canonical_family_id for family in parsed.families} == {
        "openalex:W20",
        "openalex:W30",
    }
    for family in parsed.families:
        assert family.target_link_work_ids == ("W10",)
        assert family.date_state == "missing"
        assert family.subfield_state == "missing"
        assert family.is_target_family_self_link is False
        assert family.created_at == "2026-05-21T00:00:00.000000Z"
    assert parsed.range_reads


def test_family_created_at_is_the_release_not_a_capture_clock() -> None:
    data = _part_bytes(_rows())
    fetch, _ = _fake_fetch(data)

    parsed = parse_snapshot_part(
        fetch,
        key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
        part_index=0,
        cursor_in=None,
        next_key=None,
        target_provider_ids=("W10",),
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )
    for access, _ in parsed.range_reads:
        assert access.capture_completed_at != parsed.families[0].created_at
    assert all(
        family.created_at == "2026-05-21T00:00:00.000000Z" for family in parsed.families
    )


def test_reading_the_same_release_twice_is_byte_identical() -> None:
    data = _part_bytes(_rows())

    def run() -> tuple[bytes, ...]:
        fetch, _ = _fake_fetch(data)
        parsed = parse_snapshot_part(
            fetch,
            key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
            part_index=0,
            cursor_in=None,
            next_key=None,
            target_provider_ids=("W10",),
            release="2026-05-21",
            producer_version=_PRODUCER,
            config_hash=_CONFIG_HASH,
        )
        return tuple(sorted(family.to_canonical_json() for family in parsed.families))

    assert run() == run()


def test_a_failed_range_read_produces_a_failed_page_and_no_families() -> None:
    data = _part_bytes(_rows())
    fetch, _ = _fake_fetch(data, fail_after=0)

    parsed = parse_snapshot_part(
        fetch,
        key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
        part_index=0,
        cursor_in=None,
        next_key="data/parquet/works/updated_date=2026-05-21/part_0001.parquet",
        target_provider_ids=("W10",),
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )

    assert parsed.page.status == "failed"
    assert parsed.page.failure == "timeout"
    assert parsed.page.cursor_out is None
    assert parsed.page.returned_count == 0
    assert parsed.families == ()


def test_referenced_works_count_disagreement_is_an_integrity_failure() -> None:
    rows = [
        {
            "id": "https://openalex.org/W20",
            "referenced_works": ["https://openalex.org/W10"],
            "referenced_works_count": 5,
        }
    ]
    data = _part_bytes(rows)
    fetch, _ = _fake_fetch(data)

    with pytest.raises(IntegrityFailure):
        parse_snapshot_part(
            fetch,
            key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
            part_index=0,
            cursor_in=None,
            next_key=None,
            target_provider_ids=("W10",),
            release="2026-05-21",
            producer_version=_PRODUCER,
            config_hash=_CONFIG_HASH,
        )


def test_missing_selected_column_is_an_integrity_failure() -> None:
    rows = [{"id": "https://openalex.org/W20", "referenced_works_count": 0}]
    data = _part_bytes(rows, columns=("id", "referenced_works_count"))
    fetch, _ = _fake_fetch(data)

    with pytest.raises(IntegrityFailure):
        parse_snapshot_part(
            fetch,
            key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
            part_index=0,
            cursor_in=None,
            next_key=None,
            target_provider_ids=("W10",),
            release="2026-05-21",
            producer_version=_PRODUCER,
            config_hash=_CONFIG_HASH,
        )


@pytest.mark.parametrize("targets", [(), ("W10", "W10")])
def test_target_provider_ids_must_be_unique_and_nonempty(
    targets: tuple[str, ...],
) -> None:
    data = _part_bytes(_rows())
    fetch, _ = _fake_fetch(data)

    with pytest.raises(IntegrityFailure):
        parse_snapshot_part(
            fetch,
            key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
            part_index=0,
            cursor_in=None,
            next_key=None,
            target_provider_ids=targets,
            release="2026-05-21",
            producer_version=_PRODUCER,
            config_hash=_CONFIG_HASH,
        )


def test_family_is_the_same_contract_shape_as_the_api_built_one() -> None:
    from research_agent.contracts import RecordMeta
    from research_agent.ingest.openalex import parse_retained_works_page

    api_payload = (
        b'{"meta":{"next_cursor":null},"results":[{'
        b'"id":"https://openalex.org/W20",'
        b'"ids":{"openalex":"https://openalex.org/W20","doi":null},'
        b'"doi":null,'
        b'"publication_date":"2021-01-01",'
        b'"primary_topic":null,'
        b'"referenced_works":["https://openalex.org/W10"]'
        b"}]}"
    )
    api_access = SourceAccess(
        schema_version=1,
        input_hashes=(),
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
        created_at="2026-05-21T09:00:00.000000Z",
        source="openalex",
        requested_url=(
            "https://api.openalex.org/works?"
            "filter=cites:W10&"
            "select=id,ids,doi,publication_date,primary_topic,referenced_works&"
            "per_page=1&cursor=*"
        ),
        request_parameters_hash="4" * 64,
        adapter_version="openalex-anonymous-citations-v1",
        capture_started_at="2026-05-21T09:00:00.000000Z",
        capture_completed_at="2026-05-21T09:00:00.500000Z",
        http_status=200,
        retained_payload_hash=sha256_hex(api_payload),
        retention_policy_hash="5" * 64,
        license_expression="CC0-1.0",
        permission_evidence_hash="6" * 64,
        failure=None,
    )
    api_meta = RecordMeta(
        1,
        (sha256_hex(api_payload),),
        _PRODUCER,
        _CONFIG_HASH,
        "2026-05-21T09:00:01.000000Z",
    )
    api_parsed = parse_retained_works_page(
        api_access,
        api_payload,
        page_index=0,
        cursor_in=None,
        target_provider_ids=("W10",),
        meta=api_meta,
    )

    data = _part_bytes(_rows())
    fetch, _ = _fake_fetch(data)
    snapshot_parsed = parse_snapshot_part(
        fetch,
        key="data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
        part_index=0,
        cursor_in=None,
        next_key=None,
        target_provider_ids=("W10",),
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )

    import json

    api_keys = set(json.loads(api_parsed.families[0].to_canonical_json()))
    snapshot_keys = {
        key
        for family in snapshot_parsed.families
        for key in json.loads(family.to_canonical_json())
    }
    assert api_keys == snapshot_keys
    assert type(api_parsed.families[0]) is type(snapshot_parsed.families[0])


# --- the identity pass ------------------------------------------------------


def _identity_bytes(rows: list[tuple[str, str | None]]) -> bytes:
    table = pa.table(
        {"id": [row[0] for row in rows], "doi": [row[1] for row in rows]},
        schema=pa.schema([("id", pa.string()), ("doi", pa.string())]),
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def test_identity_pass_finds_every_selected_family_by_its_arxiv_doi() -> None:
    data = _identity_bytes(
        [
            ("https://openalex.org/W10", "https://doi.org/10.48550/arXiv.2503.00001"),
            ("https://openalex.org/W11", "https://doi.org/10.48550/arxiv.2503.00002"),
            ("https://openalex.org/W12", "https://doi.org/10.48550/arxiv.2503.00002"),
            ("https://openalex.org/W13", "https://doi.org/10.48550/arxiv.2503.00009"),
            ("https://openalex.org/W14", "https://doi.org/10.1000/2503.00001"),
            ("https://openalex.org/W15", None),
        ]
    )
    fetch, _ = _fake_fetch(data)

    parsed = parse_snapshot_identities(fetch, family_ids=("2503.00001", "2503.00002"))

    # One pass answers for every family; a journal DOI is not an arXiv match,
    # and a family nobody selected is not reported.
    assert parsed.failure is None
    assert parsed.matches == {
        "2503.00001": ("W10",),
        "2503.00002": ("W11", "W12"),
    }
    assert parsed.range_reads


def test_identity_pass_reports_a_failed_read_rather_than_no_match() -> None:
    data = _identity_bytes([("https://openalex.org/W10", None)])
    fetch, _ = _fake_fetch(data, fail_after=0)

    parsed = parse_snapshot_identities(fetch, family_ids=("2503.00001",))

    assert parsed.failure == "timeout"
    assert parsed.matches == {}


# --- one family's observation cut from the corpus-wide pass ------------------

_KEYS = (
    "data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
    "data/parquet/works/updated_date=2026-05-21/part_0001.parquet",
)
_MATCH_CAPTURE = ("2026-05-21T08:59:00.000000Z", "2026-05-21T08:59:30.000000Z")


def _corpus_rows() -> list[dict[str, object]]:
    # W30 cites two corpus families' works; W10 is itself a corpus target
    # and cites W11.
    return [
        {
            "id": "https://openalex.org/W20",
            "referenced_works": ["https://openalex.org/W10"],
            "referenced_works_count": 1,
        },
        {
            "id": "https://openalex.org/W30",
            "referenced_works": [
                "https://openalex.org/W10",
                "https://openalex.org/W11",
            ],
            "referenced_works_count": 2,
        },
        {
            "id": "https://openalex.org/W10",
            "referenced_works": ["https://openalex.org/W11"],
            "referenced_works_count": 1,
        },
    ]


def _scan(targets: tuple[str, ...]) -> tuple[ParsedSnapshotPart, ...]:
    data = _part_bytes(_corpus_rows())
    parts = []
    cursor_in = None
    for index, key in enumerate(_KEYS):
        fetch, _ = _fake_fetch(data)
        next_key = _KEYS[index + 1] if index + 1 < len(_KEYS) else None
        parts.append(
            parse_snapshot_part(
                fetch,
                key=key,
                part_index=index,
                cursor_in=cursor_in,
                next_key=next_key,
                target_provider_ids=targets,
                release="2026-05-21",
                producer_version=_PRODUCER,
                config_hash=_CONFIG_HASH,
            )
        )
        cursor_in = next_key
    return tuple(parts)


def _observe(
    parts: tuple[ParsedSnapshotPart, ...],
    *,
    state: str = "matched",
    targets: tuple[str, ...] = ("W10",),
):
    return build_snapshot_observation(
        tuple(part.page for part in parts),
        tuple(family for part in parts for family in part.families),
        target_match_state=state,
        target_provider_ids=targets,
        match_capture=_MATCH_CAPTURE,
        paper_family_id="4c9b6f1a-1111-4c11-8111-111111111111",
        original_version_id="4c9b6f1a-2222-4c22-8222-222222222222",
        t0="2024-01-01T00:00:00.000000Z",
        target_registry_hash="7" * 64,
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )


def test_build_snapshot_observation_carries_the_release_not_the_capture_clock() -> None:
    observation, records = _observe(_scan(("W10", "W11")))

    assert observation.created_at == "2026-05-21T00:00:00.000000Z"
    assert observation.created_at != observation.capture_completed_at
    assert observation.target_match_state == "matched"
    assert observation.pagination_complete is True
    assert observation.failure is None
    assert len(observation.pages) == 2
    # The capture spans the identity pass that found the target as well.
    assert observation.capture_started_at == _MATCH_CAPTURE[0]
    assert observation.citation_family_hashes == tuple(
        sha256_hex(record.to_canonical_json()) for record in records
    )


def test_one_family_keeps_only_the_edges_landing_on_its_own_target() -> None:
    parts = _scan(("W10", "W11"))

    _, w10 = _observe(parts, targets=("W10",))
    _, w11 = _observe(parts, targets=("W11",))

    assert {r.representative_work_id for r in w10} == {"W20", "W30"}
    assert {r.representative_work_id for r in w11} == {"W30", "W10"}
    # A record citing two families' works names only this family's.
    assert all(r.target_link_work_ids == ("W10",) for r in w10)
    assert all(r.target_link_work_ids == ("W11",) for r in w11)
    # W10 citing W11 is not W11's self-link, though W10 is a corpus target.
    assert not any(r.is_target_family_self_link for r in w11)


def test_a_matched_family_nothing_cites_is_an_observed_zero() -> None:
    observation, records = _observe(_scan(("W10", "W77")), targets=("W77",))

    assert records == ()
    assert observation.citation_family_hashes == ()
    assert observation.pagination_complete is True
    assert observation.failure is None


@pytest.mark.parametrize("state", ["unmatched", "ambiguous"])
def test_an_unmatched_family_carries_no_pages(state: str) -> None:
    observation, records = _observe(_scan(("W10",)), state=state, targets=())

    assert records == ()
    assert observation.target_match_state == state
    assert observation.target_provider_ids == ()
    assert observation.pages == ()
    assert observation.failure == "initial_request_failed"
    assert (
        observation.capture_started_at,
        observation.capture_completed_at,
    ) == _MATCH_CAPTURE


def test_pages_read_out_of_order_stay_inside_the_capture_bounds() -> None:
    first, second = _scan(("W10",))
    # A requeued range reads its part after the parts that follow it.
    late = replace(
        first.page,
        capture_started_at="2026-05-22T00:00:00.000000Z",
        capture_completed_at="2026-05-22T00:00:01.000000Z",
    )
    observation, _ = build_snapshot_observation(
        (late, second.page),
        first.families + second.families,
        target_match_state="matched",
        target_provider_ids=("W10",),
        match_capture=_MATCH_CAPTURE,
        paper_family_id="4c9b6f1a-1111-4c11-8111-111111111111",
        original_version_id="4c9b6f1a-2222-4c22-8222-222222222222",
        t0="2024-01-01T00:00:00.000000Z",
        target_registry_hash="7" * 64,
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )

    assert observation.capture_completed_at == "2026-05-22T00:00:01.000000Z"


def test_build_snapshot_observation_refuses_a_matched_family_without_a_scan() -> None:
    with pytest.raises(IntegrityFailure):
        _observe(())


def test_build_snapshot_observation_refuses_targets_on_an_unmatched_family() -> None:
    with pytest.raises(IntegrityFailure):
        _observe(_scan(("W10",)), state="unmatched", targets=("W10",))
