"""The Jev rubric smoke test and benefit study (SDD RD-22, RD-23; TDD-4.1.60, 4.1.61).

The smoke test shows that the eight-field integration works on real papers,
not that its answers are right: no reference label, agreement or accuracy
enters, and the report claims none. `select_smoke_sample` draws the fixed
sample before any request, `smoke_test_rubric` folds the stored outcomes of
those requests into one report, and `check_smoke_activation` refuses to
activate the layer unless that report passes for the active rubric and
provider identity. All three are pure: sending requests, timing them and
pricing them belong to the caller, whose observed values are recorded here.

The sample is one paper from each of the latest complete publication weeks,
ranked by the seeded selection hash the other pilots use. A category quota
proportional to the family counts of those weeks, at least one per category,
decides which category a week's paper may come from; a week with no paper
in an open category is a recorded shortfall and is never replaced.

`JevBenefitStudy` is the paired prospective comparison of agent forecasts with
and without Jev fields. It allocates the first eligible families, fixes each
family's arm order from a recorded seed, and reads the matured Brier
differences under the assigned treatment: a with-Jev run whose delivery failed
stays in its pair. No verdict exists before the last allocated family matures.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from research_agent.assessments.schemas import (
    AssessmentResult,
    JevAvailable,
    JevUnavailable,
)
from research_agent.contracts.assessments import (
    FIELD_CATEGORIES,
    FIELD_IDS,
    JevProviderIdentity,
    JevRubric,
)
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.learning import PRIMARY_CATEGORY_IDS
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.evaluation.registrations import ComparisonRegistration
from research_agent.learning.corpus import SELECTION_SEED, selection_hash
from research_agent.measurement import MeasurementError
from research_agent.measurement.bootstrap import bootstrap_difference
from research_agent.measurement.comparisons import (
    ForecastObservation,
    interval_verdict,
    paired_forecast_rows,
)
from research_agent.outcomes.windows import instant, maturity_at

__all__ = [
    "SMOKE_SAMPLE_WEEKS",
    "SMOKE_VALID_FLOOR",
    "SmokeCandidate",
    "SmokeSample",
    "SmokeObservation",
    "OwnerReview",
    "FieldSmokeResult",
    "SmokeReport",
    "SmokeActivationRefused",
    "select_smoke_sample",
    "smoke_test_rubric",
    "check_smoke_activation",
    "BENEFIT_PRIMARY_METRIC",
    "BENEFIT_FAMILIES",
    "BENEFIT_MIN_WEEKS",
    "BENEFIT_MIN_SUPPORT",
    "BENEFIT_MIN_GAIN",
    "ARMS",
    "BenefitFamily",
    "BenefitAllocation",
    "PairedOutcome",
    "BenefitReport",
    "JevBenefitStudy",
    "validate_benefit_registration",
]

#: Appendix A: one paper from each of the latest 20 complete publication weeks.
SMOKE_SAMPLE_WEEKS = 20
#: Appendix A: every field must be schema-valid for at least 18 of the 20 papers.
SMOKE_VALID_FLOOR = 18
_INPUT_COVERAGE = ("complete", "partial", "unavailable")


@dataclass(frozen=True, slots=True)
class SmokeCandidate:
    """One target-corpus paper family eligible for the smoke draw."""

    family_id: str
    primary_category: str
    publication_week: str

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        validate_non_empty_string(self.primary_category)
        validate_non_empty_string(self.publication_week)


@dataclass(frozen=True, slots=True)
class SmokeSample:
    """The frozen draw: chosen papers, per-category quotas and visible shortfall.

    ``shortfall_weeks`` names each sampled week that yielded no paper; the
    sample is never padded from another week to hide it.
    """

    weeks: tuple[str, ...]
    quotas: tuple[tuple[str, int], ...]
    selected: tuple[SmokeCandidate, ...]
    shortfall_weeks: tuple[str, ...]

    @property
    def shortfall(self) -> int:
        return len(self.shortfall_weeks)

    def sample_hash(self) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "weeks": list(self.weeks),
                    "quotas": [list(item) for item in self.quotas],
                    "selected": [
                        [item.family_id, item.primary_category, item.publication_week]
                        for item in self.selected
                    ],
                    "shortfall_weeks": list(self.shortfall_weeks),
                }
            )
        )


def _quotas(
    counts: Counter[str], categories: Sequence[str], size: int
) -> tuple[tuple[str, int], ...]:
    """Largest-remainder shares of ``size`` by family count, at least one each."""

    total = sum(counts[category] for category in categories)
    if total == 0 or size < len(categories):
        raise MeasurementError("the sample cannot give every category a paper")
    exact = {category: size * counts[category] / total for category in categories}
    quota = {category: max(1, math.floor(exact[category])) for category in categories}
    order = sorted(
        categories,
        key=lambda category: (
            -(exact[category] - math.floor(exact[category])),
            categories.index(category),
        ),
    )
    while sum(quota.values()) < size:
        for category in order:
            if sum(quota.values()) < size:
                quota[category] += 1
    while sum(quota.values()) > size:
        # Take from the category holding the most above its exact share.
        donor = max(
            (c for c in categories if quota[c] > 1),
            key=lambda c: (quota[c] - exact[c], -categories.index(c)),
        )
        quota[donor] -= 1
    return tuple((category, quota[category]) for category in categories)


def select_smoke_sample(
    candidates: Sequence[SmokeCandidate],
    weeks: Sequence[str],
    *,
    categories: Sequence[str] = PRIMARY_CATEGORY_IDS,
    seed: int = SELECTION_SEED,
) -> SmokeSample:
    """Draw the smoke sample from ``weeks`` (latest complete week first).

    Each week contributes its first hash-ranked paper from the category with
    the most open quota that has a paper that week. A week with no paper in
    any category with open quota is a shortfall week. The draw is independent
    of the order of ``candidates``.
    """

    weeks = tuple(weeks)
    if not weeks or len(set(weeks)) != len(weeks):
        raise MeasurementError("smoke weeks must be a nonempty list without repeats")
    for week in weeks:
        validate_non_empty_string(week)
    categories = tuple(categories)
    ids = [candidate.family_id for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise MeasurementError("smoke candidates must not repeat a family")
    known = set(categories)
    pool = [
        candidate
        for candidate in candidates
        if candidate.publication_week in weeks and candidate.primary_category in known
    ]
    counts = Counter(candidate.primary_category for candidate in pool)
    quotas = dict(_quotas(counts, categories, len(weeks)))
    remaining = dict(quotas)
    selected: list[SmokeCandidate] = []
    shortfall: list[str] = []
    for week in weeks:
        ranked = sorted(
            (item for item in pool if item.publication_week == week),
            key=lambda item: (selection_hash(item.family_id, seed), item.family_id),
        )
        open_categories = [
            category
            for category in sorted(
                categories, key=lambda c: (-remaining[c], categories.index(c))
            )
            if remaining[category] > 0
            and any(item.primary_category == category for item in ranked)
        ]
        if not open_categories:
            shortfall.append(week)
            continue
        pick = next(
            item for item in ranked if item.primary_category == open_categories[0]
        )
        remaining[pick.primary_category] -= 1
        selected.append(pick)
    return SmokeSample(
        weeks=weeks,
        quotas=tuple(quotas.items()),
        selected=tuple(selected),
        shortfall_weeks=tuple(shortfall),
    )


@dataclass(frozen=True, slots=True)
class SmokeObservation:
    """One sampled paper's stored outcome, latency, cost and input coverage."""

    family_id: str
    result: AssessmentResult
    input_coverage: str
    latency_ms: int
    cost_micros: int

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        if not isinstance(self.result, (JevAvailable, JevUnavailable)):
            raise MeasurementError("an observation carries a stored assessment result")
        if self.input_coverage not in _INPUT_COVERAGE:
            raise MeasurementError("input coverage is not admitted")
        validate_non_negative_int(self.latency_ms)
        validate_non_negative_int(self.cost_micros)


