"""Schema evolution remains inactive at launch (AG-35).

There is no dormant search algorithm, extra model call or archive service
behind this mechanism -- ``reject_schema_evolution`` is the whole of it. It
never becomes cycle-eligible: activation requires an accepted future SDD
amendment and preregistered evaluation, not the completed weekly cycle
count that gates every other mechanism in this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from research_agent.contracts.primitives import ContractValidationError


@dataclass(frozen=True, slots=True)
class DisabledResult:
    """The fixed outcome of a launch request for schema evolution (AG-35)."""

    disposition: Literal["disabled_by_profile"]
    profile_hash: str


def reject_schema_evolution(*, profile_hash: str | None) -> DisabledResult:
    """Refuse every schema-evolution request with the active profile hash.

    Raises when *profile_hash* is missing -- a missing profile cannot
    enable this mechanism -- and otherwise always returns
    ``disabled_by_profile``: there is no launch state transition that
    activates it.
    """

    if not isinstance(profile_hash, str) or not profile_hash:
        raise ContractValidationError("reject_schema_evolution requires a profile hash")
    return DisabledResult(disposition="disabled_by_profile", profile_hash=profile_hash)
