"""Evidence-bearing tri-state resolver output, never a bare boolean (EN-14)."""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts import canonical_json, sha256_hex
from research_agent.contracts.learning import (
    TARGET_IDS,
    AutomaticLabel,
    CanonicalRecord,
    CountBounds,
    LabelCounts,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
)

STATUS_VALUES = frozenset({"true", "false", "unresolvable"})


def _selected_bounds(target_id: str, counts: LabelCounts) -> CountBounds:
    """The one counter that decides *target_id*'s predicate (mirrors ``resolve.py``)."""
    if target_id == "citation_reach_365d":
        return counts.year_families
    if target_id == "cross_subfield_reach_365d":
        return counts.other_primary_subfields
    first, second = counts.late_180_270_families, counts.late_270_365_families
    lower = min(first.lower, second.lower)
    if first.upper == 0 or second.upper == 0:
        upper: int | None = 0
    elif first.upper is None or second.upper is None:
        upper = None
    else:
        upper = min(first.upper, second.upper)
    return CountBounds(lower, upper)


@dataclass(frozen=True, slots=True)
class ResolutionResult(CanonicalRecord):
    """The resolver's tri-state settlement: never invents a false from an unknown."""

    status: str
    definition_hash: str
    observation_hash: str
    witness_ids: tuple[str, ...]
    completion_proof_hash: str | None
    lower_bound: int
    upper_bound: int | None
    reason: str

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALUES:
            raise ContractValidationError("resolution status is not an admitted value")
        validate_sha256(self.definition_hash)
        validate_sha256(self.observation_hash)
        validate_non_negative_int(self.lower_bound)
        if self.upper_bound is not None and self.upper_bound < self.lower_bound:
            raise ContractValidationError("resolution upper bound is below lower bound")
        for value in self.witness_ids:
            validate_non_empty_string(value)
        if len(set(self.witness_ids)) != len(self.witness_ids):
            raise ContractValidationError("resolution witnesses are duplicated")
        if self.completion_proof_hash is not None:
            validate_sha256(self.completion_proof_hash)
        validate_non_empty_string(self.reason)
        if self.status == "true" and not self.witness_ids:
            raise ContractValidationError(
                "a true resolution requires positive witnesses"
            )
        if self.status == "false" and self.completion_proof_hash is None:
            raise ContractValidationError(
                "a false resolution requires a completion proof"
            )
        if self.status != "true" and self.witness_ids:
            raise ContractValidationError(
                "only a true resolution carries positive witnesses"
            )

    @classmethod
    def from_label(cls, label: AutomaticLabel) -> "ResolutionResult":
        """Map an ``AutomaticLabel`` (``true``/``false``/``unknown``) to a stored result.

        ``unknown`` becomes ``unresolvable`` -- storage never sees a
        fabricated false event for missing or incomplete evidence.
        """
        if label.target_id not in TARGET_IDS:
            raise ContractValidationError("automatic label target is not admitted")
        status = "unresolvable" if label.state == "unknown" else label.state
        bounds = _selected_bounds(label.target_id, label.counts)
        witnesses = tuple(
            sorted({*label.witness_family_ids, *label.witness_subfield_ids})
        )
        completion_proof_hash = (
            sha256_hex(canonical_json(sorted(label.completion_page_hashes)))
            if status == "false"
            else None
        )
        return cls(
            status=status,
            definition_hash=label.target_definition_hash,
            observation_hash=label.observation_hash,
            witness_ids=witnesses if status == "true" else (),
            completion_proof_hash=completion_proof_hash,
            lower_bound=bounds.lower,
            upper_bound=bounds.upper,
            reason=label.reason,
        )
