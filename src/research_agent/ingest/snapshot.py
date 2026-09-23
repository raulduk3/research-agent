"""Bulk citation labels read from the OpenAlex snapshot's works table.

The paged Works API resolves one family's incoming citations at a time,
serialized behind its own daily budget. The same graph is published as CC0
Parquet files in the `openalex` S3 bucket (permission registry row
`openalex_snapshot`, reviewed in
`docs/evidence/source-pilot/openalex-snapshot.md`), and its columnar layout
lets a reader take only `id`, `referenced_works` and `referenced_works_count`
over HTTP range requests instead of downloading a whole part file.

Unlike the strict offline API-page parser (`ingest/openalex.py`), this module
drives its own reads: decoding one Parquet part file interactively seeks and
re-reads across it, so the ranged fetches happen during parsing, not before
it. Every fetch is still retained -- appended to the returned part's
`range_reads` -- before its bytes are trusted, the same retain-before-trust
order every other adapter in this package uses. A family built here carries
the snapshot's release date as its provenance (`created_at`), not any read's
own capture clock: two reads of the same release, whenever they run, produce
byte-identical families.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import BinaryIO, cast

import pyarrow.parquet as pq

from research_agent.contracts import canonical_json, sha256_hex
from research_agent.contracts.learning import (
    CitationFamilyRecord,
    CitationObservation,
    PaginationPage,
)
from research_agent.contracts.papers import (
    ExternalIdentifier,
    SourceAccess,
    normalize_identifier,
)
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.fetch import FetchedSnapshotRange
from research_agent.outcomes.windows import instant, maturity_at
from research_agent.storage.errors import IntegrityFailure

_OPENALEX_ORIGIN = "https://openalex.org/"
_COLUMNS = ("id", "referenced_works", "referenced_works_count")
_RANGE_FAILURES = frozenset({"timeout", "rejected", "transport", "invalid_payload"})


@dataclass(frozen=True, slots=True)
class ParsedSnapshotPart:
    page: PaginationPage
    families: tuple[CitationFamilyRecord, ...]
    range_reads: tuple[tuple[SourceAccess, bytes], ...]


class _RangeFetchFailed(Exception):
    def __init__(self, failure: str) -> None:
        super().__init__(failure)
        self.failure = failure


def _provider_id(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure("snapshot work id must be a string")
    short = value.removeprefix(_OPENALEX_ORIGIN)
    try:
        return normalize_identifier("openalex", short)
    except ValueError as error:
        raise IntegrityFailure("snapshot work id is invalid") from error


def release_instant(release: str) -> str:
    """The UTC instant a snapshot release date is dated with.

    A release names a day, not a moment; every record read from it is dated
    at that day's UTC midnight, so the same release always produces the same
    provenance regardless of when it is actually read.
    """
    try:
        parsed = date.fromisoformat(release)
    except ValueError as error:
        raise IntegrityFailure("snapshot release is not a canonical date") from error
    if parsed.isoformat() != release:
        raise IntegrityFailure("snapshot release is not canonical")
    instant = datetime.combine(parsed, time(), timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _RangeReadFile:
    """A random-access byte source over one snapshot object's ranged reads.

    Implements the read/seek/tell surface a Parquet reader needs. Every
    underlying read is one real bounded HTTPS range request, appended to
    `reads` before its bytes are returned.
    """

    def __init__(self, fetch: Callable[[str], FetchedSnapshotRange]) -> None:
        self._fetch = fetch
        self._pos = 0
        self._size: int | None = None
        self.reads: list[tuple[SourceAccess, bytes]] = []
        self.closed = False

    def _perform(self, range_spec: str) -> bytes:
        fetched = self._fetch(range_spec)
        payload = fetched.payload
        if fetched.access.failure is not None or payload is None:
            raise _RangeFetchFailed(fetched.access.failure or "invalid_payload")
        self.reads.append((fetched.access, payload))
        if fetched.content_range is not None:
            self._size = fetched.content_range[2]
        return payload

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        elif whence == 2:
            if self._size is None:
                self._perform("-1")
                assert self._size is not None
            self._pos = self._size + offset
        else:
            raise ValueError("unsupported seek whence")
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            if self._size is None:
                self._perform("-1")
                assert self._size is not None
            size = self._size - self._pos
        if size <= 0:
            return b""
        start = self._pos
        data = self._perform(f"{start}-{start + size - 1}")
        self._pos += len(data)
        return data

    def close(self) -> None:
        self.closed = True


def parse_snapshot_part(
    fetch: Callable[[str], FetchedSnapshotRange],
    *,
    key: str,
    part_index: int,
    cursor_in: str | None,
    next_key: str | None,
    target_provider_ids: tuple[str, ...],
    release: str,
    producer_version: ProducerVersion,
    config_hash: str,
) -> ParsedSnapshotPart:
    """Scan one snapshot works part file for edges landing on the target.

    `fetch` performs one bounded byte-range read per call; the caller binds
    it to the real bucket (or a fixture, in tests). `cursor_in`/`next_key`
    chain part files together the same way an API cursor chains pages, so
    `ingest.replay.validate_pagination` accepts either kind of pagination
    unchanged.
    """
    try:
        targets = frozenset(_provider_id(value) for value in target_provider_ids)
    except TypeError as error:
        raise IntegrityFailure("target provider ids are invalid") from error
    if not targets or len(targets) != len(target_provider_ids):
        raise IntegrityFailure("target provider ids must be unique and nonempty")

    created_at = release_instant(release)
    reader = _RangeReadFile(fetch)
    failure: str | None = None
    families: dict[str, CitationFamilyRecord] = {}
    try:
        table = pq.ParquetFile(cast(BinaryIO, reader)).read(columns=list(_COLUMNS))
    except _RangeFetchFailed as error:
        failure = error.failure if error.failure in _RANGE_FAILURES else "rejected"
    except IntegrityFailure:
        raise
    except Exception as error:
        raise IntegrityFailure("snapshot part file is malformed") from error
    else:
        if set(table.schema.names) != set(_COLUMNS):
            raise IntegrityFailure("snapshot table lacks a selected field")
        ids = table.column("id").to_pylist()
        refs = table.column("referenced_works").to_pylist()
        counts = table.column("referenced_works_count").to_pylist()
        if not len(ids) == len(refs) == len(counts):
            raise IntegrityFailure("snapshot columns are misaligned")
        part_hash = sha256_hex(
            canonical_json([access.retained_payload_hash for access, _ in reader.reads])
        )
        for row_id, row_refs, row_count in zip(ids, refs, counts):
            row_refs = row_refs or []
            if row_count is not None and len(row_refs) != row_count:
                raise IntegrityFailure("snapshot referenced_works count disagrees")
            references = tuple(_provider_id(value) for value in row_refs)
            if len(set(references)) != len(references):
                raise IntegrityFailure("snapshot referenced works are duplicated")
            target_links = tuple(sorted(targets.intersection(references)))
            if not target_links:
                continue
            provider_id = _provider_id(row_id)
            family = CitationFamilyRecord(
                schema_version=1,
                input_hashes=(part_hash,),
                producer_version=producer_version,
                config_hash=config_hash,
                created_at=created_at,
                canonical_family_id=f"openalex:{provider_id}",
                provider_work_ids=(provider_id,),
                external_ids=(ExternalIdentifier("openalex", provider_id),),
                identity_evidence_hashes=(part_hash,),
                representative_work_id=provider_id,
                representative_rule="lowest_provider_id",
                identity_state="resolved",
                possible_identity_cluster=None,
                target_link_work_ids=target_links,
                publication_interval=None,
                alternative_publication_intervals=(),
                date_state="missing",
                primary_subfield_id=None,
                alternative_subfield_ids=(),
                subfield_state="missing",
                raw_response_hashes=(part_hash,),
                is_target_family_self_link=provider_id in targets,
            )
            families[sha256_hex(family.to_canonical_json())] = family

    if reader.reads:
        capture_started_at = reader.reads[0][0].capture_started_at
        capture_completed_at = reader.reads[-1][0].capture_completed_at
        response_hash = sha256_hex(
            canonical_json([access.retained_payload_hash for access, _ in reader.reads])
        )
    else:
        capture_started_at = capture_completed_at = created_at
        response_hash = None
    page = PaginationPage(
        page_index=part_index,
        request_hash=sha256_hex(canonical_json({"key": key})),
        response_hash=response_hash,
        cursor_in=cursor_in,
        cursor_out=None if failure is not None else next_key,
        returned_count=0 if failure is not None else len(families),
        capture_started_at=capture_started_at,
        capture_completed_at=capture_completed_at,
        status="failed" if failure is not None else "completed",
        failure=failure,
    )
    return ParsedSnapshotPart(page, tuple(families.values()), tuple(reader.reads))


def build_snapshot_observation(
    parts: tuple[ParsedSnapshotPart, ...],
    *,
    paper_family_id: str,
    original_version_id: str,
    t0: str,
    target_registry_hash: str,
    target_provider_ids: tuple[str, ...],
    release: str,
    producer_version: ProducerVersion,
    config_hash: str,
) -> CitationObservation:
    """Assemble one family's `CitationObservation` from its scanned snapshot parts.

    `created_at` is the release's own instant, not any part's real capture
    clock: two builds from the same release, whenever they run, are
    byte-identical (SDD IN-25's snapshot channel). `capture_started_at` and
    `capture_completed_at` stay the parts' real capture bounds, since every
    page they carry must fall inside that window.
    """
    if not parts:
        raise IntegrityFailure("a snapshot observation needs at least one scanned part")
    pages = tuple(part.page for part in parts)
    families: dict[str, CitationFamilyRecord] = {}
    for part in parts:
        for family in part.families:
            families[sha256_hex(family.to_canonical_json())] = family
    capture_started_at = pages[0].capture_started_at
    capture_completed_at = pages[-1].capture_completed_at
    pagination_complete = pages[-1].status != "failed" and pages[-1].cursor_out is None
    maturity = maturity_at(t0)
    return CitationObservation(
        schema_version=1,
        input_hashes=(),
        producer_version=producer_version,
        config_hash=config_hash,
        created_at=release_instant(release),
        paper_family_id=paper_family_id,
        original_version_id=original_version_id,
        t0=t0,
        protocol="automatic-citations-v1",
        target_registry_hash=target_registry_hash,
        provider="openalex",
        kind="historical_reconstructed",
        target_match_state="matched",
        target_provider_ids=target_provider_ids,
        target_subfield_id=None,
        target_subfield_state="missing",
        taxonomy_hash=None,
        capture_started_at=capture_started_at,
        capture_completed_at=capture_completed_at,
        maturity_at=maturity,
        acquisition_lag_seconds=(
            instant(capture_completed_at) - instant(maturity)
        ).total_seconds(),
        pages=pages,
        pagination_complete=pagination_complete,
        citation_family_hashes=tuple(families),
        failure=None if pages[-1].status != "failed" else "initial_request_failed",
    )
