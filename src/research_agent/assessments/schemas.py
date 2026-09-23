"""Strict assessment results in three primitives (RD-18, TDD-4.1.56).

An assessment result is either available, with all eight fields of its
rubric version, or unavailable with a reason and no numbers at all. A
`choice` field carries its selected category, the full ordered probability
distribution and the provider's confidence; a `score` field its score, the
legend of its scale, the distribution over scale points and the confidence;
a `noul` field the probability that its statement is true, and the
statement. Validation of a provider answer is all-or-nothing: a missing or
extra field, an unknown category, a legend that differs from the question's
criteria, a nonfinite or negative probability, a noul outside [0, 1], or a
sum outside the provider's rounding makes the whole assessment invalid.
Nothing is renormalized, no argmax is recomputed over the provider's
answer, and low confidence or an `insufficient_information` answer stays a
valid result.

A stored choice field has no `type` key, as v1 stored it; score and noul
fields name theirs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from research_agent.contracts.assessments import (
    BILLING_STATES,
    FIELD_CATEGORIES,
    RUBRIC_FIELD_IDS,
    SCORE_POINTS,
    UNAVAILABLE_REASONS,
    JevAssessmentInput,
    JevProviderIdentity,
    JevRubric,
    NoulQuestion,
    RubricQuestion,
    ScoreQuestion,
    field_primitive,
    rubric_field_ids,
    validate_category,
)
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
)

__all__ = [
    "PROBABILITY_TOLERANCE",
    "InvalidResponse",
    "CategoryProbability",
    "JevFieldResult",
    "JevScoreResult",
    "JevNoulResult",
    "FieldResult",
    "fields_version",
    "JevAvailable",
    "JevUnavailable",
    "AssessmentResult",
    "JevAttemptRecord",
    "fields_to_dict",
    "fields_from_dict",
    "result_hash",
    "parse_field_answers",
    "result_from_json",
]

# The provider rounds each probability to two decimals (checked 2026-09-23 on
# jev-1.13.0), so a distribution over up to eight categories can sum to 0.99
# or 1.01. Rounding within this is absorbed; the values are recorded as sent
# and never renormalized, and anything past it is refused.
PROBABILITY_TOLERANCE = 0.05

# The decoded answer for one Choice question: the selected option, a
# probability for every option and a confidence in [0, 1] (#59's capability
# evidence). These wire keys are the adapter's reading of that evidence.
# A live answer (checked 2026-09-23 against jev-1.13.0) carries `type`,
# `choice`, `confidence` and `probabilities`; `type` names the primitive and
# must be `choice`, and `confidence` may be absent.
_ANSWER_KEYS = frozenset({"type", "choice", "probabilities", "confidence"})
_ANSWER_KEYS_NO_CONFIDENCE = frozenset({"type", "choice", "probabilities"})
_ANSWER_KEYS_UNTYPED = frozenset({"choice", "probabilities", "confidence"})
_ANSWER_KEYS_UNTYPED_NO_CONFIDENCE = frozenset({"choice", "probabilities"})
# The other two primitives, checked live the same day: a `score` answer names
# its score, a legend echoing the question's criteria keyed by scale point and
# a probability per point, with a confidence that may be absent; a `noul`
# answer is the probability of yes alone.
_SCORE_KEYS = frozenset({"type", "score", "legend", "probabilities", "confidence"})
_SCORE_KEYS_NO_CONFIDENCE = frozenset({"type", "score", "legend", "probabilities"})
_NOUL_KEYS = frozenset({"type", "noul"})


class InvalidResponse(Exception):
    """A provider answer failed validation; the assessment is unavailable."""


def _check_distribution(probabilities: tuple[float, ...]) -> None:
    total = 0.0
    for probability in probabilities:
        validate_probability(probability)
        total += probability
    if abs(total - 1.0) > PROBABILITY_TOLERANCE:
        raise ContractValidationError(
            "distribution must sum to one within the provider's rounding"
        )


@dataclass(frozen=True, slots=True)
class CategoryProbability:
    category_id: str
    probability: float

    def to_dict(self) -> dict[str, Any]:
        return {"category_id": self.category_id, "probability": self.probability}


@dataclass(frozen=True, slots=True)
class JevFieldResult:
    """One field's valid answer; confidence is a distribution summary, not accuracy."""

    field_id: str
    selected_category: str
    distribution: tuple[CategoryProbability, ...]
    provider_confidence: float | None

    def __post_init__(self) -> None:
        if field_primitive(self.field_id) != "choice":
            raise ContractValidationError(f"{self.field_id} is not a choice field")
        validate_category(self.field_id, self.selected_category)
        categories = FIELD_CATEGORIES[self.field_id]
        if tuple(item.category_id for item in self.distribution) != categories:
            raise ContractValidationError(
                "distribution must list every category of its field, in order"
            )
        _check_distribution(tuple(item.probability for item in self.distribution))
        if self.provider_confidence is not None:
            validate_probability(self.provider_confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "selected_category": self.selected_category,
            "distribution": [item.to_dict() for item in self.distribution],
            "provider_confidence": self.provider_confidence,
        }

    @classmethod
    def from_dict(cls, value: object) -> "JevFieldResult":
        if not isinstance(value, dict) or set(value) != set(cls.__slots__):
            raise ContractValidationError("JevFieldResult keys differ")
        distribution = value["distribution"]
        if not isinstance(distribution, list):
            raise ContractValidationError("distribution must be an array")
        entries = []
        for entry in distribution:
            if not isinstance(entry, dict) or set(entry) != {
                "category_id",
                "probability",
            }:
                raise ContractValidationError("CategoryProbability keys differ")
            entries.append(
                CategoryProbability(entry["category_id"], entry["probability"])
            )
        return cls(
            value["field_id"],
            value["selected_category"],
            tuple(entries),
            value["provider_confidence"],
        )


