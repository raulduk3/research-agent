"""Admission-time genome checks: tool narrowing (AG-14) and island (AG-36).

``validate_tools`` is the admission-time check between a genome's
configured tool list and the run specification that fixes what a run's
tool calls will ever be allowed to name: a genome's tools are the run's
``allowed_tools`` (``research_agent.contracts.runs.ALLOWED_TOOLS`` already
carries the five-name ceiling storage enforces), never a superset chosen
elsewhere.

``validate_island`` is AG-36's admission check: every genome names exactly
one of the three islands ``orchestration.scheduler.ISLANDS`` admits, the
same set slot creation uses to route a paper to its island.

``AgentConfiguration`` (AG-16, TDD-3.1.60) is the strict, hashed, nine-part
launch configuration record: island, founder, the four emphasis-carrying
policy parts (AG-20), tools, budgets, sampling and a structured output
schema. ``validate_seeded_population`` (AG-03, TDD-3.1.39) is the seed
manifest's own boundary: the twelve launch configurations, four per island
under decision 0017, sharing one common infrastructure identity and
differing only in their declared prompt/policy emphasis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..contracts.canonical import canonical_json, sha256_hex
from ..contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
)
from ..contracts.runs import ALLOWED_TOOLS, BUDGET_FIELDS
from ..evolution.genome import EMPHASIS_FIELDS, Genome
from ..orchestration.scheduler import ISLANDS


def validate_tools(tools: Sequence[str]) -> tuple[str, ...]:
    """Validate a configuration's tool list against the fixed five (AG-14).

    Rejects the entire configuration -- raises rather than silently
    dropping an unknown name -- when ``tools`` is empty, holds a
    duplicate, or names anything outside
    :data:`research_agent.contracts.runs.ALLOWED_TOOLS`. A configuration
    that passes admits exactly the ordered names given; nothing here can
    add a sixth tool or reorder the caller's list.
    """

    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        raise ContractValidationError("tools must be a list of tool names")
    if not 1 <= len(tools) <= len(ALLOWED_TOOLS):
        raise ContractValidationError(
            f"tools must hold 1 to {len(ALLOWED_TOOLS)} items"
        )
    if len(set(tools)) != len(tools):
        raise ContractValidationError("tools must be distinct")
    for tool in tools:
        if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
            raise ContractValidationError("tools names an inadmissible tool")
    return tuple(tools)


def validate_island(island: str) -> str:
    """Validate a genome's island against the fixed three (AG-36).

    Rejects the whole configuration -- raises rather than defaulting to an
    island -- when ``island`` is missing or names anything outside
    :data:`research_agent.orchestration.scheduler.ISLANDS`.
    """

    if not isinstance(island, str) or island not in ISLANDS:
        raise ContractValidationError(f"island must be one of {sorted(ISLANDS)}")
    return island


CONFIGURATION_SCHEMA_VERSION = 1
POLICY_FIELD_MAX_CHARS = 4000
ASSEMBLED_PROMPT_MAX_CHARS = 16000
LAUNCH_SAMPLING_COUNT = 1


def _validate_budgets(budgets: Mapping[str, object]) -> dict[str, int]:
    if not isinstance(budgets, Mapping) or set(budgets) != set(BUDGET_FIELDS):
        raise ContractValidationError(
            f"budgets must hold exactly {sorted(BUDGET_FIELDS)}"
        )
    validated: dict[str, int] = {}
    for name in BUDGET_FIELDS:
        if name in {"timeout_seconds", "wall_time_seconds"}:
            validated[name] = validate_positive_int(budgets[name])
        else:
            validated[name] = validate_non_negative_int(budgets[name])
    return validated


def _validate_sampling(sampling: Mapping[str, object]) -> dict[str, int]:
    if not isinstance(sampling, Mapping) or set(sampling) != {"count"}:
        raise ContractValidationError("sampling must hold exactly {'count'}")
    count = sampling["count"]
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count != LAUNCH_SAMPLING_COUNT
    ):
        raise ContractValidationError(
            f"sampling.count must equal {LAUNCH_SAMPLING_COUNT} at launch"
        )
    return {"count": count}


def _validate_output_schema(output_schema: object) -> dict[str, Any]:
    if not isinstance(output_schema, Mapping):
        raise ContractValidationError("output_schema must be a JSON object")
    return dict(output_schema)


@dataclass(frozen=True, slots=True)
class AgentConfiguration:
    """A genome's complete, hashed launch identity (AG-16, TDD-3.1.60).

    Holds every part AG-16 names: an island, a founder flag, the four
    emphasis-carrying policy parts AG-20 permits a mutation to change, the
    tool list AG-14 narrows, budgets, sampling and a structured output
    schema. Each policy part is bounded to 4000 characters and their
    assembled total to 16000; ``sampling.count`` must equal 1 at launch
    (AG-32's meta-schema and AG-33's protected core apply to
    ``output_schema`` separately). ``infra_hash`` is the canonical hash of
    every part but ``island`` and the four policy parts, so AG-20's
    mutation can be checked against it without carrying those parts twice;
    ``configuration_hash`` is computed by :class:`~research_agent.evolution.
    genome.Genome`'s own already-admitted formula, so a configuration built
    here and a genome read back from the population store never disagree
    about a genome's identity.
    """

    island: str
    founder: bool
    prompt: str
    scan_policy: str
    read_policy: str
    probability_assignment_rule: str
    tools: tuple[str, ...]
    budgets: Mapping[str, int]
    sampling: Mapping[str, int]
    output_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "island", validate_island(self.island))
        if not isinstance(self.founder, bool):
            raise ContractValidationError("founder must be a boolean")
        assembled_length = 0
        for name in EMPHASIS_FIELDS:
            value = validate_non_empty_string(getattr(self, name))
            if len(value) > POLICY_FIELD_MAX_CHARS:
                raise ContractValidationError(
                    f"{name} exceeds {POLICY_FIELD_MAX_CHARS} characters"
                )
            object.__setattr__(self, name, value)
            assembled_length += len(value)
        if assembled_length > ASSEMBLED_PROMPT_MAX_CHARS:
            raise ContractValidationError(
                f"assembled system prompt exceeds {ASSEMBLED_PROMPT_MAX_CHARS} characters"
            )
        object.__setattr__(self, "tools", validate_tools(self.tools))
        object.__setattr__(self, "budgets", _validate_budgets(self.budgets))
        object.__setattr__(self, "sampling", _validate_sampling(self.sampling))
        object.__setattr__(
            self, "output_schema", _validate_output_schema(self.output_schema)
        )

    @property
    def emphasis(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in sorted(EMPHASIS_FIELDS)}

    @property
    def infra_hash(self) -> str:
        payload = {
            "schema_version": CONFIGURATION_SCHEMA_VERSION,
            "tools": list(self.tools),
            "budgets": dict(self.budgets),
            "sampling": dict(self.sampling),
            "output_schema": self.output_schema,
        }
        return sha256_hex(canonical_json(payload))

    def to_genome(self, *, lineage_id: str, parent_hash: str | None = None) -> Genome:
        """Build the population store's :class:`Genome` identity for this configuration."""

        return Genome(
            lineage_id=lineage_id,
            island=self.island,
            infra_hash=self.infra_hash,
            emphasis=self.emphasis,
            founder=self.founder,
            parent_hash=parent_hash,
        )

    @property
    def configuration_hash(self) -> str:
        """This configuration's identity, computed by :class:`Genome`'s own formula."""

        return self.to_genome(lineage_id="placeholder").configuration_hash


