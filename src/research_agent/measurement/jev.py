"""The Jev rubric smoke test (SDD RD-22, TDD-4.1.60).

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
from research_agent.learning.corpus import SELECTION_SEED, selection_hash
from research_agent.measurement import MeasurementError

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
