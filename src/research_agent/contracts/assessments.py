"""Jev enums, rubric records, provider identity and assessment input (RD-16 to RD-19).

Category ids are the stable spellings of the RD-16 categories fixed in the
TDD's Jev eight-field records. Each field has exactly its own enum and no
category is borrowed from another field: `JevCategory` is the union, but
every record validates membership in its own field's enum.

A field id names one primitive and one scale in every rubric version that
asks it: `choice` fields carry their categories, `score` fields their number
of scale points and `noul` fields a probability. Each version fixes its
eight field ids in order; `jev-rubric-v1` stays defined so stored v1
assessments still load, and `jev-rubric-v2` is the launch set.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .canonical import CanonicalJsonError, canonical_json, canonical_loads, sha256_hex
from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

__all__ = [
    "JEV_SOURCE_LABEL",
    "JEV_PROVIDER",
    "V1_RUBRIC_VERSION",
    "V2_RUBRIC_VERSION",
    "FIELD_IDS",
    "V1_FIELD_IDS",
    "RUBRIC_FIELD_IDS",
    "FIELD_CATEGORIES",
    "SCORE_POINTS",
    "NOUL_FIELDS",
    "UNAVAILABLE_REASONS",
    "BILLING_STATES",
    "IDENTITY_KINDS",
    "MAX_STATE_TEXT_BYTES",
    "RubricExample",
    "RubricQuestion",
    "ScoreQuestion",
    "NoulQuestion",
    "AnyQuestion",
    "JevRubric",
    "JevProviderIdentity",
    "JevAssessmentInput",
    "field_primitive",
    "rubric_field_ids",
    "validate_field_id",
    "validate_category",
]

V1_RUBRIC_VERSION = "jev-rubric-v1"
V2_RUBRIC_VERSION = "jev-rubric-v2"

JEV_SOURCE_LABEL = "Jev paper-content assessment"
JEV_PROVIDER = "typesafe"

#: Appendix A: at most 128 KiB of UTF-8 state text, before the lower
#: verified provider limit is applied.
MAX_STATE_TEXT_BYTES = 131072

_PRESENCE = (
    "reported",
    "explicitly_absent",
    "not_reported",
    "not_applicable",
    "insufficient_information",
)

FIELD_CATEGORIES: Mapping[str, tuple[str, ...]] = {
    "primary_contribution": (
        "method_system",
        "dataset_resource",
        "benchmark_evaluation_method",
        "theoretical_result",
        "empirical_analysis_replication",
        "synthesis_survey",
        "mixed_other",
        "insufficient_information",
    ),
    "comparative_evaluation": _PRESENCE,
    "ablation_component_analysis": _PRESENCE,
    "uncertainty_reporting": _PRESENCE,
    "theoretical_support": (
        "proof_or_derivation_supplied",
        "support_elsewhere",
        "not_reported",
        "not_applicable",
        "insufficient_information",
    ),
    "evaluation_beyond_main_setting": (
        "reported",
        "explicitly_limited_to_main_setting",
        "not_reported",
        "not_applicable",
        "insufficient_information",
    ),
    "artifact_availability_statement": (
        "claimed_available",
        "future_only",
        "explicitly_unavailable",
        "not_reported",
        "not_applicable",
        "insufficient_information",
    ),
    "limitations_disclosure": (
        "concrete_limitation",
        "generic_caveats_only",
        "not_reported",
        "insufficient_information",
    ),
}

#: `score` fields and their number of scale points, 0 through n - 1.
SCORE_POINTS: Mapping[str, int] = {
    "evaluation_rigor": 5,
    "limitations_candor": 4,
    "novelty_as_claimed": 4,
}

#: `noul` fields: one probability that the field's statement is true.
NOUL_FIELDS: tuple[str, ...] = (
    "claims_supported_by_evidence",
    "reproducible_from_materials",
    "generalizes_beyond_main_setting",
    "open_problems_stated",
)

V1_FIELD_IDS: tuple[str, ...] = tuple(FIELD_CATEGORIES)
FIELD_IDS: tuple[str, ...] = (
    "primary_contribution",
    *SCORE_POINTS,
    *NOUL_FIELDS,
)
RUBRIC_FIELD_IDS: Mapping[str, tuple[str, ...]] = {
    V1_RUBRIC_VERSION: V1_FIELD_IDS,
    V2_RUBRIC_VERSION: FIELD_IDS,
}

UNAVAILABLE_REASONS = frozenset(
    {
        "missing_input",
        "input_too_large",
        "smoke_test_missing",
        "permission_missing",
        "provider_failure",
        "timeout_ambiguous",
        "budget_exhausted",
        "invalid_response",
        "identity_changed",
        "smoke_test_required",
    }
)
BILLING_STATES = frozenset(
    {"no_attempt", "known_rejected", "known_completed", "uncertain"}
)
IDENTITY_KINDS = frozenset({"immutable_revision", "mutable_alias", "not_disclosed"})
_EXAMPLE_KINDS = frozenset({"positive", "boundary"})
_INPUT_COVERAGE = frozenset({"complete", "partial", "unavailable"})


def validate_field_id(value: object) -> str:
    if not isinstance(value, str) or not (
        value in FIELD_CATEGORIES or value in SCORE_POINTS or value in NOUL_FIELDS
    ):
        raise ContractValidationError("field_id is not a Jev rubric field")
    return value


def field_primitive(field_id: str) -> str:
    """The one primitive a field id is asked as, in every rubric version."""

    validate_field_id(field_id)
    if field_id in FIELD_CATEGORIES:
        return "choice"
    return "score" if field_id in SCORE_POINTS else "noul"


def rubric_field_ids(version: object) -> tuple[str, ...]:
    """The eight field ids, in order, that a rubric version asks."""

    if not isinstance(version, str) or version not in RUBRIC_FIELD_IDS:
        raise ContractValidationError("version is not a defined Jev rubric version")
    return RUBRIC_FIELD_IDS[version]


def validate_category(field_id: str, value: object) -> str:
    if field_id not in FIELD_CATEGORIES:
        raise ContractValidationError(f"{field_id} is not a choice field")
    if not isinstance(value, str) or value not in FIELD_CATEGORIES[field_id]:
        raise ContractValidationError(
            f"category is not defined for the {field_id} field"
        )
    return value


def _closed(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{name} must be an object")
    keys = frozenset(value)
    if keys != fields:
        raise ContractValidationError(
            f"{name} keys differ: missing {sorted(fields - keys)}, "
            f"unknown {sorted(keys - fields)}"
        )
    return value


def _nullable_sha256(value: object) -> None:
    if value is not None:
        validate_sha256(value)


@dataclass(frozen=True, slots=True)
class RubricExample:
    """One development-only annotated example for a category (RD-16)."""

    category_id: str
    kind: str
    text: str
    explanation: str
    reference_hash: str | None

    def __post_init__(self) -> None:
        if self.kind not in _EXAMPLE_KINDS:
            raise ContractValidationError("example kind must be positive or boundary")
        validate_non_empty_string(self.text)
        validate_non_empty_string(self.explanation)
        _nullable_sha256(self.reference_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_id": self.category_id,
            "kind": self.kind,
            "text": self.text,
            "explanation": self.explanation,
            "reference_hash": self.reference_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RubricExample":
        fields = _closed(value, frozenset(cls.__slots__), "RubricExample")
        return cls(**fields)


@dataclass(frozen=True, slots=True)
class RubricQuestion:
    """One RD-16 `choice` row with its full category criteria.

    Its stored form carries no `type` key, as v1 stored it; a score or noul
    question names its type.
    """

    field_id: str
    question: str
    category_ids: tuple[str, ...]
    category_criteria: tuple[str, ...]
    examples: tuple[RubricExample, ...]

    def __post_init__(self) -> None:
        if field_primitive(self.field_id) != "choice":
            raise ContractValidationError(f"{self.field_id} is not a choice field")
        validate_non_empty_string(self.question)
        if self.category_ids != FIELD_CATEGORIES[self.field_id]:
            raise ContractValidationError(
                f"{self.field_id} categories must be exactly its registry, in order"
            )
        if len(self.category_criteria) != len(self.category_ids):
            raise ContractValidationError(
                "category_criteria must parallel category_ids"
            )
        for criterion in self.category_criteria:
            validate_non_empty_string(criterion)
        if not 8 <= len(self.examples) <= 16:
            raise ContractValidationError("a question carries 8 to 16 examples")
        covered: set[tuple[str, str]] = set()
        for example in self.examples:
            if not isinstance(example, RubricExample):
                raise ContractValidationError("examples must be RubricExample values")
            validate_category(self.field_id, example.category_id)
            covered.add((example.category_id, example.kind))
        for category in self.category_ids:
            for kind in ("positive", "boundary"):
                if (category, kind) not in covered:
                    raise ContractValidationError(
                        f"{self.field_id}.{category} needs a {kind} example"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "question": self.question,
            "category_ids": list(self.category_ids),
            "category_criteria": list(self.category_criteria),
            "examples": [example.to_dict() for example in self.examples],
        }

    @classmethod
    def from_dict(cls, value: object) -> "RubricQuestion":
        fields = _closed(value, frozenset(cls.__slots__), "RubricQuestion")
        for name in ("category_ids", "category_criteria", "examples"):
            if not isinstance(fields[name], list):
                raise ContractValidationError(f"{name} must be an array")
        return cls(
            field_id=fields["field_id"],
            question=fields["question"],
            category_ids=tuple(fields["category_ids"]),
            category_criteria=tuple(fields["category_criteria"]),
            examples=tuple(
                RubricExample.from_dict(item) for item in fields["examples"]
            ),
        )


@dataclass(frozen=True, slots=True)
class ScoreQuestion:
    """One `score` row: an ordered scale, one criterion per point from 0."""

    field_id: str
    question: str
    criteria: tuple[str, ...]
    type: str = "score"

    def __post_init__(self) -> None:
        if self.type != "score" or field_primitive(self.field_id) != "score":
            raise ContractValidationError(f"{self.field_id} is not a score field")
        validate_non_empty_string(self.question)
        if len(self.criteria) != SCORE_POINTS[self.field_id]:
            raise ContractValidationError(
                f"{self.field_id} needs one criterion per scale point"
            )
        for criterion in self.criteria:
            validate_non_empty_string(criterion)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "field_id": self.field_id,
            "question": self.question,
            "criteria": list(self.criteria),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ScoreQuestion":
        fields = _closed(value, frozenset(cls.__slots__), "ScoreQuestion")
        if not isinstance(fields["criteria"], list):
            raise ContractValidationError("criteria must be an array")
        return cls(**{**fields, "criteria": tuple(fields["criteria"])})


@dataclass(frozen=True, slots=True)
class NoulQuestion:
    """One `noul` row: instructions only, answered by the probability of yes.

    `statement` is what the probability is about, kept so a reader can say
    what a value answers; `question` is the instruction text sent.
    """

    field_id: str
    question: str
    statement: str
    type: str = "noul"

    def __post_init__(self) -> None:
        if self.type != "noul" or field_primitive(self.field_id) != "noul":
            raise ContractValidationError(f"{self.field_id} is not a noul field")
        validate_non_empty_string(self.question)
        validate_non_empty_string(self.statement)
        if self.statement not in self.question:
            raise ContractValidationError("a noul question must state its statement")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "field_id": self.field_id,
            "question": self.question,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: object) -> "NoulQuestion":
        return cls(**_closed(value, frozenset(cls.__slots__), "NoulQuestion"))


AnyQuestion = RubricQuestion | ScoreQuestion | NoulQuestion


def _question_from_dict(value: object) -> AnyQuestion:
    # A choice question carries no `type` key, as v1 stored it.
    kind = value.get("type") if isinstance(value, dict) else None
    if kind == "score":
        return ScoreQuestion.from_dict(value)
    if kind == "noul":
        return NoulQuestion.from_dict(value)
    return RubricQuestion.from_dict(value)


@dataclass(frozen=True, slots=True)
class JevRubric:
    """The versioned eight-question rubric; its hash covers every byte of it."""

    version: str
    questions: tuple[AnyQuestion, ...]
    created_at: str

    def __post_init__(self) -> None:
        field_ids = rubric_field_ids(self.version)
        validate_utc_instant(self.created_at)
        if not all(
            isinstance(item, (RubricQuestion, ScoreQuestion, NoulQuestion))
            for item in self.questions
        ):
            raise ContractValidationError("questions must be rubric question values")
        if tuple(item.field_id for item in self.questions) != field_ids:
            raise ContractValidationError(
                "a rubric asks exactly its version's eight RD-16 fields, in order"
            )

    @property
    def field_ids(self) -> tuple[str, ...]:
        return RUBRIC_FIELD_IDS[self.version]

    @property
    def rubric_hash(self) -> str:
        return sha256_hex(self.to_canonical_json())

    def question(self, field_id: str) -> AnyQuestion:
        validate_field_id(field_id)
        if field_id not in self.field_ids:
            raise ContractValidationError(f"{self.version} does not ask {field_id}")
        return self.questions[self.field_ids.index(field_id)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "questions": [item.to_dict() for item in self.questions],
            "created_at": self.created_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "JevRubric":
        try:
            value = canonical_loads(raw)
        except CanonicalJsonError as error:
            raise ContractValidationError(str(error)) from error
        fields = _closed(value, frozenset(cls.__slots__), "JevRubric")
        if not isinstance(fields["questions"], list):
            raise ContractValidationError("questions must be an array")
        return cls(
            version=fields["version"],
            questions=tuple(_question_from_dict(item) for item in fields["questions"]),
            created_at=fields["created_at"],
        )


@dataclass(frozen=True, slots=True)
class JevProviderIdentity:
    """Configured and returned provider identity, with its pinning kind (RD-19).

    `immutable_revision` requires a revision the capability evidence
    verified; a mutable alias or an undisclosed identity carries no revision
    and never a fabricated checkpoint hash or date.
    """

    provider: str
    configured_model_alias: str | None
    returned_model_identity: str | None
    immutable_revision: str | None
    identity_kind: str
    capability_evidence_hash: str
    configuration_hash: str

    def __post_init__(self) -> None:
        if self.provider != JEV_PROVIDER:
            raise ContractValidationError("provider must be the Jev provider")
        for value in (
            self.configured_model_alias,
            self.returned_model_identity,
            self.immutable_revision,
        ):
            if value is not None:
                validate_non_empty_string(value)
        if self.identity_kind not in IDENTITY_KINDS:
            raise ContractValidationError("identity_kind is not admitted")
        if (self.identity_kind == "immutable_revision") != (
            self.immutable_revision is not None
        ):
            raise ContractValidationError(
                "an immutable revision is recorded exactly when the kind names one"
            )
        if (
            self.identity_kind == "mutable_alias"
            and self.configured_model_alias is None
        ):
            raise ContractValidationError("a mutable alias names the configured alias")
        if self.identity_kind == "not_disclosed" and (
            self.returned_model_identity is not None
        ):
            raise ContractValidationError(
                "a returned identity is disclosed; record its kind"
            )
        validate_sha256(self.capability_evidence_hash)
        validate_sha256(self.configuration_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "configured_model_alias": self.configured_model_alias,
            "returned_model_identity": self.returned_model_identity,
            "immutable_revision": self.immutable_revision,
            "identity_kind": self.identity_kind,
            "capability_evidence_hash": self.capability_evidence_hash,
            "configuration_hash": self.configuration_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> "JevProviderIdentity":
        return cls(**_closed(value, frozenset(cls.__slots__), "JevProviderIdentity"))


@dataclass(frozen=True, slots=True)
class JevAssessmentInput:
    """What one request supplies: exactly the extracted text and its coverage (RD-17)."""

    paper_version_id: str
    extraction_hash: str
    supplied_text_hash: str
    supplied_text_bytes: int
    coverage: str
    coverage_reasons: tuple[str, ...]
    rubric_hash: str
    provider_configuration_hash: str
    smoke_report_hash: str | None

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_version_id)
        validate_sha256(self.extraction_hash)
        validate_sha256(self.supplied_text_hash)
        validate_non_negative_int(self.supplied_text_bytes)
        if self.coverage not in _INPUT_COVERAGE:
            raise ContractValidationError("coverage is not admitted")
        for reason in self.coverage_reasons:
            validate_non_empty_string(reason)
        validate_sha256(self.rubric_hash)
        validate_sha256(self.provider_configuration_hash)
        _nullable_sha256(self.smoke_report_hash)

    @property
    def input_hash(self) -> str:
        return sha256_hex(self.to_canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_version_id": self.paper_version_id,
            "extraction_hash": self.extraction_hash,
            "supplied_text_hash": self.supplied_text_hash,
            "supplied_text_bytes": self.supplied_text_bytes,
            "coverage": self.coverage,
            "coverage_reasons": list(self.coverage_reasons),
            "rubric_hash": self.rubric_hash,
            "provider_configuration_hash": self.provider_configuration_hash,
            "smoke_report_hash": self.smoke_report_hash,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "JevAssessmentInput":
        fields = _closed(value, frozenset(cls.__slots__), "JevAssessmentInput")
        if not isinstance(fields["coverage_reasons"], list):
            raise ContractValidationError("coverage_reasons must be an array")
        return cls(**{**fields, "coverage_reasons": tuple(fields["coverage_reasons"])})
