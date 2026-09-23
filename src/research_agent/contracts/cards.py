"""Paper card wire contracts: identity, per-signal availability and inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, cast

from research_agent.assessments.schemas import (
    FieldResult,
    fields_from_dict,
    fields_to_dict,
    fields_version,
)

from .assessments import (
    JEV_SOURCE_LABEL,
    UNAVAILABLE_REASONS,
    JevProviderIdentity,
    rubric_field_ids,
)
from .canonical import canonical_json, canonical_loads, sha256_hex
from .learning import TARGET_IDS, AutomaticLabel
from .passages import SourceLocator
from .primitives import (
    ContractValidationError,
    validate_finite,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")

_AVAILABILITY_REASONS = frozenset(
    {
        "missing_source",
        "missing_vector",
        "zero_centroid",
        "incompatible_representation",
        "no_neighbors",
        "no_known_labels",
        "disabled_by_profile",
        "not_available_as_of",
    }
)
_FORECAST_ELIGIBILITY = frozenset(
    {
        "eligible",
        "retrospective",
        "late_arrival",
        "preexisting_event",
        "ambiguous_pre_event",
        "unknown_t0",
    }
)
_PASSAGE_COVERAGE = frozenset({"complete", "partial", "unavailable"})
_AUTHOR_UNAVAILABLE_REASONS = frozenset({"missing_source", "not_available_as_of"})
_CARD_TOKEN_CAP = 3000


def _closed(raw: bytes, fields: frozenset[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return cast(dict[str, Any], value)


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


def _unique(values: tuple[str, ...], name: str) -> None:
    if len(set(values)) != len(values):
        raise ContractValidationError(f"{name} must not repeat")


@dataclass(frozen=True, slots=True)
class AvailabilityValue:
    """A model-free scalar that is either present or explicitly missing."""

    status: str
    value: int | float | None
    reason: str | None
    evidence_hashes: tuple[str, ...]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"status", "value", "reason", "evidence_hashes"}
    )

    def __post_init__(self) -> None:
        if self.status not in {"available", "unavailable"}:
            raise ContractValidationError("availability status is not admitted")
        if self.status == "available":
            if self.value is None or self.reason is not None:
                raise ContractValidationError(
                    "an available value requires a value and no reason"
                )
            validate_finite(self.value)
        else:
            if self.value is not None or self.reason not in _AVAILABILITY_REASONS:
                raise ContractValidationError(
                    "an unavailable value requires a null value and a known reason"
                )
        for value in self.evidence_hashes:
            validate_sha256(value)
        _unique(self.evidence_hashes, "evidence_hashes")

    @classmethod
    def available(
        cls, value: int | float, *, evidence_hashes: tuple[str, ...] = ()
    ) -> "AvailabilityValue":
        return cls("available", value, None, evidence_hashes)

    @classmethod
    def unavailable(
        cls, reason: str, *, evidence_hashes: tuple[str, ...] = ()
    ) -> "AvailabilityValue":
        return cls("unavailable", None, reason, evidence_hashes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": self.value,
            "reason": self.reason,
            "evidence_hashes": list(self.evidence_hashes),
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "AvailabilityValue":
        values = _closed(raw, cls._FIELDS, "AvailabilityValue")
        hashes = values["evidence_hashes"]
        if not isinstance(hashes, list):
            raise ContractValidationError("evidence_hashes must be an array")
        values["evidence_hashes"] = tuple(hashes)
        return _construct(cls, values, "AvailabilityValue")


@dataclass(frozen=True, slots=True)
class HeadCardValue:
    """One of the three prediction-head outputs on a paper card."""

    target_id: str
    target_version: str
    question: str
    probability: int | float | None
    availability: str
    unavailable_reason: str | None
    horizon_end: str | None
    model_bundle_id: str | None
    training_cutoff: str | None
    evaluation_report_id: str | None
    forecast_eligibility: str
    eligibility_evidence_hash: str | None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "target_id",
            "target_version",
            "question",
            "probability",
            "availability",
            "unavailable_reason",
            "horizon_end",
            "model_bundle_id",
            "training_cutoff",
            "evaluation_report_id",
            "forecast_eligibility",
            "eligibility_evidence_hash",
        }
    )

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise ContractValidationError("target_id is not a registered target")
        validate_sha256(self.target_version)
        validate_non_empty_string(self.question)
        if self.availability not in {"qualified", "unavailable"}:
            raise ContractValidationError("head availability is not admitted")
        if self.forecast_eligibility not in _FORECAST_ELIGIBILITY:
            raise ContractValidationError("forecast eligibility is not admitted")
        if self.forecast_eligibility == "unknown_t0" and self.horizon_end is not None:
            raise ContractValidationError("an unknown t0 carries no horizon")
        if self.horizon_end is None and self.availability == "qualified":
            raise ContractValidationError("a qualified head requires a known horizon")
        if self.availability == "qualified":
            if self.probability is None or self.unavailable_reason is not None:
                raise ContractValidationError(
                    "a qualified head requires a probability and no reason"
                )
            validate_probability(self.probability)
        else:
            if self.probability is not None or not self.unavailable_reason:
                raise ContractValidationError(
                    "an unavailable head requires no probability and a reason"
                )
            validate_non_empty_string(self.unavailable_reason)
        if self.horizon_end is not None:
            validate_utc_instant(self.horizon_end)
        for value in (self.model_bundle_id, self.evaluation_report_id):
            if value is not None:
                validate_sha256(value)
        if self.training_cutoff is not None:
            validate_utc_instant(self.training_cutoff)
        if self.eligibility_evidence_hash is not None:
            validate_sha256(self.eligibility_evidence_hash)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self._FIELDS}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "HeadCardValue":
        return _construct(
            cls, _closed(raw, cls._FIELDS, "HeadCardValue"), "HeadCardValue"
        )


@dataclass(frozen=True, slots=True)
class NeighborCardSummary:
    """One of a paper's nearest earlier neighbors, listed nearest first."""

    paper_family_id: str
    paper_version_id: str
    title: str
    similarity: int | float
    card_id: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"paper_family_id", "paper_version_id", "title", "similarity", "card_id"}
    )

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.paper_version_id)
        validate_non_empty_string(self.title)
        similarity = validate_finite(self.similarity)
        if not -1 <= similarity <= 1:
            raise ContractValidationError("similarity must be in [-1, 1]")
        validate_sha256(self.card_id)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self._FIELDS}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "NeighborCardSummary":
        return _construct(
            cls, _closed(raw, cls._FIELDS, "NeighborCardSummary"), "NeighborCardSummary"
        )


