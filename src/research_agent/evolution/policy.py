"""Report forecast measurements without selection authority (SDD-EN-16).

``selection_disposition`` is what a weekly or comparison report may safely
read: the active configuration-manifest hash beside each target's already
computed skill and skill-per-dollar record (TDD-4.1.75). The returned value
carries no weighted aggregate fitness field and no cost objective, and
exposes no operation that could request a parent draw or a replacement --
only ``research_agent.orchestration.selection.select_population`` (FT-14)
changes a population. A report built from this object cannot smuggle a
fitness number into selection through the one channel it is allowed to read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_agent.contracts.primitives import ContractValidationError, validate_sha256
from research_agent.scoring.scores import TargetSkill


@dataclass(frozen=True, slots=True)
class SelectionDisposition:
    """A read-only report of one genome's measurements (SDD-EN-16).

    Carries the active configuration-manifest hash and each target's skill
    and skill-per-dollar record, and nothing else: no averaged fitness
    field, no cost objective, and no field or method a caller could use to
    request a parent draw or a replacement.
    """

    configuration_manifest_hash: str
    target_skills: tuple[TargetSkill, ...]


def selection_disposition(
    *, configuration_manifest_hash: str, target_skills: Sequence[TargetSkill]
) -> SelectionDisposition:
    """Report per-target skill beside the manifest hash; select nothing.

    Raises when the manifest hash is missing or malformed -- fail-closed,
    the same as every cycle-gated mechanism in this package -- rather than
    reporting under an unidentified configuration. Drastically changing the
    citation, preference or cost inputs behind *target_skills* changes only
    what this report shows: it has no path back into population identity.
    """

    validate_sha256(configuration_manifest_hash)
    if not isinstance(target_skills, Sequence) or isinstance(
        target_skills, (str, bytes)
    ):
        raise ContractValidationError("target_skills must be a sequence")
    for skill in target_skills:
        if not isinstance(skill, TargetSkill):
            raise ContractValidationError("target_skills must hold TargetSkill values")
    return SelectionDisposition(
        configuration_manifest_hash=configuration_manifest_hash,
        target_skills=tuple(target_skills),
    )
