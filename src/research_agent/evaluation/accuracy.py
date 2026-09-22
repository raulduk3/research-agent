"""Accuracy obligations as scheduled records (SDD-SR-27).

`AccuracyRegistry` fixes, once per active launch profile, the complete
inventory of output-producing components this system runs and the schedule on
which each is measured against a reference. `compute_accuracy_report` is a
pure function of the outcomes a caller already resolved: it never re-derives
an outcome and never invents a score for a component with no reference
support, matching `score_ledger`'s intended/eligible/excluded counting in
`research_agent.scoring.scores`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar, cast

from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")

# The fixed, ordered component inventory Appendix A: Launch profile names for
# the accuracy registry. Order is the registry's canonical coverage check.
COMPONENT_IDS: tuple[str, ...] = (
    "acquisition",
    "extraction",
    "resolver",
    "retrieval",
    "prediction_head_citation_reach_365d",
    "prediction_head_late_citation_activity_365d",
    "prediction_head_cross_subfield_reach_365d",
    "jev",
    "agent_calibration",
    "integrity",
)

# The one schedule Appendix A: Launch profile fixes for each component; a
# registry entry cannot choose its own cadence.
CADENCE_BY_COMPONENT: dict[str, str] = {
    "acquisition": "monthly",
    "extraction": "monthly",
    "resolver": "every_build",
    "retrieval": "monthly_plus_quarterly_refresh",
    "prediction_head_citation_reach_365d": "every_promotion_and_weekly",
    "prediction_head_late_citation_activity_365d": "every_promotion_and_weekly",
    "prediction_head_cross_subfield_reach_365d": "every_promotion_and_weekly",
    "jev": "every_promotion_and_weekly",
    "agent_calibration": "weekly_when_outcomes_exist",
    "integrity": "every_build_and_weekly",
}

# SR-27's named exception: Jev fields carry the RD-22 smoke test and are shown
# as unqualified, with no accuracy measure or reference.
UNQUALIFIED_COMPONENT_IDS: frozenset[str] = frozenset({"jev"})

DENOMINATOR_POLICIES: frozenset[str] = frozenset(
    {"eligible_known_only", "eligible_including_unknown"}
)
DISPOSITIONS: frozenset[str] = frozenset({"available", "insufficient_reference"})


def _closed(raw: bytes, fields: set[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return cast(dict[str, Any], value)


def _meta(values: dict[str, Any]) -> None:
    producer = values.get("producer_version")
    inputs = values.get("input_hashes")
    if not isinstance(producer, dict) or not isinstance(inputs, list):
        raise ContractValidationError("RecordMeta fields are invalid")
    values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
    values["input_hashes"] = tuple(inputs)


def _fields(cls: Any, *, meta: bool = False) -> set[str]:
    fields = set(cls.__slots__)
    if meta:
        fields.update(RecordMeta.__slots__)
    return fields


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


@dataclass(frozen=True, slots=True)
class AccuracyEntry:
    """One component's accuracy obligation: what it is measured against, and when."""

    component_id: str
    component_version: str
    metric_definition_hash: str | None
    reference_manifest: str | None
    denominator_policy: str
    cadence: str
    last_report: str | None
    next_due_at: str

    def __post_init__(self) -> None:
        if self.component_id not in COMPONENT_IDS:
            raise ContractValidationError("component_id is not a registered component")
        if self.cadence != CADENCE_BY_COMPONENT[self.component_id]:
            raise ContractValidationError(
                "component has no matching schedule in the launch profile"
            )
        validate_non_empty_string(self.component_version)
        unqualified = self.component_id in UNQUALIFIED_COMPONENT_IDS
        if unqualified:
            if (
                self.metric_definition_hash is not None
                or self.reference_manifest is not None
            ):
                raise ContractValidationError(
                    "an unqualified component carries no accuracy measure or reference"
                )
        else:
            if self.metric_definition_hash is None or self.reference_manifest is None:
                raise ContractValidationError(
                    "a qualified component needs its accuracy measure and reference"
                )
            validate_sha256(self.metric_definition_hash)
            validate_sha256(self.reference_manifest)
        if self.denominator_policy not in DENOMINATOR_POLICIES:
            raise ContractValidationError("denominator_policy is invalid")
        if self.last_report is not None:
            validate_utc_instant(self.last_report)
        if validate_utc_instant(self.next_due_at) <= (self.last_report or ""):
            raise ContractValidationError("next_due_at must follow the last report")

    @property
    def qualified(self) -> bool:
        return self.component_id not in UNQUALIFIED_COMPONENT_IDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "component_version": self.component_version,
            "metric_definition_hash": self.metric_definition_hash,
            "reference_manifest": self.reference_manifest,
            "denominator_policy": self.denominator_policy,
            "cadence": self.cadence,
            "last_report": self.last_report,
            "next_due_at": self.next_due_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "AccuracyEntry":
        return _construct(
            cls, _closed(raw, _fields(cls), "AccuracyEntry"), "AccuracyEntry"
        )


