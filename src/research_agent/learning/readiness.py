"""Engineering, per-head, three-head and prospective readiness, apart (SDD FT-24).

Readiness is read from the currently active bundle (or its absence), never
recomputed from statistical qualification here: whether a target actually
qualifies is decided upstream, when its bundle entry is built (SDD FT-22,
FT-23); this module only reports what the active bundle already says,
plus the engineering/Jev gates that stay available before any target ever
qualifies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from research_agent.contracts.learning import TARGET_IDS
from research_agent.models.registry import ServingHandle


class ReadinessError(ValueError):
    """A readiness report is not internally consistent."""


@dataclass(frozen=True, slots=True)
class TargetReadiness:
    """Whether one registry target is currently qualified to serve, and why not."""

    target_id: str
    qualified: bool
    reason: str | None

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise ReadinessError("target readiness names an unregistered target")
        if self.qualified and self.reason is not None:
            raise ReadinessError("a qualified target carries no reason")
        if not self.qualified and not self.reason:
            raise ReadinessError("an unqualified target requires a reason")


@dataclass(frozen=True, slots=True)
class ForecastReadiness:
    """SDD FT-24: engineering operation, individual heads and the three-head feature, apart."""

    engineering_ready: bool
    paper_cards_readable: bool
    jev_smoke_tested: bool
    targets: tuple[TargetReadiness, TargetReadiness, TargetReadiness]
    all_three_qualified: bool
    mature_prospective_evaluation: bool

    def __post_init__(self) -> None:
        if tuple(target.target_id for target in self.targets) != TARGET_IDS:
            raise ReadinessError("target readiness must cover the registry in order")
        if self.all_three_qualified != all(target.qualified for target in self.targets):
            raise ReadinessError(
                "all-three readiness disagrees with its own per-target gates"
            )
        if self.mature_prospective_evaluation and not self.all_three_qualified:
            raise ReadinessError(
                "prospective benefit requires all-three readiness first"
            )

    def qualified_target_ids(self) -> tuple[str, ...]:
        return tuple(target.target_id for target in self.targets if target.qualified)


def forecast_readiness(
    *,
    engineering_ready: bool,
    paper_cards_readable: bool,
    jev_smoke_tested: bool,
    handle: ServingHandle | None,
    mature_sealed_predictions: bool,
) -> ForecastReadiness:
    """Build the readiness report from the currently active bundle, if any.

    An empty registry -- no bundle has ever been activated -- still permits
    source capture and readable paper cards (SDD FT-24); every target is
    simply reported unqualified for that reason.
    """

    if handle is None:
        targets = tuple(
            TargetReadiness(target_id, False, "no_bundle_activated")
            for target_id in TARGET_IDS
        )
    else:
        targets = tuple(
            TargetReadiness(
                entry.target_id,
                entry.status == "qualified",
                None if entry.status == "qualified" else entry.reason,
            )
            for entry in handle.manifest.entries
        )
    all_three = all(target.qualified for target in targets)
    return ForecastReadiness(
        engineering_ready=engineering_ready,
        paper_cards_readable=paper_cards_readable,
        jev_smoke_tested=jev_smoke_tested,
        targets=cast(
            "tuple[TargetReadiness, TargetReadiness, TargetReadiness]", targets
        ),
        all_three_qualified=all_three,
        mature_prospective_evaluation=all_three and mature_sealed_predictions,
    )