@dataclass(frozen=True, slots=True)
class JevScoreResult:
    """One `score` field's valid answer: a point on the field's ordered scale.

    `legend` is the scale as the provider returned it, one criterion per
    point, already checked against the question; `distribution` is one
    probability per point, in point order.
    """

    field_id: str
    score: int
    legend: tuple[str, ...]
    distribution: tuple[float, ...]
    provider_confidence: float | None
    type: str = "score"

    def __post_init__(self) -> None:
        if self.type != "score" or field_primitive(self.field_id) != "score":
            raise ContractValidationError(f"{self.field_id} is not a score field")
        points = SCORE_POINTS[self.field_id]
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, int)
            or not 0 <= self.score < points
        ):
            raise ContractValidationError("score must be a point on the field's scale")
        if len(self.legend) != points:
            raise ContractValidationError("legend must name every scale point")
        for line in self.legend:
            validate_non_empty_string(line)
        if len(self.distribution) != points:
            raise ContractValidationError(
                "distribution must give every scale point, in order"
            )
        _check_distribution(self.distribution)
        if self.provider_confidence is not None:
            validate_probability(self.provider_confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "field_id": self.field_id,
            "score": self.score,
            "legend": list(self.legend),
            "distribution": list(self.distribution),
            "provider_confidence": self.provider_confidence,
        }

    @classmethod
    def from_dict(cls, value: object) -> "JevScoreResult":
        if not isinstance(value, dict) or set(value) != set(cls.__slots__):
            raise ContractValidationError("JevScoreResult keys differ")
        for name in ("legend", "distribution"):
            if not isinstance(value[name], list):
                raise ContractValidationError(f"{name} must be an array")
        return cls(
            **{
                **value,
                "legend": tuple(value["legend"]),
                "distribution": tuple(value["distribution"]),
            }
        )


@dataclass(frozen=True, slots=True)
class JevNoulResult:
    """One `noul` field's valid answer: the probability its statement is true."""

    field_id: str
    probability: float
    statement: str
    type: str = "noul"

    def __post_init__(self) -> None:
        if self.type != "noul" or field_primitive(self.field_id) != "noul":
            raise ContractValidationError(f"{self.field_id} is not a noul field")
        validate_probability(self.probability)
        validate_non_empty_string(self.statement)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "field_id": self.field_id,
            "probability": self.probability,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: object) -> "JevNoulResult":
        if not isinstance(value, dict) or set(value) != set(cls.__slots__):
            raise ContractValidationError("JevNoulResult keys differ")
        return cls(**value)


FieldResult = JevFieldResult | JevScoreResult | JevNoulResult


def _field_from_dict(value: object) -> FieldResult:
    kind = value.get("type") if isinstance(value, dict) else None
    if kind == "score":
        return JevScoreResult.from_dict(value)
    if kind == "noul":
        return JevNoulResult.from_dict(value)
    return JevFieldResult.from_dict(value)


