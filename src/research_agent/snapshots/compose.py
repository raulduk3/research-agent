"""Compose the next snapshot from the last one and the papers acquired since.

Decision 0025: a paper acquired for an agent's request enters the *next*
snapshot beside the drawn corpus; the snapshot the request was made from is
never rewritten. ``compose_next_snapshot`` is the pure rule: every item the
prior snapshot pinned is kept exactly, each acquired paper is added, and an
acquired paper that would change an already-pinned version is refused
rather than merged. ``seal_next_snapshot`` publishes that paper manifest,
seals the snapshot through storage and pins its items to each of the day's
sheets, so the new snapshot hash differs from the old one and the old one's
rows are untouched.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from research_agent.contracts import canonical_loads
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.snapshots import validate_snapshot_payload
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.idempotency import StoredResponse

__all__ = ["SnapshotCommands", "compose_next_snapshot", "seal_next_snapshot"]

PAPER_MANIFEST_KIND = "snapshot_papers"
_PIN_CHUNK = 1000


class SnapshotCommands(Protocol):
    """The snapshot record owner (``storage.snapshots.SnapshotRepository``)."""

    def execute(
        self, operation: str, *, identity: CommandIdentity, payload: object
    ) -> StoredResponse: ...


def _items(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not values:
        return []
    payload = {"snapshot_hash": "0" * 64, "sheet_hash": "0" * 64, "items": list(values)}
    return cast(
        list[dict[str, Any]], validate_snapshot_payload("pin_items", payload)["items"]
    )


def compose_next_snapshot(
    prior_items: Sequence[Mapping[str, Any]],
    acquired: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The next snapshot's paper manifest: the prior items plus the acquired.

    Items are ordered by paper version id, so the same inputs always give the
    same manifest bytes. Re-adding an item already pinned identically is a
    no-op; an acquired item that differs from a pinned one is refused.
    """

    items: dict[str, dict[str, Any]] = {}
    for item in _items(prior_items):
        items[item["paper_version_id"]] = item
    for item in _items(acquired):
        pinned = items.get(item["paper_version_id"])
        if pinned is not None and pinned != item:
            raise ContractValidationError(
                "an acquired paper would rewrite a version the prior snapshot pinned"
            )
        items[item["paper_version_id"]] = item
    if not items:
        raise ContractValidationError("a snapshot needs at least one paper")
    return {
        "schema_version": 1,
        "kind": PAPER_MANIFEST_KIND,
        "items": [items[version] for version in sorted(items)],
    }


def seal_next_snapshot(
    snapshots: SnapshotCommands,
    publish: Callable[[dict[str, Any]], str],
    *,
    principal_id: UUID,
    prior_items: Sequence[Mapping[str, Any]],
    acquired: Sequence[Mapping[str, Any]],
    index_identity_hashes: tuple[str, ...],
    sheet_hashes: Sequence[str],
) -> str:
    """Seal and pin the composed snapshot; return its hash.

    ``publish`` stores the paper manifest and returns its manifest hash.
    The snapshot is the day's, sealed after the day's sheets exist, and is
    pinned to every one of them (#283). No sheet, no seal.
    """

    if not sheet_hashes:
        raise ContractValidationError("a snapshot is sealed after its day's sheets")
    manifest = compose_next_snapshot(prior_items, acquired)
    sealed = snapshots.execute(
        "seal",
        identity=CommandIdentity(principal_id, uuid4(), uuid4(), uuid4()),
        payload={
            "paper_manifest_hash": publish(manifest),
            "index_identity_hashes": list(index_identity_hashes),
        },
    )
    body = cast(dict[str, Any], canonical_loads(sealed.body))
    snapshot_hash = str(body["data"]["snapshot_hash"])
    items = manifest["items"]
    for sheet_hash in dict.fromkeys(sheet_hashes):
        # Every sheet of the day reads the whole snapshot; storage keeps one
        # item row per version however many sheets pin it.
        for start in range(0, len(items), _PIN_CHUNK):
            snapshots.execute(
                "pin_items",
                identity=CommandIdentity(principal_id, uuid4(), uuid4(), uuid4()),
                payload={
                    "snapshot_hash": snapshot_hash,
                    "sheet_hash": sheet_hash,
                    "items": items[start : start + _PIN_CHUNK],
                },
            )
    return snapshot_hash
