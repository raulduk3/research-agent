"""Fit and calibrate the three registry prediction heads as one unit (SDD-FT-08, FT-11).

Each target is an independent logistic head over the same joined feature
matrix; a target's fit or calibration failure never blocks the other two, and
none of them ever falls back to a partial or overview-only vector — that
refusal already lives in ``MaterializedPartition``, which admits only the
fixed [N,2d] joined representation (SDD-FT-09). Numerical fitting and
calibration themselves stay in :mod:`research_agent.learning.fit` and
:mod:`research_agent.learning.calibration`; this module only sequences the
three registry targets through them in registry order.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.learning import TARGET_IDS, TargetRegistry
from research_agent.learning.calibration import CalibrationResult, fit_calibrator
from research_agent.learning.fit import (
    FitError,
    FitResult,
    MaterializedPartition,
    fit_head,
)


@dataclass(frozen=True, slots=True)
class HeadUnavailable:
    """A registry target that failed fitting or calibration, with why."""

    target_id: str
    reason: str

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise FitError("unavailable head names an unregistered target")


@dataclass(frozen=True, slots=True)
class ThreeHeadFit:
    """The registry-ordered fit outcome of all three targets, together."""

    fitted: tuple[FitResult | HeadUnavailable, ...]

    def __post_init__(self) -> None:
        if (
            len(self.fitted) != 3
            or tuple(item.target_id for item in self.fitted) != TARGET_IDS
        ):
            raise FitError("three-head fit must cover the registry in order")


def fit_three_heads(
    registry: TargetRegistry,
    fit: MaterializedPartition,
    development: MaterializedPartition,
) -> ThreeHeadFit:
    """Attempt one independent logistic fit per registry target.

    A target whose fit fails (insufficient classes, nonconvergence, a
    partition-identity mismatch) is recorded unavailable rather than raised;
    the other two targets still fit from the same partitions, since the three
    events can co-occur and are never combined into one shared model
    (SDD-FT-08).
    """

    results: list[FitResult | HeadUnavailable] = []
    for target in registry.definitions:
        try:
            results.append(fit_head(target, fit, development))
        except FitError as error:
            results.append(HeadUnavailable(target.target_id, str(error)))
    return ThreeHeadFit(tuple(results))


@dataclass(frozen=True, slots=True)
class CalibratedHead:
    """A fitted head paired with its own independently fitted calibrator."""

    head: FitResult
    calibrator: CalibrationResult

    def __post_init__(self) -> None:
        if self.head.target_id != self.calibrator.target_id:
            raise FitError("calibrated head target mismatch")

    @property
    def target_id(self) -> str:
        return self.head.target_id


@dataclass(frozen=True, slots=True)
class ThreeHeadCalibration:
    """The registry-ordered calibration outcome of all three fitted heads."""

    calibrated: tuple[CalibratedHead | HeadUnavailable, ...]

    def __post_init__(self) -> None:
        if (
            len(self.calibrated) != 3
            or tuple(item.target_id for item in self.calibrated) != TARGET_IDS
        ):
            raise FitError("three-head calibration must cover the registry in order")


def calibrate_three_heads(
    fitted: ThreeHeadFit, calibration: MaterializedPartition
) -> ThreeHeadCalibration:
    """Calibrate each fitted head on the shared calibration partition.

    A target that failed fitting stays unavailable without being calibrated.
    A target whose calibration fails (an overlapping family, insufficient
    calibration classes, nonconvergence) is demoted to unavailable: promotion
    always uses the calibrated probability, so an uncalibrated head is never
    eligible for it (SDD-FT-11).
    """

    results: list[CalibratedHead | HeadUnavailable] = []
    for item in fitted.fitted:
        if isinstance(item, HeadUnavailable):
            results.append(item)
            continue
        try:
            calibrator = fit_calibrator(item, calibration)
        except FitError as error:
            results.append(HeadUnavailable(item.target_id, str(error)))
            continue
        results.append(CalibratedHead(item, calibrator))
    return ThreeHeadCalibration(tuple(results))