@dataclass(frozen=True, slots=True)
class OwnerReview:
    """The owner's recorded reading of the stored answers; no accuracy is claimed."""

    reviewer: str
    reviewed_at: str
    notes_hash: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.reviewer)
        validate_utc_instant(self.reviewed_at)
        validate_sha256(self.notes_hash)


@dataclass(frozen=True, slots=True)
class FieldSmokeResult:
    """One field's smoke outcome across the sample."""

    field_id: str
    valid_count: int
    category_counts: tuple[tuple[str, int], ...]
    unavailable_reasons: tuple[tuple[str, int], ...]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "valid_count": self.valid_count,
            "category_counts": [list(item) for item in self.category_counts],
            "unavailable_reasons": [list(item) for item in self.unavailable_reasons],
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """RD-22's stored report. It states no accuracy and no agreement figure."""

    rubric_hash: str
    provider_identity: JevProviderIdentity
    sample_hash: str
    sample_size: int
    shortfall_weeks: tuple[str, ...]
    fields: tuple[FieldSmokeResult, ...]
    input_coverage_counts: tuple[tuple[str, int], ...]
    latency_ms_total: int
    latency_ms_max: int
    cost_micros_total: int
    request_artifact_hashes: tuple[str, ...]
    response_artifact_hashes: tuple[str, ...]
    owner_review: OwnerReview | None
    valid_floor: int = SMOKE_VALID_FLOOR

    @property
    def fields_passed(self) -> bool:
        return all(field.passed for field in self.fields)

    @property
    def passed(self) -> bool:
        return self.fields_passed and self.owner_review is not None

    def to_dict(self) -> dict[str, Any]:
        review = self.owner_review
        return {
            "rubric_hash": self.rubric_hash,
            "provider_identity": self.provider_identity.to_dict(),
            "sample_hash": self.sample_hash,
            "sample_size": self.sample_size,
            "shortfall_weeks": list(self.shortfall_weeks),
            "fields": [field.to_dict() for field in self.fields],
            "input_coverage_counts": [list(i) for i in self.input_coverage_counts],
            "latency_ms_total": self.latency_ms_total,
            "latency_ms_max": self.latency_ms_max,
            "cost_micros_total": self.cost_micros_total,
            "request_artifact_hashes": list(self.request_artifact_hashes),
            "response_artifact_hashes": list(self.response_artifact_hashes),
            "owner_review": (
                None
                if review is None
                else {
                    "reviewer": review.reviewer,
                    "reviewed_at": review.reviewed_at,
                    "notes_hash": review.notes_hash,
                }
            ),
            "valid_floor": self.valid_floor,
        }

    def report_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


