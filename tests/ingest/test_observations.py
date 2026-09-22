from __future__ import annotations

from urllib.parse import urlencode
from uuid import uuid4

import pytest

from research_agent.contracts import (
    ProducerVersion,
    RecordMeta,
    canonical_json,
    sha256_hex,
)
from research_agent.contracts.learning import CitationObservation
from research_agent.contracts.papers import SourceAccess
from research_agent.ingest.fetch import FetchedOpenAlexPage
from research_agent.ingest.observations import (
    ObservationSources,
    capture_citation_observation,
)
from research_agent.ingest.pilot import BudgetExhausted, RateGate

T0 = "2020-01-01T00:00:00.000000Z"
MATURITY = "2021-03-31T00:00:00.000000Z"
PRODUCER = ProducerVersion("1" * 64, "2" * 40, 1)
CONFIG_HASH = "3" * 64
TARGET_REGISTRY_HASH = "4" * 64
ARXIV_ID = "2001.00001"
_FIELDS = "id,ids,doi,publication_date,primary_topic,referenced_works"


def _access(
    *,
    url: str,
    payload: bytes | None,
    started: str = MATURITY,
    completed: str = MATURITY,
    status: int | None = 200,
    failure: str | None = None,
) -> SourceAccess:
    return SourceAccess(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash=CONFIG_HASH,
        created_at=completed,
        source="openalex",
        requested_url=url,
        request_parameters_hash=sha256_hex(url.encode()),
        adapter_version="openalex-anonymous-citations-v1",
        capture_started_at=started,
        capture_completed_at=completed,
        http_status=status,
        retained_payload_hash=None if payload is None else sha256_hex(payload),
        retention_policy_hash="5" * 64,
        license_expression="CC0-1.0",
        permission_evidence_hash="6" * 64,
        failure=failure,
    )


def _fetched(access: SourceAccess, payload: bytes | None) -> FetchedOpenAlexPage:
    return FetchedOpenAlexPage(access, payload, b"{}", (), 0.01)


def _match_url() -> str:
    return "https://api.openalex.org/works?" + urlencode(
        {
            "filter": f"doi:10.48550/arxiv.{ARXIV_ID}",
            "select": _FIELDS,
            "per_page": "2",
            "cursor": "*",
        }
    )


def _cites_url(target: str, cursor: str | None) -> str:
    return "https://api.openalex.org/works?" + urlencode(
        {
            "filter": f"cites:{target}",
            "select": _FIELDS,
            "per_page": "100",
            "cursor": "*" if cursor is None else cursor,
        }
    )


def _match_payload(ids: tuple[str, ...], *, next_cursor: str | None = None) -> bytes:
    return canonical_json(
        {
            "meta": {"next_cursor": next_cursor},
            "results": [
                {
                    "id": f"https://openalex.org/{value}",
                    "ids": {"openalex": f"https://openalex.org/{value}"},
                    "doi": None,
                    "publication_date": None,
                    "primary_topic": None,
                    "referenced_works": [],
                }
                for value in ids
            ],
        }
    )


def _work(work_id: str, *, ref: str, subfield: str = "1702") -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{work_id}",
        "ids": {"openalex": f"https://openalex.org/{work_id}"},
        "doi": None,
        "publication_date": "2021-01-01",
        "primary_topic": {
            "subfield": {"id": f"https://openalex.org/subfields/{subfield}"}
        },
        "referenced_works": [f"https://openalex.org/{ref}"],
    }


def _cites_payload(
    works: tuple[dict[str, object], ...], *, next_cursor: str | None = None
) -> bytes:
    return canonical_json(
        {"meta": {"next_cursor": next_cursor}, "results": list(works)}
    )


def _sources(
    match: object, cites: object, *, gate: RateGate | None = None
) -> tuple[ObservationSources, list[bytes], list[object]]:
    responses: list[bytes] = []
    families: list[object] = []
    sources = ObservationSources(
        match,  # type: ignore[arg-type]
        cites,  # type: ignore[arg-type]
        gate or RateGate(0.001),
        responses.append,
        families.append,
    )
    return sources, responses, families


def _unexpected_cites(
    work: str, cursor: str | None, meta: RecordMeta
) -> FetchedOpenAlexPage:
    raise AssertionError("citation pagination must not run without one matched target")


