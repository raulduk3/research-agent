"""Pure ledger scoring: binary Brier loss and per-target skill (SDD-IN-01, FT-12).

Every function here is a pure function of its arguments. Nothing reads a clock,
draws a random value or calls a model; the caller supplies `computed_at` so that
running the same ledger records through `score_ledger` twice, at any two wall
times, gives byte-identical output.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, ClassVar, TypeVar, cast

from research_agent.contracts.canonical import (
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.scoring.schemas import ScoreInput

T = TypeVar("T")

DISPOSITIONS: frozenset[str] = frozenset({"available", "no_resolved_support"})
SKILL_DISPOSITIONS: frozenset[str] = frozenset({"available", "unavailable"})


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


@dataclass(frozen=True, slots=True)
class ForecastLoss:
    """The binary Brier loss of one resolved forecast."""

    forecast_id: str
    question_id: str
    squared_error: float

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"forecast_id", "question_id", "squared_error"}
    )

    def __post_init__(self) -> None:
        validate_uuid4(self.forecast_id)
        validate_uuid4(self.question_id)
        validate_probability(self.squared_error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "question_id": self.question_id,
            "squared_error": self.squared_error,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ForecastLoss":
        return _construct(
            cls, _closed(raw, cls._FIELDS, "ForecastLoss"), "ForecastLoss"
        )


@dataclass(frozen=True, slots=True)
class ScoreRecord:
    """The recorded outcome of scoring one target's rows in one ScoreInput."""

    schema_version: int
    input_manifest_hash: str
    target_id: str
    target_definition_hash: str
    producer_id: str
    scoring_watermark: int
    intended_count: int
    eligible_count: int
    resolved_count: int
    unresolved_count: int
    excluded_count: int
    losses: tuple[ForecastLoss, ...]
    mean_brier: float | None
    disposition: str
    computed_at: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "input_manifest_hash",
            "target_id",
            "target_definition_hash",
            "producer_id",
            "scoring_watermark",
            "intended_count",
            "eligible_count",
            "resolved_count",
            "unresolved_count",
            "excluded_count",
            "losses",
            "mean_brier",
            "disposition",
            "computed_at",
        }
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or self.schema_version != 1
        ):
            raise ContractValidationError("schema_version must be 1")
        validate_sha256(self.input_manifest_hash)
        if self.target_id not in TARGET_IDS:
            raise ContractValidationError("target_id is not a registered target")
        validate_sha256(self.target_definition_hash)
        validate_non_empty_string(self.producer_id)
        validate_positive_int(self.scoring_watermark)
        for count in (
            self.intended_count,
            self.eligible_count,
            self.resolved_count,
            self.unresolved_count,
            self.excluded_count,
        ):
            validate_non_negative_int(count)
        if self.resolved_count + self.unresolved_count != self.eligible_count:
            raise ContractValidationError(
                "resolved and unresolved counts must sum to eligible",
            )
        if self.eligible_count + self.excluded_count != self.intended_count:
            raise ContractValidationError(
                "eligible and excluded counts must sum to intended",
            )
        losses_are_consistent = (
            isinstance(self.losses, tuple) and len(self.losses) == self.resolved_count
        )
        if not losses_are_consistent:
            raise ContractValidationError(
                "losses must carry exactly resolved_count entries",
            )
        for loss in self.losses:
            if not isinstance(loss, ForecastLoss):
                raise ContractValidationError("losses must be ForecastLoss values")
        if self.disposition not in DISPOSITIONS:
            raise ContractValidationError("disposition is not a recognized value")
        if self.disposition == "available":
            if self.resolved_count == 0 or self.mean_brier is None:
                raise ContractValidationError(
                    "an available score carries resolved support",
                )
            validate_probability(self.mean_brier)
        elif self.resolved_count != 0 or self.mean_brier is not None:
            raise ContractValidationError(
                "an unsupported score carries no mean or losses",
            )
        validate_utc_instant(self.computed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_manifest_hash": self.input_manifest_hash,
            "target_id": self.target_id,
            "target_definition_hash": self.target_definition_hash,
            "producer_id": self.producer_id,
            "scoring_watermark": self.scoring_watermark,
            "intended_count": self.intended_count,
            "eligible_count": self.eligible_count,
            "resolved_count": self.resolved_count,
            "unresolved_count": self.unresolved_count,
            "excluded_count": self.excluded_count,
            "losses": [loss.to_dict() for loss in self.losses],
            "mean_brier": self.mean_brier,
            "disposition": self.disposition,
            "computed_at": self.computed_at,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ScoreRecord":
        values = _closed(raw, cls._FIELDS, "ScoreRecord")
        losses = values["losses"]
        if not isinstance(losses, list):
            raise ContractValidationError("losses must be a JSON array")
        values["losses"] = tuple(
            ForecastLoss.from_json(canonical_json(item)) for item in losses
        )
        return _construct(cls, values, "ScoreRecord")


def score_ledger(
    score_input: ScoreInput,
    *,
    producer_id: str,
    computed_at: str,
) -> ScoreRecord:
    """Score one target's rows in *score_input* as a pure function of its records.

    Reads only `score_input`: sealed forecasts and the resolution each carries,
    never paper content and never anything the ledger did not record. Missing or
    malformed rows already failed `ScoreInput.from_json`/`ScoringRow.__post_init__`
    before this runs, so any row that reaches here is well-formed; a row with no
    resolution stays unresolved and never adds a loss (SDD-IN-03 stays out of this
    slice's scope, but this function never counts an unresolved row as false).
    """

    rows = score_input.rows
    if not rows:
        raise ContractValidationError("score_ledger requires at least one row")
    target_id = rows[0].target_id
    target_definition_hash = rows[0].target_definition_hash
    for row in rows:
        same_target = (
            row.target_id == target_id
            and row.target_definition_hash == target_definition_hash
        )
        if not same_target:
            raise ContractValidationError(
                "score_ledger scores exactly one target definition per call",
            )
    ordered = sorted(rows, key=lambda row: row.forecast_id)
    canonical_input = replace(score_input, rows=tuple(ordered))
    eligible = [row for row in ordered if row.eligible]
    losses: list[ForecastLoss] = []
    unresolved_count = 0
    for row in eligible:
        if row.resolution is None:
            unresolved_count += 1
            continue
        outcome = 1.0 if row.resolution.outcome else 0.0
        squared_error = (float(row.probability) - outcome) ** 2
        losses.append(ForecastLoss(row.forecast_id, row.question_id, squared_error))
    resolved_count = len(losses)
    excluded_count = len(ordered) - len(eligible)
    mean_brier = (
        sum(loss.squared_error for loss in losses) / resolved_count
        if resolved_count
        else None
    )
    disposition = "available" if resolved_count else "no_resolved_support"
    return ScoreRecord(
        schema_version=1,
        input_manifest_hash=sha256_hex(canonical_input.to_canonical_json()),
        target_id=target_id,
        target_definition_hash=target_definition_hash,
        producer_id=producer_id,
        scoring_watermark=score_input.scoring_watermark,
        intended_count=len(ordered),
        eligible_count=len(eligible),
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        excluded_count=excluded_count,
        losses=tuple(losses),
        mean_brier=mean_brier,
        disposition=disposition,
        computed_at=computed_at,
    )


@dataclass(frozen=True, slots=True)
class TargetSkill:
    """Target-specific forecast skill against a baseline; no fitness (SDD-EN-16)."""

    target_id: str
    agent_producer_id: str
    baseline_producer_id: str
    support_count: int
    agent_mean_brier: float | None
    baseline_mean_brier: float | None
    skill: float | None
    disposition: str

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise ContractValidationError("target_id is not a registered target")
        validate_non_empty_string(self.agent_producer_id)
        validate_non_empty_string(self.baseline_producer_id)
        validate_non_negative_int(self.support_count)
        if self.disposition not in SKILL_DISPOSITIONS:
            raise ContractValidationError("disposition is not a recognized value")
        if self.disposition == "available":
            if (
                self.support_count == 0
                or self.agent_mean_brier is None
                or self.baseline_mean_brier is None
                or self.skill is None
            ):
                raise ContractValidationError(
                    "an available skill carries every value",
                )
            validate_probability(self.agent_mean_brier)
            validate_probability(self.baseline_mean_brier)
            if self.baseline_mean_brier == 0.0:
                raise ContractValidationError(
                    "an available skill needs a nonzero baseline",
                )
        elif self.skill is not None:
            raise ContractValidationError("an unavailable skill carries no ratio")


def target_skill(agent: ScoreRecord, baseline: ScoreRecord) -> TargetSkill:
    """Report Brier loss and skill for one target over the matched resolved support.

    Only questions both records resolved enter the comparison; nothing here reads
    or writes evolutionary fitness, and no average is taken across targets — this
    is called once per target (SDD-FT-12, SDD-EN-16).
    """

    if agent.target_id != baseline.target_id:
        raise ContractValidationError("target_skill compares the same target only")
    if agent.target_definition_hash != baseline.target_definition_hash:
        raise ContractValidationError(
            "target_skill compares the same target version only",
        )
    agent_losses = {loss.question_id: loss.squared_error for loss in agent.losses}
    baseline_losses = {loss.question_id: loss.squared_error for loss in baseline.losses}
    shared = sorted(set(agent_losses) & set(baseline_losses))
    if not shared:
        return TargetSkill(
            target_id=agent.target_id,
            agent_producer_id=agent.producer_id,
            baseline_producer_id=baseline.producer_id,
            support_count=0,
            agent_mean_brier=None,
            baseline_mean_brier=None,
            skill=None,
            disposition="unavailable",
        )
    support_count = len(shared)
    agent_total = sum(agent_losses[question_id] for question_id in shared)
    baseline_total = sum(baseline_losses[question_id] for question_id in shared)
    agent_mean = agent_total / support_count
    baseline_mean = baseline_total / support_count
    if baseline_mean == 0.0:
        return TargetSkill(
            target_id=agent.target_id,
            agent_producer_id=agent.producer_id,
            baseline_producer_id=baseline.producer_id,
            support_count=support_count,
            agent_mean_brier=agent_mean,
            baseline_mean_brier=baseline_mean,
            skill=None,
            disposition="unavailable",
        )
    return TargetSkill(
        target_id=agent.target_id,
        agent_producer_id=agent.producer_id,
        baseline_producer_id=baseline.producer_id,
        support_count=support_count,
        agent_mean_brier=agent_mean,
        baseline_mean_brier=baseline_mean,
        skill=1.0 - agent_mean / baseline_mean,
        disposition="available",
    )