@dataclass(frozen=True, slots=True)
class NeighborTargetValue:
    """The Laplace-smoothed outcome rate among a target's known earlier neighbors."""

    target_id: str
    known_neighbor_count: int
    positive_neighbor_count: int
    probability: int | float | None
    reason: str | None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "target_id",
            "known_neighbor_count",
            "positive_neighbor_count",
            "probability",
            "reason",
        }
    )

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise ContractValidationError("target_id is not a registered target")
        known = validate_non_negative_int(self.known_neighbor_count)
        positive = validate_non_negative_int(self.positive_neighbor_count)
        if known > 5:
            raise ContractValidationError("known_neighbor_count exceeds five neighbors")
        if positive > known:
            raise ContractValidationError("positive_neighbor_count exceeds known count")
        if known > 0:
            if self.reason is not None:
                raise ContractValidationError("a known count carries no reason")
            expected = (positive + 1) / (known + 2)
            if self.probability != expected:
                raise ContractValidationError(
                    "probability disagrees with the Laplace-smoothed rate"
                )
        else:
            if self.probability is not None or self.reason != "no_known_labels":
                raise ContractValidationError(
                    "zero known neighbors require a null probability and reason"
                )

    @classmethod
    def from_counts(
        cls, target_id: str, known_neighbor_count: int, positive_neighbor_count: int
    ) -> "NeighborTargetValue":
        if known_neighbor_count > 0:
            probability = (positive_neighbor_count + 1) / (known_neighbor_count + 2)
            reason = None
        else:
            probability = None
            reason = "no_known_labels"
        return cls(
            target_id,
            known_neighbor_count,
            positive_neighbor_count,
            probability,
            reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self._FIELDS}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "NeighborTargetValue":
        return _construct(
            cls, _closed(raw, cls._FIELDS, "NeighborTargetValue"), "NeighborTargetValue"
        )


