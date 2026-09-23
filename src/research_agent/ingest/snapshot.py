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

The works table is read for the whole corpus at once, never per family: one
pass over `id` and `doi` finds every selected family's own work
(`parse_snapshot_identities`), one pass over the reference columns keeps the
edges landing on any of them (`parse_snapshot_part`), and each family's
observation is then cut from that shared pass (`build_snapshot_observation`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from typing import BinaryIO, cast

import pyarrow as pa
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
_IDENTITY_COLUMNS = ("id", "doi")
_ARXIV_DOI_PREFIX = "10.48550/arxiv."
_DOI_ORIGIN = "https://doi.org/"
_RANGE_FAILURES = frozenset({"timeout", "rejected", "transport", "invalid_payload"})


@dataclass(frozen=True, slots=True)
class ParsedSnapshotPart:
    page: PaginationPage
    families: tuple[CitationFamilyRecord, ...]
    range_reads: tuple[tuple[SourceAccess, bytes], ...]


@dataclass(frozen=True, slots=True)
class ParsedSnapshotIdentities:
    """Each selected arXiv family's works found in one part, by exact arXiv DOI.

    `failure` is set when a range read failed; the part was then not read
    and `matches` is empty, which is not the same as having no match.
    """

    matches: dict[str, tuple[str, ...]]
    failure: str | None
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


def _read_columns(
    reader: _RangeReadFile, columns: tuple[str, ...]
) -> tuple[pa.Table | None, str | None]:
    """Read exactly `columns` from one part, or the range failure that stopped it."""
    try:
        table = pq.ParquetFile(cast(BinaryIO, reader)).read(columns=list(columns))
    except _RangeFetchFailed as error:
        return None, error.failure if error.failure in _RANGE_FAILURES else "rejected"
    except IntegrityFailure:
        raise
    except Exception as error:
        raise IntegrityFailure("snapshot part file is malformed") from error
    if set(table.schema.names) != set(columns):
        raise IntegrityFailure("snapshot table lacks a selected field")
    return table, None


def _arxiv_family(doi: object) -> str | None:
    """The arXiv family an arXiv-minted DOI names, or None for any other DOI."""
    if doi is None:
        return None
    if not isinstance(doi, str):
        raise IntegrityFailure("snapshot work doi must be a string")
    short = doi.removeprefix(_DOI_ORIGIN).lower()
    if not short.startswith(_ARXIV_DOI_PREFIX):
        return None
    return short.removeprefix(_ARXIV_DOI_PREFIX)


def parse_snapshot_identities(
    fetch: Callable[[str], FetchedSnapshotRange],
    *,
    family_ids: tuple[str, ...],
) -> ParsedSnapshotIdentities:
    """Find the works in one part whose DOI is a selected family's arXiv DOI.

    The same exact lookup the paged API's match request makes
    (`doi:10.48550/arxiv.<id>`), made for every selected family at once.
    A family can match more than one work across the table; the caller
    merges every part's matches and treats more than one as ambiguous.
    """
    wanted = frozenset(family_ids)
    if not wanted or len(wanted) != len(family_ids):
        raise IntegrityFailure("family ids must be unique and nonempty")
    reader = _RangeReadFile(fetch)
    table, failure = _read_columns(reader, _IDENTITY_COLUMNS)
    matches: dict[str, set[str]] = {}
    if table is not None:
        ids = table.column("id").to_pylist()
        dois = table.column("doi").to_pylist()
        if len(ids) != len(dois):
            raise IntegrityFailure("snapshot columns are misaligned")
        for row_id, doi in zip(ids, dois):
            family_id = _arxiv_family(doi)
            if family_id in wanted:
                matches.setdefault(family_id, set()).add(_provider_id(row_id))
    return ParsedSnapshotIdentities(
        {family: tuple(sorted(works)) for family, works in sorted(matches.items())},
        failure,
        tuple(reader.reads),
    )


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
    """Scan one snapshot works part file for edges landing on any target.

    `target_provider_ids` is the whole corpus's target set, so one pass over
    the table serves every family; a record's `target_link_work_ids` names
    every target it cites, and `build_snapshot_observation` narrows it to one
    family's own. `fetch` performs one bounded byte-range read per call; the
    caller binds it to the real bucket (or a fixture, in tests).
    `cursor_in`/`next_key` chain part files together the same way an API
    cursor chains pages, so `ingest.replay.validate_pagination` accepts
    either kind of pagination unchanged.
    """
    try:
        targets = frozenset(_provider_id(value) for value in target_provider_ids)
    except TypeError as error:
        raise IntegrityFailure("target provider ids are invalid") from error
    if not targets or len(targets) != len(target_provider_ids):
        raise IntegrityFailure("target provider ids must be unique and nonempty")

    created_at = release_instant(release)
    reader = _RangeReadFile(fetch)
    families: dict[str, CitationFamilyRecord] = {}
    table, failure = _read_columns(reader, _COLUMNS)
    if table is not None:
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
    pages: tuple[PaginationPage, ...],
    families: tuple[CitationFamilyRecord, ...],
    *,
    target_match_state: str,
    target_provider_ids: tuple[str, ...],
    match_capture: tuple[str, str],
    paper_family_id: str,
    original_version_id: str,
    t0: str,
    target_registry_hash: str,
    release: str,
    producer_version: ProducerVersion,
    config_hash: str,
) -> tuple[CitationObservation, tuple[CitationFamilyRecord, ...]]:
    """Cut one family's `CitationObservation` from the corpus-wide pass.

    `pages` are every part the edge pass read, in order, and `families`
    every citing record it kept for any target. This family keeps the
    records citing its own target, each narrowed to that target (and its
    self-link judged against it alone), and returns them with the
    observation so the caller can retain exactly what it names. A matched
    family no record cites is an observed zero over a complete pass, not a
    missing observation. An unmatched or ambiguous family carries no pages,
    exactly as the paged API's match failure does.

    `created_at` is the release's own instant, not any read's capture clock:
    two builds from the same release, whenever they run, are byte-identical.
    The capture bounds are the real ones, spanning the identity pass
    (`match_capture`) and every page, which need not have run in order.
    """
    if target_match_state not in {"matched", "unmatched", "ambiguous"}:
        raise IntegrityFailure("target match state is invalid")
    matched = target_match_state == "matched"
    if matched != bool(target_provider_ids):
        raise IntegrityFailure("only a matched family carries target provider ids")
    if matched and not pages:
        raise IntegrityFailure("a snapshot observation needs at least one scanned part")
    targets = frozenset(target_provider_ids)
    kept: dict[str, CitationFamilyRecord] = {}
    if matched:
        for family in families:
            links = tuple(sorted(targets.intersection(family.target_link_work_ids)))
            if not links:
                continue
            narrowed = replace(
                family,
                target_link_work_ids=links,
                is_target_family_self_link=family.representative_work_id in targets,
            )
            kept[sha256_hex(narrowed.to_canonical_json())] = narrowed
    else:
        pages = ()
    starts = [match_capture[0], *(page.capture_started_at for page in pages)]
    ends = [match_capture[1], *(page.capture_completed_at for page in pages)]
    capture_started_at = min(starts, key=instant)
    capture_completed_at = max(ends, key=instant)
    failed = not pages or pages[-1].status == "failed"
    initial_failed = not pages or pages[0].status == "failed"
    maturity = maturity_at(t0)
    observation = CitationObservation(
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
        target_match_state=target_match_state,
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
        pagination_complete=not failed and pages[-1].cursor_out is None,
        citation_family_hashes=tuple(kept),
        failure="initial_request_failed" if initial_failed else None,
    )
    return observation, tuple(kept.values())
