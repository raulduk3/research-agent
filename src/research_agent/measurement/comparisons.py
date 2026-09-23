"""The forecast as the unit of analysis, and the verdict a bootstrap interval earns.

`paired_forecast_rows` matches two sides' resolved forecasts by question id and
keeps each matched pair's own run, family and publication-week identity, so the
pooled mean difference (SDD-IN-14) is never diluted or inflated by first
averaging within a run. `interval_verdict` turns a `bootstrap.BootstrapInterval`
into a disposition without ever reading it as evidence of equivalence
(SDD-IN-16). Neither function reads a clock, draws a random value or touches
storage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_agent.contracts.primitives import (
    validate_finite,
    validate_non_empty_string,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError

FAVORABLE_DIRECTIONS: frozenset[str] = frozenset({"lower", "higher"})
VERDICTS: frozenset[str] = frozenset(
    {"favorable", "unfavorable", "inconclusive", "unavailable"}
)


@dataclass(frozen=True, slots=True)
class ForecastObservation:
    """One side's resolved forecast, with the clustering identity it carries."""

    question_id: str
    run_id: str
    family_id: str
    publication_week: str
    loss: float

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_non_empty_string(self.run_id)
        validate_uuid4(self.family_id)
        validate_finite(self.loss)


@dataclass(frozen=True, slots=True)
class PairedForecastRow:
    """One matched question/configuration pair, with both sides' individual losses."""

    question_id: str
    family_id: str
    publication_week: str
    candidate_run_id: str
    baseline_run_id: str
    candidate_loss: float
    baseline_loss: float

    @property
    def difference(self) -> float:
        return self.candidate_loss - self.baseline_loss


@dataclass(frozen=True, slots=True)
class PairedForecastRowSet:
    """Every matched row plus the counts and omitted support the match found."""

    rows: tuple[PairedForecastRow, ...]
    candidate_count: int
    baseline_count: int
    matched_count: int
    candidate_only_question_ids: tuple[str, ...]
    baseline_only_question_ids: tuple[str, ...]


def paired_forecast_rows(
    candidate: Sequence[ForecastObservation],
    baseline: Sequence[ForecastObservation],
) -> PairedForecastRowSet:
    """Match candidate and baseline forecasts by question id into paired rows.

    A question answered by only one side never enters `rows`; it is counted
    and named in the omitted-support fields instead of silently dropped
    (SDD-IN-14: "each reported comparison gives the count of forecasts on
    each side").
    """

    candidate_by_question = _by_question(candidate, "candidate")
    baseline_by_question = _by_question(baseline, "baseline")
    matched_ids = sorted(set(candidate_by_question) & set(baseline_by_question))
    rows = []
    for question_id in matched_ids:
        c = candidate_by_question[question_id]
        b = baseline_by_question[question_id]
        if c.family_id != b.family_id or c.publication_week != b.publication_week:
            raise MeasurementError(
                "a matched question must share one family and publication week"
            )
        rows.append(
            PairedForecastRow(
                question_id=question_id,
                family_id=c.family_id,
                publication_week=c.publication_week,
                candidate_run_id=c.run_id,
                baseline_run_id=b.run_id,
                candidate_loss=c.loss,
                baseline_loss=b.loss,
            )
        )
    candidate_only = tuple(
        sorted(set(candidate_by_question) - set(baseline_by_question))
    )
    baseline_only = tuple(
        sorted(set(baseline_by_question) - set(candidate_by_question))
    )
    return PairedForecastRowSet(
        rows=tuple(rows),
        candidate_count=len(candidate_by_question),
        baseline_count=len(baseline_by_question),
        matched_count=len(rows),
        candidate_only_question_ids=candidate_only,
        baseline_only_question_ids=baseline_only,
    )


def pooled_mean_difference(rows: Sequence[PairedForecastRow]) -> float | None:
    """The forecast-level pooled mean difference (SDD-IN-14).

    Every row counts once regardless of which run produced it, so a run with
    more matched forecasts than another is not equal-weighted against it; a
    resampled row set from `bootstrap.bootstrap_difference` recomputes this
    same statistic.
    """

    if not rows:
        return None
    return sum(row.difference for row in rows) / len(rows)


def _by_question(
    observations: Sequence[ForecastObservation], side: str
) -> dict[str, ForecastObservation]:
    by_question: dict[str, ForecastObservation] = {}
    for observation in observations:
        if observation.question_id in by_question:
            raise MeasurementError(f"{side} forecasts must not repeat a question id")
        by_question[observation.question_id] = observation
    return by_question


@dataclass(frozen=True, slots=True)
class IntervalVerdict:
    """A comparison's disposition against its preregistered favorable direction."""

    verdict: str
    low: float | None
    high: float | None
    favorable_direction: str
    minimum_effect: float | None
    minimum_effect_pass: bool | None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise MeasurementError("verdict is not a recognized value")
        if self.favorable_direction not in FAVORABLE_DIRECTIONS:
            raise MeasurementError("favorable_direction must be 'lower' or 'higher'")
        if self.verdict == "unavailable":
            if self.low is not None or self.high is not None:
                raise MeasurementError("an unavailable verdict carries no bounds")
        elif self.low is None or self.high is None:
            raise MeasurementError("a produced verdict carries its interval bounds")
        elif self.low > self.high:
            raise MeasurementError("interval bounds must be ordered low <= high")
        if self.minimum_effect is not None and self.minimum_effect <= 0:
            raise MeasurementError(
                "minimum_effect must be strictly positive when given"
            )
        if self.verdict != "favorable" and self.minimum_effect_pass not in (
            None,
            False,
        ):
            raise MeasurementError(
                "only a favorable verdict can pass a minimum-effect margin"
            )
        if self.minimum_effect is None and self.minimum_effect_pass is not None:
            raise MeasurementError(
                "minimum_effect_pass requires a registered minimum_effect"
            )


def interval_verdict(
    low: float | None,
    high: float | None,
    *,
    favorable_direction: str,
    minimum_effect: float | None = None,
) -> IntervalVerdict:
    """Classify a percentile interval as favorable, unfavorable or inconclusive.

    An interval spanning zero is always inconclusive, never a tie or evidence
    of equivalence (SDD-IN-16); missing bounds are unavailable rather than
    inconclusive, since no comparison was actually produced. A minimum-effect
    pass is only ever reported for a favorable verdict clearing a separately
    registered margin -- there is no equivalence verdict without one.
    """

    if favorable_direction not in FAVORABLE_DIRECTIONS:
        raise MeasurementError("favorable_direction must be 'lower' or 'higher'")
    if minimum_effect is not None and validate_finite(minimum_effect) <= 0:
        raise MeasurementError("minimum_effect must be strictly positive when given")
    if low is None or high is None:
        return IntervalVerdict(
            "unavailable", None, None, favorable_direction, minimum_effect, None
        )
    low = validate_finite(low)
    high = validate_finite(high)
    if low > high:
        raise MeasurementError("interval bounds must be ordered low <= high")
    if low <= 0 <= high:
        return IntervalVerdict(
            "inconclusive", low, high, favorable_direction, minimum_effect, None
        )
    favorable = high < 0 if favorable_direction == "lower" else low > 0
    verdict = "favorable" if favorable else "unfavorable"
    minimum_effect_pass: bool | None = None
    if minimum_effect is not None:
        if favorable:
            bound = -high if favorable_direction == "lower" else low
            minimum_effect_pass = bound >= minimum_effect
        else:
            minimum_effect_pass = False
    return IntervalVerdict(
        verdict, low, high, favorable_direction, minimum_effect, minimum_effect_pass
    )