@dataclass(frozen=True, slots=True)
class AuthorCitationValue:
    """One author's snapshot-visible prior citation count, or why it is absent."""

    author_id: str
    count: int | None
    source_capture_hash: str | None
    captured_at: str | None
    reason: str | None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"author_id", "count", "source_capture_hash", "captured_at", "reason"}
    )

    def __post_init__(self) -> None:
        validate_non_empty_string(self.author_id)
        if self.count is None:
            if (
                self.source_capture_hash is not None
                or self.captured_at is not None
                or self.reason not in _AUTHOR_UNAVAILABLE_REASONS
            ):
                raise ContractValidationError(
                    "a missing author count requires no other field but a known reason"
                )
        else:
            validate_non_negative_int(self.count)
            if (
                self.source_capture_hash is None
                or self.captured_at is None
                or self.reason is not None
            ):
                raise ContractValidationError(
                    "an available author count requires its source and no reason"
                )
            validate_sha256(self.source_capture_hash)
            validate_utc_instant(self.captured_at)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self._FIELDS}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "AuthorCitationValue":
        return _construct(
            cls, _closed(raw, cls._FIELDS, "AuthorCitationValue"), "AuthorCitationValue"
        )


@dataclass(frozen=True, slots=True)
class AuthorCitationCapture:
    """A preserved public prior-citation count for one author, as captured."""

    author_id: str
    count: int
    source_capture_hash: str
    captured_at: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.author_id)
        validate_non_negative_int(self.count)
        validate_sha256(self.source_capture_hash)
        validate_utc_instant(self.captured_at)


@dataclass(frozen=True, slots=True)
class GraphCardValues:
    """The citation-graph features a paper card shows (RD-10, RD-13)."""

    incoming_family_count: int | None
    outgoing_family_count: int | None
    reference_match_fraction: int | float | None
    reference_count: int
    matched_reference_count: int
    reference_vector_count: int
    missing_reference_vector_count: int
    reference_centroid_distance: AvailabilityValue
    graph_manifest_hash: str | None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "incoming_family_count",
            "outgoing_family_count",
            "reference_match_fraction",
            "reference_count",
            "matched_reference_count",
            "reference_vector_count",
            "missing_reference_vector_count",
            "reference_centroid_distance",
            "graph_manifest_hash",
        }
    )

    def __post_init__(self) -> None:
        for value in (self.incoming_family_count, self.outgoing_family_count):
            if value is not None:
                validate_non_negative_int(value)
        reference_count = validate_non_negative_int(self.reference_count)
        matched = validate_non_negative_int(self.matched_reference_count)
        if matched > reference_count:
            raise ContractValidationError(
                "matched_reference_count cannot exceed reference_count"
            )
        if reference_count > 0:
            expected = matched / reference_count
            if self.reference_match_fraction != expected:
                raise ContractValidationError(
                    "reference_match_fraction disagrees with matched/reference"
                )
        elif self.reference_match_fraction is not None:
            raise ContractValidationError(
                "an empty bibliography carries no match fraction"
            )
        vector_count = validate_non_negative_int(self.reference_vector_count)
        missing_vector_count = validate_non_negative_int(
            self.missing_reference_vector_count
        )
        if vector_count + missing_vector_count != reference_count:
            raise ContractValidationError(
                "reference vector counts must partition reference_count"
            )
        if not isinstance(self.reference_centroid_distance, AvailabilityValue):
            raise ContractValidationError(
                "reference_centroid_distance must be an AvailabilityValue"
            )
        if self.graph_manifest_hash is not None:
            validate_sha256(self.graph_manifest_hash)

    def to_dict(self) -> dict[str, Any]:
        value = {name: getattr(self, name) for name in self._FIELDS}
        value["reference_centroid_distance"] = (
            self.reference_centroid_distance.to_dict()
        )
        return value

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "GraphCardValues":
        values = _closed(raw, cls._FIELDS, "GraphCardValues")
        centroid = values["reference_centroid_distance"]
        if not isinstance(centroid, dict):
            raise ContractValidationError(
                "reference_centroid_distance must be an object"
            )
        values["reference_centroid_distance"] = AvailabilityValue.from_json(
            canonical_json(centroid)
        )
        return _construct(cls, values, "GraphCardValues")


@dataclass(frozen=True, slots=True)
class OverviewSpan:
    """One preserved source span used by a referenced-overview projection."""

    locator: SourceLocator
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.locator, SourceLocator):
            raise ContractValidationError("locator must be a SourceLocator")
        validate_non_empty_string(self.text)


