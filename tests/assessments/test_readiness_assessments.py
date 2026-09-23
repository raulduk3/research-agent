"""SDD-RD-24: launch readiness for the Jev layer."""

from dataclasses import fields, replace

import pytest

from research_agent.assessments.readiness import (
    READINESS_GATES,
    EvidenceRef,
    ReadinessEvidence,
    ReadinessRecord,
    ReadinessRefused,
    check_assessment_readiness,
)
from research_agent.assessments.rubric import Rubric
from research_agent.contracts import ProducerVersion
from research_agent.contracts.assessments import FIELD_IDS, JevProviderIdentity
from research_agent.evaluation.registrations import (
    ComparisonEndpoint,
    ComparisonRegistration,
)
from research_agent.measurement.jev import (
    BENEFIT_FAMILIES,
    BENEFIT_PRIMARY_METRIC,
    FieldSmokeResult,
    OwnerReview,
    SmokeReport,
)

RUBRIC = Rubric.launch().record
CHECKED_AT = "2026-09-24T00:00:00.000000Z"
DATED = "2026-09-23T00:00:00.000000Z"
IDENTITY = JevProviderIdentity(
    "typesafe",
    "typesafeai/jev-latest",
    "jev-1.13.0",
    "jev-1.13.0",
    "immutable_revision",
    "c" * 64,
    "d" * 64,
)


def _ref(char: str) -> EvidenceRef:
    return EvidenceRef(char * 64, DATED)


def _report(**changes: object) -> SmokeReport:
    values: dict[str, object] = {
        "rubric_hash": RUBRIC.rubric_hash,
        "provider_identity": IDENTITY,
        "sample_hash": "1" * 64,
        "sample_size": 20,
        "shortfall_weeks": (),
        "fields": tuple(
            FieldSmokeResult(field_id, 20, (), (), True) for field_id in FIELD_IDS
        ),
        "input_coverage_counts": (("complete", 20),),
        "latency_ms_total": 20,
        "latency_ms_max": 1,
        "cost_micros_total": 20,
        "request_artifact_hashes": (),
        "response_artifact_hashes": (),
        "owner_review": OwnerReview("owner", DATED, "e" * 64),
    }
    values.update(changes)
    return SmokeReport(**values)  # type: ignore[arg-type]


def _registration(**changes: object) -> ComparisonRegistration:
    values: dict[str, object] = {
        "schema_version": 1,
        "input_hashes": (),
        "producer_version": ProducerVersion("a" * 64, "b" * 40, 1),
        "config_hash": "c" * 64,
        "created_at": "2026-09-01T00:00:00.000000Z",
        "registration_id": "11111111-1111-4111-8111-111111111111",
        "hypothesis": "with-Jev forecasts improve citation-reach Brier",
        "population_hash": "d" * 64,
        "split_hash": "e" * 64,
        "subject_configuration_hash": "f" * 64,
        "endpoints": (ComparisonEndpoint(BENEFIT_PRIMARY_METRIC, "primary", "lower"),),
        "pass_threshold": -0.01,
        "kill_threshold": 0.0,
        "minimum_effect": 0.01,
        "exclusions": (),
        "sample_size": BENEFIT_FAMILIES,
        "failure_handling": "count_as_failure",
        "stop_rule_hash": "0" * 64,
        "provenance": "runtime",
        "registered_at": "2026-09-02T00:00:00.000000Z",
        "imported_at": None,
        "signature_evidence_hash": None,
        "exploratory_of": None,
    }
    values.update(changes)
    return ComparisonRegistration(**values)  # type: ignore[arg-type]


def _evidence(**changes: object) -> ReadinessEvidence:
    values: dict[str, object] = {
        "provider_access": _ref("1"),
        "retention_permission": _ref("2"),
        "identity_semantics": _ref("3"),
        "input_limits": _ref("4"),
        "corpus_input_coverage": _ref("5"),
        "operating_profile": _ref("6"),
        "rubric_pin": RUBRIC.rubric_hash,
        "smoke_report": _report(),
        "registration": _registration(),
        "registration_watermark_at": "2026-09-23T00:00:00.000000Z",
    }
    values.update(changes)
    return ReadinessEvidence(**values)  # type: ignore[arg-type]


