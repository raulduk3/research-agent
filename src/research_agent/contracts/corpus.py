"""Closed immutable corpus selection and temporal split records."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, TypeVar, cast

from .canonical import canonical_json, canonical_loads
from .primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")
_WEEK = re.compile(r"[0-9]{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])\Z")
_PARTITIONS = frozenset(
    {
        "pilot",
        "fit",
        "development",
        "calibration",
        "locked_evaluation",
        "refresh_fit",
        "refresh_calibration",
        "excluded",
    }
)
_EXCLUSIONS = frozenset(
    {
        "shortfall",
        "unknown_t0",
        "family_alias",
        "source_unavailable",
        "feature_unavailable",
        "missing_label",
        "pilot_reserved",
        "consumed_holdout",
        "slice_unqualified",
    }
)
_CARD_FIELDS = (
    "abstract_tokens",
    "title_tokens",
    "first_available_weekday",
    "code_link",
)


def _text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise ContractValidationError(f"{name} is invalid")
    return value


def _week(value: object) -> str:
    week = _text(value, "publication week")
    if _WEEK.fullmatch(week) is None:
        raise ContractValidationError("publication week is invalid")
    try:
        datetime.strptime(f"{week}-1", "%G-W%V-%u")
    except ValueError as error:
        raise ContractValidationError("publication week is invalid") from error
    return week


def _closed(raw: bytes, fields: set[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} fields do not match schema")
    return cast(dict[str, Any], value)


def _meta(values: dict[str, Any]) -> None:
    producer, inputs = values.get("producer_version"), values.get("input_hashes")
    if not isinstance(producer, dict) or not isinstance(inputs, list):
        raise ContractValidationError("RecordMeta fields are invalid")
    values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
    values["input_hashes"] = tuple(inputs)


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (TypeError, AttributeError, KeyError, ValueError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


@dataclass(frozen=True, slots=True)
class CorpusRow:
    paper_family_id: str
    original_version_id: str
    t0: str | None
    publication_week: str | None
    source_subfield: str | None
    selection_rank: int
    feature_hash: str | None
    label_hashes: tuple[str | None, str | None, str | None]
    known_mask: tuple[bool, bool, bool]
    partition: str
    exclusion_reasons: tuple[str, ...]
    author_count: int | None
    categories: tuple[str, ...] | None
    version_count: int | None
    # The rest of the declared metadata block's card fields (#149 Appendix B,
    # #278). A release written before they were recorded has none of the four
    # keys; its rows parse, and head fitting refuses them by name.
    abstract_tokens: int | None = None
    title_tokens: int | None = None
    first_available_weekday: int | None = None
    code_link: bool | None = None

    def __post_init__(self) -> None:
        validate_uuid4(self.paper_family_id)
        validate_uuid4(self.original_version_id)
        if self.t0 is not None:
            validate_utc_instant(self.t0)
        if (self.t0 is None) != (self.publication_week is None):
            raise ContractValidationError("publication week requires verified t0")
        if self.publication_week is not None:
            _week(self.publication_week)
            assert self.t0 is not None
            actual = datetime.fromisoformat(self.t0.replace("Z", "+00:00")).strftime(
                "%G-W%V"
            )
            if self.publication_week != actual:
                raise ContractValidationError("publication week differs from t0")
        if self.source_subfield is not None:
            _text(self.source_subfield, "source subfield")
        validate_non_negative_int(self.selection_rank)
        if self.feature_hash is not None:
            validate_sha256(self.feature_hash)
        if (
            not isinstance(self.label_hashes, tuple)
            or len(self.label_hashes) != 3
            or not isinstance(self.known_mask, tuple)
            or len(self.known_mask) != 3
        ):
            raise ContractValidationError(
                "label references and known mask must have three entries"
            )
        for label_hash, known in zip(self.label_hashes, self.known_mask, strict=True):
            if label_hash is not None:
                validate_sha256(label_hash)
            if not isinstance(known, bool) or (known and label_hash is None):
                raise ContractValidationError("known mask requires a label reference")
        if not isinstance(self.partition, str) or self.partition not in _PARTITIONS:
            raise ContractValidationError("corpus partition is invalid")
        if (
            not isinstance(self.exclusion_reasons, tuple)
            or any(
                not isinstance(reason, str) or reason not in _EXCLUSIONS
                for reason in self.exclusion_reasons
            )
            or len(set(self.exclusion_reasons)) != len(self.exclusion_reasons)
        ):
            raise ContractValidationError("corpus exclusion reasons are invalid")
        if self.partition == "excluded" and not self.exclusion_reasons:
            raise ContractValidationError("excluded corpus row requires a reason")
        if self.partition != "excluded" and "shortfall" in self.exclusion_reasons:
            raise ContractValidationError("shortfall cannot be an admitted corpus row")
        if self.author_count is not None:
            validate_non_negative_int(self.author_count)
        if self.categories is not None:
            if not isinstance(self.categories, tuple) or not self.categories:
                raise ContractValidationError(
                    "categories must be a nonempty, ordered tuple with the primary "
                    "first"
                )
            for category in self.categories:
                _text(category, "category")
        if self.version_count is not None:
            validate_positive_int(self.version_count)
        for tokens in (self.abstract_tokens, self.title_tokens):
            if tokens is not None:
                validate_non_negative_int(tokens)
        if self.first_available_weekday is not None:
            if (
                type(self.first_available_weekday) is not int
                or not 0 <= self.first_available_weekday <= 6
            ):
                raise ContractValidationError("first-availability weekday is invalid")
            if (
                self.t0 is None
                or self.first_available_weekday
                != datetime.fromisoformat(self.t0.replace("Z", "+00:00")).weekday()
            ):
                raise ContractValidationError(
                    "first-availability weekday differs from t0"
                )
        if self.code_link is not None and not isinstance(self.code_link, bool):
            raise ContractValidationError("code link flag must be boolean")

    def to_dict(self) -> dict[str, Any]:
        """The row's fields, without the card fields a row does not record."""
        value = asdict(self)
        if all(value[name] is None for name in _CARD_FIELDS):
            for name in _CARD_FIELDS:
                del value[name]
        return value

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "CorpusRow":
        fields = set(cls.__slots__)
        value = canonical_loads(raw)
        if isinstance(value, dict) and not set(_CARD_FIELDS) & set(value):
            fields -= set(_CARD_FIELDS)
        values = _closed(raw, fields, "CorpusRow")
        if set(_CARD_FIELDS) <= set(values) and all(
            values[name] is None for name in _CARD_FIELDS
        ):
            raise ContractValidationError(
                "unrecorded card fields are omitted, never null"
            )
        for name in ("label_hashes", "known_mask", "exclusion_reasons"):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        if values["categories"] is not None:
            if not isinstance(values["categories"], list):
                raise ContractValidationError("categories must be an array")
            values["categories"] = tuple(values["categories"])
        return _construct(cls, values, "CorpusRow")


