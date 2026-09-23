from dataclasses import replace
from uuid import uuid4

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta, sha256_hex
from research_agent.contracts.learning import CitationObservation, PaginationPage
from research_agent.contracts.papers import ExternalIdentifier, PaperVersionRecord
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.targets import definitions, registry
from research_agent.outcomes.windows import instant, maturity_at
from research_agent.storage.errors import IntegrityFailure
from test_bounds import T0, family

AS_OF = "2022-01-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def scenario(count: int = 5, *, complete: bool = True):  # type: ignore[no-untyped-def]
    paper = PaperVersionRecord(
        1,
        (),
        META.producer_version,
        META.config_hash,
        AS_OF,
        str(uuid4()),
        str(uuid4()),
        (ExternalIdentifier("openalex", "W1000"),),
        True,
        T0,
        None,
        ("d" * 64,),
        ("e" * 64,),
        "Title",
        "Abstract",
        (),
        "A",
        "f" * 64,
        "metadata",
        "v1",
        3,
        ("cs.AI",),
        1,
    )
    records = tuple(family(index + 1, 10) for index in range(count))
    stored = {sha256_hex(record.to_canonical_json()): record for record in records}
    page = PaginationPage(
        0,
        "a" * 64,
        "b" * 64,
        None,
        None if complete else "next",
        count,
        AS_OF,
        AS_OF,
        "completed",
        None,
    )
    observation = CitationObservation(
        1,
        tuple(stored),
        META.producer_version,
        META.config_hash,
        AS_OF,
        paper.family_id,
        paper.version_id,
        T0,
        "automatic-citations-v1",
        sha256_hex(registry(META).to_canonical_json()),
        "openalex",
        "historical_reconstructed",
        "matched",
        ("W1000",),
        "A",
        "known",
        "d" * 64,
        AS_OF,
        AS_OF,
        maturity_at(T0),
        (instant(AS_OF) - instant(maturity_at(T0))).total_seconds(),
        (page,),
        complete,
        tuple(stored),
        None,
    )
    return paper, observation, stored


def test_reach_positive_can_survive_later_incomplete_capture() -> None:
    paper, observation, stored = scenario(6, complete=False)
    resolver = Resolver(stored.__getitem__, META, registry=registry(META))
    result = resolver.resolve_target(definitions(META)[0], paper, observation, AS_OF)
    assert result.state == "true"
    assert result.reason == "sufficient_positive_witnesses"
    assert result.counts.year_families.lower == 6
    assert result.counts.year_families.upper is None
    assert result.witness_family_ids == tuple(
        f"family-{index}" for index in range(1, 6)
    )
    assert result == resolver.resolve_target(
        definitions(META)[0], paper, observation, AS_OF
    )


def test_negative_requires_complete_capture() -> None:
    for complete, expected in ((True, "false"), (False, "unknown")):
        paper, observation, stored = scenario(4, complete=complete)
        result = Resolver(
            stored.__getitem__, META, registry=registry(META)
        ).resolve_target(definitions(META)[0], paper, observation, AS_OF)
        assert result.state == expected
        assert not result.witness_family_ids


def test_immature_and_mismatched_observations_do_not_read_families() -> None:
    paper, observation, _ = scenario()

    def refuse(_: str):  # type: ignore[no-untyped-def]
        raise AssertionError("inadmissible evidence must not be counted")

    resolver = Resolver(refuse, META, registry=registry(META))
    assert (
        resolver.resolve_target(definitions(META)[0], paper, observation, T0).reason
        == "immature"
    )
    assert (
        resolver.resolve_target(
            definitions(META)[0],
            paper,
            replace(observation, paper_family_id=str(uuid4())),
            AS_OF,
        ).reason
        == "invalid_source"
    )


def test_corrupt_retained_family_fails_closed() -> None:
    paper, observation, stored = scenario()
    key = next(iter(stored))
    stored[key] = replace(stored[key], canonical_family_id="tampered")
    with pytest.raises(IntegrityFailure, match="identity"):
        Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
            definitions(META)[0], paper, observation, AS_OF
        )


def test_breadth_missing_target_subfield_stays_unknown() -> None:
    paper, observation, stored = scenario()
    observation = replace(
        observation, target_subfield_state="missing", target_subfield_id=None
    )
    result = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[2], paper, observation, AS_OF
    )
    assert (result.state, result.reason) == ("unknown", "missing_target_subfield")


