"""Immutable run-slot identity, and the population slot set for one paper.

A slot is the daily batch, one paper, one configuration and an attempt
(decision 0022): ``Slot`` names that four-part identity, and
:func:`create_slots` builds the whole population's slots for one island's
daily coverage sample before dispatch (AG-04, TDD-3.1.40).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
    validate_uuid4,
)


def _paper_id(value: str) -> str:
    if not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError(
            "paper_id must be 1 to 128 characters without NUL"
        )
    return value


@dataclass(frozen=True, slots=True)
class Slot:
    """The unique identity of one run attempt.

    Fields match ``contracts.runs``' ``RunSlot`` exactly, so a built slot is
    always acceptable to the run-record ``create`` command: ``batch_id`` is
    the sealed daily sheet's content hash (EN-10), ``paper_id`` names the
    one paper the run reads and forecasts (AG-25, AG-26), and one
    ``configuration_id`` runs it at a given ``attempt`` (AG-17).
    """

    batch_id: str
    paper_id: str
    configuration_id: str
    attempt: int = 0

    def __post_init__(self) -> None:
        validate_sha256(self.batch_id)
        _paper_id(self.paper_id)
        validate_uuid4(self.configuration_id)
        validate_non_negative_int(self.attempt)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "paper_id": self.paper_id,
            "configuration_id": self.configuration_id,
            "attempt": self.attempt,
        }


def build_slot(
    batch_id: str, paper_id: str, configuration_id: str, *, attempt: int = 0
) -> Slot:
    """Construct one run attempt's immutable slot tuple (AG-17).

    Raises ``ContractValidationError`` for any part that the run-record
    contract storing it would also refuse, so a rejected slot never reaches
    a run specification.
    """

    return Slot(batch_id, paper_id, configuration_id, attempt)


@dataclass(frozen=True, slots=True)
class ConfigurationLaunch:
    """One active configuration's identity and its launch fields.

    ``configuration_hash`` and ``seed`` are the deliberate differing fields
    across an island's configurations; every other field here must be
    identical for every configuration in one :func:`create_slots` call
    (TDD-3.1.40).
    """

    configuration_id: str
    configuration_hash: str
    seed: int
    snapshot_hash: str
    model_deployment: str
    loop_image: str
    budgets: Mapping[str, int]
    tool_schema_manifest: str

    def __post_init__(self) -> None:
        validate_uuid4(self.configuration_id)
        validate_sha256(self.configuration_hash)
        validate_non_negative_int(self.seed)
        validate_sha256(self.snapshot_hash)
        validate_sha256(self.model_deployment)
        validate_sha256(self.loop_image)
        validate_sha256(self.tool_schema_manifest)
        if not isinstance(self.budgets, Mapping) or not self.budgets:
            raise ContractValidationError(
                "ConfigurationLaunch.budgets must be a nonempty mapping"
            )
        for name, value in self.budgets.items():
            if not isinstance(name, str):
                raise ContractValidationError("budgets keys must be strings")
            validate_non_negative_int(value)

    def _shared_identity(self) -> tuple[object, ...]:
        """Every field besides ``configuration_id``, ``configuration_hash``
        and ``seed``; two configurations of the same slot set must agree on
        this exactly (TDD-3.1.40)."""

        return (
            self.snapshot_hash,
            self.model_deployment,
            self.loop_image,
            tuple(sorted(self.budgets.items())),
            self.tool_schema_manifest,
        )


@dataclass(frozen=True, slots=True)
class PopulationSlot:
    """One (paper, configuration) run's slot and its launch fields.

    All pairwise shared fields (``snapshot_hash``, ``model_deployment``,
    ``loop_image``, ``budgets``, ``tool_schema_manifest``) are identical
    across every :class:`PopulationSlot` a single :func:`create_slots` call
    returns; only ``configuration_hash`` and ``seed`` differ (AG-04).
    """

    slot: Slot
    configuration_hash: str
    seed: int
    snapshot_hash: str
    model_deployment: str
    loop_image: str
    budgets: Mapping[str, int]
    tool_schema_manifest: str


def create_slots(
    batch_id: str,
    paper_ids: Sequence[str],
    configurations: Sequence[ConfigurationLaunch],
) -> tuple[PopulationSlot, ...]:
    """Build one slot per active configuration for every sampled paper.

    ``paper_ids`` is the island's daily coverage sample; ``configurations``
    is that island's active configurations. Every configuration must share
    identical launch fields besides its own hash and seed, so a caller that
    slips in a configuration on a newer snapshot (or any other differing
    shared field) is refused whole rather than producing a mismatched
    population (TDD-3.1.40). The result is ordered by paper id then
    configuration id regardless of input order, so shuffled configuration
    input yields the same canonical slot identities.
    """

    validate_sha256(batch_id)
    if not paper_ids:
        raise ContractValidationError("create_slots requires at least one paper id")
    if len(set(paper_ids)) != len(paper_ids):
        raise ContractValidationError("paper_ids must be distinct")
    if not configurations:
        raise ContractValidationError(
            "create_slots requires at least one configuration"
        )
    configuration_ids = [
        configuration.configuration_id for configuration in configurations
    ]
    if len(set(configuration_ids)) != len(configuration_ids):
        raise ContractValidationError(
            "configurations must have distinct configuration_id"
        )
    shared_identity = configurations[0]._shared_identity()
    for configuration in configurations[1:]:
        if configuration._shared_identity() != shared_identity:
            raise ContractValidationError(
                "every configuration of one slot set must share the same "
                "snapshot, model deployment, loop image, budgets and "
                "tool-schema manifest"
            )
    ordered_configurations = sorted(
        configurations, key=lambda configuration: configuration.configuration_id
    )
    return tuple(
        PopulationSlot(
            slot=build_slot(
                batch_id, paper_id, configuration.configuration_id, attempt=0
            ),
            configuration_hash=configuration.configuration_hash,
            seed=configuration.seed,
            snapshot_hash=configuration.snapshot_hash,
            model_deployment=configuration.model_deployment,
            loop_image=configuration.loop_image,
            budgets=configuration.budgets,
            tool_schema_manifest=configuration.tool_schema_manifest,
        )
        for paper_id in sorted(paper_ids)
        for configuration in ordered_configurations
    )
