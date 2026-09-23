"""A genome's identity and standing for evolution (AG-16, AG-36, FT-12, FT-27).

The full nine-part launch configuration contract (AG-16, TDD-3.1.60) and its
admission validator belong to a later slice; this module holds the narrower
shape the selection, mutation, migration and archive owners in this package
need: a genome's island and founder flag, its four emphasis-carrying parts
(AG-20) hashed separately from the rest of its configuration, and the
standing -- skill, cost and eligibility -- a caller supplies from wherever
the scorer (FT-12), the island's registered proxy (IN-43) and the grounding
gate (FT-27) already compute it. Nothing here reads storage, the scorer or
the proxy; a caller supplies those as data, the same boundary
``orchestration/scheduler.py`` draws for the coverage sample.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_non_empty_string,
    validate_probability,
    validate_sha256,
)
from research_agent.orchestration.scheduler import ISLANDS
from research_agent.scoring.scores import TargetSkill

#: The four hashed parts AG-20 permits a mutation to change; every other
#: part of the genome (model, tools, budgets, targets, schema) is common
#: infrastructure a mutation must leave equal (AG-03, AG-34, AG-35).
EMPHASIS_FIELDS: frozenset[str] = frozenset(
    {"prompt", "scan_policy", "read_policy", "probability_assignment_rule"}
)

EligibilityReason = Literal[
    "below_claim_count", "below_grounding_floor", "no_skill_or_proxy"
]

T = TypeVar("T")


def _validate_emphasis(emphasis: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(emphasis, Mapping) or set(emphasis) != EMPHASIS_FIELDS:
        raise ContractValidationError(
            f"emphasis must hold exactly {sorted(EMPHASIS_FIELDS)}"
        )
    validated: dict[str, str] = {}
    for name, value in emphasis.items():
        validated[name] = validate_non_empty_string(value)
    return validated


@dataclass(frozen=True, slots=True)
class Genome:
    """One admitted configuration's identity for evolution (AG-16, AG-36).

    ``infra_hash`` stands in for every part besides ``island`` and
    ``emphasis`` -- model, tools, budgets, targets and schema -- so a
    mutation (AG-20) can be checked against it without this module holding
    those parts itself. ``configuration_hash`` is the whole genome's
    identity, recomputed from ``infra_hash``, ``island`` and ``emphasis``
    rather than carried as a separate mutable field.
    """

    lineage_id: str
    island: str
    infra_hash: str
    emphasis: Mapping[str, str]
    founder: bool = False
    parent_hash: str | None = None

    def __post_init__(self) -> None:
        validate_non_empty_string(self.lineage_id)
        if self.island not in ISLANDS:
            raise ContractValidationError(f"island must be one of {sorted(ISLANDS)}")
        validate_sha256(self.infra_hash)
        object.__setattr__(self, "emphasis", _validate_emphasis(self.emphasis))
        if not isinstance(self.founder, bool):
            raise ContractValidationError("founder must be a boolean")
        if self.parent_hash is not None:
            validate_sha256(self.parent_hash)

    @property
    def configuration_hash(self) -> str:
        payload = {
            "infra_hash": self.infra_hash,
            "island": self.island,
            "emphasis": dict(self.emphasis),
        }
        return sha256_hex(canonical_json(payload))


@dataclass(frozen=True, slots=True)
class GenomeStanding:
    """One genome's measured standing for a select stage (FT-12, FT-27, IN-43).

    ``target_skills`` carries FT-12's per-target skill records over the
    genome's resolved registered targets; :attr:`skill` and
    :attr:`skill_per_dollar` are FT-14's own internal ranking statistic, the
    mean over the targets where a record is available -- never a value FT-12
    itself reports or a figure presented as scientific skill (EN-16).
    ``proxy`` is the island's registered proxy (IN-43) a caller computes
    elsewhere and supplies unchanged; ``grounding_share`` is ``None`` while
    FT-27's gate does not yet apply (fewer than 30 sealed claims).
    """

    genome: Genome
    resolved_claim_count: int
    grounding_share: float | None
    target_skills: tuple[TargetSkill, ...]
    proxy: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.genome, Genome):
            raise ContractValidationError("GenomeStanding.genome must be a Genome")
        validate_non_negative_int(self.resolved_claim_count)
        if self.grounding_share is not None:
            validate_probability(self.grounding_share)
        if not isinstance(self.target_skills, tuple):
            raise ContractValidationError("target_skills must be a tuple")
        for skill in self.target_skills:
            if not isinstance(skill, TargetSkill):
                raise ContractValidationError(
                    "target_skills must hold TargetSkill values"
                )
        if self.proxy is not None and (
            isinstance(self.proxy, bool) or not isinstance(self.proxy, (int, float))
        ):
            raise ContractValidationError("proxy must be numeric")

    @property
    def skill(self) -> float | None:
        available = [
            skill.skill
            for skill in self.target_skills
            if skill.disposition == "available" and skill.skill is not None
        ]
        if not available:
            return None
        return sum(available) / len(available)

    @property
    def skill_per_dollar(self) -> float | None:
        available = [
            skill.skill_per_dollar
            for skill in self.target_skills
            if skill.cost_disposition == "available"
            and skill.skill_per_dollar is not None
        ]
        if not available:
            return None
        return sum(available) / len(available)


@dataclass(frozen=True, slots=True)
class Lineage:
    """One population slot's genealogy within an island (FT-14, FT-15).

    ``history`` is every genome that has occupied this lineage's slot,
    oldest first; :attr:`current` is what a select stage ranks, and the
    whole of ``history`` is what FT-15 searches for the highest-skill
    member when the lineage is retired.
    """

    lineage_id: str
    island: str
    founder: bool
    history: tuple[GenomeStanding, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.lineage_id)
        if self.island not in ISLANDS:
            raise ContractValidationError(f"island must be one of {sorted(ISLANDS)}")
        if not isinstance(self.history, tuple) or not self.history:
            raise ContractValidationError(
                "Lineage requires at least one standing in history"
            )
        for standing in self.history:
            if not isinstance(standing, GenomeStanding):
                raise ContractValidationError("history must hold GenomeStanding values")
            if standing.genome.island != self.island:
                raise ContractValidationError(
                    "every standing's genome must belong to the lineage's island"
                )
            if standing.genome.founder != self.founder:
                raise ContractValidationError(
                    "every standing's genome founder flag must match the lineage"
                )

    @property
    def current(self) -> GenomeStanding:
        return self.history[-1]


def gate_eligibility(
    standing: GenomeStanding,
    *,
    minimum_resolved_claim_count: int,
    grounding_floor: float,
) -> EligibilityReason | None:
    """Apply FT-27's grounding gate and AG-19's claim-count floor (order fixed).

    Returns ``None`` when *standing* is eligible to be drawn as a parent or
    kept as a survivor, or the reason it is excluded. Both gates apply
    before any ranking on skill, exactly as FT-27 requires.
    """

    if standing.resolved_claim_count < minimum_resolved_claim_count:
        return "below_claim_count"
    if (
        standing.grounding_share is not None
        and standing.grounding_share < grounding_floor
    ):
        return "below_grounding_floor"
    if standing.skill is None and standing.proxy is None:
        return "no_skill_or_proxy"
    return None


def rank_items(
    items: Sequence[T],
    *,
    standing_of: Callable[[T], GenomeStanding],
    minimum_resolved_claim_count: int,
    grounding_floor: float,
) -> tuple[tuple[T, ...], tuple[tuple[T, EligibilityReason], ...]]:
    """Rank eligible items by their standing's skill, tie-broken on cost.

    *items* is generic -- a caller passes ``GenomeStanding`` values directly
    (``standing_of=lambda standing: standing``) or, when it must map a
    ranked result back to something else it owns (a lineage, a slot),
    whatever carries a standing plus that identity, via *standing_of*.
    Ranking never round-trips through a genome's configuration hash to
    recover *items*, since two distinct items can carry byte-identical
    genomes without being the same item.

    Ranking is by FT-12's mean skill over the genome's resolved registered
    targets when available, or by the island's registered proxy (IN-43)
    while skill is unavailable; ties break on skill per dollar (FT-14).
    Neither is used to rank a genome the claim-count floor or the grounding
    floor excludes -- those are returned separately, never silently dropped.
    The final tie-break is the genome's own configuration hash, so ranking
    never depends on input order.
    """

    eligible: list[T] = []
    excluded: list[tuple[T, EligibilityReason]] = []
    for item in items:
        reason = gate_eligibility(
            standing_of(item),
            minimum_resolved_claim_count=minimum_resolved_claim_count,
            grounding_floor=grounding_floor,
        )
        if reason is None:
            eligible.append(item)
        else:
            excluded.append((item, reason))

    def sort_key(item: T) -> tuple[float, int, float, str]:
        standing = standing_of(item)
        effective_skill = (
            standing.skill if standing.skill is not None else standing.proxy
        )
        # Only an eligible item (gate_eligibility already passed) reaches
        # here, and eligibility requires at least one of skill or proxy.
        assert effective_skill is not None
        skill_per_dollar = standing.skill_per_dollar
        return (
            -float(effective_skill),
            0 if skill_per_dollar is not None else 1,
            -(float(skill_per_dollar) if skill_per_dollar is not None else 0.0),
            standing.genome.configuration_hash,
        )

    ranked = tuple(sorted(eligible, key=sort_key))
    return ranked, tuple(excluded)