@dataclass(frozen=True, slots=True)
class CardOverview:
    """A paper's overview text, complete or reduced to fit the token cap."""

    kind: str
    title: str
    abstract: str | None
    spans: tuple[OverviewSpan, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.title)
        if self.kind == "complete":
            if self.abstract is None or self.spans:
                raise ContractValidationError(
                    "a complete overview carries an abstract and no spans"
                )
            validate_non_empty_string(self.abstract)
        elif self.kind == "referenced":
            if self.abstract is not None or not self.spans:
                raise ContractValidationError(
                    "a referenced overview carries source spans and no abstract"
                )
            for span in self.spans:
                if not isinstance(span, OverviewSpan):
                    raise ContractValidationError("spans must be OverviewSpan values")
        else:
            raise ContractValidationError("overview kind is not admitted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "abstract": self.abstract,
            "spans": [
                {"locator": span.locator.to_dict(), "text": span.text}
                for span in self.spans
            ],
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class JevCardAvailable:
    """A stored valid result, projected without request, response or billing.

    The fields are exactly the eight of the rubric version the card names.
    """

    assessment_id: str
    fields: tuple[FieldResult, ...]
    paper_version_id: str
    extraction_hash: str
    rubric_hash: str
    rubric_version: str
    provider_identity: JevProviderIdentity
    computed_at: str
    qualification_report_hash: str
    status: str = "available"

    def __post_init__(self) -> None:
        if self.status != "available":
            raise ContractValidationError("status must be available")
        validate_sha256(self.assessment_id)
        if fields_version(self.fields) != self.rubric_version:
            raise ContractValidationError(
                "fields must be exactly the eight fields of the card's rubric version"
            )
        validate_uuid4(self.paper_version_id)
        validate_sha256(self.extraction_hash)
        validate_sha256(self.rubric_hash)
        rubric_field_ids(self.rubric_version)
        validate_utc_instant(self.computed_at)
        validate_sha256(self.qualification_report_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "assessment_id": self.assessment_id,
            "fields": fields_to_dict(self.fields),
            "paper_version_id": self.paper_version_id,
            "extraction_hash": self.extraction_hash,
            "rubric_hash": self.rubric_hash,
            "rubric_version": self.rubric_version,
            "provider_identity": self.provider_identity.to_dict(),
            "computed_at": self.computed_at,
            "qualification_report_hash": self.qualification_report_hash,
        }


@dataclass(frozen=True, slots=True)
class JevCardUnavailable:
    """An unavailable section: a reason, never fabricated categories or numbers."""

    reason: str
    rubric_hash: str
    assessment_id: str | None
    status: str = "unavailable"

    def __post_init__(self) -> None:
        if self.status != "unavailable":
            raise ContractValidationError("status must be unavailable")
        if self.reason not in UNAVAILABLE_REASONS:
            raise ContractValidationError(
                "reason is not an admitted unavailable reason"
            )
        validate_sha256(self.rubric_hash)
        if self.assessment_id is not None:
            validate_sha256(self.assessment_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "rubric_hash": self.rubric_hash,
            "assessment_id": self.assessment_id,
        }


@dataclass(frozen=True, slots=True)
class JevCardAssessment:
    """The paper card's separated Jev section: eight fields, or one reason."""

    assessment: JevCardAvailable | JevCardUnavailable
    source_label: str = JEV_SOURCE_LABEL

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, (JevCardAvailable, JevCardUnavailable)):
            raise ContractValidationError("assessment must be a Jev card record")
        if self.source_label != JEV_SOURCE_LABEL:
            raise ContractValidationError("jev source_label must be the fixed label")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment": self.assessment.to_dict(),
            "source_label": self.source_label,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @property
    def section_hash(self) -> str:
        return sha256_hex(self.to_canonical_json())

    @classmethod
    def from_json(cls, raw: bytes) -> "JevCardAssessment":
        value = _closed(
            raw, frozenset({"assessment", "source_label"}), "JevCardAssessment"
        )
        body = value["assessment"]
        if not isinstance(body, dict):
            raise ContractValidationError("assessment must be an object")
        assessment: JevCardAvailable | JevCardUnavailable
        if body.get("status") == "available":
            if set(body) != set(JevCardAvailable.__slots__):
                raise ContractValidationError("JevCardAvailable keys differ")
            assessment = JevCardAvailable(
                assessment_id=body["assessment_id"],
                fields=fields_from_dict(body["fields"], body["rubric_version"]),
                paper_version_id=body["paper_version_id"],
                extraction_hash=body["extraction_hash"],
                rubric_hash=body["rubric_hash"],
                rubric_version=body["rubric_version"],
                provider_identity=JevProviderIdentity.from_dict(
                    body["provider_identity"]
                ),
                computed_at=body["computed_at"],
                qualification_report_hash=body["qualification_report_hash"],
            )
        else:
            if set(body) != set(JevCardUnavailable.__slots__):
                raise ContractValidationError("JevCardUnavailable keys differ")
            assessment = JevCardUnavailable(**body)
        return cls(assessment, value["source_label"])


