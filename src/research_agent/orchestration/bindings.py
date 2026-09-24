"""What a day's runs are bound to, and what the day may still spend (#285).

`current_bindings` gathers the caller-fixed half of a run record: the
pinned agent model manifest, the service image versions observed at daily
run time, and the launch profile's per-run budgets and tools. Nothing is
stored or read from an active pointer; the snapshot-derived half, the paper
card manifest and prediction head bundles, comes from
`orchestration/stamps.py#build_run_stamp` (SR-15).

`remaining_spend` is the amount an island's coverage draw may still
reserve today: the smaller of the profile's daily and monthly caps less
the settled spend the owner cost read reports (#251), zero unless funded
execution is enabled. A settled run with no price yet is charged its full
per-run reservation, because an ambiguous billed attempt consumes its
reserved amount until reconciled (Appendix A).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from research_agent.contracts.primitives import (
    validate_non_negative_int,
    validate_sha256,
)
from research_agent.platform.builds import ObservedImage
from research_agent.platform.profile import LaunchProfile
from research_agent.storage.errors import UnavailableInput

__all__ = ["CostReader", "RunBindings", "current_bindings", "remaining_spend"]


class _Costs(Protocol):
    @property
    def data(self) -> Mapping[str, Any]: ...


class CostReader(Protocol):
    """The owner cost read (#251): ``StorageClient`` over the service, or
    the operator's own settlement read in process."""

    def read_costs(self, day: str) -> _Costs: ...


@dataclass(frozen=True, slots=True)
class RunBindings:
    """The caller-fixed fields of every run record a day issues."""

    agent_model_manifest: str
    service_image_versions: dict[str, str]
    budgets: dict[str, int]
    allowed_tools: tuple[str, ...]


def current_bindings(
    profile: LaunchProfile,
    *,
    agent_model_manifest_hash: str,
    observed_images: tuple[ObservedImage, ...],
) -> RunBindings:
    """Bind a day's runs to the pinned model, the observed images and the profile.

    Each service is named by its container role and versioned by the image
    digest it actually runs. No observed image, or two images claiming one
    role, refuses with a named reason rather than recording an identity
    that does not say what served the run. The whole identity is
    validated against the run contract when the stamp adds the snapshot's
    half (`RunStamp.model_identity`).
    """

    validate_sha256(agent_model_manifest_hash)
    if not observed_images:
        raise UnavailableInput("no_observed_service_images")
    versions: dict[str, str] = {}
    for image in observed_images:
        if image.role in versions:
            raise UnavailableInput(f"duplicate_service_role:{image.role}")
        versions[image.role] = image.image_digest
    return RunBindings(
        agent_model_manifest=agent_model_manifest_hash,
        service_image_versions=versions,
        budgets=profile.run.budgets(),
        allowed_tools=tuple(sorted(profile.run.allowed_tools)),
    )


def _spent(totals: Mapping[str, Any], reservation: int) -> int:
    priced = validate_non_negative_int(totals["priced_micros"])
    unpriced = validate_non_negative_int(totals["unpriced_runs"])
    return priced + unpriced * reservation


def remaining_spend(client: CostReader, profile: LaunchProfile, day: str) -> int:
    """Microdollars the day's draw may still reserve under both caps.

    Zero unless the profile is funded with paid execution enabled; never
    negative, however far settled spend has run past a cap.
    """

    budget = profile.budget
    if not (budget.funded and budget.paid_execution_enabled):
        return 0
    costs = client.read_costs(day).data
    reservation = profile.run.spend_micros
    day_left = budget.daily_cap_micros - _spent(costs["day_totals"], reservation)
    month_left = budget.monthly_cap_micros - _spent(costs["month_totals"], reservation)
    return max(0, min(day_left, month_left))