@dataclass(frozen=True, slots=True)
class CorpusRelease(RecordMeta):
    purpose: str
    target_registry_hash: str
    representation_hash: str
    selection_seed: int
    selection_frozen_at: str
    fitting_cutoff: str
    intended_population_count: int
    enumerated_population_hash: str
    rows: tuple[CorpusRow, ...]
    shortfall_count: int
    split_hash: str
    coverage_report_hash: str
    source_observation_hashes: tuple[str, ...]
    prior_release_hash: str | None

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        if not isinstance(self.purpose, str) or self.purpose not in {
            "acquisition_pilot",
            "initial_fit",
            "initial_expansion",
            "weekly_refresh",
        }:
            raise ContractValidationError("corpus purpose is invalid")
        for value in (
            self.target_registry_hash,
            self.representation_hash,
            self.enumerated_population_hash,
            self.split_hash,
            self.coverage_report_hash,
        ):
            validate_sha256(value)
        if self.selection_seed != 20260920 or isinstance(self.selection_seed, bool):
            raise ContractValidationError("selection seed is invalid")
        start = validate_utc_instant(self.selection_frozen_at)
        cutoff = validate_utc_instant(self.fitting_cutoff)
        if start > cutoff or cutoff > self.created_at:
            raise ContractValidationError(
                "corpus freeze, cutoff and creation are out of order"
            )
        validate_positive_int(self.intended_population_count)
        fixed = {
            "acquisition_pilot": 100,
            "initial_fit": 2000,
            "initial_expansion": 5000,
        }
        if (
            self.purpose in fixed
            and self.intended_population_count != fixed[self.purpose]
        ):
            raise ContractValidationError(
                "corpus intended population differs from fixed protocol"
            )
        validate_non_negative_int(self.shortfall_count)
        if not isinstance(self.rows, tuple) or not all(
            isinstance(row, CorpusRow) for row in self.rows
        ):
            raise ContractValidationError("corpus rows must be immutable typed records")
        # Weekly refresh retains prior membership while adding newly mature weeks.
        # Its intended denominator is validated against its frozen enumeration by
        # the admission owner; this record alone cannot reconstruct it.
        if (
            self.purpose != "weekly_refresh"
            and len(self.rows) + self.shortfall_count != self.intended_population_count
        ):
            raise ContractValidationError(
                "corpus shortfall differs from intended population"
            )
        ids = [row.paper_family_id for row in self.rows]
        ranks = [row.selection_rank for row in self.rows]
        if (
            len(set(ids)) != len(ids)
            or len(set(ranks)) != len(ranks)
            or ranks != sorted(ranks)
        ):
            raise ContractValidationError(
                "corpus rows must have unique families and ordered ranks"
            )
        if not isinstance(self.source_observation_hashes, tuple):
            raise ContractValidationError("source observation hashes must be immutable")
        for value in self.source_observation_hashes:
            validate_sha256(value)
        if len(set(self.source_observation_hashes)) != len(
            self.source_observation_hashes
        ):
            raise ContractValidationError("source observation hashes are duplicated")
        if self.prior_release_hash is not None:
            validate_sha256(self.prior_release_hash)

    def to_canonical_json(self) -> bytes:
        value = asdict(self)
        value["rows"] = [row.to_dict() for row in self.rows]
        return canonical_json(value)

    @classmethod
    def from_json(cls, raw: bytes) -> "CorpusRelease":
        values = _closed(
            raw, set(cls.__slots__) | set(RecordMeta.__slots__), "CorpusRelease"
        )
        _meta(values)
        if not isinstance(values["rows"], list) or not isinstance(
            values["source_observation_hashes"], list
        ):
            raise ContractValidationError("corpus arrays are invalid")
        values["rows"] = tuple(
            CorpusRow.from_json(canonical_json(row)) for row in values["rows"]
        )
        values["source_observation_hashes"] = tuple(values["source_observation_hashes"])
        return _construct(cls, values, "CorpusRelease")