def smoke_test_rubric(
    sample: SmokeSample,
    observations: Sequence[SmokeObservation],
    *,
    rubric: JevRubric,
    provider_identity: JevProviderIdentity,
    owner_review: OwnerReview | None,
    valid_floor: int = SMOKE_VALID_FLOOR,
) -> SmokeReport:
    """Fold the stored outcomes of the sample's requests into a smoke report.

    Every sampled paper needs exactly one observation and no unsampled paper
    may appear. Every result must name the rubric and provider identity under
    test. A field passes with at least ``valid_floor`` schema-valid results;
    a shortfall sample is counted as it is, so its missing papers can only
    lower a field's count. Unavailable results add to reason counts and never
    to a category count.
    """

    sampled = {item.family_id for item in sample.selected}
    seen = [item.family_id for item in observations]
    if len(set(seen)) != len(seen) or set(seen) != sampled:
        raise MeasurementError(
            "observations must cover each sampled paper exactly once"
        )
    rubric_hash = rubric.rubric_hash
    valid: Counter[str] = Counter()
    categories: dict[str, Counter[str]] = {field: Counter() for field in FIELD_IDS}
    reasons: Counter[str] = Counter()
    coverage: Counter[str] = Counter()
    request_hashes: list[str] = []
    response_hashes: list[str] = []
    for observation in observations:
        result = observation.result
        if result.rubric_hash != rubric_hash:
            raise MeasurementError("a result was produced under another rubric")
        if (
            result.provider_identity is not None
            and result.provider_identity != provider_identity
        ):
            raise MeasurementError("a result was produced under another identity")
        coverage[observation.input_coverage] += 1
        if result.sanitized_request_hash is not None:
            request_hashes.append(result.sanitized_request_hash)
        if result.sanitized_response_hash is not None:
            response_hashes.append(result.sanitized_response_hash)
        if isinstance(result, JevAvailable):
            for field in result.fields:
                valid[field.field_id] += 1
                categories[field.field_id][field.selected_category] += 1
        else:
            reasons[result.reason] += 1
    fields = tuple(
        FieldSmokeResult(
            field_id=field_id,
            valid_count=valid[field_id],
            category_counts=tuple(
                (category, categories[field_id][category])
                for category in FIELD_CATEGORIES[field_id]
            ),
            unavailable_reasons=tuple(sorted(reasons.items())),
            passed=valid[field_id] >= valid_floor,
        )
        for field_id in FIELD_IDS
    )
    return SmokeReport(
        rubric_hash=rubric_hash,
        provider_identity=provider_identity,
        sample_hash=sample.sample_hash(),
        sample_size=len(sample.selected),
        shortfall_weeks=sample.shortfall_weeks,
        fields=fields,
        input_coverage_counts=tuple((name, coverage[name]) for name in _INPUT_COVERAGE),
        latency_ms_total=sum(item.latency_ms for item in observations),
        latency_ms_max=max((item.latency_ms for item in observations), default=0),
        cost_micros_total=sum(item.cost_micros for item in observations),
        request_artifact_hashes=tuple(request_hashes),
        response_artifact_hashes=tuple(response_hashes),
        owner_review=owner_review,
        valid_floor=valid_floor,
    )


