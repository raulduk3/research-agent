"""The weekly select stage: cycle guard, ranking, founder exemption and archive.

``cycle_guard`` is the one shared gate AG-06, AG-18 to AG-21 and FT-15 all
apply first: a missing profile hash or an unreadable completed-cycle count
fails closed by raising, the same way ``orchestration/specifications.py``
treats a missing ``profile_hash`` as unable to derive a seed, and a count
below two returns ``disabled_by_profile`` rather than ranking anything. What
reads the active profile and the count from storage is a caller's job, the
same boundary ``orchestration/scheduler.py`` draws for its coverage sample
and launcher; this module decides what a caller does with those two values.

``select_population`` (FT-14), ``exempt_founders`` (AG-38) and
``archive_lineage`` (FT-15) rank one island's lineages, and
``record_selection_stage`` (AG-18, FT-13) runs all of an island set's
select stages together as one idempotent event a caller commits atomically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.genome import EligibilityReason, Lineage, rank_items

CycleDisposition = Literal["disabled_by_profile", "enabled"]


@dataclass(frozen=True, slots=True)
class CycleGuardResult:
    """The shared cycle guard's answer: enabled, or disabled by profile."""

    disposition: CycleDisposition
    profile_hash: str
    completed_weekly_cycles: int


#: The seeded population runs unchanged for its first two weekly cycles
#: (AG-18, FT-13, FT-14), so the first selection comparison has a control.
CYCLES_BEFORE_ACTIVATION: int = 2


def cycle_guard(
    *, profile_hash: str | None, completed_weekly_cycles: int | None
) -> CycleGuardResult:
    """Gate every cycle-dependent evolution operation on the same two counts.

    Raises ``ContractValidationError`` for a missing or malformed profile
    hash or completed-cycle count -- fail-closed, never implicit permission
    (AG-06, AG-18 to AG-21). Otherwise returns ``disabled_by_profile`` while
    the seeded population has completed fewer than two weekly cycles, and
    ``enabled`` afterward.
    """

    if not isinstance(profile_hash, str) or not profile_hash:
        raise ContractValidationError("cycle_guard requires a profile hash")
    if (
        completed_weekly_cycles is None
        or isinstance(completed_weekly_cycles, bool)
        or not isinstance(completed_weekly_cycles, int)
        or completed_weekly_cycles < 0
    ):
        raise ContractValidationError(
            "cycle_guard requires a non-negative completed weekly cycle count"
        )
    disposition: CycleDisposition = (
        "disabled_by_profile"
        if completed_weekly_cycles < CYCLES_BEFORE_ACTIVATION
        else "enabled"
    )
    return CycleGuardResult(
        disposition=disposition,
        profile_hash=profile_hash,
        completed_weekly_cycles=completed_weekly_cycles,
    )


def exempt_founders(lineages: Sequence[Lineage]) -> tuple[Lineage, tuple[Lineage, ...]]:
    """Separate an island's one founder lineage from the rest (AG-38).

    Refuses whole -- raises -- when the island holds zero or more than one
    founder, so a misconfigured seed cannot silently run the select stage
    without its no-selection control arm or with two.
    """

    founders = [lineage for lineage in lineages if lineage.founder]
    if len(founders) != 1:
        raise ContractValidationError(
            "an island must have exactly one founder to run the select stage"
        )
    founder = founders[0]
    return founder, tuple(lineage for lineage in lineages if not lineage.founder)


RetirementReason = EligibilityReason | Literal["ranked_beyond_ceiling"]


@dataclass(frozen=True, slots=True)
class RetirementCandidate:
    """One lineage a select stage retires, and why."""

    lineage_id: str
    reason: RetirementReason


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """One island's select-stage outcome (FT-13, FT-14)."""

    island: str
    disposition: Literal["selection_disabled", "selected"]
    profile_hash: str
    survivors: tuple[str, ...]
    retired: tuple[RetirementCandidate, ...]
    ranked_support: tuple[str, ...]