def fields_to_dict(fields: tuple[FieldResult, ...]) -> dict[str, Any]:
    return {item.field_id: item.to_dict() for item in fields}


def fields_version(fields: tuple[FieldResult, ...]) -> str:
    """The rubric version whose eight fields, in order, these are."""

    if not all(
        isinstance(item, (JevFieldResult, JevScoreResult, JevNoulResult))
        for item in fields
    ):
        raise ContractValidationError("fields must be Jev field results")
    field_ids = tuple(item.field_id for item in fields)
    for version, expected in RUBRIC_FIELD_IDS.items():
        if field_ids == expected:
            return version
    raise ContractValidationError("fields must be exactly one rubric's eight fields")


def fields_from_dict(
    value: object, version: str | None = None
) -> tuple[FieldResult, ...]:
    """Decode a stored field map; `version`, when known, must be the map's."""

    if not isinstance(value, dict):
        raise ContractValidationError("fields must be an object")
    candidates = (
        (rubric_field_ids(version),)
        if version is not None
        else tuple(RUBRIC_FIELD_IDS.values())
    )
    field_ids = next((ids for ids in candidates if sorted(ids) == sorted(value)), None)
    if field_ids is None:
        raise ContractValidationError(
            "fields must be exactly one rubric's eight fields"
        )
    results = []
    for field_id in field_ids:
        result = _field_from_dict(value[field_id])
        if result.field_id != field_id:
            raise ContractValidationError("field_id must equal its map key")
        results.append(result)
    return tuple(results)


