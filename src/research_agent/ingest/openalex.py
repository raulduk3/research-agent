"""Strict offline parser for retained OpenAlex Works API pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from research_agent.contracts import RecordMeta, canonical_loads
from research_agent.contracts.learning import CitationFamilyRecord, PaginationPage
from research_agent.contracts.papers import (
    ExternalIdentifier,
    SourceAccess,
    SourceInterval,
    normalize_identifier,
)
from research_agent.ingest.replay import replay_retained_source
from research_agent.storage.errors import IntegrityFailure, UnavailableInput

_OPENALEX_ORIGIN = "https://openalex.org/"


@dataclass(frozen=True, slots=True)
class ParsedOpenAlexPage:
    page: PaginationPage
    families: tuple[CitationFamilyRecord, ...]


@dataclass(frozen=True, slots=True)
class _Work:
    provider_id: str
    doi: str | None
    publication_interval: SourceInterval | None
    primary_subfield_id: str | None
    target_link_work_ids: tuple[str, ...]


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrityFailure(f"OpenAlex {name} must be an object")
    return cast(dict[str, Any], value)


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise IntegrityFailure(f"OpenAlex {name} must be an array")
    return value


def _provider_id(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityFailure("OpenAlex work id must be a string")
    short = value.removeprefix(_OPENALEX_ORIGIN)
    try:
        return normalize_identifier("openalex", short)
    except ValueError as error:
        raise IntegrityFailure("OpenAlex work id is invalid") from error


def _doi(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntegrityFailure("OpenAlex DOI must be a string or null")
    try:
        return normalize_identifier("doi", value)
    except ValueError as error:
        raise IntegrityFailure("OpenAlex DOI is invalid") from error


def _day_interval(value: object) -> SourceInterval | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntegrityFailure("OpenAlex publication_date must be a date or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise IntegrityFailure("OpenAlex publication_date is invalid") from error
    if parsed.isoformat() != value:
        raise IntegrityFailure("OpenAlex publication_date is not canonical")
    start = datetime.combine(parsed, time(), timezone.utc)
    return SourceInterval(
        start.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        (start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )


def _subfield(value: object) -> str | None:
    if value is None:
        return None
    topic = _object(value, "primary_topic")
    subfield_value = topic.get("subfield")
    if subfield_value is None:
        return None
    subfield = _object(subfield_value, "primary_topic.subfield")
    identifier = subfield.get("id")
    if (
        not isinstance(identifier, str)
        or not identifier.startswith(f"{_OPENALEX_ORIGIN}subfields/")
        or not identifier.removeprefix(f"{_OPENALEX_ORIGIN}subfields/").isdigit()
    ):
        raise IntegrityFailure("OpenAlex primary subfield id is invalid")
    return identifier


def _parse_work(value: object, targets: frozenset[str]) -> _Work:
    work = _object(value, "work")
    required = {
        "id",
        "ids",
        "doi",
        "publication_date",
        "primary_topic",
        "referenced_works",
    }
    if not required.issubset(work):
        raise IntegrityFailure("OpenAlex work lacks a selected field")
    provider_id = _provider_id(work["id"])
    ids = _object(work["ids"], "work.ids")
    if _provider_id(ids.get("openalex")) != provider_id:
        raise IntegrityFailure("OpenAlex work id fields disagree")
    direct_doi = _doi(work["doi"])
    ids_doi = _doi(ids.get("doi"))
    if direct_doi != ids_doi:
        raise IntegrityFailure("OpenAlex DOI fields disagree")
    references = tuple(
        _provider_id(item)
        for item in _array(work["referenced_works"], "referenced_works")
    )
    if len(set(references)) != len(references):
        raise IntegrityFailure("OpenAlex referenced works are duplicated")
    target_links = tuple(sorted(targets.intersection(references)))
    if not target_links:
        raise IntegrityFailure("OpenAlex work has no exact requested target link")
    return _Work(
        provider_id,
        direct_doi,
        _day_interval(work["publication_date"]),
        _subfield(work["primary_topic"]),
        target_links,
    )


def _family(
    works: tuple[_Work, ...],
    *,
    response_hash: str,
    meta: RecordMeta,
    targets: frozenset[str],
) -> CitationFamilyRecord:
    provider_ids = tuple(sorted(work.provider_id for work in works))
    dois = tuple(sorted({work.doi for work in works if work.doi is not None}))
    external_ids = tuple(
        sorted(
            (
                *(ExternalIdentifier("openalex", value) for value in provider_ids),
                *(ExternalIdentifier("doi", value) for value in dois),
            ),
            key=lambda item: (item.scheme, item.value),
        )
    )
    intervals = tuple(
        sorted(
            {work.publication_interval for work in works if work.publication_interval},
            key=lambda interval: interval.start,
        )
    )
    subfields = tuple(
        sorted({work.primary_subfield_id for work in works if work.primary_subfield_id})
    )
    has_missing_date = any(work.publication_interval is None for work in works)
    has_missing_subfield = any(work.primary_subfield_id is None for work in works)
    if not intervals or (has_missing_date and len(intervals) == 1):
        publication_interval = None
        alternative_intervals: tuple[SourceInterval, ...] = ()
        date_state = "missing"
    elif len(intervals) == 1:
        publication_interval = intervals[0]
        alternative_intervals = ()
        date_state = "known"
    else:
        publication_interval = None
        alternative_intervals = intervals
        date_state = "conflicting"
    if not subfields or (has_missing_subfield and len(subfields) == 1):
        primary_subfield_id = None
        alternative_subfields: tuple[str, ...] = ()
        subfield_state = "missing"
    elif len(subfields) == 1:
        primary_subfield_id = subfields[0]
        alternative_subfields = ()
        subfield_state = "known"
    else:
        primary_subfield_id = None
        alternative_subfields = subfields
        subfield_state = "conflicting"
    target_links = tuple(
        sorted({value for work in works for value in work.target_link_work_ids})
    )
    canonical_family_id = f"doi:{dois[0]}" if dois else f"openalex:{provider_ids[0]}"
    return CitationFamilyRecord(
        schema_version=meta.schema_version,
        input_hashes=meta.input_hashes,
        producer_version=meta.producer_version,
        config_hash=meta.config_hash,
        created_at=meta.created_at,
        canonical_family_id=canonical_family_id,
        provider_work_ids=provider_ids,
        external_ids=external_ids,
        identity_evidence_hashes=(response_hash,),
        representative_work_id=provider_ids[0],
        representative_rule="lowest_provider_id",
        identity_state="resolved",
        possible_identity_cluster=None,
        target_link_work_ids=target_links,
        publication_interval=publication_interval,
        alternative_publication_intervals=alternative_intervals,
        date_state=date_state,
        primary_subfield_id=primary_subfield_id,
        alternative_subfield_ids=alternative_subfields,
        subfield_state=subfield_state,
        raw_response_hashes=(response_hash,),
        is_target_family_self_link=bool(targets.intersection(provider_ids)),
    )


def parse_retained_works_page(
    access: SourceAccess,
    payload: bytes,
    *,
    page_index: int,
    cursor_in: str | None,
    target_provider_ids: tuple[str, ...],
    meta: RecordMeta,
) -> ParsedOpenAlexPage:
    """Parse one verified retained cursor page without any network fallback."""

    if access.source != "openalex" or access.license_expression != "CC0-1.0":
        raise UnavailableInput("retained page lacks admitted OpenAlex CC0 provenance")
    request_url = urlsplit(access.requested_url)
    if (
        access.http_status != 200
        or request_url.scheme != "https"
        or request_url.netloc != "api.openalex.org"
        or request_url.path != "/works"
    ):
        raise UnavailableInput(
            "retained page is not a successful OpenAlex Works response"
        )
    replay_retained_source(access, payload)
    response_hash = access.retained_payload_hash
    assert response_hash is not None
    if response_hash not in meta.input_hashes:
        raise IntegrityFailure("record provenance omits retained OpenAlex response")
    try:
        targets = frozenset(_provider_id(value) for value in target_provider_ids)
    except TypeError as error:
        raise IntegrityFailure("target provider ids are invalid") from error
    if not targets or len(targets) != len(target_provider_ids):
        raise IntegrityFailure("target provider ids must be unique and nonempty")

    query = parse_qs(request_url.query, keep_blank_values=True)
    expected_select = {
        "id",
        "ids",
        "doi",
        "publication_date",
        "primary_topic",
        "referenced_works",
    }
    if set(query) != {"filter", "select", "per_page", "cursor"}:
        raise IntegrityFailure("retained request parameters are not the closed query")
    filters = query.get("filter", [])
    selections = query.get("select", [])
    page_sizes = query.get("per_page", [])
    if (
        len(filters) != 1
        or not filters[0].startswith("cites:")
        or len(selections) != 1
        or len(page_sizes) != 1
    ):
        raise IntegrityFailure("retained OpenAlex query shape is invalid")
    filter_ids = filters[0].removeprefix("cites:").split("|")
    try:
        normalized_filter_ids = tuple(_provider_id(value) for value in filter_ids)
        per_page = int(page_sizes[0])
    except (TypeError, ValueError) as error:
        raise IntegrityFailure("retained OpenAlex query values are invalid") from error
    selected_fields = selections[0].split(",")
    if (
        len(set(normalized_filter_ids)) != len(normalized_filter_ids)
        or frozenset(normalized_filter_ids) != targets
        or len(selected_fields) != len(expected_select)
        or set(selected_fields) != expected_select
        or not 1 <= per_page <= 100
    ):
        raise IntegrityFailure("retained query does not exactly bind parser inputs")
    requested_cursors = query.get("cursor", [])
    wire_cursor = "*" if cursor_in is None else cursor_in
    if len(requested_cursors) != 1 or requested_cursors[0] != wire_cursor:
        raise IntegrityFailure("retained request cursor differs from parser cursor")

    try:
        envelope = _object(canonical_loads(payload), "response")
        response_meta = _object(envelope.get("meta"), "response.meta")
        results = _array(envelope.get("results"), "response.results")
        if "next_cursor" not in response_meta:
            raise IntegrityFailure("cursor response omits explicit continuation state")
        if len(results) > per_page:
            raise IntegrityFailure("OpenAlex page exceeds requested page size")
        next_cursor = response_meta["next_cursor"]
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not next_cursor
        ):
            raise IntegrityFailure("OpenAlex next_cursor is invalid")
        works = tuple(_parse_work(item, targets) for item in results)
        provider_ids = tuple(work.provider_id for work in works)
        if len(set(provider_ids)) != len(provider_ids):
            raise IntegrityFailure("OpenAlex page repeats a provider work id")
    except IntegrityFailure:
        raise
    except (TypeError, ValueError, KeyError) as error:
        raise IntegrityFailure("retained OpenAlex page is malformed") from error

    groups: dict[str, list[_Work]] = {}
    for work in works:
        identity = f"doi:{work.doi}" if work.doi else f"openalex:{work.provider_id}"
        groups.setdefault(identity, []).append(work)
    try:
        families = tuple(
            _family(
                tuple(groups[key]),
                response_hash=response_hash,
                meta=meta,
                targets=targets,
            )
            for key in sorted(groups)
        )
    except ValueError as error:
        raise IntegrityFailure("retained OpenAlex family is invalid") from error
    return ParsedOpenAlexPage(
        PaginationPage(
            page_index=page_index,
            request_hash=access.request_parameters_hash,
            response_hash=response_hash,
            cursor_in=cursor_in,
            cursor_out=next_cursor,
            returned_count=len(results),
            capture_started_at=access.capture_started_at,
            capture_completed_at=access.capture_completed_at,
            status="completed",
            failure=None,
        ),
        families,
    )
