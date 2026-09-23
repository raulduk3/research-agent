"""Weekly refresh: freeze a mature-label watermark and refit from it (SDD-FT-10).

``build_refresh`` freezes one committed evidence watermark and label-version
map at the job's own start, verifies every row it is about to fit or
calibrate on is backed by a label observation mature at that freeze, hashes
the resulting dataset and fitting configuration, and either skips fitting
entirely when that identity is unchanged from a prior run or refits,
recalibrates per category and records an explicit per-target outcome.
Corrections recorded after the freeze cannot enter this run; TDD-1.1.10 has
them "wait for a later run" instead of silently mixing into the current one.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from research_agent.contracts import canonical_json
from research_agent.contracts.learning import TARGET_IDS, TargetRegistry
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.learning.calibration import (
    CalibrationResult,
    CalibrationUnavailable,
    fit_calibrators_by_category,
)
from research_agent.learning.fit import (
    FitError,
    FitResult,
    MaterializedPartition,
    fit_head,
)

OUTCOME_STATUSES: frozenset[str] = frozenset(
    {"completed", "insufficient_data", "failed", "unchanged_data"}
)


class RefreshError(ValueError):
    """A refresh job's inputs cannot be frozen or fit as given."""


@dataclass(frozen=True, slots=True)
class LabelObservation:
    """One row's per-target label maturity, as known at refresh time.

    ``available_at`` is compared against the job's freeze: an observation
    later than the freeze cannot back a row this refresh fits or calibrates
    on, exactly the "select only mature labels whose available_at is at or
    before the freeze" rule.
    """

    family_id: str
    target_id: str
    label_version: str
    available_at: str

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        if self.target_id not in TARGET_IDS:
            raise RefreshError("label observation names an unregistered target")
        validate_non_empty_string(self.label_version)
        validate_utc_instant(self.available_at)


@dataclass(frozen=True, slots=True)
class RefreshWatermark:
    """The committed evidence watermark and label-version map, frozen at job start."""

    freeze_at: str
    label_version_map: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        validate_utc_instant(self.freeze_at)
        if not isinstance(self.label_version_map, tuple):
            raise RefreshError(
                "a watermark's label-version map must be an immutable tuple"
            )
        seen: set[tuple[str, str]] = set()
        for family_id, target_id, _version in self.label_version_map:
            validate_uuid4(family_id)
            if target_id not in TARGET_IDS:
                raise RefreshError(
                    "watermark label-version map names an unregistered target"
                )
            key = (family_id, target_id)
            if key in seen:
                raise RefreshError(
                    "watermark label-version map repeats a family/target pair"
                )
            seen.add(key)

    @property
    def watermark_hash(self) -> str:
        return sha256(
            canonical_json(
                {
                    "freeze_at": self.freeze_at,
                    "label_version_map": [
                        list(row) for row in sorted(self.label_version_map)
                    ],
                }
            )
        ).hexdigest()


def freeze_watermark(
    freeze_at: str, observations: tuple[LabelObservation, ...]
) -> RefreshWatermark:
    """Freeze one watermark from the observations known at job start.

    Any observation later than ``freeze_at`` refuses the freeze outright: a
    correction recorded after the watermark cannot retroactively join it,
    matching "corrections after the watermark wait for a later run."
    """

    for observation in observations:
        if observation.available_at > freeze_at:
            raise RefreshError(
                "a label observed after the freeze cannot enter this refresh"
            )
    label_version_map = tuple(
        sorted(
            (observation.family_id, observation.target_id, observation.label_version)
            for observation in observations
        )
    )
    return RefreshWatermark(freeze_at, label_version_map)


def _verify_maturity(
    watermark: RefreshWatermark,
    partitions: tuple[MaterializedPartition, ...],
) -> None:
    covered = {
        (family_id, target_id)
        for family_id, target_id, _ in watermark.label_version_map
    }
    for partition in partitions:
        for row, family_id in enumerate(partition.family_ids):
            for index, target_id in enumerate(TARGET_IDS):
                if not partition.known_mask[row, index]:
                    continue
                if (family_id, target_id) not in covered:
                    raise RefreshError(
                        "a materialized label has no covering mature observation"
                    )


