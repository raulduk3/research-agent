from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_agent.contracts import ProducerVersion, sha256_hex
from research_agent.contracts.papers import SourceAccess
from research_agent.ingest.fetch import FetchedSnapshotRange
from research_agent.ingest.snapshot import (
    build_snapshot_observation,
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


def test_build_snapshot_observation_carries_the_release_not_the_capture_clock() -> None:
    data = _part_bytes(_rows())
    keys = (
        "data/parquet/works/updated_date=2026-05-21/part_0000.parquet",
        "data/parquet/works/updated_date=2026-05-21/part_0001.parquet",
    )
    parts = []
    cursor_in = None
    for index, key in enumerate(keys):
        fetch, _ = _fake_fetch(data)
        next_key = keys[index + 1] if index + 1 < len(keys) else None
        parsed = parse_snapshot_part(
            fetch,
            key=key,
            part_index=index,
            cursor_in=cursor_in,
            next_key=next_key,
            target_provider_ids=("W10",),
            release="2026-05-21",
            producer_version=_PRODUCER,
            config_hash=_CONFIG_HASH,
        )
        parts.append(parsed)
        cursor_in = next_key

    observation = build_snapshot_observation(
        tuple(parts),
        paper_family_id="4c9b6f1a-1111-4c11-8111-111111111111",
        original_version_id="4c9b6f1a-2222-4c22-8222-222222222222",
        t0="2024-01-01T00:00:00.000000Z",
        target_registry_hash="7" * 64,
        target_provider_ids=("W10",),
        release="2026-05-21",
        producer_version=_PRODUCER,
        config_hash=_CONFIG_HASH,
    )

    assert observation.created_at == "2026-05-21T00:00:00.000000Z"
    assert observation.created_at != observation.capture_completed_at
    assert observation.target_match_state == "matched"
    assert observation.pagination_complete is True
    assert observation.failure is None
    assert len(observation.citation_family_hashes) == 2


def test_build_snapshot_observation_refuses_an_empty_scan() -> None:
    with pytest.raises(IntegrityFailure):
        build_snapshot_observation(
            (),
            paper_family_id="4c9b6f1a-1111-4c11-8111-111111111111",
            original_version_id="4c9b6f1a-2222-4c22-8222-222222222222",
            t0="2024-01-01T00:00:00.000000Z",
            target_registry_hash="7" * 64,
            target_provider_ids=("W10",),
            release="2026-05-21",
            producer_version=_PRODUCER,
            config_hash=_CONFIG_HASH,
        )