def _check(
    evidence: ReadinessEvidence, identity: JevProviderIdentity = IDENTITY
) -> ReadinessRecord:
    return check_assessment_readiness(
        evidence, rubric=RUBRIC, provider_identity=identity, checked_at=CHECKED_AT
    )


def test_all_items_supplied_is_ready_with_immature_outcomes() -> None:
    record = _check(_evidence())
    assert record.failed_gates == ()
    assert record.study_activation_allowed
    assert {name for name, _ in record.evidence_hashes} == set(READINESS_GATES)
    assert record.require_study_activation() == record.record_hash()


@pytest.mark.parametrize(
    "item",
    [
        field.name
        for field in fields(ReadinessEvidence)
        if field.name != "registration_watermark_at"
    ],
)
def test_removing_each_required_item_refuses_study_activation(item: str) -> None:
    record = _check(_evidence(**{item: None}))
    assert len(record.failed_gates) == 1
    gate, reason = record.failed_gates[0]
    assert gate in READINESS_GATES
    assert reason.startswith("missing") or gate == "smoke_test"
    assert not record.study_activation_allowed
    assert record.collection_allowed
    with pytest.raises(ReadinessRefused) as refused:
        record.require_study_activation()
    assert refused.value.gates == record.failed_gates


def test_a_missing_watermark_fails_the_registration_gate() -> None:
    record = _check(_evidence(registration_watermark_at=None))
    assert record.failed_gates == (("registration", "missing"),)


def test_a_smoke_report_without_owner_review_fails() -> None:
    record = _check(_evidence(smoke_report=_report(owner_review=None)))
    assert record.failed_gates == (("smoke_test", "owner_review_missing"),)


def test_a_smoke_report_for_another_identity_fails() -> None:
    other = replace(IDENTITY, immutable_revision="jev-2.0.0")
    record = _check(_evidence(), identity=other)
    assert record.failed_gates == (("smoke_test", "identity_changed"),)


def test_a_field_below_the_floor_fails_the_smoke_gate() -> None:
    low = tuple(
        FieldSmokeResult(field_id, 17 if n == 0 else 20, (), (), n != 0)
        for n, field_id in enumerate(FIELD_IDS)
    )
    record = _check(_evidence(smoke_report=_report(fields=low)))
    assert record.failed_gates == (("smoke_test", f"field_below_floor:{FIELD_IDS[0]}"),)


def test_a_changed_rubric_pin_fails() -> None:
    record = _check(_evidence(rubric_pin="9" * 64))
    assert record.failed_gates == (("rubric_pin", "rubric_changed"),)


def test_evidence_dated_after_the_check_does_not_count() -> None:
    late = EvidenceRef("7" * 64, "2026-09-25T00:00:00.000000Z")
    record = _check(_evidence(provider_access=late))
    assert record.failed_gates == (("provider_access", "dated_after_check"),)


def test_a_registration_recorded_after_the_watermark_fails() -> None:
    record = _check(_evidence(registration_watermark_at="2026-09-01T00:00:00.000000Z"))
    assert record.failed_gates == (("registration", "not_recorded_at_watermark"),)


def test_another_comparisons_registration_is_not_the_benefit_registration() -> None:
    other = _registration(
        endpoints=(ComparisonEndpoint("skill_gain", "primary", "higher"),),
        pass_threshold=0.05,
    )
    record = _check(_evidence(registration=other))
    assert record.failed_gates == (("registration", "not_the_benefit_registration"),)


def test_every_unmet_gate_is_named_together() -> None:
    record = _check(_evidence(provider_access=None, retention_permission=None))
    assert [name for name, _ in record.failed_gates] == [
        "provider_access",
        "retention_permission",
    ]
