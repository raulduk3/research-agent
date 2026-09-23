"""Field-level mutation, performance-gated mutation and migration (AG-06, AG-20, AG-37).

``propose_mutation`` is AG-20's own operator: it accepts a proposal that
changes exactly one of a parent genome's four emphasis-carrying parts,
copies every other part byte for byte, and refuses whole a proposal that
touches more than one part or a part outside that fixed set -- no model
call ever generates the new value. ``propose_performance_mutation`` is
AG-06's cycle-gated wrapper around it, bounding a parent to one child per
cycle. ``propose_migration`` is AG-37: a mutation whose parent or changed
value comes from another island, refused whole into the q-bio island and
recorded as a migration wherever it is admitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
)
from research_agent.evolution.genome import EMPHASIS_FIELDS, Genome
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.orchestration.selection import cycle_guard

MutationRejectionReason = Literal["invalid_proposal", "already_mutated_this_cycle"]


@dataclass(frozen=True, slots=True)
class MutationResult:
    """The outcome of one mutation proposal (AG-20)."""

    disposition: Literal["disabled_by_profile", "rejected", "accepted"]
    profile_hash: str
    parent_hash: str | None
    changed_field: str | None
    child: Genome | None
    reason: MutationRejectionReason | None = None


def propose_mutation(
    *,
    parent: Genome,
    changes: Mapping[str, str],
    lineage_id: str,
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
    destination_island: str | None = None,
) -> MutationResult:
    """Accept a proposal that changes exactly one emphasis part of *parent*.

    Applies the cycle guard first. Afterward, a proposal naming more than
    one field, naming a field outside the four emphasis-carrying parts
    (:data:`research_agent.evolution.genome.EMPHASIS_FIELDS`), or an unknown
    *destination_island*, is refused whole rather than partially applied.
    An accepted child copies every other part of *parent* byte for byte
    (its ``infra_hash`` is unchanged), so the common-infrastructure hash of
    AG-03 stays equal; *destination_island* lets AG-37 place the child in a
    different island than its parent while recording that as a migration.
    """

    if not isinstance(parent, Genome):
        raise ContractValidationError("propose_mutation requires a Genome parent")

    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    parent_hash = parent.configuration_hash
    if guard.disposition == "disabled_by_profile":
        return MutationResult(
            disposition="disabled_by_profile",
            profile_hash=guard.profile_hash,
            parent_hash=parent_hash,
            changed_field=None,
            child=None,
        )

    island = destination_island if destination_island is not None else parent.island
    if island not in ISLANDS:
        raise ContractValidationError(
            f"destination_island must be one of {sorted(ISLANDS)}"
        )

    if len(changes) != 1:
        return MutationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            parent_hash=parent_hash,
            changed_field=None,
            child=None,
            reason="invalid_proposal",
        )
    ((changed_field, new_value),) = changes.items()
    if changed_field not in EMPHASIS_FIELDS:
        return MutationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            parent_hash=parent_hash,
            changed_field=None,
            child=None,
            reason="invalid_proposal",
        )
    new_value = validate_non_empty_string(new_value)

    child_emphasis = dict(parent.emphasis)
    child_emphasis[changed_field] = new_value
    child = Genome(
        lineage_id=lineage_id,
        island=island,
        infra_hash=parent.infra_hash,
        emphasis=child_emphasis,
        founder=False,
        parent_hash=parent_hash,
    )
    return MutationResult(
        disposition="accepted",
        profile_hash=guard.profile_hash,
        parent_hash=parent_hash,
        changed_field=changed_field,
        child=child,
    )


def propose_performance_mutation(
    *,
    parent: Genome,
    changes: Mapping[str, str],
    lineage_id: str,
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
    already_mutated_this_cycle: bool = False,
) -> MutationResult:
    """AG-06's cycle-gated wrapper: at most one child per parent per cycle.

    Applies the same cycle guard as :func:`propose_mutation`, keeping the
    population and immutable schemas unchanged while disabled. Afterward it
    refuses a second proposal for a parent that already produced a child
    this cycle -- *already_mutated_this_cycle* is a caller-tracked fact,
    since counting proposals per cycle is a storage concern this module does
    not own -- and otherwise defers to :func:`propose_mutation` unchanged,
    still with no model call.
    """

    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    if guard.disposition == "disabled_by_profile":
        return MutationResult(
            disposition="disabled_by_profile",
            profile_hash=guard.profile_hash,
            parent_hash=parent.configuration_hash,
            changed_field=None,
            child=None,
        )
    if already_mutated_this_cycle:
        return MutationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            parent_hash=parent.configuration_hash,
            changed_field=None,
            child=None,
            reason="already_mutated_this_cycle",
        )
    return propose_mutation(
        parent=parent,
        changes=changes,
        lineage_id=lineage_id,
        completed_weekly_cycles=completed_weekly_cycles,
        profile_hash=profile_hash,
    )


@dataclass(frozen=True, slots=True)
class Migration:
    """One mutation's cross-island provenance, recorded wherever admitted (AG-37)."""

    child_hash: str
    source_island: str
    source_hash: str
    kind: Literal["parent", "field"]
    field_name: str | None
    cycle_id: str

    def __post_init__(self) -> None:
        validate_sha256(self.child_hash)
        if self.source_island not in ISLANDS:
            raise ContractValidationError(
                f"source_island must be one of {sorted(ISLANDS)}"
            )
        validate_sha256(self.source_hash)
        if self.kind not in ("parent", "field"):
            raise ContractValidationError("kind must be 'parent' or 'field'")
        if self.kind == "parent" and self.field_name is not None:
            raise ContractValidationError("a parent migration carries no field_name")
        if self.kind == "field":
            if self.field_name not in EMPHASIS_FIELDS:
                raise ContractValidationError(
                    f"field_name must be one of {sorted(EMPHASIS_FIELDS)}"
                )
        validate_non_empty_string(self.cycle_id)


