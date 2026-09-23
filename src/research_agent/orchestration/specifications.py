"""Immutable run specification and its derived seed (AG-17, TDD-3.1.61).

A run specification is written before a run starts and the run cannot
change it (IN-24): its six SDD-named parts are the slot, a genome hash, a
seed, a snapshot hash, budgets and the tools allowed. This module builds
that record and its identity hash from the caller's already-resolved
values; persisting it through ``storage/runs.py``'s ``create`` command --
and refusing a slot reused with a changed specification -- is that
module's own job (its unique ``(batch_id, paper_id, configuration_id,
attempt)`` constraint already refuses a second, different run for one
slot).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.orchestration.slots import Slot

#: TDD-3.1.61's fifth slot component. Every run is "population" while the
#: Jev comparison arms stay held out of the launch (SR-17, #123); TDD-3.1.40
#: creates no comparison slot until they are admitted.
ARM_VALUES = frozenset({"population", "jev_present", "jev_absent"})
DEFAULT_ARM = "population"


def derive_specification_seed(slot: Slot, *, profile_hash: str) -> int:
    """The first unsigned 64 bits of SHA-256 over the slot identity and
    profile hash (Shared implementation rules)."""

    validate_sha256(profile_hash)
    digest = sha256(
        canonical_json({"slot": slot.to_dict(), "profile_hash": profile_hash})
    ).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True, slots=True)
class RunSpecification:
    """A run's complete immutable identity, written before it starts (AG-17).

    ``specification_hash`` covers every field here, including ``mode``,
    the model/service manifests and ``question_seal_deadline``, so a
    changed value produces a different identity a reused slot cannot
    silently adopt.
    """

    run_id: str
    slot: Slot
    arm: str
    genome_hash: str
    snapshot_hash: str
    budgets: Mapping[str, int]
    allowed_tools: tuple[str, ...]
    specification_seed: int
    mode: str
    model_manifest: str
    service_manifests: Mapping[str, str]
    question_seal_deadline: str
    specification_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "slot": self.slot.to_dict(),
            "arm": self.arm,
            "genome_hash": self.genome_hash,
            "snapshot_hash": self.snapshot_hash,
            "budgets": dict(self.budgets),
            "allowed_tools": list(self.allowed_tools),
            "specification_seed": self.specification_seed,
            "mode": self.mode,
            "model_manifest": self.model_manifest,
            "service_manifests": dict(self.service_manifests),
            "question_seal_deadline": self.question_seal_deadline,
        }


def build_run_specification(
    *,
    run_id: str,
    slot: Slot,
    genome_hash: str,
    snapshot_hash: str,
    budgets: Mapping[str, int],
    allowed_tools: Sequence[str],
    profile_hash: str,
    mode: str,
    model_manifest: str,
    service_manifests: Mapping[str, str],
    question_seal_deadline: str,
    arm: str = DEFAULT_ARM,
) -> RunSpecification:
    """Construct one run's immutable specification before dispatch.

    Raises ``ContractValidationError`` for any missing or malformed part,
    including a missing or malformed ``profile_hash`` -- the seed cannot be
    derived without it. ``question_seal_deadline`` is the earliest issued
    question's seal deadline, or the batch seal time plus 24 hours for a
    questionless engineering slot (TDD-3.1.61); the caller resolves which
    applies, since this module has no storage access of its own.
    """

    validate_uuid4(run_id)
    if not isinstance(slot, Slot):
        raise ContractValidationError("slot must be a built Slot")
    if arm not in ARM_VALUES:
        raise ContractValidationError("arm is not an admitted value")
    validate_sha256(genome_hash)
    validate_sha256(snapshot_hash)
    if not budgets:
        raise ContractValidationError("budgets must not be empty")
    tools = tuple(allowed_tools)
    if not tools or len(set(tools)) != len(tools):
        raise ContractValidationError("allowed_tools must be nonempty and distinct")
    mode_text = validate_non_empty_string(mode)
    validate_sha256(model_manifest)
    if not service_manifests:
        raise ContractValidationError("service_manifests must not be empty")
    for name, digest in service_manifests.items():
        validate_non_empty_string(name)
        validate_sha256(digest)
    validate_utc_instant(question_seal_deadline)

    seed = derive_specification_seed(slot, profile_hash=profile_hash)
    payload = {
        "run_id": run_id,
        "slot": slot.to_dict(),
        "arm": arm,
        "genome_hash": genome_hash,
        "snapshot_hash": snapshot_hash,
        "budgets": dict(sorted(budgets.items())),
        "allowed_tools": sorted(tools),
        "specification_seed": seed,
        "mode": mode_text,
        "model_manifest": model_manifest,
        "service_manifests": dict(sorted(service_manifests.items())),
        "question_seal_deadline": question_seal_deadline,
    }
    specification_hash = sha256(canonical_json(payload)).hexdigest()
    return RunSpecification(
        run_id=run_id,
        slot=slot,
        arm=arm,
        genome_hash=genome_hash,
        snapshot_hash=snapshot_hash,
        budgets=dict(budgets),
        allowed_tools=tools,
        specification_seed=seed,
        mode=mode_text,
        model_manifest=model_manifest,
        service_manifests=dict(service_manifests),
        question_seal_deadline=question_seal_deadline,
        specification_hash=specification_hash,
    )
