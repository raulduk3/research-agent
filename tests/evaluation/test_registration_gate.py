import dataclasses

import pytest

from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.evaluation.registrations import (
    ComparisonEndpoint,
    ComparisonRegistration,
    admit_execution,
    derive_exploratory_registration,
    registration_identity_hash,
)

CREATED_AT = "2026-01-01T00:00:00.000000Z"
REGISTERED_AT = "2026-01-02T00:00:00.000000Z"
IMPORTED_AT = "2026-01-05T00:00:00.000000Z"
EXECUTION_AT = "2026-01-10T00:00:00.000000Z"
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
REGISTRATION_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"


def registration(
    *,
    registration_id: str = REGISTRATION_ID,
    endpoints: tuple[ComparisonEndpoint, ...] | None = None,
    pass_threshold: float = 0.05,
    kill_threshold: float = 0.0,
    provenance: str = "runtime",
    registered_at: str = REGISTERED_AT,
    imported_at: str | None = None,
    signature_evidence_hash: str | None = None,
    exploratory_of: str | None = None,
) -> ComparisonRegistration:
    if endpoints is None:
        endpoints = (ComparisonEndpoint("skill_gain", "primary", "higher"),)
    return ComparisonRegistration(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        created_at=CREATED_AT,
        registration_id=registration_id,
        hypothesis="the candidate configuration beats the incumbent on skill_gain",
        population_hash="d" * 64,
        split_hash="e" * 64,
        subject_configuration_hash="f" * 64,
        endpoints=endpoints,
        pass_threshold=pass_threshold,
        kill_threshold=kill_threshold,
        minimum_effect=0.01,
        exclusions=("timed_out",),
        sample_size=200,
        failure_handling="exclude",
        stop_rule_hash="0" * 64,
        provenance=provenance,
        registered_at=registered_at,
        imported_at=imported_at,
        signature_evidence_hash=signature_evidence_hash,
        exploratory_of=exploratory_of,
    )


def test_registration_round_trips_through_canonical_json() -> None:
    original = registration()
    assert original == ComparisonRegistration.from_json(original.to_canonical_json())


def test_registration_is_frozen_and_cannot_be_altered_in_place() -> None:
    live = registration()
    with pytest.raises(dataclasses.FrozenInstanceError):
        live.hypothesis = "a different hypothesis"  # type: ignore[misc]


def test_modified_content_under_the_same_registration_id_changes_its_hash() -> None:
    original = registration()
    modified = registration(pass_threshold=0.5)
    assert original.registration_id == modified.registration_id
    assert registration_identity_hash(original) != registration_identity_hash(modified)


def test_registration_rejects_two_primary_endpoints() -> None:
    with pytest.raises(ContractValidationError):
        registration(
            endpoints=(
                ComparisonEndpoint("skill_gain", "primary", "higher"),
                ComparisonEndpoint("latency_seconds", "primary", "lower"),
            )
        )


def test_registration_rejects_no_primary_endpoint() -> None:
    with pytest.raises(ContractValidationError):
        registration(
            endpoints=(ComparisonEndpoint("skill_gain", "secondary", "higher"),)
        )


def test_registration_rejects_a_pass_threshold_below_kill_for_higher_direction() -> (
    None
):
    with pytest.raises(ContractValidationError):
        registration(pass_threshold=0.0, kill_threshold=0.5)


def test_admit_execution_accepts_a_runtime_registration_before_its_execution() -> None:
    live = registration(registered_at=REGISTERED_AT)
    assert admit_execution(live, execution_at=EXECUTION_AT) == REGISTERED_AT


def test_admit_execution_rejects_execution_before_registration() -> None:
    live = registration(registered_at=REGISTERED_AT)
    with pytest.raises(ContractValidationError):
        admit_execution(live, execution_at=CREATED_AT)


def test_admit_execution_relies_on_import_time_not_the_original_date() -> None:
    imported = registration(
        provenance="imported",
        registered_at=CREATED_AT,
        imported_at=IMPORTED_AT,
        signature_evidence_hash="1" * 64,
    )
    # The original date long precedes IMPORTED_AT; execution only relies on
    # the later, independently-evidenced import into this system.
    assert admit_execution(imported, execution_at=EXECUTION_AT) == IMPORTED_AT
    with pytest.raises(ContractValidationError):
        admit_execution(imported, execution_at=CREATED_AT)


def test_imported_registration_rejects_a_backdated_import() -> None:
    with pytest.raises(ContractValidationError):
        registration(
            provenance="imported",
            registered_at=IMPORTED_AT,
            imported_at=CREATED_AT,
            signature_evidence_hash="1" * 64,
        )


def test_imported_registration_requires_signature_evidence() -> None:
    with pytest.raises(ContractValidationError):
        registration(
            provenance="imported",
            registered_at=CREATED_AT,
            imported_at=IMPORTED_AT,
            signature_evidence_hash=None,
        )


def test_runtime_registration_carries_no_import_provenance() -> None:
    with pytest.raises(ContractValidationError):
        registration(provenance="runtime", imported_at=IMPORTED_AT)


def test_derive_exploratory_registration_leaves_the_original_untouched() -> None:
    original = registration()
    exploratory = derive_exploratory_registration(
        original,
        new_registration_id=OTHER_ID,
        pass_threshold=0.2,
    )
    assert original.pass_threshold == 0.05
    assert exploratory.pass_threshold == 0.2
    assert exploratory.registration_id == OTHER_ID
    assert exploratory.exploratory_of == original.registration_id
    assert original.to_canonical_json() == registration().to_canonical_json()


def test_derive_exploratory_registration_requires_a_new_identity() -> None:
    original = registration()
    with pytest.raises(ContractValidationError):
        derive_exploratory_registration(original, new_registration_id=REGISTRATION_ID)