@dataclass(frozen=True, slots=True)
class TemporalSplit(RecordMeta):
    ordered_weeks: tuple[str, ...]
    fit_weeks: tuple[str, ...]
    development_weeks: tuple[str, ...]
    calibration_weeks: tuple[str, ...]
    locked_evaluation_weeks: tuple[str, ...]
    family_partition_hash: str
    created_before_outcome_inspection: bool

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        names = (
            "ordered_weeks",
            "fit_weeks",
            "development_weeks",
            "calibration_weeks",
            "locked_evaluation_weeks",
        )
        arrays = tuple(getattr(self, name) for name in names)
        if any(not isinstance(weeks, tuple) for weeks in arrays):
            raise ContractValidationError("temporal weeks must be immutable arrays")
        ordered, fit, development, calibration, evaluation = arrays
        if len(ordered) < 40 or len(set(ordered)) != len(ordered):
            raise ContractValidationError(
                "temporal split needs at least forty unique weeks"
            )
        for week in ordered:
            _week(week)
        dates = [datetime.strptime(f"{week}-1", "%G-W%V-%u") for week in ordered]
        if dates != sorted(dates):
            raise ContractValidationError("temporal weeks must be chronological")
        count = len(ordered)
        lengths = (count * 60 // 100, count * 15 // 100, count * 10 // 100)
        if min(len(fit), len(development), len(calibration), len(evaluation)) < 4 or (
            fit,
            development,
            calibration,
            evaluation,
        ) != (
            ordered[: lengths[0]],
            ordered[lengths[0] : sum(lengths[:2])],
            ordered[sum(lengths[:2]) : sum(lengths)],
            ordered[sum(lengths) :],
        ):
            raise ContractValidationError(
                "temporal split partitions differ from fixed boundaries"
            )
        validate_sha256(self.family_partition_hash)
        if self.created_before_outcome_inspection is not True:
            raise ContractValidationError(
                "temporal split must precede outcome inspection"
            )

    def to_canonical_json(self) -> bytes:
        return canonical_json(asdict(self))

    @classmethod
    def from_json(cls, raw: bytes) -> "TemporalSplit":
        values = _closed(
            raw, set(cls.__slots__) | set(RecordMeta.__slots__), "TemporalSplit"
        )
        _meta(values)
        for name in (
            "ordered_weeks",
            "fit_weeks",
            "development_weeks",
            "calibration_weeks",
            "locked_evaluation_weeks",
        ):
            if not isinstance(values[name], list):
                raise ContractValidationError(f"{name} must be an array")
            values[name] = tuple(values[name])
        return _construct(cls, values, "TemporalSplit")
