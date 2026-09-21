from dataclasses import replace
from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.learning import (
    AutomaticLabel,
    CitationFamilyRecord,
    CitationObservation,
    CountBounds,
    LabelCounts,
    PaginationPage,
    TargetDefinition,
    TargetRegistry,
    TargetWindow,
)
from research_agent.contracts.papers import ExternalIdentifier, SourceInterval
from research_agent.outcomes.targets import definitions

T0 = "2020-01-01T00:00:00.000000Z"
MATURITY = "2021-03-31T00:00:00.000000Z"
CAPTURED = "2021-03-31T00:00:01.000000Z"
META = RecordMeta(
    1,
    ("1" * 64,),
    ProducerVersion("2" * 64, "3" * 40, 1),
    "4" * 64,
    CAPTURED,
)


def meta() -> dict[str, object]:
    return {
        "schema_version": META.schema_version,
        "input_hashes": META.input_hashes,
        "producer_version": META.producer_version,
        "config_hash": META.config_hash,
        "created_at": META.created_at,
    }


def completed_page(*, cursor_out: str | None = None) -> PaginationPage:
    return PaginationPage(
        0,
        "5" * 64,
        "6" * 64,
        None,
        cursor_out,
        1,
        MATURITY,
        CAPTURED,
        "completed",
        None,
    )


def family() -> CitationFamilyRecord:
    return CitationFamilyRecord(
        **meta(),
        canonical_family_id="family-1",
        provider_work_ids=("W1",),
        external_ids=(ExternalIdentifier("openalex", "W1"),),
        identity_evidence_hashes=("7" * 64,),
        representative_work_id="W1",
        representative_rule="lowest_provider_id",
        identity_state="resolved",
        possible_identity_cluster=None,
        target_link_work_ids=("W100",),
        publication_interval=SourceInterval(
            "2020-01-02T00:00:00.000000Z", "2020-01-03T00:00:00.000000Z"
        ),
        alternative_publication_intervals=(),
        date_state="known",
        primary_subfield_id="cs.AI",
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("8" * 64,),
        is_target_family_self_link=False,
    )


def observation() -> CitationObservation:
    return CitationObservation(
        **meta(),
        paper_family_id=str(uuid4()),
        original_version_id=str(uuid4()),
        t0=T0,
        protocol="automatic-citations-v1",
        target_registry_hash="9" * 64,
        provider="openalex",
        kind="prospective_maturity",
        target_match_state="matched",
        target_provider_ids=("W100",),
        target_subfield_id="cs.AI",
        target_subfield_state="known",
        taxonomy_hash="a" * 64,
        capture_started_at=MATURITY,
        capture_completed_at=CAPTURED,
        maturity_at=MATURITY,
        acquisition_lag_seconds=1,
        pages=(completed_page(),),
        pagination_complete=True,
        citation_family_hashes=("b" * 64,),
        failure=None,
    )


def counts() -> LabelCounts:
    return LabelCounts(
        CountBounds(5, 5),
        CountBounds(1, 1),
        CountBounds(1, 1),
        CountBounds(2, 2),
    )


def test_fixed_target_registry_round_trips_as_closed_ordered_contract() -> None:
    target_definitions = definitions(META)
    registry = TargetRegistry(
        **meta(),
        protocol="automatic-citations-v1",
        definitions=target_definitions,
        calibrated_domains=("cs.AI", "cs.LG"),
    )
    assert TargetRegistry.from_json(registry.to_canonical_json()) == registry
    assert all(
        TargetDefinition.from_json(item.to_canonical_json()) == item
        for item in target_definitions
    )
    assert (
        TargetWindow.from_json(target_definitions[0].windows[0].to_canonical_json())
        == target_definitions[0].windows[0]
    )

    with pytest.raises(ContractValidationError):
        replace(registry, definitions=tuple(reversed(target_definitions)))
    with pytest.raises(ContractValidationError):
        replace(registry, calibrated_domains=("cs.LG", "cs.AI"))
    with pytest.raises(ContractValidationError):
        replace(target_definitions[0].windows[0], start_inclusive=0)  # type: ignore[arg-type]

    body = canonical_loads(registry.to_canonical_json())
    body["future"] = "field"
    with pytest.raises(ContractValidationError):
        TargetRegistry.from_json(canonical_json(body))

    invalid_definition = canonical_loads(target_definitions[0].to_canonical_json())
    invalid_definition["target_id"] = []
    with pytest.raises(ContractValidationError, match="field types"):
        TargetDefinition.from_json(canonical_json(invalid_definition))