@dataclass(frozen=True, slots=True)
class PaperCardBody:
    """The immutable, versioned paper card (RD-01): identity plus typed signals."""

    schema_version: int
    paper_family_id: str
    paper_version_id: str
    as_of: str
    overview: CardOverview
    first_public_at: str | None
    original_source: SourceLocator
    overview_available: bool
    passage_coverage: str
    passage_count: int
    extraction_hash: str | None
    representation_hash: str | None
    head_feature_eligible: bool
    head_feature_unavailable_reason: str | None
    head_predictions: tuple[HeadCardValue, ...]
    neighbors: tuple[NeighborCardSummary, ...]
    neighbor_embedding_distance: AvailabilityValue
    neighbor_outcomes: tuple[NeighborTargetValue, ...]
    graph: GraphCardValues
    author_citations: tuple[AuthorCitationValue, ...]
    jev: JevCardAssessment
    card_token_count: int
    author_count: int
    categories: tuple[str, ...]
    version_count: int
    title_tokens: int
    abstract_tokens: int
    code_link: bool
    first_available_weekday: int | None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractValidationError("schema_version must be 1")
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.paper_version_id)
        validate_utc_instant(self.as_of)
        if not isinstance(self.overview, CardOverview):
            raise ContractValidationError("overview must be a CardOverview")
        if self.first_public_at is not None:
            validate_utc_instant(self.first_public_at)
        if not isinstance(self.original_source, SourceLocator):
            raise ContractValidationError("original_source must be a SourceLocator")
        if not isinstance(self.overview_available, bool):
            raise ContractValidationError("overview_available must be boolean")
        if self.passage_coverage not in _PASSAGE_COVERAGE:
            raise ContractValidationError("passage_coverage is not admitted")
        validate_non_negative_int(self.passage_count)
        for value in (self.extraction_hash, self.representation_hash):
            if value is not None:
                validate_sha256(value)
        if not isinstance(self.head_feature_eligible, bool):
            raise ContractValidationError("head_feature_eligible must be boolean")
        if self.head_feature_eligible == (
            self.head_feature_unavailable_reason is not None
        ):
            raise ContractValidationError(
                "head feature eligibility disagrees with its reason"
            )
        self._check_heads()
        self._check_neighbors()
        self._check_neighbor_outcomes()
        if not isinstance(self.graph, GraphCardValues):
            raise ContractValidationError("graph must be GraphCardValues")
        if not isinstance(self.neighbor_embedding_distance, AvailabilityValue):
            raise ContractValidationError(
                "neighbor_embedding_distance must be an AvailabilityValue"
            )
        self._check_authors()
        if not isinstance(self.jev, JevCardAssessment):
            raise ContractValidationError("jev must be a JevCardAssessment")
        token_count = validate_non_negative_int(self.card_token_count)
        if token_count > _CARD_TOKEN_CAP:
            raise ContractValidationError(
                f"card_token_count exceeds the {_CARD_TOKEN_CAP}-token cap"
            )
        self._check_metadata()

    def _check_metadata(self) -> None:
        validate_non_negative_int(self.author_count)
        validate_positive_int(self.version_count)
        if not isinstance(self.categories, tuple) or not self.categories:
            raise ContractValidationError(
                "categories must be a nonempty, ordered tuple with the primary first"
            )
        for category in self.categories:
            validate_non_empty_string(category)
        validate_non_negative_int(self.title_tokens)
        validate_non_negative_int(self.abstract_tokens)
        if not isinstance(self.code_link, bool):
            raise ContractValidationError("code_link must be boolean")
        if self.first_available_weekday is not None and (
            type(self.first_available_weekday) is not int
            or not 0 <= self.first_available_weekday <= 6
        ):
            raise ContractValidationError(
                "first_available_weekday must be 0 to 6 or null"
            )
        if (self.first_public_at is None) != (self.first_available_weekday is None):
            raise ContractValidationError(
                "first_available_weekday must be known exactly when first_public_at is"
            )

    def _check_heads(self) -> None:
        if not all(isinstance(item, HeadCardValue) for item in self.head_predictions):
            raise ContractValidationError(
                "head_predictions must be HeadCardValue values"
            )
        if tuple(item.target_id for item in self.head_predictions) != TARGET_IDS:
            raise ContractValidationError(
                "head_predictions must name exactly the three targets in order"
            )

    def _check_neighbors(self) -> None:
        if not all(isinstance(item, NeighborCardSummary) for item in self.neighbors):
            raise ContractValidationError(
                "neighbors must be NeighborCardSummary values"
            )
        if len(self.neighbors) > 5:
            raise ContractValidationError("neighbors must list at most five papers")
        family_ids = [item.paper_family_id for item in self.neighbors]
        _unique(tuple(family_ids), "neighbor family ids")
        if self.paper_family_id in family_ids:
            raise ContractValidationError("a paper cannot neighbor itself")
        for earlier, later in zip(self.neighbors, self.neighbors[1:]):
            if later.similarity > earlier.similarity:
                raise ContractValidationError("neighbors must be ordered nearest first")

    def _check_neighbor_outcomes(self) -> None:
        if not all(
            isinstance(item, NeighborTargetValue) for item in self.neighbor_outcomes
        ):
            raise ContractValidationError(
                "neighbor_outcomes must be NeighborTargetValue values"
            )
        if tuple(item.target_id for item in self.neighbor_outcomes) != TARGET_IDS:
            raise ContractValidationError(
                "neighbor_outcomes must name exactly the three targets in order"
            )

    def _check_authors(self) -> None:
        if not all(
            isinstance(item, AuthorCitationValue) for item in self.author_citations
        ):
            raise ContractValidationError(
                "author_citations must be AuthorCitationValue values"
            )
        _unique(
            tuple(item.author_id for item in self.author_citations), "author_citations"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "paper_family_id": self.paper_family_id,
            "paper_version_id": self.paper_version_id,
            "as_of": self.as_of,
            "overview": self.overview.to_dict(),
            "first_public_at": self.first_public_at,
            "original_source": self.original_source.to_dict(),
            "overview_available": self.overview_available,
            "passage_coverage": self.passage_coverage,
            "passage_count": self.passage_count,
            "extraction_hash": self.extraction_hash,
            "representation_hash": self.representation_hash,
            "head_feature_eligible": self.head_feature_eligible,
            "head_feature_unavailable_reason": self.head_feature_unavailable_reason,
            "head_predictions": [item.to_dict() for item in self.head_predictions],
            "neighbors": [item.to_dict() for item in self.neighbors],
            "neighbor_embedding_distance": self.neighbor_embedding_distance.to_dict(),
            "neighbor_outcomes": [item.to_dict() for item in self.neighbor_outcomes],
            "graph": self.graph.to_dict(),
            "author_citations": [item.to_dict() for item in self.author_citations],
            "jev": self.jev.to_dict(),
            "card_token_count": self.card_token_count,
            "author_count": self.author_count,
            "categories": list(self.categories),
            "version_count": self.version_count,
            "title_tokens": self.title_tokens,
            "abstract_tokens": self.abstract_tokens,
            "code_link": self.code_link,
            "first_available_weekday": self.first_available_weekday,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CardBuildInput:
    """The declared, already-committed inputs `assemble_card` may read (RD-01)."""

    paper_family_id: str
    paper_version_id: str
    as_of: str
    corpus_arrival_at: str
    overview: CardOverview
    overview_available: bool
    first_public_at: str | None
    original_source: SourceLocator
    passage_coverage: str
    passage_count: int
    extraction_hash: str | None
    representation_hash: str | None
    head_feature_eligible: bool
    head_feature_unavailable_reason: str | None
    head_predictions: tuple[HeadCardValue, ...]
    neighbors: tuple[NeighborCardSummary, ...]
    neighbor_arrivals: tuple[tuple[str, str], ...]
    neighbor_embedding_distance: AvailabilityValue
    outcome_labels: tuple[AutomaticLabel, ...]
    graph_incoming_family_ids: tuple[str, ...] | None
    graph_outgoing_family_ids: tuple[str, ...] | None
    graph_parsed_reference_count: int
    graph_matched_reference_ids: tuple[str, ...]
    graph_reference_vector_count: int
    graph_missing_reference_vector_count: int
    graph_reference_centroid_distance: AvailabilityValue
    graph_manifest_hash: str | None
    author_ids: tuple[str, ...]
    author_captures: tuple[AuthorCitationCapture, ...]
    jev: JevCardAssessment
    card_token_count: int
    author_count: int
    categories: tuple[str, ...]
    version_count: int
    title_tokens: int
    abstract_tokens: int
    code_link: bool