@dataclass(frozen=True, slots=True)
class TargetRefreshOutcome:
    """One target's completion, insufficiency, failure or unchanged-data record."""

    target_id: str
    status: str
    reason: str | None
    fit: FitResult | None
    calibrations: tuple[CalibrationResult | CalibrationUnavailable, ...]

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise RefreshError("refresh outcome names an unregistered target")
        if self.status not in OUTCOME_STATUSES:
            raise RefreshError("refresh outcome status is not recognized")
        if self.status == "completed":
            if self.fit is None or self.reason is not None:
                raise RefreshError("a completed outcome requires its fit and no reason")
        else:
            if self.fit is not None or self.calibrations:
                raise RefreshError(
                    "a non-completed outcome carries no fit or calibration artifacts"
                )
            if self.status != "unchanged_data" and self.reason is None:
                raise RefreshError(f"a {self.status} outcome requires its reason")
            if self.status == "unchanged_data" and self.reason is not None:
                raise RefreshError(
                    "an unchanged-data outcome carries no failure reason"
                )


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """The registry-ordered outcome of one weekly refresh job."""

    watermark: RefreshWatermark
    dataset_hash: str
    fitting_config_hash: str
    outcomes: tuple[TargetRefreshOutcome, TargetRefreshOutcome, TargetRefreshOutcome]

    def __post_init__(self) -> None:
        validate_sha256(self.dataset_hash)
        validate_sha256(self.fitting_config_hash)
        if tuple(item.target_id for item in self.outcomes) != TARGET_IDS:
            raise RefreshError("refresh outcomes must cover the registry in order")


def _dataset_hash(
    watermark: RefreshWatermark,
    fitting_config_hash: str,
    fit: MaterializedPartition,
    development: MaterializedPartition,
    calibration: MaterializedPartition,
) -> str:
    def partition_identity(partition: MaterializedPartition) -> dict[str, object]:
        return {
            "partition": partition.partition,
            "family_ids": list(partition.family_ids),
            "labels": partition.labels.tolist(),
            "known_mask": partition.known_mask.tolist(),
            "corpus_release_hash": partition.corpus_release_hash,
            "split_hash": partition.split_hash,
            "target_registry_hash": partition.target_registry_hash,
            "representation_hash": partition.representation_hash,
        }

    return sha256(
        canonical_json(
            {
                "watermark_hash": watermark.watermark_hash,
                "fitting_config_hash": fitting_config_hash,
                "fit": partition_identity(fit),
                "development": partition_identity(development),
                "calibration": partition_identity(calibration),
            }
        )
    ).hexdigest()


def _classify_fit_error(error: FitError) -> str:
    return "insufficient_data" if "insufficient" in str(error) else "failed"


def build_refresh(
    registry: TargetRegistry,
    watermark: RefreshWatermark,
    fit: MaterializedPartition,
    development: MaterializedPartition,
    calibration: MaterializedPartition,
    fitting_config_hash: str,
    prior_dataset_hash: str | None = None,
) -> RefreshResult:
    """Freeze-verify, hash and, unless unchanged, refit and recalibrate all three targets.

    Every known row in ``fit``, ``development`` and ``calibration`` must be
    covered by a mature observation already folded into ``watermark``; this
    is the "select only mature labels" gate, checked before any fitting
    starts. When the resulting dataset-and-configuration hash matches
    ``prior_dataset_hash``, every target is recorded unchanged-data without
    calling the optimizer at all. Otherwise each registry target is fit and,
    on success, calibrated per primary category independently: one target's
    failure never blocks another's completion (SDD-FT-08, FT-10, FT-11).
    """

    validate_sha256(fitting_config_hash)
    _verify_maturity(watermark, (fit, development, calibration))
    dataset_hash = _dataset_hash(
        watermark, fitting_config_hash, fit, development, calibration
    )

    if prior_dataset_hash is not None and prior_dataset_hash == dataset_hash:
        unchanged = cast(
            "tuple[TargetRefreshOutcome, TargetRefreshOutcome, TargetRefreshOutcome]",
            tuple(
                TargetRefreshOutcome(target_id, "unchanged_data", None, None, ())
                for target_id in TARGET_IDS
            ),
        )
        return RefreshResult(watermark, dataset_hash, fitting_config_hash, unchanged)

    outcomes_list: list[TargetRefreshOutcome] = []
    for target in registry.definitions:
        try:
            fit_result = fit_head(target, fit, development)
        except FitError as error:
            outcomes_list.append(
                TargetRefreshOutcome(
                    target.target_id, _classify_fit_error(error), str(error), None, ()
                )
            )
            continue
        calibrations = fit_calibrators_by_category(fit_result, calibration)
        outcomes_list.append(
            TargetRefreshOutcome(
                target.target_id, "completed", None, fit_result, calibrations
            )
        )
    outcomes = cast(
        "tuple[TargetRefreshOutcome, TargetRefreshOutcome, TargetRefreshOutcome]",
        tuple(outcomes_list),
    )
    return RefreshResult(watermark, dataset_hash, fitting_config_hash, outcomes)
