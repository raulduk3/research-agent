"""Snapshot-derived immutable run stamps: what a run's snapshot actually pins (SR-15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import (
    validate_non_negative_int,
    validate_sha256,
)
from research_agent.contracts.runs import validate_model_identity
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.errors import UnavailableInput

__all__ = ["RunStamp", "build_run_stamp"]


@dataclass(frozen=True, slots=True)
class RunStamp:
    """The immutable artifacts a run's snapshot actually makes visible (SR-15).

    ``genome_hash``, ``seed``, ``agent_model_manifest`` and
    ``service_image_versions`` are fixed by the caller issuing the run;
    ``paper_card_manifest`` and ``prediction_head_bundles`` are resolved
    here from the snapshot itself. The latter is read from the pinned
    papers' own cards -- each bundle id was fixed when its card was built,
    before the snapshot ever existed -- never from whichever bundle is
    active now, so a run queued against an older snapshot keeps citing the
    bundles that produced that snapshot's cards even after a newer bundle
    is promoted.
    """

    genome_hash: str
    seed: int
    agent_model_manifest: str
    service_image_versions: dict[str, str]
    snapshot_hash: str
    paper_card_manifest: str
    prediction_head_bundles: dict[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        validate_sha256(self.genome_hash)
        validate_non_negative_int(self.seed)
        validate_sha256(self.agent_model_manifest)
        for digest in self.service_image_versions.values():
            validate_sha256(digest)

    def model_identity(self) -> dict[str, Any]:
        """The stamp in the run record's wire shape, `contracts/runs.py` (#285).

        A run launches against one bundle per target, so each target's
        bundle tuple becomes that one id, or null for a target no pinned
        card was scored by. A snapshot whose cards mix bundles for one
        target has no single identity to record, and the run is refused
        naming the target rather than recording one of them.
        """

        bundles: dict[str, str | None] = {}
        for target_id, ids in self.prediction_head_bundles.items():
            if len(ids) > 1:
                raise UnavailableInput(f"mixed_prediction_head_bundles:{target_id}")
            bundles[target_id] = ids[0] if ids else None
        return validate_model_identity(
            {
                "agent_model_manifest": self.agent_model_manifest,
                "service_image_versions": dict(self.service_image_versions),
                "paper_card_manifest": self.paper_card_manifest,
                "prediction_head_bundles": bundles,
            }
        )


def build_run_stamp(
    documents: SnapshotDocuments,
    *,
    genome_hash: str,
    seed: int,
    agent_model_manifest: str,
    service_image_versions: dict[str, str],
    snapshot_hash: str,
    paper_version_ids: tuple[str, ...],
) -> RunStamp:
    """Resolve a run's stamp from its snapshot before its first provider call.

    Every producing bundle id is read out of the pinned cards'
    ``head_predictions``, already immutable once the card was pinned --
    never from an active model pointer -- so later bundle promotion cannot
    change what a queued run reports. An unresolved snapshot or an
    unpinned requested paper blocks the run from starting, propagated as
    :class:`~research_agent.storage.errors.UnavailableInput` by the
    resolvers this calls.
    """

    paper_card_manifest = documents.paper_manifest_hash(snapshot_hash)
    bundles: dict[str, set[str]] = {target_id: set() for target_id in TARGET_IDS}
    if paper_version_ids:
        for card in documents.cards(snapshot_hash, paper_version_ids):
            for head in cast(list[dict[str, Any]], card.get("head_predictions", [])):
                target_id = head.get("target_id")
                bundle_id = head.get("model_bundle_id")
                if target_id in bundles and isinstance(bundle_id, str):
                    bundles[target_id].add(bundle_id)
    prediction_head_bundles = {
        target_id: tuple(sorted(ids)) for target_id, ids in bundles.items()
    }
    return RunStamp(
        genome_hash,
        seed,
        agent_model_manifest,
        service_image_versions,
        snapshot_hash,
        paper_card_manifest,
        prediction_head_bundles,
    )