def select_population(
    *,
    island: str,
    lineages: Sequence[Lineage],
    ceiling: int,
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
    minimum_resolved_claim_count: int = 30,
    grounding_floor: float = 0.95,
    floor: int = 4,
) -> SelectionResult:
    """Rank one island's genomes on skill and retire the worst (FT-14).

    Applies the cycle guard first, so the seeded population's first two
    weekly cycles record ``selection_disabled`` with every lineage kept
    unchanged. Afterward: the founder is exempt from ranking and retirement
    (AG-38); the rest are gated by claim count and grounding floor (FT-27)
    before being ranked on skill, or the island's registered proxy while
    skill is unavailable, tied on skill per dollar; the *ceiling* worst
    ranked survive up to that admitted count. Whatever the gate or the rank
    would retire, the island's *floor* is never crossed: the lowest-ranked
    protected lineages stay rather than shrinking the island below it
    (AG-38's ``never fall below four genomes``).

    ``ceiling`` is the island's spend-share admission count; computing it
    from the authorized monthly cap and the measured per-run cost is a
    caller's job, the same boundary ``orchestration/scheduler.py`` draws
    for coverage-sample spend.
    """

    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    if guard.disposition == "disabled_by_profile":
        return SelectionResult(
            island=island,
            disposition="selection_disabled",
            profile_hash=guard.profile_hash,
            survivors=tuple(lineage.lineage_id for lineage in lineages),
            retired=(),
            ranked_support=(),
        )

    for lineage in lineages:
        if lineage.island != island:
            raise ContractValidationError(
                "select_population received a lineage of another island"
            )

    founder, others = exempt_founders(lineages)

    ranked_lineages_seq, gated_out = rank_items(
        others,
        standing_of=lambda lineage: lineage.current,
        minimum_resolved_claim_count=minimum_resolved_claim_count,
        grounding_floor=grounding_floor,
    )
    ranked_lineages = list(ranked_lineages_seq)
    gated_out_lineages: list[tuple[Lineage, RetirementReason]] = list(gated_out)

    admitted_count = max(0, min(ceiling, len(ranked_lineages)))
    kept_ranked = ranked_lineages[:admitted_count]
    beyond_ceiling: list[tuple[Lineage, RetirementReason]] = [
        (lineage, "ranked_beyond_ceiling")
        for lineage in ranked_lineages[admitted_count:]
    ]

    total_population = 1 + len(others)
    max_retirable = max(0, total_population - floor)
    ordered_candidates = gated_out_lineages + list(reversed(beyond_ceiling))
    to_retire = ordered_candidates[:max_retirable]
    protected = ordered_candidates[max_retirable:]

    retired = tuple(
        RetirementCandidate(lineage_id=lineage.lineage_id, reason=reason)
        for lineage, reason in to_retire
    )
    retired_ids = {candidate.lineage_id for candidate in retired}
    survivors = tuple(
        lineage.lineage_id
        for lineage in (founder, *kept_ranked, *(entry[0] for entry in protected))
        if lineage.lineage_id not in retired_ids
    )
    return SelectionResult(
        island=island,
        disposition="selected",
        profile_hash=guard.profile_hash,
        survivors=survivors,
        retired=retired,
        ranked_support=tuple(lineage.lineage_id for lineage in ranked_lineages),
    )


@dataclass(frozen=True, slots=True)
class ArchivedGenome:
    """A retired lineage's best-scoring member, kept and run no further (FT-15)."""

    genome_hash: str
    island: str
    lineage_id: str
    skill: float
    resolved_claim_count: int


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """The outcome of archiving one retired lineage (FT-15)."""

    disposition: Literal["disabled_by_profile", "archived"]
    profile_hash: str
    archived: ArchivedGenome | None