@dataclass(frozen=True, slots=True)
class JevAvailable:
    """A valid eight-field assessment with its input, rubric and provider provenance.

    `smoke_report_hash` is null only for engineering or smoke-test processing
    artifacts; such a result cannot enter a study paper card.
    """

    fields: tuple[FieldResult, ...]
    input_hash: str
    rubric_hash: str
    provider_identity: JevProviderIdentity
    sanitized_request_hash: str
    sanitized_response_hash: str
    computed_at: str
    smoke_report_hash: str | None
    status: str = "available"

    def __post_init__(self) -> None:
        if self.status != "available":
            raise ContractValidationError("status must be available")
        fields_version(self.fields)
        for value in (
            self.input_hash,
            self.rubric_hash,
            self.sanitized_request_hash,
            self.sanitized_response_hash,
        ):
            validate_sha256(value)
        if not isinstance(self.provider_identity, JevProviderIdentity):
            raise ContractValidationError(
                "provider_identity must be a JevProviderIdentity"
            )
        validate_utc_instant(self.computed_at)
        if self.smoke_report_hash is not None:
            validate_sha256(self.smoke_report_hash)

    def field(self, field_id: str) -> FieldResult:
        for item in self.fields:
            if item.field_id == field_id:
                return item
        raise ContractValidationError(f"the assessment has no {field_id} field")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fields": fields_to_dict(self.fields),
            "input_hash": self.input_hash,
            "rubric_hash": self.rubric_hash,
            "provider_identity": self.provider_identity.to_dict(),
            "sanitized_request_hash": self.sanitized_request_hash,
            "sanitized_response_hash": self.sanitized_response_hash,
            "computed_at": self.computed_at,
            "smoke_report_hash": self.smoke_report_hash,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class JevUnavailable:
    """A processing failure: a reason, never fabricated categories or numbers."""

    reason: str
    input_hash: str | None
    rubric_hash: str
    provider_identity: JevProviderIdentity | None
    sanitized_request_hash: str | None
    sanitized_response_hash: str | None
    billing_state: str
    recorded_at: str
    status: str = "unavailable"

    def __post_init__(self) -> None:
        if self.status != "unavailable":
            raise ContractValidationError("status must be unavailable")
        if self.reason not in UNAVAILABLE_REASONS:
            raise ContractValidationError(
                "reason is not an admitted unavailable reason"
            )
        for value in (
            self.input_hash,
            self.sanitized_request_hash,
            self.sanitized_response_hash,
        ):
            if value is not None:
                validate_sha256(value)
        validate_sha256(self.rubric_hash)
        if self.provider_identity is not None and not isinstance(
            self.provider_identity, JevProviderIdentity
        ):
            raise ContractValidationError(
                "provider_identity must be a JevProviderIdentity"
            )
        if self.billing_state not in BILLING_STATES:
            raise ContractValidationError("billing_state is not admitted")
        validate_utc_instant(self.recorded_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "input_hash": self.input_hash,
            "rubric_hash": self.rubric_hash,
            "provider_identity": (
                None
                if self.provider_identity is None
                else self.provider_identity.to_dict()
            ),
            "sanitized_request_hash": self.sanitized_request_hash,
            "sanitized_response_hash": self.sanitized_response_hash,
            "billing_state": self.billing_state,
            "recorded_at": self.recorded_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


AssessmentResult = JevAvailable | JevUnavailable


def result_from_json(raw: bytes) -> AssessmentResult:
    """Decode a stored result, refusing any key its status does not define."""

    try:
        loaded = canonical_loads(raw)
    except CanonicalJsonError as error:
        raise ContractValidationError(str(error)) from error
    if not isinstance(loaded, dict):
        raise ContractValidationError("an assessment result must be an object")
    value: dict[str, Any] = loaded
    status = value.get("status")
    if status == "available":
        keys = set(JevAvailable.__slots__)
        if set(value) != keys:
            raise ContractValidationError("JevAvailable keys differ")
        return JevAvailable(
            fields=fields_from_dict(value["fields"]),
            input_hash=value["input_hash"],
            rubric_hash=value["rubric_hash"],
            provider_identity=JevProviderIdentity.from_dict(value["provider_identity"]),
            sanitized_request_hash=value["sanitized_request_hash"],
            sanitized_response_hash=value["sanitized_response_hash"],
            computed_at=value["computed_at"],
            smoke_report_hash=value["smoke_report_hash"],
        )
    if status == "unavailable":
        if set(value) != set(JevUnavailable.__slots__):
            raise ContractValidationError("JevUnavailable keys differ")
        identity = value["provider_identity"]
        return JevUnavailable(
            reason=value["reason"],
            input_hash=value["input_hash"],
            rubric_hash=value["rubric_hash"],
            provider_identity=(
                None if identity is None else JevProviderIdentity.from_dict(identity)
            ),
            sanitized_request_hash=value["sanitized_request_hash"],
            sanitized_response_hash=value["sanitized_response_hash"],
            billing_state=value["billing_state"],
            recorded_at=value["recorded_at"],
        )
    raise ContractValidationError("status must be available or unavailable")


@dataclass(frozen=True, slots=True)
class JevAttemptRecord:
    """The committed provenance of one assessment attempt (RD-19).

    It names the exact input, the rubric version, the request and response
    artifacts, when the request was sent and answered, how many provider
    attempts were made and the result artifact. The time the result became
    available to snapshots is storage's commit time, kept apart from
    `completed_at`, the provider's computation time.
    """

    work_key: str
    input: JevAssessmentInput
    rubric_version: str
    result_artifact_hash: str
    request_artifact_hash: str | None
    response_artifact_hash: str | None
    requested_at: str | None
    completed_at: str
    attempts: int

    def __post_init__(self) -> None:
        validate_sha256(self.work_key)
        validate_non_empty_string(self.rubric_version)
        validate_sha256(self.result_artifact_hash)
        for value in (self.request_artifact_hash, self.response_artifact_hash):
            if value is not None:
                validate_sha256(value)
        if self.requested_at is not None:
            validate_utc_instant(self.requested_at)
        validate_utc_instant(self.completed_at)
        validate_non_negative_int(self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_key": self.work_key,
            "input": self.input.to_dict(),
            "rubric_version": self.rubric_version,
            "result_artifact_hash": self.result_artifact_hash,
            "request_artifact_hash": self.request_artifact_hash,
            "response_artifact_hash": self.response_artifact_hash,
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "JevAttemptRecord":
        try:
            loaded = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise ContractValidationError(str(error)) from error
        if not isinstance(loaded, dict) or set(loaded) != set(cls.__slots__):
            raise ContractValidationError("JevAttemptRecord keys differ")
        value: dict[str, Any] = loaded
        return cls(**{**value, "input": JevAssessmentInput.from_dict(value["input"])})


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidResponse("a probability is not a number")
    if not math.isfinite(value):
        raise InvalidResponse("a probability is not finite")
    return float(value)


def _choice_answer(field_id: str, answer: object) -> JevFieldResult:
    if not isinstance(answer, dict) or frozenset(answer) not in (
        _ANSWER_KEYS,
        _ANSWER_KEYS_NO_CONFIDENCE,
        _ANSWER_KEYS_UNTYPED,
        _ANSWER_KEYS_UNTYPED_NO_CONFIDENCE,
    ):
        raise InvalidResponse(f"{field_id}: answer keys differ")
    if "type" in answer and answer["type"] != "choice":
        raise InvalidResponse(f"{field_id}: answer is not a choice")
    probabilities = answer["probabilities"]
    categories = FIELD_CATEGORIES[field_id]
    if not isinstance(probabilities, dict) or set(probabilities) != set(categories):
        raise InvalidResponse(f"{field_id}: probabilities must name every category")
    confidence = answer.get("confidence")
    try:
        return JevFieldResult(
            field_id=field_id,
            selected_category=answer["choice"],
            distribution=tuple(
                CategoryProbability(category, _number(probabilities[category]))
                for category in categories
            ),
            provider_confidence=None if confidence is None else _number(confidence),
        )
    except ContractValidationError as error:
        raise InvalidResponse(f"{field_id}: {error}") from error


def _score_answer(question: ScoreQuestion, answer: object) -> JevScoreResult:
    field_id = question.field_id
    if not isinstance(answer, dict) or frozenset(answer) not in (
        _SCORE_KEYS,
        _SCORE_KEYS_NO_CONFIDENCE,
    ):
        raise InvalidResponse(f"{field_id}: answer keys differ")
    if answer["type"] != "score":
        raise InvalidResponse(f"{field_id}: answer is not a score")
    points = tuple(str(point) for point in range(len(question.criteria)))
    legend = answer["legend"]
    if not isinstance(legend, dict) or set(legend) != set(points):
        raise InvalidResponse(f"{field_id}: legend must name every scale point")
    if tuple(legend[point] for point in points) != question.criteria:
        raise InvalidResponse(
            f"{field_id}: legend differs from the question's criteria"
        )
    probabilities = answer["probabilities"]
    if not isinstance(probabilities, dict) or set(probabilities) != set(points):
        raise InvalidResponse(f"{field_id}: probabilities must name every scale point")
    confidence = answer.get("confidence")
    try:
        return JevScoreResult(
            field_id=field_id,
            score=answer["score"],
            legend=question.criteria,
            distribution=tuple(_number(probabilities[point]) for point in points),
            provider_confidence=None if confidence is None else _number(confidence),
        )
    except ContractValidationError as error:
        raise InvalidResponse(f"{field_id}: {error}") from error


def _noul_answer(question: NoulQuestion, answer: object) -> JevNoulResult:
    field_id = question.field_id
    if not isinstance(answer, dict) or frozenset(answer) != _NOUL_KEYS:
        raise InvalidResponse(f"{field_id}: answer keys differ")
    if answer["type"] != "noul":
        raise InvalidResponse(f"{field_id}: answer is not a noul")
    try:
        return JevNoulResult(
            field_id=field_id,
            probability=_number(answer["noul"]),
            statement=question.statement,
        )
    except ContractValidationError as error:
        raise InvalidResponse(f"{field_id}: {error}") from error


def parse_field_answers(answers: object, rubric: JevRubric) -> tuple[FieldResult, ...]:
    """Validate the eight decoded answers to `rubric` all-or-nothing.

    Each answer must be in its question's primitive. Raises
    :class:`InvalidResponse` on any defect; never returns a partial rubric
    or a repaired distribution.
    """

    if not isinstance(answers, dict):
        raise InvalidResponse("answers must be an object")
    if set(answers) != set(rubric.field_ids):
        raise InvalidResponse("answers must name exactly the eight rubric fields")
    results: list[FieldResult] = []
    for question in rubric.questions:
        answer = answers[question.field_id]
        if isinstance(question, RubricQuestion):
            results.append(_choice_answer(question.field_id, answer))
        elif isinstance(question, ScoreQuestion):
            results.append(_score_answer(question, answer))
        else:
            results.append(_noul_answer(question, answer))
    return tuple(results)


def result_hash(result: AssessmentResult) -> str:
    """The content identity of a stored result artifact."""

    return sha256_hex(result.to_canonical_json())
