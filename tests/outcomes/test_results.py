from dataclasses import replace

import pytest

from research_agent.contracts import sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.results import ResolutionResult
from research_agent.outcomes.targets import definitions, registry
from tests.outcomes.test_bounds import family
from tests.outcomes.test_resolution import AS_OF, META, scenario


def test_true_resolution_carries_positive_witnesses_and_no_completion_proof() -> None:
    paper, observation, stored = scenario(6, complete=False)
    label = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[0], paper, observation, AS_OF
    )
    result = ResolutionResult.from_label(label)
    assert result.status == "true"
    assert result.witness_ids
    assert result.completion_proof_hash is None
    assert result.lower_bound == 6
    assert result.upper_bound is None


def test_false_resolution_requires_a_completion_proof_and_no_witnesses() -> None:
    paper, observation, stored = scenario(4, complete=True)
    label = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[0], paper, observation, AS_OF
    )
    result = ResolutionResult.from_label(label)
    assert result.status == "false"
    assert not result.witness_ids
    assert result.completion_proof_hash is not None
    assert result.upper_bound is not None and result.upper_bound < 5


def test_missing_or_ambiguous_source_maps_unknown_to_unresolvable() -> None:
    paper, observation, stored = scenario(4, complete=False)
    label = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[0], paper, observation, AS_OF
    )
    assert label.state == "unknown"
    result = ResolutionResult.from_label(label)
    assert result.status == "unresolvable"
    assert not result.witness_ids
    assert result.completion_proof_hash is None
    assert result.reason == label.reason


def test_bare_boolean_or_unknown_status_fails_persistence() -> None:
    with pytest.raises(ContractValidationError):
        ResolutionResult(
            status=True,  # type: ignore[arg-type]
            definition_hash="a" * 64,
            observation_hash="b" * 64,
            witness_ids=(),
            completion_proof_hash=None,
            lower_bound=0,
            upper_bound=None,
            reason="incomplete_capture",
        )
    with pytest.raises(ContractValidationError):
        ResolutionResult(
            status="maybe",
            definition_hash="a" * 64,
            observation_hash="b" * 64,
            witness_ids=(),
            completion_proof_hash=None,
            lower_bound=0,
            upper_bound=None,
            reason="incomplete_capture",
        )


def test_a_true_status_without_witnesses_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="positive witnesses"):
        ResolutionResult(
            status="true",
            definition_hash="a" * 64,
            observation_hash="b" * 64,
            witness_ids=(),
            completion_proof_hash=None,
            lower_bound=5,
            upper_bound=None,
            reason="sufficient_positive_witnesses",
        )


def test_late_activity_bound_is_the_more_restrictive_of_both_windows() -> None:
    paper, observation, _ = scenario(4)
    records = tuple(
        family(index + 1, day) for index, day in enumerate((10, 20, 200, 300))
    )
    stored = {sha256_hex(record.to_canonical_json()): record for record in records}
    observation = replace(
        observation, citation_family_hashes=tuple(stored), input_hashes=tuple(stored)
    )
    label = Resolver(stored.__getitem__, META, registry=registry(META)).resolve_target(
        definitions(META)[1], paper, observation, AS_OF
    )
    result = ResolutionResult.from_label(label)
    assert result.status == "true"
    assert result.lower_bound == 1


def test_a_false_status_without_completion_proof_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="completion proof"):
        ResolutionResult(
            status="false",
            definition_hash="a" * 64,
            observation_hash="b" * 64,
            witness_ids=(),
            completion_proof_hash=None,
            lower_bound=0,
            upper_bound=0,
            reason="complete_negative_evidence",
        )