def archive_lineage(
    *,
    lineage: Lineage,
    completed_weekly_cycles: int | None,
    profile_hash: str | None,
) -> ArchiveResult:
    """Archive a retired lineage's highest-skill member (FT-15).

    Applies the cycle guard first, since the launch profile keeps this
    disabled through the seeded population's first two weekly cycles the
    same as every other cycle-gated mechanism. Afterward, of every genome
    that has occupied *lineage*'s slot, the one with the highest available
    skill is archived with the skill and support it was scored on; archived
    genomes run no further and bound AG-21 admission.
    """

    guard = cycle_guard(
        profile_hash=profile_hash, completed_weekly_cycles=completed_weekly_cycles
    )
    if guard.disposition == "disabled_by_profile":
        return ArchiveResult(
            disposition="disabled_by_profile",
            profile_hash=guard.profile_hash,
            archived=None,
        )

    scored = [standing for standing in lineage.history if standing.skill is not None]
    if not scored:
        raise ContractValidationError(
            "archive_lineage requires at least one scored member in history"
        )
    best = max(scored, key=lambda standing: standing.skill)  # type: ignore[arg-type,return-value]
    archived = ArchivedGenome(
        genome_hash=best.genome.configuration_hash,
        island=lineage.island,
        lineage_id=lineage.lineage_id,
        skill=best.skill,  # type: ignore[arg-type]
        resolved_claim_count=best.resolved_claim_count,
    )
    return ArchiveResult(
        disposition="archived", profile_hash=guard.profile_hash, archived=archived
    )


@dataclass(frozen=True, slots=True)
class SelectionEvent:
    """One weekly select stage's complete, idempotent disposition (AG-18, FT-13)."""

    cycle_id: str
    profile_hash: str
    disposition: Literal["selection_disabled", "selected"]
    results: Mapping[str, SelectionResult]
    archived: tuple[ArchivedGenome, ...]


def record_selection_stage(
    *,
    cycle_id: str,
    profile_hash: str | None,
    completed_weekly_cycles: int | None,
    islands: Mapping[str, Sequence[Lineage]],
    ceilings: Mapping[str, int],
    previous_event: SelectionEvent | None = None,
) -> SelectionEvent:
    """Run every island's select stage once and bundle one atomic disposition.

    Keyed by ``(cycle_id, select, profile_hash)`` (AG-18, FT-13): replaying
    the same *cycle_id* and *profile_hash* against a *previous_event* for
    that key returns it unchanged rather than recomputing or appending a
    second event, so an interrupted stage resumes idempotently. A mismatched
    *previous_event* is refused rather than silently superseded. Exactly one
    disposition per island is produced together, so a caller can commit the
    resulting population and the archive of every island's retired lineages
    in the one transaction FT-13 requires.
    """

    if previous_event is not None:
        if (
            previous_event.cycle_id == cycle_id
            and previous_event.profile_hash == profile_hash
        ):
            return previous_event
        raise ContractValidationError(
            "record_selection_stage received a previous event for a different "
            "cycle or profile"
        )
    if not isinstance(cycle_id, str) or not cycle_id:
        raise ContractValidationError("record_selection_stage requires a cycle_id")

    results: dict[str, SelectionResult] = {}
    archived: list[ArchivedGenome] = []
    overall_disposition: Literal["selection_disabled", "selected"] = (
        "selection_disabled"
    )
    for island, lineages in islands.items():
        if island not in ceilings:
            raise ContractValidationError(
                f"record_selection_stage is missing a ceiling for island {island!r}"
            )
        result = select_population(
            island=island,
            lineages=lineages,
            ceiling=ceilings[island],
            completed_weekly_cycles=completed_weekly_cycles,
            profile_hash=profile_hash,
        )
        results[island] = result
        if result.disposition != "selected":
            continue
        overall_disposition = "selected"
        retired_ids = {candidate.lineage_id for candidate in result.retired}
        for lineage in lineages:
            if lineage.lineage_id not in retired_ids:
                continue
            archive_result = archive_lineage(
                lineage=lineage,
                completed_weekly_cycles=completed_weekly_cycles,
                profile_hash=profile_hash,
            )
            if archive_result.archived is not None:
                archived.append(archive_result.archived)

    return SelectionEvent(
        cycle_id=cycle_id,
        profile_hash=profile_hash,  # type: ignore[arg-type]
        disposition=overall_disposition,
        results=results,
        archived=tuple(archived),
    )
