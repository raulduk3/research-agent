"""The one resampling routine every comparison shares (SDD-IN-15, TDD-4.1.19).

Resampling draws whole publication weeks with replacement, never individual
forecasts or families, so a week's families are never separated from each
other or from their own forecasts. The routine is a pure function of its
rows, an immutable family/week cluster map, the requested percentile tails
and a seed: the same four inputs always reproduce the identical interval,
independent of the order `rows` arrives in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.measurement import MeasurementError

METHOD = "percentile_bootstrap"
METHOD_VERSION = 1
BOOTSTRAP_SEED = 20260920
RESAMPLE_COUNT = 10_000
DISPOSITIONS: frozenset[str] = frozenset({"available", "unavailable"})


class ClusteredDifference(Protocol):
    """The shape `bootstrap_difference` needs from each paired row."""

    publication_week: str
    family_id: str

    @property
    def difference(self) -> float: ...


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    """A percentile-bootstrap interval for a paired difference, or its absence."""

    method: str
    method_version: int
    resamples: int
    seed: int
    lower_tail: float
    upper_tail: float
    support_count: int
    support_hash: str
    estimate: float | None
    low: float | None
    high: float | None
    disposition: str

    def __post_init__(self) -> None:
        if self.disposition not in DISPOSITIONS:
            raise MeasurementError("disposition is not a recognized value")
        if self.disposition == "available":
            if self.estimate is None or self.low is None or self.high is None:
                raise MeasurementError("an available interval carries every bound")
            if self.low > self.high:
                raise MeasurementError("interval bounds must be ordered low <= high")
        elif self.estimate is not None or self.low is not None or self.high is not None:
            raise MeasurementError("an unavailable interval carries no bounds")


def bootstrap_difference(
    rows: Sequence[ClusteredDifference],
    cluster_map: Mapping[str, frozenset[str]],
    *,
    lower_tail: float,
    upper_tail: float,
    seed: int = BOOTSTRAP_SEED,
    resamples: int = RESAMPLE_COUNT,
) -> BootstrapInterval:
    """Bootstrap the mean paired difference by resampling publication weeks.

    `cluster_map` is the immutable, independently supplied publication-week
    to family-id assignment; every row must name a week and family already
    present in it, so a row referencing a week or family outside the frozen
    mapping is rejected rather than silently pooled (SDD-IN-15's "one
    resampling routine, shared by all comparisons"). Each of `resamples`
    draws samples the observed weeks with replacement and carries every row
    of a drawn week into that draw's statistic, so families are never
    resampled apart from their own week.
    """

    if not 0 <= lower_tail < upper_tail <= 100:
        raise MeasurementError(
            "bootstrap tails must be an ordered percentile pair within [0, 100]"
        )
    if resamples <= 0:
        raise MeasurementError("resamples must be a positive integer")

    support_hash = _support_hash(rows)
    if not rows:
        return BootstrapInterval(
            method=METHOD,
            method_version=METHOD_VERSION,
            resamples=resamples,
            seed=seed,
            lower_tail=lower_tail,
            upper_tail=upper_tail,
            support_count=0,
            support_hash=support_hash,
            estimate=None,
            low=None,
            high=None,
            disposition="unavailable",
        )

    rows_by_week: dict[str, list[ClusteredDifference]] = {}
    for row in rows:
        families = cluster_map.get(row.publication_week)
        if families is None or row.family_id not in families:
            raise MeasurementError(
                "a row's publication week and family must be in the cluster map"
            )
        rows_by_week.setdefault(row.publication_week, []).append(row)

    weeks = sorted(rows_by_week)
    week_sums = np.array(
        [sum(row.difference for row in rows_by_week[week]) for week in weeks],
        dtype=np.float64,
    )
    week_counts = np.array(
        [len(rows_by_week[week]) for week in weeks], dtype=np.float64
    )
    observed_estimate = float(week_sums.sum() / week_counts.sum())

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(weeks), size=(resamples, len(weeks)))
    totals = week_sums[draws].sum(axis=1)
    counts = week_counts[draws].sum(axis=1)
    estimates = totals / counts

    if not np.isfinite(observed_estimate) or not np.all(np.isfinite(estimates)):
        return BootstrapInterval(
            method=METHOD,
            method_version=METHOD_VERSION,
            resamples=resamples,
            seed=seed,
            lower_tail=lower_tail,
            upper_tail=upper_tail,
            support_count=len(rows),
            support_hash=support_hash,
            estimate=None,
            low=None,
            high=None,
            disposition="unavailable",
        )

    percentiles = np.percentile(estimates, [lower_tail, upper_tail])
    low = float(percentiles[0])
    high = float(percentiles[1])
    return BootstrapInterval(
        method=METHOD,
        method_version=METHOD_VERSION,
        resamples=resamples,
        seed=seed,
        lower_tail=lower_tail,
        upper_tail=upper_tail,
        support_count=len(rows),
        support_hash=support_hash,
        estimate=observed_estimate,
        low=float(low),
        high=float(high),
        disposition="available",
    )


def _support_hash(rows: Sequence[ClusteredDifference]) -> str:
    entries = sorted(
        (row.publication_week, row.family_id, row.difference) for row in rows
    )
    return sha256_hex(
        canonical_json(
            [
                {"publication_week": w, "family_id": f, "difference": d}
                for w, f, d in entries
            ]
        )
    )
