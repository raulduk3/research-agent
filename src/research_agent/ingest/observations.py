"""Capture one dated citation observation from OpenAlex with pagination.

For one paper family, resolve its OpenAlex work by exact arXiv DOI, then
fully paginate its incoming citations by cursor. Every raw provider response
is handed to the caller's storage callback before this module trusts it
(SDD-EN-07); the returned ``CitationObservation`` is assembled only from
those stored pages. The same function serves historical reconstruction and
prospective maturity capture (SDD-FT-19): only the ``kind`` argument and the
caller's schedule differ, never a separate code path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from research_agent.contracts import (
    ProducerVersion,
    RecordMeta,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.learning import (
    CitationFamilyRecord,
    CitationObservation,
    PaginationPage,
)
from research_agent.contracts.papers import normalize_identifier
from research_agent.ingest.fetch import FetchedOpenAlexPage
from research_agent.ingest.openalex import parse_retained_works_page
from research_agent.ingest.pilot import BudgetExhausted, RateGate
from research_agent.outcomes.windows import (
    CAPTURE_ALLOWANCE_SECONDS,
    instant,
    maturity_at,
)
from research_agent.storage.errors import IntegrityFailure

_OPENALEX_ORIGIN = "https://openalex.org/"
_PAGE_FAILURES = frozenset({"timeout", "rejected", "transport", "invalid_payload"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class ObservationSources:
    """Injectable request functions; the caller binds them to real hosts."""

    match: Callable[[str, RecordMeta], FetchedOpenAlexPage]
    cites: Callable[[str, str | None, RecordMeta], FetchedOpenAlexPage]
    gate: RateGate
    store_response: Callable[[bytes], None]
    store_family: Callable[[CitationFamilyRecord], None]


def _page_failure(value: str | None) -> str:
    return value if value in _PAGE_FAILURES else "rejected"


def _openalex_id(raw: object) -> str:
    if not isinstance(raw, str):
        raise IntegrityFailure("OpenAlex match result id must be a string")
    return normalize_identifier("openalex", raw.removeprefix(_OPENALEX_ORIGIN))


def _match_result(payload: bytes) -> tuple[tuple[str, ...], str | None]:
    """The matched work ids and continuation cursor of a match response."""
    try:
        envelope = canonical_loads(payload)
        if not isinstance(envelope, dict):
            raise IntegrityFailure("OpenAlex match response must be an object")
        meta = envelope.get("meta")
        results = envelope.get("results")
        if (
            not isinstance(meta, dict)
            or "next_cursor" not in meta
            or not isinstance(results, list)
        ):
            raise IntegrityFailure("OpenAlex match response envelope is invalid")
        next_cursor = meta["next_cursor"]
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not next_cursor
        ):
            raise IntegrityFailure("OpenAlex match next_cursor is invalid")
        ids = tuple(
            _openalex_id(item.get("id") if isinstance(item, dict) else item)
            for item in results
        )
    except IntegrityFailure:
        raise
    except (TypeError, ValueError, KeyError) as error:
        raise IntegrityFailure("OpenAlex match response is malformed") from error
    return ids, next_cursor


def _outside_prospective_window(t0: str, started_at: str, completed_at: str) -> bool:
    maturity = instant(maturity_at(t0))
    return instant(started_at) < maturity or instant(
        completed_at
    ) > maturity + timedelta(seconds=CAPTURE_ALLOWANCE_SECONDS)


def capture_citation_observation(
    sources: ObservationSources,
    *,
    paper_family_id: str,
    original_version_id: str,
    arxiv_family_id: str,
    t0: str,
    kind: str,
    target_registry_hash: str,
    producer_version: ProducerVersion,
    config_hash: str,
    record_budget: int,
) -> CitationObservation:
    """Match one target family and fully paginate its incoming citations.

    Raises ``BudgetExhausted`` on a provider refusal (429), the same signal
    the acquisition pilot's 100000-record cap uses, so a caller resumes at
    the same cursor once the provider's budget resets rather than recording
    a false failure.
    """
    if record_budget < 1:
        raise ValueError("record budget must be positive")

    def _meta(response_hash: str) -> RecordMeta:
        return RecordMeta(1, (response_hash,), producer_version, config_hash, utc_now())

    def _observation(
        *,
        target_match_state: str,
        target_provider_ids: tuple[str, ...],
        capture_started_at: str,
        capture_completed_at: str,
        input_hashes: tuple[str, ...],
        pages: tuple[PaginationPage, ...],
        pagination_complete: bool,
        citation_family_hashes: tuple[str, ...],
        failure: str | None,
    ) -> CitationObservation:
        maturity = maturity_at(t0)
        if (
            kind == "prospective_maturity"
            and failure is None
            and _outside_prospective_window(
                t0, capture_started_at, capture_completed_at
            )
        ):
            failure = "outside_capture_window"
        return CitationObservation(
            schema_version=1,
            input_hashes=input_hashes,
            producer_version=producer_version,
            config_hash=config_hash,
            created_at=capture_completed_at,
            paper_family_id=paper_family_id,
            original_version_id=original_version_id,
            t0=t0,
            protocol="automatic-citations-v1",
            target_registry_hash=target_registry_hash,
            provider="openalex",
            kind=kind,
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
            pagination_complete=pagination_complete,
            citation_family_hashes=citation_family_hashes,
            failure=failure,
        )

    sources.gate.wait()
    fetched = sources.match(
        arxiv_family_id, RecordMeta(1, (), producer_version, config_hash, utc_now())
    )
    if fetched.access.http_status == 429:
        raise BudgetExhausted("OpenAlex refused further requests today")
    if fetched.payload is None:
        return _observation(
            target_match_state="unmatched",
            target_provider_ids=(),
            capture_started_at=fetched.access.capture_started_at,
            capture_completed_at=fetched.access.capture_completed_at,
            input_hashes=(),
            pages=(),
            pagination_complete=False,
            citation_family_hashes=(),
            failure="initial_request_failed",
        )

    sources.store_response(fetched.payload)
    match_response_hash = fetched.access.retained_payload_hash
    assert match_response_hash is not None
    match_ids, match_cursor_out = _match_result(fetched.payload)
    match_started_at = fetched.access.capture_started_at
    match_completed_at = fetched.access.capture_completed_at

    if match_cursor_out is not None or len(match_ids) != 1:
        target_match_state = (
            "ambiguous" if match_ids or match_cursor_out else "unmatched"
        )
        return _observation(
            target_match_state=target_match_state,
            target_provider_ids=(),
            capture_started_at=match_started_at,
            capture_completed_at=match_completed_at,
            input_hashes=(match_response_hash,),
            pages=(),
            pagination_complete=False,
            citation_family_hashes=(),
            failure="initial_request_failed",
        )

    target_provider_ids = match_ids
    pages: list[PaginationPage] = []
    citation_family_hashes: list[str] = []
    response_hashes = {match_response_hash}
    received = 0
    cursor: str | None = None
    while received < record_budget:
        sources.gate.wait()
        fetched = sources.cites(
            target_provider_ids[0],
            cursor,
            RecordMeta(1, (), producer_version, config_hash, utc_now()),
        )
        if fetched.access.http_status == 429:
            raise BudgetExhausted("OpenAlex refused further requests today")
        if fetched.payload is None:
            pages.append(
                PaginationPage(
                    page_index=len(pages),
                    request_hash=fetched.access.request_parameters_hash,
                    response_hash=fetched.access.retained_payload_hash,
                    cursor_in=cursor,
                    cursor_out=None,
                    returned_count=0,
                    capture_started_at=fetched.access.capture_started_at,
                    capture_completed_at=fetched.access.capture_completed_at,
                    status="failed",
                    failure=_page_failure(fetched.access.failure),
                )
            )
            break
        sources.store_response(fetched.payload)
        response_hash = fetched.access.retained_payload_hash
        assert response_hash is not None
        response_hashes.add(response_hash)
        parsed = parse_retained_works_page(
            fetched.access,
            fetched.payload,
            page_index=len(pages),
            cursor_in=cursor,
            target_provider_ids=target_provider_ids,
            meta=_meta(response_hash),
        )
        pages.append(parsed.page)
        for family in parsed.families:
            family_hash = sha256_hex(family.to_canonical_json())
            if family_hash not in citation_family_hashes:
                citation_family_hashes.append(family_hash)
                sources.store_family(family)
        received += parsed.page.returned_count
        if parsed.page.cursor_out is None:
            break
        cursor = parsed.page.cursor_out

    pagination_complete = pages[-1].status != "failed" and pages[-1].cursor_out is None
    return _observation(
        target_match_state="matched",
        target_provider_ids=target_provider_ids,
        capture_started_at=match_started_at,
        capture_completed_at=pages[-1].capture_completed_at,
        input_hashes=tuple(sorted(response_hashes)),
        pages=tuple(pages),
        pagination_complete=pagination_complete,
        citation_family_hashes=tuple(citation_family_hashes),
        failure=None,
    )