def test_citation_family_round_trip_and_uncertainty_states_fail_closed() -> None:
    record = family()
    assert CitationFamilyRecord.from_json(record.to_canonical_json()) == record
    with pytest.raises(ContractValidationError):
        replace(record, representative_work_id="W2")
    with pytest.raises(ContractValidationError):
        replace(record, identity_state="ambiguous", possible_identity_cluster=None)
    with pytest.raises(ContractValidationError):
        replace(
            record,
            publication_interval=None,
            date_state="conflicting",
            alternative_publication_intervals=(
                SourceInterval(
                    "2020-01-02T00:00:00.000000Z",
                    "2020-01-03T00:00:00.000000Z",
                ),
            ),
        )
    with pytest.raises(ContractValidationError):
        replace(record, is_target_family_self_link=1)  # type: ignore[arg-type]

    invalid = canonical_loads(record.to_canonical_json())
    invalid["representative_rule"] = []
    with pytest.raises(ContractValidationError, match="field types"):
        CitationFamilyRecord.from_json(canonical_json(invalid))


def test_citation_observation_round_trip_binds_clocks_and_terminal_pagination() -> None:
    record = observation()
    assert CitationObservation.from_json(record.to_canonical_json()) == record
    assert (
        PaginationPage.from_json(record.pages[0].to_canonical_json()) == record.pages[0]
    )

    trailing = replace(
        completed_page(),
        page_index=1,
        request_hash="c" * 64,
        cursor_in=None,
    )
    with pytest.raises(ContractValidationError, match="terminal cursor"):
        replace(record, pages=(completed_page(), trailing))
    with pytest.raises(ContractValidationError, match="completeness"):
        replace(record, pages=(completed_page(cursor_out="next"),))
    with pytest.raises(ContractValidationError, match="lag"):
        replace(record, acquisition_lag_seconds=0)
    with pytest.raises(ContractValidationError):
        replace(record, capture_started_at="not-a-clock")

    failed = PaginationPage(
        0,
        "d" * 64,
        "e" * 64,
        None,
        None,
        0,
        MATURITY,
        CAPTURED,
        "failed",
        "invalid_payload",
    )
    assert failed.response_hash is not None
    assert CitationObservation.from_json(
        replace(
            record,
            pages=(failed,),
            pagination_complete=False,
            failure="initial_request_failed",
        ).to_canonical_json()
    )

    no_response = replace(
        record,
        pages=(),
        pagination_complete=False,
        citation_family_hashes=(),
        failure="initial_request_failed",
    )
    assert CitationObservation.from_json(no_response.to_canonical_json()) == no_response


def test_prospective_outside_window_is_retained_only_as_explicit_failure() -> None:
    record = observation()
    late = "2021-04-01T00:00:01.000000Z"
    late_page = replace(
        completed_page(), capture_started_at=late, capture_completed_at=late
    )
    retained = replace(
        record,
        capture_started_at=late,
        capture_completed_at=late,
        acquisition_lag_seconds=86401,
        pages=(late_page,),
        failure="outside_capture_window",
    )
    assert CitationObservation.from_json(retained.to_canonical_json()) == retained
    with pytest.raises(ContractValidationError, match="failure state"):
        replace(retained, failure=None)
    with pytest.raises(ContractValidationError, match="outside observation"):
        replace(record, capture_started_at="2021-03-31T00:00:00.500000Z")


def test_label_counts_and_automatic_label_round_trip_without_unknown_as_false() -> None:
    label = AutomaticLabel(
        **meta(),
        paper_family_id=str(uuid4()),
        target_id="citation_reach_365d",
        target_definition_hash="d" * 64,
        state="true",
        reason="sufficient_positive_witnesses",
        observation_hash="e" * 64,
        counts=counts(),
        witness_family_ids=("family-1", "family-2"),
        witness_subfield_ids=("cs.AI", "cs.LG"),
        completion_page_hashes=("f" * 64, "a" * 64),
        maturity_at=MATURITY,
        resolved_at=CAPTURED,
        supersedes_label_hash=None,
        correction_hash=None,
    )
    assert AutomaticLabel.from_json(label.to_canonical_json()) == label
    assert LabelCounts.from_json(label.counts.to_canonical_json()) == label.counts
    assert CountBounds.from_json(
        CountBounds(0, None).to_canonical_json()
    ) == CountBounds(0, None)
    with pytest.raises(ContractValidationError):
        CountBounds(2, 1)
    with pytest.raises(ContractValidationError):
        replace(label, state="unknown")
    with pytest.raises(ContractValidationError):
        replace(label, supersedes_label_hash="a" * 64)
    with pytest.raises(ContractValidationError):
        replace(label, witness_family_ids=("family-2", "family-1"))
