"""A fixture digest standing in for a wired composition root (#120, #179).

The digest builder (EN-40) and its storage persistence (#179) exist now, but
nothing in this repository yet composes the rating app against a real daily
digest; this fixture keeps serving that role. ``store_fixture_digest`` below
persists this exact fixture through the same write path a real orchestrator
would use, so a rating against one of its entries satisfies the storage
foreign key from ``ratings`` to ``digest_entries`` -- tests seed through it
instead of rating an entry id storage has never heard of. ``load_digest``
reads a real stored digest back into this same shape for a rater, deliberately
blind to origin and nomination (SR-21, SR-22); title and abstract are not yet
resolvable from a digest entry alone (paper card text has no read route open
to the rating app) and stay empty until that lands.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from research_agent.storage.client import StorageClient
from research_agent.web.projections import SourceEntry


def _hash(label: str) -> str:
    return sha256(label.encode()).hexdigest()


_FIXTURE_SEED = _hash("fixture-digest-seed").encode()

_FIXTURE_ENTRIES: tuple[SourceEntry, ...] = (
    SourceEntry(
        paper_hash=_hash("fixture-paper-1"),
        digest_entry_id=UUID("11111111-1111-4111-8111-111111111111"),
        title="Calibrated forecasting across shifting subfields",
        abstract="A study of forecast calibration as subfield composition drifts.",
        genome_hash=_hash("fixture-genome-a"),
        origin="population",
    ),
    SourceEntry(
        paper_hash=_hash("fixture-paper-2"),
        digest_entry_id=UUID("22222222-2222-4222-8222-222222222222"),
        title="Passage retrieval for long scientific documents",
        abstract="Comparing retrieval strategies over full-length paper text.",
        genome_hash=_hash("fixture-genome-a"),
        origin="population",
    ),
    SourceEntry(
        paper_hash=_hash("fixture-paper-3"),
        digest_entry_id=UUID("33333333-3333-4333-8333-333333333333"),
        title="Measuring uncertainty in scientific forecasts",
        abstract="An analysis of uncertainty estimates across scientific datasets.",
        genome_hash=None,
        origin="random_control",
    ),
    SourceEntry(
        paper_hash=_hash("fixture-paper-4"),
        digest_entry_id=UUID("44444444-4444-4444-8444-444444444444"),
        title="Representations for comparing research documents",
        abstract="A comparison of document representations for scientific retrieval.",
        genome_hash=None,
        origin="service",
    ),
)

_FIXTURE_BATCH_ID = _hash("fixture-digest-batch")
_FIXTURE_ISLAND = "cs"


@dataclass(frozen=True, slots=True)
class DigestFixture:
    """A fixed digest used until a composition root reads a real one (#120)."""

    seed: bytes
    entries: tuple[SourceEntry, ...]
    island: str = _FIXTURE_ISLAND
    batch_id: str = _FIXTURE_BATCH_ID


def default_fixture() -> DigestFixture:
    return DigestFixture(seed=_FIXTURE_SEED, entries=_FIXTURE_ENTRIES)


def fixture_store_payload(
    fixture: DigestFixture | None = None,
    *,
    batch_id: str | None = None,
    island: str | None = None,
) -> dict[str, Any]:
    """Build the digest-store payload for ``fixture`` (#179).

    Pure so a repository-level test can pass it to ``DigestRepository``
    directly, without opening the HTTPS boundary ``store_fixture_digest``
    goes through.
    """

    fixture = fixture if fixture is not None else default_fixture()
    batch_id = batch_id if batch_id is not None else fixture.batch_id
    island = island if island is not None else fixture.island
    entries = [
        {
            "entry_id": str(entry.digest_entry_id),
            "paper_hash": entry.paper_hash,
            "origin": entry.origin,
            "display_position": position,
            "service_source": "fixture-service" if entry.origin == "service" else None,
            "candidate_pool_hash": _hash("fixture-pool")
            if entry.origin == "random_control"
            else None,
            "inclusion_probability": 0.5 if entry.origin == "random_control" else None,
        }
        for position, entry in enumerate(fixture.entries)
    ]
    return {
        "digest_hash": _hash(f"fixture-digest:{batch_id}:{island}"),
        "batch_id": batch_id,
        "island": island,
        "source_watermark": 0,
        "shuffle_seed": fixture.seed[:8].hex(),
        "entries": entries,
        "nominations": [],
    }


def store_fixture_digest(
    storage: StorageClient,
    fixture: DigestFixture | None = None,
    *,
    batch_id: str | None = None,
    island: str | None = None,
) -> None:
    """Persist ``fixture`` through the real digest write path (#179).

    Lets a test rate one of the fixture's entries without inventing a second,
    storage-unaware notion of what a digest entry is: the same
    ``digest_entries`` row the rating's foreign key checks against is the one
    this writes.
    """

    payload = fixture_store_payload(fixture, batch_id=batch_id, island=island)
    storage.store_digest(
        digest_hash=payload["digest_hash"],
        batch_id=payload["batch_id"],
        island=payload["island"],
        source_watermark=payload["source_watermark"],
        shuffle_seed=payload["shuffle_seed"],
        entries=tuple(payload["entries"]),
        nominations=(),
        command_id=uuid4(),
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )


def load_digest(storage: StorageClient, *, island: str, batch_id: str) -> DigestFixture:
    """Read a stored digest for a rater and adapt it to this app's shape.

    Blind by construction (SR-21, SR-22): storage's rater-facing read never
    carries origin or nomination, so every entry here gets a neutral,
    non-revealing placeholder for both instead of a guessed value.
    """

    result = storage.read_digest_for_rater(island=island, batch_id=batch_id)
    entries = tuple(_entry_from_storage(entry) for entry in result.data["entries"])
    seed = bytes.fromhex(result.data["shuffle_seed"])
    return DigestFixture(seed=seed, entries=entries, island=island, batch_id=batch_id)


def _entry_from_storage(entry: Mapping[str, Any]) -> SourceEntry:
    return SourceEntry(
        paper_hash=entry["paper_hash"],
        digest_entry_id=UUID(entry["entry_id"]),
        title="",
        abstract="",
        genome_hash=None,
        origin="digest",
    )