MigrationRejectionReason = Literal[
    "unresolvable_source",
    "not_a_migration",
    "q_bio_destination_refused",
    "missing_local_parent",
    "invalid_proposal",
]


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """The outcome of one migration proposal (AG-37)."""

    disposition: Literal["disabled_by_profile", "rejected", "accepted"]
    profile_hash: str
    child: Genome | None
    migration: Migration | None
    reason: MigrationRejectionReason | None = None


def propose_migration(
    *,
    destination_island: str,
    kind: Literal["parent", "field"],
    source_genome: Genome | None,
    field_name: str,
    lineage_id: str,
    cycle_id: str,
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
    new_value: str | None = None,
    local_parent: Genome | None = None,
) -> MigrationResult:
    """Propose a mutation whose parent or changed value crosses islands (AG-37).

    ``kind="parent"`` draws the mutation's parent from *source_genome*, a
    genome of another island, changing *field_name* to *new_value* as an
    ordinary AG-20 proposal on that foreign parent. ``kind="field"`` keeps
    *local_parent* as the parent and copies *field_name*'s value from
    *source_genome* instead of an operator-written one. Both are refused
    whole when *source_genome* is ``None`` (unresolvable), when its island
    already equals *destination_island* (an ordinary proposal, not a
    migration), or when *destination_island* is q-bio -- migration into the
    control island is never admitted, though migration out of it is.
    """

    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    if guard.disposition == "disabled_by_profile":
        return MigrationResult(
            disposition="disabled_by_profile",
            profile_hash=guard.profile_hash,
            child=None,
            migration=None,
        )

    if source_genome is None:
        return MigrationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            child=None,
            migration=None,
            reason="unresolvable_source",
        )
    if source_genome.island == destination_island:
        return MigrationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            child=None,
            migration=None,
            reason="not_a_migration",
        )
    if destination_island == "q-bio":
        return MigrationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            child=None,
            migration=None,
            reason="q_bio_destination_refused",
        )

    if kind == "parent":
        mutation_parent = source_genome
        value = new_value
    else:
        if local_parent is None:
            return MigrationResult(
                disposition="rejected",
                profile_hash=guard.profile_hash,
                child=None,
                migration=None,
                reason="missing_local_parent",
            )
        mutation_parent = local_parent
        value = source_genome.emphasis.get(field_name)
    if value is None:
        return MigrationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            child=None,
            migration=None,
            reason="invalid_proposal",
        )

    mutation = propose_mutation(
        parent=mutation_parent,
        changes={field_name: value},
        lineage_id=lineage_id,
        destination_island=destination_island,
        completed_weekly_cycles=completed_weekly_cycles,
        profile_hash=profile_hash,
    )
    if mutation.disposition != "accepted" or mutation.child is None:
        # propose_mutation (not the performance-mutation wrapper) is called
        # above, so its only possible rejection reason is invalid_proposal.
        return MigrationResult(
            disposition="rejected",
            profile_hash=guard.profile_hash,
            child=None,
            migration=None,
            reason="invalid_proposal",
        )

    migration = Migration(
        child_hash=mutation.child.configuration_hash,
        source_island=source_genome.island,
        source_hash=source_genome.configuration_hash,
        kind=kind,
        field_name=field_name if kind == "field" else None,
        cycle_id=cycle_id,
    )
    return MigrationResult(
        disposition="accepted",
        profile_hash=guard.profile_hash,
        child=mutation.child,
        migration=migration,
    )