@dataclass(frozen=True, slots=True)
class AccuracyRegistry(RecordMeta):
    """The complete, ordered accuracy-obligation coverage for the active profile."""

    entries: tuple[AccuracyEntry, ...]

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        if not isinstance(self.entries, tuple) or any(
            not isinstance(entry, AccuracyEntry) for entry in self.entries
        ):
            raise ContractValidationError("entries must be a tuple of AccuracyEntry")
        if tuple(entry.component_id for entry in self.entries) != COMPONENT_IDS:
            raise ContractValidationError(
                "accuracy registry coverage is incomplete, unordered or duplicated"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_hashes": list(self.input_hashes),
            "producer_version": self.producer_version.to_dict(),
            "config_hash": self.config_hash,
            "created_at": self.created_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "AccuracyRegistry":
        values = _closed(raw, _fields(cls, meta=True), "AccuracyRegistry")
        _meta(values)
        entries = values["entries"]
        if not isinstance(entries, list):
            raise ContractValidationError("entries must be an array")
        values["entries"] = tuple(
            AccuracyEntry.from_json(canonical_json(item)) for item in entries
        )
        return _construct(cls, values, "AccuracyRegistry")


@dataclass(frozen=True, slots=True)
class AccuracyOutcome:
    """One case a component's accuracy report may draw on."""

    outcome_id: str
    eligible: bool
    ineligible_reason: str | None
    known: bool
    correct: bool | None

    def __post_init__(self) -> None:
        validate_uuid4(self.outcome_id)
        if not isinstance(self.eligible, bool) or not isinstance(self.known, bool):
            raise ContractValidationError("eligible and known must be boolean")
        if self.eligible:
            if self.ineligible_reason is not None:
                raise ContractValidationError("an eligible outcome carries no reason")
        else:
            if self.ineligible_reason is None:
                raise ContractValidationError("an excluded outcome needs a reason")
            validate_non_empty_string(self.ineligible_reason)
        if self.known:
            if not isinstance(self.correct, bool):
                raise ContractValidationError("a known outcome carries a verdict")
        elif self.correct is not None:
            raise ContractValidationError("an unknown outcome carries no verdict")


@dataclass(frozen=True, slots=True)
class AccuracyReport:
    """The recorded outcome of measuring one component's accuracy at a watermark."""

    component_id: str
    component_version: str
    metric_definition_hash: str
    reference_manifest: str
    source_watermark: int
    reference_watermark: int
    intended_count: int
    eligible_count: int
    known_count: int
    unknown_count: int
    excluded_count: int
    accuracy: float | None
    disposition: str
    computed_at: str

    def __post_init__(self) -> None:
        if self.component_id not in COMPONENT_IDS:
            raise ContractValidationError("component_id is not a registered component")
        validate_non_empty_string(self.component_version)
        validate_sha256(self.metric_definition_hash)
        validate_sha256(self.reference_manifest)
        validate_non_negative_int(self.source_watermark)
        validate_non_negative_int(self.reference_watermark)
        for count in (
            self.intended_count,
            self.eligible_count,
            self.known_count,
            self.unknown_count,
            self.excluded_count,
        ):
            validate_non_negative_int(count)
        if self.known_count + self.unknown_count != self.eligible_count:
            raise ContractValidationError(
                "known and unknown counts must sum to eligible"
            )
        if self.eligible_count + self.excluded_count != self.intended_count:
            raise ContractValidationError(
                "eligible and excluded counts must sum to intended"
            )
        if self.disposition not in DISPOSITIONS:
            raise ContractValidationError("disposition is not a recognized value")
        if self.disposition == "available":
            if self.known_count == 0 or self.accuracy is None:
                raise ContractValidationError(
                    "an available report carries resolved support"
                )
            validate_probability(self.accuracy)
        elif self.known_count != 0 or self.accuracy is not None:
            raise ContractValidationError(
                "an unsupported report carries no accuracy value"
            )
        validate_utc_instant(self.computed_at)


def compute_accuracy_report(
    entry: AccuracyEntry,
    outcomes: tuple[AccuracyOutcome, ...],
    *,
    source_watermark: int,
    reference_watermark: int,
    computed_at: str,
) -> AccuracyReport:
    """Report *entry*'s accuracy over *outcomes* as a pure function of its arguments.

    Only eligible, already-known outcomes enter the metric; an ineligible
    outcome keeps its original exclusion and an eligible-but-unresolved
    outcome stays unknown support, never a fabricated score (SDD-SR-27).
    """

    metric_definition_hash = entry.metric_definition_hash
    reference_manifest = entry.reference_manifest
    if metric_definition_hash is None or reference_manifest is None:
        raise ContractValidationError(
            "a component with no accuracy measure or reference has no report"
        )
    if not outcomes:
        raise ContractValidationError("compute_accuracy_report requires an outcome")
    validate_non_negative_int(source_watermark)
    validate_non_negative_int(reference_watermark)
    eligible = [outcome for outcome in outcomes if outcome.eligible]
    known = [outcome for outcome in eligible if outcome.known]
    correct = [outcome for outcome in known if outcome.correct]
    accuracy = len(correct) / len(known) if known else None
    disposition = "available" if known else "insufficient_reference"
    return AccuracyReport(
        component_id=entry.component_id,
        component_version=entry.component_version,
        metric_definition_hash=metric_definition_hash,
        reference_manifest=reference_manifest,
        source_watermark=source_watermark,
        reference_watermark=reference_watermark,
        intended_count=len(outcomes),
        eligible_count=len(eligible),
        known_count=len(known),
        unknown_count=len(eligible) - len(known),
        excluded_count=len(outcomes) - len(eligible),
        accuracy=accuracy,
        disposition=disposition,
        computed_at=computed_at,
    )
