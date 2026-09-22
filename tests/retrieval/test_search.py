from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.passages import SourceLocator
from research_agent.retrieval.passages import (
    SearchCandidate,
    attach_evidence,
    search_passages,
)

FAMILY_A = "123e4567-e89b-42d3-a456-426614174000"
VERSION_A = "123e4567-e89b-42d3-a456-426614174001"
FAMILY_B = "123e4567-e89b-42d3-a456-426614174002"
VERSION_B = "123e4567-e89b-42d3-a456-426614174003"
LOCATOR = SourceLocator("a" * 64, "pdf", 1, None, None, None)


def _candidate(
    *,
    family: str,
    version: str,
    section_order: int,
    char_start: int,
    char_end: int,
    vector: tuple[float, ...],
    text: str = "some passage text",
) -> SearchCandidate:
    return SearchCandidate(
        paper_family_id=family,
        paper_version_id=version,
        section_order=section_order,
        section_path=("Body",),
        char_start=char_start,
        char_end_exclusive=char_end,
        text=text,
        text_hash="b" * 64,
        source_locators=(LOCATOR,),
        vector=vector,
    )


def test_search_passages_ranks_by_descending_cosine_similarity() -> None:
    strong = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(1.0, 0.0),
    )
    weak = _candidate(
        family=FAMILY_B,
        version=VERSION_B,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(0.1, 0.99),
    )
    results = search_passages(
        candidates=[weak, strong],
        query_vector=(1.0, 0.0),
        paper_filter=None,
        limit=5,
    )
    assert [result.candidate.paper_family_id for result in results] == [
        FAMILY_A,
        FAMILY_B,
    ]
    assert results[0].similarity > results[1].similarity


def test_search_passages_breaks_ties_by_family_version_section_and_offset() -> None:
    first = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(1.0, 0.0),
    )
    second = _candidate(
        family=FAMILY_B,
        version=VERSION_B,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(1.0, 0.0),
    )
    results = search_passages(
        candidates=[second, first],
        query_vector=(1.0, 0.0),
        paper_filter=None,
        limit=5,
    )
    assert [result.candidate.paper_family_id for result in results] == [
        FAMILY_A,
        FAMILY_B,
    ]


def test_search_passages_without_filter_returns_at_most_two_per_family() -> None:
    candidates = [
        _candidate(
            family=FAMILY_A,
            version=VERSION_A,
            section_order=index,
            char_start=index * 20,
            char_end=index * 20 + 10,
            vector=(1.0, 0.0),
        )
        for index in range(3)
    ]
    results = search_passages(
        candidates=candidates, query_vector=(1.0, 0.0), paper_filter=None, limit=5
    )
    assert len(results) == 2


def test_search_passages_without_filter_limit_counts_distinct_families() -> None:
    candidates = []
    for index, family, version in (
        (0, FAMILY_A, VERSION_A),
        (1, FAMILY_B, VERSION_B),
    ):
        candidates.append(
            _candidate(
                family=family,
                version=version,
                section_order=0,
                char_start=0,
                char_end=10,
                vector=(1.0, 0.0),
            )
        )
    results = search_passages(
        candidates=candidates, query_vector=(1.0, 0.0), paper_filter=None, limit=1
    )
    assert len(results) == 1
    assert results[0].candidate.paper_family_id == FAMILY_A


def test_search_passages_with_filter_limit_counts_passages_from_that_paper() -> None:
    candidates = [
        _candidate(
            family=FAMILY_A,
            version=VERSION_A,
            section_order=index,
            char_start=index * 20,
            char_end=index * 20 + 10,
            vector=(1.0, 0.0),
        )
        for index in range(3)
    ]
    results = search_passages(
        candidates=candidates, query_vector=(1.0, 0.0), paper_filter=FAMILY_A, limit=3
    )
    assert len(results) == 3
    assert all(result.candidate.paper_family_id == FAMILY_A for result in results)


def test_search_passages_skips_overlapping_spans_in_the_same_version() -> None:
    first = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=0,
        char_end=20,
        vector=(1.0, 0.0),
    )
    overlapping = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=10,
        char_end=30,
        vector=(0.99, 0.1),
    )
    results = search_passages(
        candidates=[first, overlapping],
        query_vector=(1.0, 0.0),
        paper_filter=FAMILY_A,
        limit=5,
    )
    assert len(results) == 1
    assert results[0].candidate.char_start == 0


def test_search_passages_returns_fewer_results_when_fewer_are_eligible() -> None:
    only = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(1.0, 0.0),
    )
    results = search_passages(
        candidates=[only], query_vector=(1.0, 0.0), paper_filter=None, limit=5
    )
    assert len(results) == 1


def test_search_passages_rejects_a_zero_vector_and_out_of_range_limit() -> None:
    candidate = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(0.0, 0.0),
    )
    with pytest.raises(ContractValidationError):
        search_passages(
            candidates=[candidate], query_vector=(1.0, 0.0), paper_filter=None, limit=5
        )
    with pytest.raises(ContractValidationError):
        search_passages(
            candidates=[], query_vector=(1.0, 0.0), paper_filter=None, limit=6
        )


def test_attach_evidence_preserves_the_base_card_hash_across_distinct_queries() -> None:
    candidate = _candidate(
        family=FAMILY_A,
        version=VERSION_A,
        section_order=0,
        char_start=0,
        char_end=10,
        vector=(1.0, 0.0),
        text="exact matched text",
    )
    results = search_passages(
        candidates=[candidate], query_vector=(1.0, 0.0), paper_filter=None, limit=5
    )
    base_card_hash = "d" * 64
    first_card, first_envelopes = attach_evidence(
        base_card_hash=base_card_hash,
        query_hash="e" * 64,
        snapshot_id="f" * 64,
        mode="passages",
        manifest_ids=("a" * 64,),
        coverage_by_version={VERSION_A: "complete"},
        results=results,
    )
    second_card, second_envelopes = attach_evidence(
        base_card_hash=base_card_hash,
        query_hash="1" * 64,
        snapshot_id="f" * 64,
        mode="passages",
        manifest_ids=("a" * 64,),
        coverage_by_version={VERSION_A: "complete"},
        results=results,
    )
    assert first_card == second_card == base_card_hash
    assert first_envelopes != second_envelopes
    assert first_envelopes[0].text == "exact matched text"
    assert first_envelopes[0].coverage == "complete"
    assert first_envelopes[0].source_locators == (LOCATOR,)
