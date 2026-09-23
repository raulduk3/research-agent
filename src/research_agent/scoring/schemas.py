"""The content-free wire contract the scorer reads: forecasts and resolutions only.

A row names a paper only by its family id. No field here can carry paper text, a
paper card, an image or a model output, so a scorer bound to this schema has no
interface to read paper content through (SDD-IN-02).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, cast

from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    validate_non_negative_int,
    validate_positive_int,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")

INELIGIBLE_REASONS: frozenset[str] = frozenset(
    {"late", "invalidated", "wrong_target_version"}
)
_PUBLICATION_WEEK = re.compile(r"[0-9]{4}-W[0-9]{2}\Z")


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


def validate_publication_week(value: object) -> str:
    if not isinstance(value, str) or _PUBLICATION_WEEK.fullmatch(value) is None:
        raise ContractValidationError(
            "publication_week must be an ISO YYYY-Www string",
        )
    return value


@dataclass(frozen=True, slots=True)
class ScoringResolution:
    """The settled outcome for a question, known no earlier than its horizon."""

    outcome: bool
    resolved_at: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"outcome", "resolved_at"})

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, bool):
            raise ContractValidationError("outcome must be a boolean")
        validate_utc_instant(self.resolved_at)

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "resolved_at": self.resolved_at}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ScoringResolution":
        return _construct(
            cls, _closed(raw, cls._FIELDS, "ScoringResolution"), "ScoringResolution"
        )


@dataclass(frozen=True, slots=True)
class SettledCost:
    """A run's reconciled `agent_inference` reservation (SDD-FT-12)."""

    reservation_id: str
    amount_microdollars: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"reservation_id", "amount_microdollars"}
    )

    def __post_init__(self) -> None:
        validate_uuid4(self.reservation_id)
        validate_non_negative_int(self.amount_microdollars)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "amount_microdollars": self.amount_microdollars,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "SettledCost":
        return _construct(cls, _closed(raw, cls._FIELDS, "SettledCost"), "SettledCost")


@dataclass(frozen=True, slots=True)
class ScoringRow:
    """One sealed forecast the scorer may read, with its resolution if known."""

    forecast_id: str
    question_id: str
    family_id: str
    publication_week: str
    target_id: str
    target_definition_hash: str
    probability: float
    sealed_at: str
    eligible: bool
    ineligible_reason: str | None
    resolution: ScoringResolution | None
    settled_cost: SettledCost | None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "forecast_id",
            "question_id",
            "family_id",
            "publication_week",
            "target_id",
            "target_definition_hash",
            "probability",
            "sealed_at",
            "eligible",
            "ineligible_reason",
            "resolution",
            "settled_cost",
        }
    )

    def __post_init__(self) -> None:
        validate_uuid4(self.forecast_id)
        validate_uuid4(self.question_id)
        validate_uuid4(self.family_id)
        validate_publication_week(self.publication_week)
        if self.target_id not in TARGET_IDS:
            raise ContractValidationError("target_id is not a registered target")
        validate_sha256(self.target_definition_hash)
        validate_probability(self.probability)
        validate_utc_instant(self.sealed_at)
        if not isinstance(self.eligible, bool):
            raise ContractValidationError("eligible must be a boolean")
        if self.eligible:
            if self.ineligible_reason is not None:
                raise ContractValidationError(
                    "an eligible row carries no ineligible_reason"
                )
        elif self.ineligible_reason not in INELIGIBLE_REASONS:
            raise ContractValidationError("an ineligible row requires a known reason")
        if self.resolution is not None and not isinstance(
            self.resolution, ScoringResolution
        ):
            raise ContractValidationError("resolution must be a ScoringResolution")
        if self.settled_cost is not None and not isinstance(
            self.settled_cost, SettledCost
        ):
            raise ContractValidationError("settled_cost must be a SettledCost")

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "question_id": self.question_id,
            "family_id": self.family_id,
            "publication_week": self.publication_week,
            "target_id": self.target_id,
            "target_definition_hash": self.target_definition_hash,
            "probability": self.probability,
            "sealed_at": self.sealed_at,
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
            "resolution": self.resolution.to_dict() if self.resolution else None,
            "settled_cost": self.settled_cost.to_dict() if self.settled_cost else None,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ScoringRow":
        values = _closed(raw, cls._FIELDS, "ScoringRow")
        resolution = values["resolution"]
        if resolution is not None:
            if not isinstance(resolution, dict):
                raise ContractValidationError("resolution must be a JSON object")
            values["resolution"] = ScoringResolution.from_json(
                canonical_json(resolution),
            )
        settled_cost = values["settled_cost"]
        if settled_cost is not None:
            if not isinstance(settled_cost, dict):
                raise ContractValidationError("settled_cost must be a JSON object")
            values["settled_cost"] = SettledCost.from_json(
                canonical_json(settled_cost),
            )
        return _construct(cls, values, "ScoringRow")


@dataclass(frozen=True, slots=True)
class ScoreInput(RecordMeta):
    """The complete versioned projection a scorer role may read (SDD-IN-02)."""

    scoring_watermark: int
    as_of: str
    protocol_hash: str
    rows: tuple[ScoringRow, ...]
    intended_forecast_count: int

    _FIELDS: ClassVar[frozenset[str]] = RecordMeta._FIELDS | frozenset(
        {
            "scoring_watermark",
            "as_of",
            "protocol_hash",
            "rows",
            "intended_forecast_count",
        }
    )

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_positive_int(self.scoring_watermark)
        validate_utc_instant(self.as_of)
        validate_sha256(self.protocol_hash)
        if not isinstance(self.rows, tuple) or len(self.rows) > 1_000_000:
            raise ContractValidationError(
                "rows must be an ordered list of at most 1000000 rows"
            )
        for row in self.rows:
            if not isinstance(row, ScoringRow):
                raise ContractValidationError("rows must be ScoringRow values")
        if len({row.forecast_id for row in self.rows}) != len(self.rows):
            raise ContractValidationError("forecast ids must be unique")
        validate_non_negative_int(self.intended_forecast_count)
        if self.intended_forecast_count < len(self.rows):
            raise ContractValidationError(
                "intended_forecast_count cannot undercount recorded rows"
            )

    def to_dict(self) -> dict[str, Any]:
        body = RecordMeta.to_dict(self)
        body.update(
            {
                "scoring_watermark": self.scoring_watermark,
                "as_of": self.as_of,
                "protocol_hash": self.protocol_hash,
                "rows": [row.to_dict() for row in self.rows],
                "intended_forecast_count": self.intended_forecast_count,
            }
        )
        return body

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ScoreInput":
        values = _closed(raw, cls._FIELDS, "ScoreInput")
        producer = values["producer_version"]
        hashes = values["input_hashes"]
        rows = values["rows"]
        if not isinstance(producer, dict) or not isinstance(hashes, list):
            raise ContractValidationError("ScoreInput RecordMeta fields are invalid")
        if not isinstance(rows, list):
            raise ContractValidationError("rows must be a JSON array")
        values["producer_version"] = ProducerVersion.from_json(
            canonical_json(producer),
        )
        values["input_hashes"] = tuple(hashes)
        values["rows"] = tuple(
            ScoringRow.from_json(canonical_json(item)) for item in rows
        )
        return _construct(cls, values, "ScoreInput")