SEED_ISLAND_COUNT = 4
SEED_POPULATION_COUNT = SEED_ISLAND_COUNT * 3


def validate_seeded_population(
    configurations: Sequence[AgentConfiguration],
) -> tuple[AgentConfiguration, ...]:
    """Validate a proposed activation manifest against AG-03's seeded boundary.

    Admits only exactly :data:`SEED_POPULATION_COUNT` configurations, four
    in each of the three islands (decision 0017), each island naming
    exactly one founder. Every configuration must share the same
    ``infra_hash`` -- the common model, tools, budgets, targets and schema
    AG-03 fixes -- so a per-member model, resolver or tool-behavior
    override is refused whole rather than admitted with the rest; only the
    prompt/policy emphasis may vary. Raises :class:`ContractValidationError`
    for any violation, never admitting a partial population.
    """

    if not isinstance(configurations, Sequence) or isinstance(
        configurations, (str, bytes)
    ):
        raise ContractValidationError(
            "seeded population must be a list of configurations"
        )
    if len(configurations) != SEED_POPULATION_COUNT:
        raise ContractValidationError(
            f"seeded population must hold exactly {SEED_POPULATION_COUNT} configurations"
        )
    for configuration in configurations:
        if not isinstance(configuration, AgentConfiguration):
            raise ContractValidationError(
                "seeded population entries must be AgentConfiguration values"
            )

    infra_hashes = {configuration.infra_hash for configuration in configurations}
    if len(infra_hashes) != 1:
        raise ContractValidationError(
            "seeded population must share one common infrastructure identity"
        )

    by_island: dict[str, list[AgentConfiguration]] = {island: [] for island in ISLANDS}
    for configuration in configurations:
        by_island[configuration.island].append(configuration)
    for island, members in by_island.items():
        if len(members) != SEED_ISLAND_COUNT:
            raise ContractValidationError(
                f"island {island!r} must hold exactly {SEED_ISLAND_COUNT} "
                "seeded configurations"
            )
        founders = [member for member in members if member.founder]
        if len(founders) != 1:
            raise ContractValidationError(
                f"island {island!r} must hold exactly one founder"
            )

    hashes = [configuration.configuration_hash for configuration in configurations]
    if len(set(hashes)) != len(hashes):
        raise ContractValidationError(
            "seeded population must not repeat a configuration"
        )
    return tuple(configurations)
