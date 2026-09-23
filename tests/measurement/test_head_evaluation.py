"""Prospective vs retrospective prediction-head evaluation (SDD IN-38).

TDD-1.1.23: computing a probability after a known event and resolving it
later cannot enter the prospective report; a training family is excluded
from every kind; no eligible predictions yields an unavailable result
rather than a zero loss.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from research_agent.contracts.learning import TARGET_IDS
from research_agent.measurement.heads import (
    EvaluationError,
    MatchedPrediction,
    evaluate_predictions,
)
from research_agent.models.predict import PredictionArtifact

TARGET_ID = TARGET_IDS[0]
BUNDLE_HASH = sha256(b"bundle").hexdigest()
REPRESENTATION_HASH = sha256(b"representation").hexdigest()
TARGET_DEFINITION_HASH = sha256(b"target-definition").hexdigest()
FAMILY_A = "00000000-0000-4000-8000-00000000000a"
FAMILY_B = "00000000-0000-4000-8000-00000000000b"


def _baselines(value: float = 0.3) -> dict[str, float]:
    return {target_id: value for target_id in TARGET_IDS}


def _prediction(
    *,
    family: str,
    probability: float | None,
    computed_at: str,
    available_at: str,
    status: str = "available",
    reason: str | None = None,
) -> PredictionArtifact:
    return PredictionArtifact(
        target_id=TARGET_ID,
        target_definition_hash=TARGET_DEFINITION_HASH,
        question="Will at least five indexed works cite this paper?",
        original_version_id=family,
        bundle_hash=BUNDLE_HASH,
        representation_hash=REPRESENTATION_HASH,
        status=status,
        reason=reason,
        raw_logit=None if probability is None else 0.1,
        probability=probability,
        input_hash=sha256(family.encode()).hexdigest(),
        computed_at=computed_at,
        available_at=available_at,
    )


def _matched(
    *,
    family: str,
    probability: float,
    label_state: str,
    label_maturity_at: str,
    observation_kind: str,
    available_at: str,
    training_family: bool = False,
) -> MatchedPrediction:
    return MatchedPrediction(
        prediction=_prediction(
            family=family,
            probability=probability,
            computed_at=available_at,
            available_at=available_at,
        ),
        family_id=family,
        label_state=label_state,
        label_maturity_at=label_maturity_at,
        observation_kind=observation_kind,
        training_family=training_family,
    )


def test_no_eligible_predictions_yields_unavailable_rather_than_zero_loss() -> None:
    report = evaluate_predictions((), _baselines())
    prospective = report.for_target(TARGET_ID, "prospective")
    assert prospective.status == "unavailable"
    assert prospective.reason == "no_eligible_predictions"
    assert prospective.support_count == 0
    assert prospective.brier_score is None


def test_a_prediction_sealed_after_its_event_cannot_enter_the_prospective_report() -> (
    None
):
    late = _matched(
        family=FAMILY_A,
        probability=0.9,
        label_state="true",
        label_maturity_at="2026-01-01T00:00:00.000000Z",
        observation_kind="prospective_maturity",
        available_at="2026-01-02T00:00:00.000000Z",
    )
    report = evaluate_predictions((late,), _baselines())
    prospective = report.for_target(TARGET_ID, "prospective")
    assert prospective.status == "unavailable"


def test_a_prediction_sealed_before_the_event_enters_the_prospective_report() -> None:
    early = _matched(
        family=FAMILY_A,
        probability=0.9,
        label_state="true",
        label_maturity_at="2026-01-10T00:00:00.000000Z",
        observation_kind="prospective_maturity",
        available_at="2026-01-01T00:00:00.000000Z",
    )
    report = evaluate_predictions((early,), _baselines())
    prospective = report.for_target(TARGET_ID, "prospective")
    assert prospective.status == "available"
    assert prospective.support_count == 1
    assert prospective.brier_score == pytest.approx((0.9 - 1.0) ** 2)
    assert len(prospective.reliability_bins) == 10
    assert sum(b.count for b in prospective.reliability_bins) == 1


def test_a_training_family_is_excluded_from_every_kind() -> None:
    trained = _matched(
        family=FAMILY_A,
        probability=0.9,
        label_state="true",
        label_maturity_at="2026-01-10T00:00:00.000000Z",
        observation_kind="prospective_maturity",
        available_at="2026-01-01T00:00:00.000000Z",
        training_family=True,
    )
    report = evaluate_predictions((trained,), _baselines())
    assert report.for_target(TARGET_ID, "prospective").status == "unavailable"
    assert report.for_target(TARGET_ID, "retrospective").status == "unavailable"


def test_retrospective_and_prospective_denominators_stay_separate() -> None:
    prospective_row = _matched(
        family=FAMILY_A,
        probability=0.8,
        label_state="true",
        label_maturity_at="2026-01-10T00:00:00.000000Z",
        observation_kind="prospective_maturity",
        available_at="2026-01-01T00:00:00.000000Z",
    )
    retrospective_row = _matched(
        family=FAMILY_B,
        probability=0.2,
        label_state="false",
        label_maturity_at="2020-01-10T00:00:00.000000Z",
        observation_kind="historical_reconstructed",
        available_at="2024-01-01T00:00:00.000000Z",
    )
    report = evaluate_predictions((prospective_row, retrospective_row), _baselines())
    prospective = report.for_target(TARGET_ID, "prospective")
    retrospective = report.for_target(TARGET_ID, "retrospective")
    assert prospective.support_count == 1
    assert retrospective.support_count == 1
    assert prospective.bundle_hashes == (BUNDLE_HASH,)
    assert retrospective.bundle_hashes == (BUNDLE_HASH,)


def test_baselines_must_cover_every_registry_target() -> None:
    with pytest.raises(EvaluationError):
        evaluate_predictions((), {TARGET_ID: 0.3})