class SmokeActivationRefused(Exception):
    """Activation is refused; ``reasons`` names every unmet condition."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("smoke test does not permit activation: " + ", ".join(reasons))
        self.reasons = reasons


def check_smoke_activation(
    report: SmokeReport | None,
    *,
    rubric_hash: str,
    provider_identity: JevProviderIdentity,
) -> str:
    """Return the report hash a snapshot may pin, or refuse activation.

    Refuses with no report, a field below the floor, a missing owner review
    and a rubric or provider identity that differs from the report's. A
    changed identity needs a fresh smoke test; nothing here repairs it.
    """

    if report is None:
        raise SmokeActivationRefused(("smoke_test_missing",))
    reasons: list[str] = []
    for field in report.fields:
        if not field.passed:
            reasons.append(f"field_below_floor:{field.field_id}")
    if report.owner_review is None:
        reasons.append("owner_review_missing")
    if report.rubric_hash != rubric_hash:
        reasons.append("rubric_changed")
    if report.provider_identity != provider_identity:
        reasons.append("identity_changed")
    if reasons:
        raise SmokeActivationRefused(tuple(reasons))
    return report.report_hash()


#: Appendix A: the primary endpoint, and the fixed size and reach of the study.
BENEFIT_PRIMARY_METRIC = "citation_reach_365d_brier"
BENEFIT_FAMILIES = 2000
BENEFIT_MIN_WEEKS = 26
#: Share of registered families that must have a matched pair of resolved forecasts.
BENEFIT_MIN_SUPPORT = 0.70
#: Absolute Brier improvement the with-Jev arm must show.
BENEFIT_MIN_GAIN = 0.01
ARMS = ("with_jev", "without_jev")
_EXPOSURES = ("delivered", "unavailable")
_VERDICTS = ("pending", "passed", "failed", "inconclusive")


@dataclass(frozen=True, slots=True)
class BenefitFamily:
    """One eligible paper family, with the instant its maturity clock starts."""

    family_id: str
    publication_week: str
    first_public_at: str

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        validate_non_empty_string(self.publication_week)
        validate_utc_instant(self.first_public_at)


@dataclass(frozen=True, slots=True)
class BenefitAllocation:
    """The frozen allocation: the first eligible families and the weeks they span."""

    selected: tuple[BenefitFamily, ...]
    weeks: tuple[str, ...]
    sample_size: int
    min_weeks: int

    @property
    def complete(self) -> bool:
        return (
            len(self.selected) == self.sample_size and len(self.weeks) >= self.min_weeks
        )

    def allocation_hash(self) -> str:
        return sha256_hex(
            canonical_json(
                [
                    [item.family_id, item.publication_week, item.first_public_at]
                    for item in self.selected
                ]
            )
        )


@dataclass(frozen=True, slots=True)
class PairedOutcome:
    """One family's pair: assigned order, actual exposure and resolved losses.

    A loss is ``None`` when that arm produced no resolved forecast. Exposure
    describes the with-Jev arm only; ``unavailable`` needs its reason and the
    pair stays in the assigned-treatment analysis.
    """

    question_id: str
    family_id: str
    assigned_first: str
    exposure: str
    unavailable_reason: str | None
    with_run_id: str | None
    with_loss: float | None
    without_run_id: str | None
    without_loss: float | None

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_uuid4(self.family_id)
        if self.assigned_first not in ARMS:
            raise MeasurementError("assigned arm is not admitted")
        if self.exposure not in _EXPOSURES:
            raise MeasurementError("exposure is not admitted")
        if (self.exposure == "unavailable") != (self.unavailable_reason is not None):
            raise MeasurementError("an unavailable exposure names its reason")
        for run_id, loss in (
            (self.with_run_id, self.with_loss),
            (self.without_run_id, self.without_loss),
        ):
            if (run_id is None) != (loss is None):
                raise MeasurementError("a resolved forecast has both its run and loss")


@dataclass(frozen=True, slots=True)
class BenefitReport:
    """The study's reading: a verdict, its reason and the support behind it."""

    study_id: str
    verdict: str
    reason: str
    registered_families: int
    matched_families: int
    matched_support: float
    delivered: int
    unavailable: int
    estimate: float | None
    low: float | None
    high: float | None
    gain: float | None
    matures_at: str | None

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICTS:
            raise MeasurementError("verdict is not admitted")
        if self.verdict == "pending" and (
            self.estimate is not None or self.gain is not None
        ):
            raise MeasurementError("a pending study reports no effect")


