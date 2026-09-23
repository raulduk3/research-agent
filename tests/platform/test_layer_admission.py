import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.readiness import ComparisonReport, evaluate_admission

BASELINE_HASH = "a" * 64
CANDIDATE_HASH = "b" * 64
REGISTERED_AT = "2026-09-01T00:00:00.000000Z"
EXECUTED_AT = "2026-09-02T00:00:00.000000Z"
REPORT_ID = "8b6a5f2e-5c1a-4b4b-9b3d-8e2f6a7c1d90"


def _report(**overrides: object) -> ComparisonReport:
    values: dict[str, object] = {
        "report_id": REPORT_ID,
        "primary_metric": "citation_reach_365d_brier",
        "registered_at": REGISTERED_AT,
        "executed_at": EXECUTED_AT,
    }
    values.update(overrides)
    return ComparisonReport(**values)  # type: ignore[arg-type]


def _admit(**overrides: object):
    values: dict[str, object] = {
        "layer_id": "retrieval",
        "baseline_config_hash": BASELINE_HASH,
        "candidate_config_hash": CANDIDATE_HASH,
        "registered_primary_metric": "citation_reach_365d_brier",
        "reports": (_report(),),
        "activation_scope": "study",
        "jev_admitted": False,
    }
    values.update(overrides)
    return evaluate_admission(**values)  # type: ignore[arg-type]


def test_comparison_report_rejects_post_hoc_registration() -> None:
    with pytest.raises(ContractValidationError):
        _report(registered_at=EXECUTED_AT, executed_at=REGISTERED_AT)


def test_admission_passes_with_a_baseline_and_a_matching_registered_comparison() -> (
    None
):
    record = _admit()
    assert record.admitted
    assert record.denial_reasons == ()


def test_admission_rejects_a_missing_baseline() -> None:
    record = _admit(baseline_config_hash=None)
    assert not record.admitted
    assert "missing_baseline" in record.denial_reasons


def test_admission_rejects_a_wrong_metric_report() -> None:
    record = _admit(reports=(_report(primary_metric="unrelated_metric"),))
    assert not record.admitted
    assert "wrong_metric_report" in record.denial_reasons


def test_admission_rejects_no_comparison_report_at_all() -> None:
    record = _admit(reports=())
    assert not record.admitted
    assert "missing_comparison_report" in record.denial_reasons


def test_jev_admission_is_denied_under_the_current_profile() -> None:
    record = _admit(layer_id="jev", jev_admitted=False)
    assert not record.admitted
    assert "jev_layer_held_out" in record.denial_reasons


def test_jev_admission_passes_once_a_later_decision_admits_it() -> None:
    record = _admit(layer_id="jev", jev_admitted=True)
    assert record.admitted


def test_future_prediction_head_is_denied_regardless_of_evidence() -> None:
    record = _admit(layer_id="encoder_fine_tuning")
    assert not record.admitted
    assert "future_prediction_head_denied" in record.denial_reasons


def test_record_hash_is_stable_for_identical_records() -> None:
    assert _admit().record_hash() == _admit().record_hash()