def _capture(
    sources: ObservationSources,
    *,
    kind: str = "historical_reconstructed",
    t0: str = T0,
    record_budget: int = 100,
) -> CitationObservation:
    return capture_citation_observation(
        sources,
        paper_family_id=str(uuid4()),
        original_version_id=str(uuid4()),
        arxiv_family_id=ARXIV_ID,
        t0=t0,
        kind=kind,
        target_registry_hash=TARGET_REGISTRY_HASH,
        producer_version=PRODUCER,
        config_hash=CONFIG_HASH,
        record_budget=record_budget,
    )


def test_matched_target_paginates_across_cursors_and_stores_every_page() -> None:
    match_bytes = _match_payload(("W500",))
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)

    page1_bytes = _cites_payload((_work("W10", ref="W500"),), next_cursor="cursor-2")
    page1 = _fetched(
        _access(url=_cites_url("W500", None), payload=page1_bytes), page1_bytes
    )
    page2_bytes = _cites_payload((_work("W20", ref="W500"),), next_cursor=None)
    page2 = _fetched(
        _access(url=_cites_url("W500", "cursor-2"), payload=page2_bytes), page2_bytes
    )
    responses_by_cursor = iter([page1, page2])

    def cites(work: str, cursor: str | None, meta: RecordMeta) -> FetchedOpenAlexPage:
        assert work == "W500"
        return next(responses_by_cursor)

    sources, responses, families = _sources(lambda arxiv, meta: match, cites)

    observation = _capture(sources)

    assert observation.target_match_state == "matched"
    assert observation.target_provider_ids == ("W500",)
    assert observation.pagination_complete is True
    assert [page.status for page in observation.pages] == ["completed"] * 2
    assert observation.pages[0].returned_count == 1
    assert len(observation.citation_family_hashes) == 2
    assert responses == [match_bytes, page1_bytes, page2_bytes]
    assert len(families) == 2
    assert observation.failure is None
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_zero_match_candidates_are_recorded_as_unmatched_without_paginating() -> None:
    match_bytes = _match_payload(())
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)
    sources, _, families = _sources(lambda a, m: match, _unexpected_cites)

    observation = _capture(sources)

    assert observation.target_match_state == "unmatched"
    assert observation.target_provider_ids == ()
    assert len(observation.pages) == 0
    assert observation.pagination_complete is False
    assert observation.failure == "initial_request_failed"
    assert observation.citation_family_hashes == ()
    assert families == []
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_multiple_match_candidates_are_recorded_as_ambiguous_without_paginating() -> (
    None
):
    match_bytes = _match_payload(("W10", "W20"))
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)
    sources, _, _ = _sources(lambda a, m: match, _unexpected_cites)

    observation = _capture(sources)

    assert observation.target_match_state == "ambiguous"
    assert observation.target_provider_ids == ()
    assert len(observation.pages) == 0
    assert observation.pagination_complete is False
    assert observation.failure == "initial_request_failed"
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_initial_match_failure_is_recorded_as_incomplete_never_truncated() -> None:
    access = _access(url=_match_url(), payload=None, status=None, failure="timeout")
    match = _fetched(access, None)
    sources, responses, families = _sources(lambda a, m: match, _unexpected_cites)

    observation = _capture(sources)

    assert observation.pages == ()
    assert observation.pagination_complete is False
    assert observation.failure == "initial_request_failed"
    assert observation.citation_family_hashes == ()
    assert responses == []
    assert families == []
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_a_429_on_the_match_request_raises_the_reused_budget_signal() -> None:
    access = _access(url=_match_url(), payload=None, status=429, failure="rejected")
    match = _fetched(access, None)
    sources, _, _ = _sources(lambda a, m: match, _unexpected_cites)

    with pytest.raises(BudgetExhausted):
        _capture(sources)


def test_a_429_mid_pagination_raises_the_reused_budget_signal() -> None:
    match_bytes = _match_payload(("W500",))
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)
    page1_bytes = _cites_payload((_work("W10", ref="W500"),), next_cursor="cursor-2")
    page1 = _fetched(
        _access(url=_cites_url("W500", None), payload=page1_bytes), page1_bytes
    )
    refusal = _fetched(
        _access(
            url=_cites_url("W500", "cursor-2"),
            payload=None,
            status=429,
            failure="rejected",
        ),
        None,
    )
    calls = iter([page1, refusal])

    def cites(work: str, cursor: str | None, meta: RecordMeta) -> FetchedOpenAlexPage:
        return next(calls)

    sources, _, _ = _sources(lambda a, m: match, cites)

    with pytest.raises(BudgetExhausted):
        _capture(sources)


