"""Recompute a superseding label from new evidence or a named resolver defect (IN-12)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from research_agent.contracts import canonical_json, sha256_hex
from research_agent.contracts.learning import (
    AutomaticLabel,
    CitationFamilyRecord,
    CitationObservation,
    TargetDefinition,
    TargetRegistry,
)
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.contracts.primitives import (
    ContractValidationError,
    RecordMeta,
    validate_non_empty_string,
)
from research_agent.outcomes.resolve import Resolver

CORRECTION_REASONS = frozenset({"replacement_source_evidence", "resolver_defect"})


@dataclass(frozen=True, slots=True)
class CorrectionRequest:
    """Either replacement preserved evidence or an identified resolver defect.

    A bare preference disagreement with no new evidence and no named defect
    is not a valid basis; :meth:`CorrectionService.correct` refuses it.
    """

    reason: str
    defect_description: str | None
    observation: CitationObservation


class CorrectionService:
    """Append a superseding label; the original resolved label is never edited."""

    def __init__(
        self,
        read_family: Callable[[str], CitationFamilyRecord],
        meta: RecordMeta,
        *,
        registry: TargetRegistry,
    ) -> None:
        self._resolver = Resolver(read_family, meta, registry=registry)

    def correct(
        self,
        target: TargetDefinition,
        paper: PaperVersionRecord,
        original: AutomaticLabel,
        request: CorrectionRequest,
        as_of: str,
    ) -> AutomaticLabel:
        if request.reason not in CORRECTION_REASONS:
            raise ContractValidationError(
                "correction reason is not an accepted evidence or defect basis"
            )
        if request.reason == "resolver_defect":
            if not request.defect_description:
                raise ContractValidationError(
                    "a resolver-defect correction requires a defect description"
                )
            validate_non_empty_string(request.defect_description)
        if (
            original.target_id != target.target_id
            or original.paper_family_id != paper.family_id
        ):
            raise ContractValidationError(
                "correction target does not match the original label"
            )
        original_hash = sha256_hex(original.to_canonical_json())
        new_observation_hash = sha256_hex(request.observation.to_canonical_json())
        if (
            request.reason == "replacement_source_evidence"
            and new_observation_hash == original.observation_hash
        ):
            raise ContractValidationError(
                "a correction requires new preserved evidence or a named resolver defect"
            )
        recomputed = self._resolver.resolve_target(
            target, paper, request.observation, as_of
        )
        correction_hash = sha256_hex(
            canonical_json(
                {
                    "reason": request.reason,
                    "defect_description": request.defect_description,
                    "observation_hash": new_observation_hash,
                }
            )
        )
        return replace(
            recomputed,
            supersedes_label_hash=original_hash,
            correction_hash=correction_hash,
        )