@pytest.mark.parametrize(
    ("days", "fields", "expected"),
    [
        ((), (), ("false", "false", "false")),
        ((10, 20, 30, 40, 50), ("A",) * 5, ("true", "false", "false")),
        ((10, 20, 200, 300), ("B", "C", "B", "C"), ("false", "true", "true")),
    ],
)
def test_protocol_conformance_rows(days, fields, expected) -> None:  # type: ignore[no-untyped-def]
    paper, observation, _ = scenario(len(days))
    records = tuple(
        family(index + 1, day, field)
        for index, (day, field) in enumerate(zip(days, fields, strict=True))
    )
    stored = {sha256_hex(record.to_canonical_json()): record for record in records}
    observation = replace(
        observation, citation_family_hashes=tuple(stored), input_hashes=tuple(stored)
    )
    resolver = Resolver(stored.__getitem__, META, registry=registry(META))
    labels = tuple(
        resolver.resolve_target(target, paper, observation, AS_OF)
        for target in definitions(META)
    )
    assert tuple(label.state for label in labels) == expected
    assert all(
        label.observation_hash == sha256_hex(observation.to_canonical_json())
        for label in labels
    )


def test_missing_taxonomy_masks_only_breadth() -> None:
    paper, observation, _ = scenario()
    records = tuple(
        family(index + 1, day) for index, day in enumerate((10, 20, 30, 200, 300))
    )
    stored = {sha256_hex(record.to_canonical_json()): record for record in records}
    observation = replace(
        observation,
        citation_family_hashes=tuple(stored),
        input_hashes=tuple(stored),
        target_subfield_id=None,
        target_subfield_state="missing",
    )
    resolver = Resolver(stored.__getitem__, META, registry=registry(META))
    assert tuple(
        resolver.resolve_target(target, paper, observation, AS_OF).state
        for target in definitions(META)
    ) == ("true", "true", "unknown")


def test_definition_must_match_exact_registry_identity() -> None:
    paper, observation, stored = scenario()
    altered = replace(definitions(META)[0], question="Different question wording")
    with pytest.raises(IntegrityFailure, match="registry"):
        Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
            altered, paper, observation, AS_OF
        )


def test_future_registry_and_post_observation_families_are_refused() -> None:
    paper, observation, stored = scenario()
    future_meta = replace(META, created_at="2023-01-01T00:00:00.000000Z")
    future_registry = registry(future_meta)
    future_observation = replace(
        observation,
        target_registry_hash=sha256_hex(future_registry.to_canonical_json()),
    )
    result = Resolver(
        stored.__getitem__, META, registry=future_registry
    ).resolve_target(future_registry.definitions[0], paper, future_observation, AS_OF)
    assert (result.state, result.reason) == ("unknown", "invalid_source")
    records = tuple(
        replace(record, created_at="2022-06-01T00:00:00.000000Z")
        for record in stored.values()
    )
    later_stored = {
        sha256_hex(record.to_canonical_json()): record for record in records
    }
    incoherent = replace(observation, citation_family_hashes=tuple(later_stored))
    with pytest.raises(IntegrityFailure):
        Resolver(
            later_stored.__getitem__, META, registry=registry(META)
        ).resolve_target(
            definitions(META)[0], paper, incoherent, "2022-07-01T00:00:00.000000Z"
        )


def test_complete_page_proof_retains_capture_order_not_hash_order() -> None:
    paper, observation, stored = scenario(0)
    first = replace(observation.pages[0], response_hash="f" * 64, cursor_out="next")
    second = replace(
        first, page_index=1, response_hash="a" * 64, cursor_in="next", cursor_out=None
    )
    observation = replace(observation, pages=(first, second))
    result = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[0], paper, observation, AS_OF
    )
    assert result.state == "false"
    assert result.completion_page_hashes == ("f" * 64, "a" * 64)


def test_empty_initial_failure_cannot_turn_into_zero_citations() -> None:
    paper, observation, stored = scenario(0)
    observation = replace(
        observation,
        pages=(),
        pagination_complete=False,
        failure="initial_request_failed",
    )
    result = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[0], paper, observation, AS_OF
    )
    assert (result.state, result.reason) == ("unknown", "initial_request_failed")
    assert result.counts.year_families.upper is None


def test_historical_and_prospective_paths_share_resolution_not_provenance() -> None:
    paper, historical, stored = scenario()
    capture = maturity_at(T0)
    page = replace(
        historical.pages[0], capture_started_at=capture, capture_completed_at=capture
    )
    prospective = replace(
        historical,
        kind="prospective_maturity",
        capture_started_at=capture,
        capture_completed_at=capture,
        acquisition_lag_seconds=0,
        pages=(page,),
    )
    resolver = Resolver(stored.__getitem__, META, registry=registry(META))
    target = definitions(META)[0]
    left = resolver.resolve_target(target, paper, historical, AS_OF)
    right = resolver.resolve_target(target, paper, prospective, AS_OF)
    assert (left.state, left.reason, left.counts, left.witness_family_ids) == (
        right.state,
        right.reason,
        right.counts,
        right.witness_family_ids,
    )
    assert left.observation_hash != right.observation_hash


def test_outside_capture_window_is_preserved_but_cannot_credit_positive() -> None:
    paper, observation, stored = scenario()
    outside = replace(
        observation, kind="prospective_maturity", failure="outside_capture_window"
    )
    result = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[0], paper, outside, AS_OF
    )
    assert (result.state, result.reason) == ("unknown", "outside_capture_window")