@dataclass(slots=True)
class _Difference:
    """A matched pair's difference in the shape the shared bootstrap reads."""

    publication_week: str
    family_id: str
    difference: float


def validate_benefit_registration(registration: ComparisonRegistration) -> None:
    """Refuse a registration that does not freeze Appendix A's comparison."""

    primary = registration.primary_endpoint
    if primary.metric != BENEFIT_PRIMARY_METRIC or primary.direction != "lower":
        raise MeasurementError(
            "the Jev benefit study's primary endpoint is the citation-reach Brier score"
        )
    if registration.sample_size != BENEFIT_FAMILIES:
        raise MeasurementError("the Jev benefit study registers 2000 families")
    if registration.minimum_effect != BENEFIT_MIN_GAIN:
        raise MeasurementError("the Jev benefit study's minimum effect is 0.01")
    if registration.failure_handling != "count_as_failure":
        raise MeasurementError("failed Jev delivery stays in the assigned analysis")
    if registration.exploratory_of is not None:
        raise MeasurementError("an exploratory registration cannot gate launch")


class JevBenefitStudy:
    """The registered paired comparison of forecasts with and without Jev (RD-23).

    The registration must freeze the endpoint, size, minimum effect and failure
    handling of Appendix A. Comparison runs are not population runs: nothing
    here yields a parent or a selection fitness.
    """

    def __init__(self, registration: ComparisonRegistration, *, seed: int) -> None:
        validate_benefit_registration(registration)
        validate_non_negative_int(seed)
        self.registration = registration
        self.seed = seed

    @property
    def study_id(self) -> str:
        return self.registration.registration_id

    def arm_order(self, family_id: str) -> tuple[str, str]:
        """The randomized execution order of a family's two arms, from the seed."""

        digest = sha256_hex(
            canonical_json(
                {"study_id": self.study_id, "seed": self.seed, "family_id": family_id}
            )
        )
        return ARMS if int(digest[-1], 16) % 2 == 0 else (ARMS[1], ARMS[0])

    def allocate(self, eligible: Sequence[BenefitFamily]) -> BenefitAllocation:
        """Take the first ``sample_size`` eligible families in publication order.

        Order is publication week, then the seeded selection hash; the result
        does not depend on input order. A short or too-narrow allocation is
        returned as it is and reads as incomplete, never padded.
        """

        ids = [item.family_id for item in eligible]
        if len(set(ids)) != len(ids):
            raise MeasurementError("eligible families must not repeat")
        ranked = sorted(
            eligible,
            key=lambda item: (
                item.publication_week,
                selection_hash(item.family_id, self.seed),
                item.family_id,
            ),
        )
        selected = tuple(ranked[: self.registration.sample_size])
        return BenefitAllocation(
            selected=selected,
            weeks=tuple(sorted({item.publication_week for item in selected})),
            sample_size=self.registration.sample_size,
            min_weeks=BENEFIT_MIN_WEEKS,
        )

    def evaluate(
        self,
        allocation: BenefitAllocation,
        outcomes: Sequence[PairedOutcome],
        *,
        as_of: str,
    ) -> BenefitReport:
        """Read the study as of ``as_of``; nothing is concluded before maturity.

        Every pair with both resolved forecasts enters the comparison as
        assigned, including a with-Jev run whose delivery failed. Pairs
        missing a side lower the matched support and are never imputed.
        """

        by_family = {item.family_id: item for item in allocation.selected}
        seen = [item.family_id for item in outcomes]
        if len(set(seen)) != len(seen) or not set(seen) <= set(by_family):
            raise MeasurementError(
                "outcomes must name each allocated family at most once"
            )
        matures = (
            max(maturity_at(item.first_public_at) for item in allocation.selected)
            if allocation.selected
            else None
        )
        delivered = sum(item.exposure == "delivered" for item in outcomes)
        unavailable = len(outcomes) - delivered

        def report(verdict: str, reason: str, **values: Any) -> BenefitReport:
            fields: dict[str, Any] = {
                "matched_families": 0,
                "matched_support": 0.0,
                "estimate": None,
                "low": None,
                "high": None,
                "gain": None,
            }
            fields.update(values)
            return BenefitReport(
                study_id=self.study_id,
                verdict=verdict,
                reason=reason,
                registered_families=allocation.sample_size,
                delivered=delivered,
                unavailable=unavailable,
                matures_at=matures,
                **fields,
            )

        if not allocation.complete:
            return report("pending", "allocation_incomplete")
        assert matures is not None
        if instant(as_of) < instant(matures):
            return report("pending", "outcomes_immature")

        candidate: list[ForecastObservation] = []
        baseline: list[ForecastObservation] = []
        for item in outcomes:
            if item.with_loss is None or item.without_loss is None:
                continue
            assert item.with_run_id is not None and item.without_run_id is not None
            week = by_family[item.family_id].publication_week
            candidate.append(
                ForecastObservation(
                    item.question_id,
                    item.with_run_id,
                    item.family_id,
                    week,
                    item.with_loss,
                )
            )
            baseline.append(
                ForecastObservation(
                    item.question_id,
                    item.without_run_id,
                    item.family_id,
                    week,
                    item.without_loss,
                )
            )
        matched = paired_forecast_rows(candidate, baseline)
        support = matched.matched_count / allocation.sample_size
        if support < BENEFIT_MIN_SUPPORT:
            return report(
                "inconclusive",
                "matched_support_below_floor",
                matched_families=matched.matched_count,
                matched_support=support,
            )
        weeks: dict[str, set[str]] = {}
        for family in allocation.selected:
            weeks.setdefault(family.publication_week, set()).add(family.family_id)
        interval = bootstrap_difference(
            [
                _Difference(row.publication_week, row.family_id, row.difference)
                for row in matched.rows
            ],
            {week: frozenset(ids) for week, ids in weeks.items()},
            lower_tail=2.5,
            upper_tail=97.5,
        )
        shared: dict[str, Any] = {
            "matched_families": matched.matched_count,
            "matched_support": support,
            "estimate": interval.estimate,
            "low": interval.low,
            "high": interval.high,
        }
        if interval.estimate is None:
            return report("inconclusive", "interval_unavailable", **shared)
        gain = -interval.estimate
        shared["gain"] = gain
        direction = interval_verdict(
            interval.low, interval.high, favorable_direction="lower"
        ).verdict
        if direction == "inconclusive":
            return report("inconclusive", "interval_spans_zero", **shared)
        if direction == "unfavorable":
            return report("failed", "with_jev_worse", **shared)
        if gain < BENEFIT_MIN_GAIN:
            return report("failed", "gain_below_minimum", **shared)
        return report("passed", "criteria_met", **shared)
