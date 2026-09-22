from uuid import uuid4

import pytest

from research_agent.contracts import ContractValidationError, ProducerVersion
from research_agent.evaluation.accuracy import (
    CADENCE_BY_COMPONENT,
    COMPONENT_IDS,
    AccuracyEntry,
    AccuracyOutcome,
    AccuracyRegistry,
    compute_accuracy_report,
)

CREATED_AT = "2026-01-01T00:00:00.000000Z"
LAST_REPORT = "2026-01-08T00:00:00.000000Z"
NEXT_DUE_AT = "2026-01-15T00:00:00.000000Z"
COMPUTED_AT = "2026-01-09T00:00:00.000000Z"
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)


def entry(component_id: str) -> AccuracyEntry:
    unqualified = component_id == "jev"
    return AccuracyEntry(
        component_id=component_id,
        component_version="1",
        metric_definition_hash=None if unqualified else "d" * 64,
        reference_manifest=None if unqualified else "e" * 64,
        denominator_policy="eligible_known_only",
        cadence=CADENCE_BY_COMPONENT[component_id],
        last_report=LAST_REPORT,
        next_due_at=NEXT_DUE_AT,
    )


def full_registry(entries: tuple[AccuracyEntry, ...] | None = None) -> AccuracyRegistry:
    return AccuracyRegistry(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        created_at=CREATED_AT,
        entries=entries
        if entries is not None
        else tuple(entry(c) for c in COMPONENT_IDS),
    )


def outcome(
    *, eligible: bool = True, known: bool = True, correct: bool | None = True
) -> AccuracyOutcome:
    return AccuracyOutcome(
        outcome_id=str(uuid4()),
        eligible=eligible,
        ineligible_reason=None if eligible else "late",
        known=known if eligible else False,
        correct=correct if (eligible and known) else None,
    )


def test_full_registry_round_trips_through_canonical_json() -> None:
    registry = full_registry()
    assert registry == AccuracyRegistry.from_json(registry.to_canonical_json())


def test_registry_refuses_activation_with_a_missing_component() -> None:
    incomplete = tuple(entry(c) for c in COMPONENT_IDS if c != "resolver")
    with pytest.raises(ContractValidationError):
        full_registry(incomplete)


def test_registry_refuses_activation_with_components_out_of_order() -> None:
    reordered = tuple(entry(c) for c in reversed(COMPONENT_IDS))
    with pytest.raises(ContractValidationError):
        full_registry(reordered)


def test_registry_refuses_a_duplicated_component() -> None:
    entries = tuple(entry(c) for c in COMPONENT_IDS[:-1]) + (entry(COMPONENT_IDS[-2]),)
    with pytest.raises(ContractValidationError):
        full_registry(entries)


def test_entry_refuses_an_unregistered_component() -> None:
    with pytest.raises(ContractValidationError):
        AccuracyEntry(
            component_id="paper_card_summarizer",
            component_version="1",
            metric_definition_hash="d" * 64,
            reference_manifest="e" * 64,
            denominator_policy="eligible_known_only",
            cadence="weekly",
            last_report=None,
            next_due_at=NEXT_DUE_AT,
        )


def test_entry_refuses_a_cadence_that_disagrees_with_the_launch_profile() -> None:
    with pytest.raises(ContractValidationError):
        AccuracyEntry(
            component_id="resolver",
            component_version="1",
            metric_definition_hash="d" * 64,
            reference_manifest="e" * 64,
            denominator_policy="eligible_known_only",
            cadence="weekly",
            last_report=None,
            next_due_at=NEXT_DUE_AT,
        )


def test_jev_entry_carries_no_accuracy_measure_or_reference() -> None:
    with pytest.raises(ContractValidationError):
        AccuracyEntry(
            component_id="jev",
            component_version="1",
            metric_definition_hash="d" * 64,
            reference_manifest=None,
            denominator_policy="eligible_known_only",
            cadence=CADENCE_BY_COMPONENT["jev"],
            last_report=None,
            next_due_at=NEXT_DUE_AT,
        )


def test_qualified_entry_requires_its_accuracy_measure_and_reference() -> None:
    with pytest.raises(ContractValidationError):
        AccuracyEntry(
            component_id="resolver",
            component_version="1",
            metric_definition_hash=None,
            reference_manifest=None,
            denominator_policy="eligible_known_only",
            cadence=CADENCE_BY_COMPONENT["resolver"],
            last_report=None,
            next_due_at=NEXT_DUE_AT,
        )


def test_compute_accuracy_report_counts_only_eligible_known_outcomes() -> None:
    outcomes = (
        outcome(correct=True),
        outcome(correct=True),
        outcome(correct=False),
        outcome(known=False),
        outcome(eligible=False),
    )
    report = compute_accuracy_report(
        entry("resolver"),
        outcomes,
        source_watermark=7,
        reference_watermark=3,
        computed_at=COMPUTED_AT,
    )
    assert report.intended_count == 5
    assert report.excluded_count == 1
    assert report.eligible_count == 4
    assert report.known_count == 3
    assert report.unknown_count == 1
    assert report.accuracy == pytest.approx(2 / 3)
    assert report.disposition == "available"


def test_compute_accuracy_report_is_insufficient_reference_with_no_known_outcomes() -> (
    None
):
    outcomes = (outcome(known=False), outcome(eligible=False))
    report = compute_accuracy_report(
        entry("resolver"),
        outcomes,
        source_watermark=1,
        reference_watermark=1,
        computed_at=COMPUTED_AT,
    )
    assert report.known_count == 0
    assert report.accuracy is None
    assert report.disposition == "insufficient_reference"


def test_compute_accuracy_report_refuses_an_empty_outcome_set() -> None:
    with pytest.raises(ContractValidationError):
        compute_accuracy_report(
            entry("resolver"),
            (),
            source_watermark=1,
            reference_watermark=1,
            computed_at=COMPUTED_AT,
        )


def test_compute_accuracy_report_refuses_the_unqualified_jev_component() -> None:
    with pytest.raises(ContractValidationError):
        compute_accuracy_report(
            entry("jev"),
            (outcome(),),
            source_watermark=1,
            reference_watermark=1,
            computed_at=COMPUTED_AT,
        )