def test_record_budget_caps_pagination_and_marks_it_incomplete_not_truncated() -> None:
    match_bytes = _match_payload(("W500",))
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)
    page1_bytes = _cites_payload((_work("W10", ref="W500"),), next_cursor="cursor-2")
    page1 = _fetched(
        _access(url=_cites_url("W500", None), payload=page1_bytes), page1_bytes
    )

    calls = iter([page1])

    def cites(work: str, cursor: str | None, meta: RecordMeta) -> FetchedOpenAlexPage:
        return next(calls)

    sources, _, families = _sources(lambda a, m: match, cites)

    observation = _capture(sources, record_budget=1)

    assert observation.pagination_complete is False
    assert observation.failure is None
    assert len(observation.pages) == 1
    assert len(observation.citation_family_hashes) == 1
    assert len(families) == 1
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_a_failed_continuation_page_ends_pagination_without_a_top_level_failure() -> (
    None
):
    match_bytes = _match_payload(("W500",))
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)
    page1_bytes = _cites_payload((_work("W10", ref="W500"),), next_cursor="cursor-2")
    page1 = _fetched(
        _access(url=_cites_url("W500", None), payload=page1_bytes), page1_bytes
    )
    failed = _fetched(
        _access(url=_cites_url("W500", "cursor-2"), payload=None, failure="transport"),
        None,
    )
    calls = iter([page1, failed])

    def cites(work: str, cursor: str | None, meta: RecordMeta) -> FetchedOpenAlexPage:
        return next(calls)

    sources, _, _ = _sources(lambda a, m: match, cites)

    observation = _capture(sources)

    assert observation.pages[-1].status == "failed"
    assert observation.pages[-1].failure == "transport"
    assert observation.pagination_complete is False
    assert observation.failure is None
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def _matched_single_page_sources(*, started: str, completed: str) -> ObservationSources:
    match_bytes = _match_payload(("W500",))
    match = _fetched(
        _access(
            url=_match_url(), payload=match_bytes, started=started, completed=started
        ),
        match_bytes,
    )
    page_bytes = _cites_payload((_work("W10", ref="W500"),), next_cursor=None)
    page = _fetched(
        _access(
            url=_cites_url("W500", None),
            payload=page_bytes,
            started=started,
            completed=completed,
        ),
        page_bytes,
    )
    sources, _, _ = _sources(lambda a, m: match, lambda w, c, m: page)
    return sources


def test_prospective_capture_outside_its_window_is_recorded_as_an_explicit_failure() -> (
    None
):
    late = "2021-04-02T00:00:00.000000Z"
    sources = _matched_single_page_sources(started=late, completed=late)

    observation = _capture(sources, kind="prospective_maturity")

    assert observation.target_match_state == "matched"
    assert observation.kind == "prospective_maturity"
    assert observation.failure == "outside_capture_window"
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_historical_capture_outside_the_prospective_window_carries_no_failure() -> None:
    late = "2021-04-02T00:00:00.000000Z"
    sources = _matched_single_page_sources(started=late, completed=late)

    observation = _capture(sources, kind="historical_reconstructed")

    assert observation.target_match_state == "matched"
    assert observation.failure is None
    assert CitationObservation.from_json(observation.to_canonical_json()) == observation


def test_the_reused_rate_gate_spaces_every_request_including_the_match_call() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    gate = RateGate(0.2, clock=lambda: now[0], sleep=sleep)
    match_bytes = _match_payload(("W500",))
    match = _fetched(_access(url=_match_url(), payload=match_bytes), match_bytes)
    page_bytes = _cites_payload((_work("W10", ref="W500"),), next_cursor=None)
    page = _fetched(
        _access(url=_cites_url("W500", None), payload=page_bytes), page_bytes
    )

    sources, _, _ = _sources(lambda a, m: match, lambda w, c, m: page, gate=gate)

    _capture(sources)

    assert slept == [pytest.approx(0.2), pytest.approx(0.2)]
