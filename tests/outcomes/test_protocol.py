from dataclasses import replace
from datetime import timedelta

from research_agent.contracts import sha256_hex
from research_agent.outcomes.protocol import ObservationProtocol
from research_agent.outcomes.targets import registry
from research_agent.outcomes.windows import instant, maturity_at
from tests.outcomes.test_resolution import AS_OF, META, scenario


def test_protocol_binds_the_exact_registry_hash_and_fixed_policy() -> None:
    protocol = ObservationProtocol.from_registry(registry(META))
    assert protocol.protocol == "automatic-citations-v1"
    assert protocol.source == "openalex"
    assert protocol.family_policy == "exact_identifiers_explicit_versions_v1"
    assert protocol.taxonomy_policy == "captured_primary_subfield"
    assert protocol.registry_hash == sha256_hex(registry(META).to_canonical_json())


def test_capture_deadline_is_maturity_plus_the_prospective_allowance() -> None:
    paper, observation, _ = scenario()
    protocol = ObservationProtocol.from_registry(registry(META))
    t0 = paper.first_public_at
    deadline = protocol.capture_deadline(t0)
    assert instant(deadline) - instant(maturity_at(t0)) == timedelta(
        seconds=protocol.prospective_capture_allowance_seconds
    )


def test_admit_rejects_an_observation_bound_to_a_different_registry() -> None:
    paper, observation, _ = scenario()
    protocol = ObservationProtocol.from_registry(registry(META))
    assert protocol.admit(observation, as_of=AS_OF) is None
    assert (
        protocol.admit(replace(observation, target_registry_hash="a" * 64), as_of=AS_OF)
        == "invalid_source"
    )


def test_admit_defers_capture_timing_to_windows() -> None:
    paper, observation, _ = scenario()
    protocol = ObservationProtocol.from_registry(registry(META))
    assert protocol.admit(observation, as_of=paper.first_public_at) == "immature"


def test_admit_is_kind_invariant_for_a_wellformed_observation() -> None:
    paper, historical, _ = scenario()
    capture = maturity_at(paper.first_public_at)
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
    protocol = ObservationProtocol.from_registry(registry(META))
    assert protocol.admit(historical, as_of=AS_OF) is None
    assert protocol.admit(prospective, as_of=AS_OF) is None
