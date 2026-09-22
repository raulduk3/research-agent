"""IN-17: a comparison job cannot obtain a lease with no dated primary-measure record.

These tests exercise `research_agent.evaluation.registrations` from the
comparison-job side (SDD-IN-17), delegating to the same registration
validator SDD-SR-18 uses (TDD-2.1.21) rather than a second implementation.
"""

import dataclasses

import pytest

from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.evaluation.registrations import (
    ComparisonEndpoint,
    ComparisonRegistration,
    admit_execution,
)

REGISTERED_AT = "2026-02-01T00:00:00.000000Z"
LEASE_REQUESTED_AT = "2026-02-05T00:00:00.000000Z"
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
REGISTRATION_ID = "33333333-3333-4333-8333-333333333333"


def registration(
    *, endpoints: tuple[ComparisonEndpoint, ...]
) -> ComparisonRegistration:
    return ComparisonRegistration(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        created_at=REGISTERED_AT,
        registration_id=REGISTRATION_ID,
        hypothesis="the candidate wins on paired_brier_improvement",
        population_hash="d" * 64,
        split_hash="e" * 64,
        subject_configuration_hash="f" * 64,
        endpoints=endpoints,
        pass_threshold=0.0,
        kill_threshold=0.05,
        minimum_effect=0.01,
        exclusions=(),
        sample_size=100,
        failure_handling="exclude",
        stop_rule_hash="0" * 64,
        provenance="runtime",
        registered_at=REGISTERED_AT,
        imported_at=None,
        signature_evidence_hash=None,
        exploratory_of=None,
    )


def obtain_lease(reg: ComparisonRegistration, *, requested_at: str) -> str:
    """Stand in for storage's lease grant: it must admit the registration first."""

    return admit_execution(reg, execution_at=requested_at)


def test_lease_is_refused_without_exactly_one_primary_measure() -> None:
    with pytest.raises(ContractValidationError):
        registration(
            endpoints=(
                ComparisonEndpoint("brier", "primary", "lower"),
                ComparisonEndpoint("coverage", "primary", "higher"),
            )
        )


def test_lease_is_refused_with_no_primary_measure_at_all() -> None:
    with pytest.raises(ContractValidationError):
        registration(endpoints=(ComparisonEndpoint("coverage", "secondary", "higher"),))


def test_lease_is_granted_only_after_registration_is_evidenced() -> None:
    reg = registration(endpoints=(ComparisonEndpoint("brier", "primary", "lower"),))
    assert obtain_lease(reg, requested_at=LEASE_REQUESTED_AT) == REGISTERED_AT


def test_lease_is_refused_for_a_backdated_unproven_registration() -> None:
    # An "imported" registration with no signature evidence is unproven: it
    # cannot be admitted no matter how early it claims to be.
    with pytest.raises(ContractValidationError):
        ComparisonRegistration(
            schema_version=1,
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            created_at=REGISTERED_AT,
            registration_id=REGISTRATION_ID,
            hypothesis="a pre-runtime comparison",
            population_hash="d" * 64,
            split_hash="e" * 64,
            subject_configuration_hash="f" * 64,
            endpoints=(ComparisonEndpoint("brier", "primary", "lower"),),
            pass_threshold=0.0,
            kill_threshold=0.05,
            minimum_effect=0.01,
            exclusions=(),
            sample_size=100,
            failure_handling="exclude",
            stop_rule_hash="0" * 64,
            provenance="imported",
            registered_at="2020-01-01T00:00:00.000000Z",
            imported_at=None,
            signature_evidence_hash=None,
            exploratory_of=None,
        )


def test_lease_is_refused_when_the_run_would_precede_registration() -> None:
    reg = registration(endpoints=(ComparisonEndpoint("brier", "primary", "lower"),))
    with pytest.raises(ContractValidationError):
        obtain_lease(reg, requested_at="2026-01-01T00:00:00.000000Z")


def test_a_consumed_registration_cannot_be_altered_in_place() -> None:
    reg = registration(endpoints=(ComparisonEndpoint("brier", "primary", "lower"),))
    obtain_lease(reg, requested_at=LEASE_REQUESTED_AT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        reg.sample_size = 999  # type: ignore[misc]
