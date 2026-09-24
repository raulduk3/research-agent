"""Deterministic digest construction from frozen watermark inputs (EN-40)."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from research_agent.contracts.canonical import canonical_json, sha256_hex

from .controls import sample_controls
from .nominations import Nomination, allocate_population_entries
from .services import ServicePick, allocate_service_entries

ENTRY_LIMIT = 12

Origin = Literal["population", "random_control", "service"]


@dataclass(frozen=True, slots=True)
class DigestEntry:
    """One built digest entry, positioned after selection and blind shuffling."""

    entry_id: str
    paper_id: str
    origin: Origin
    position: int


@dataclass(frozen=True, slots=True)
class DigestManifest:
    """A fully built, immutable island digest (EN-40)."""

    schema_version: int
    batch_id: str
    island: str
    source_watermark: int
    cutoff: str
    profile_id: str
    shuffle_seed: int
    entries: tuple[DigestEntry, ...]
    digest_hash: str
    # The control draw a random_control entry was sampled from (EN-33),
    # recorded for storage beside the manifest rather than hashed into it.
    control_pool_hash: str
    control_inclusion_probability: float | None


def build_digest(
    *,
    batch_id: str,
    island: str,
    source_watermark: int,
    cutoff: str,
    profile_id: str,
    control_rubric_version: str,
    day_ordinal: int,
    population_nominations: Mapping[str, Sequence[Nomination]],
    eligible_family_ids: Sequence[str],
    service_picks: Mapping[str, Sequence[ServicePick]],
) -> DigestManifest:
    """Build one island's digest from inputs already frozen at a ledger watermark.

    Population entries are allocated first (EN-41), then controls from the
    residual pool (EN-33), then service picks from what remains (EN-42).
    Every argument is a plain value already read at the watermark; this
    function reads nothing else, so calling it twice with the same arguments
    -- including after new ratings, late service captures or late submission
    attempts a caller chooses not to pass in -- reproduces the identical
    manifest and ``digest_hash``. ``cutoff`` becomes the manifest's recorded
    creation time; it is the watermark's freeze time, not wall-clock time at
    build.
    """

    population = allocate_population_entries(
        population_nominations, day_ordinal=day_ordinal
    )
    population_ids = {winner.family_id for winner in population.winners}

    controls = sample_controls(
        eligible_family_ids,
        population_family_ids=population_ids,
        batch_hash=batch_id,
        island=island,
        control_rubric_version=control_rubric_version,
    )

    services = allocate_service_entries(
        service_picks,
        already_selected=population_ids | set(controls.selected),
    )

    candidates: list[tuple[str, Origin]] = (
        [(winner.family_id, "population") for winner in population.winners]
        + [(family_id, "random_control") for family_id in controls.selected]
        + [(family_id, "service") for family_id in services.selected]
    )[:ENTRY_LIMIT]

    shuffle_seed = _shuffle_seed(batch_id, island, profile_id, source_watermark)
    scored = [
        (_entry_id(batch_id, source_watermark, paper_id, profile_id), paper_id, origin)
        for paper_id, origin in candidates
    ]
    canonical_order = sorted(scored, key=lambda item: item[0])
    shuffled = list(canonical_order)
    random.Random(shuffle_seed).shuffle(shuffled)

    entries = tuple(
        DigestEntry(
            entry_id=entry_id, paper_id=paper_id, origin=origin, position=position
        )
        for position, (entry_id, paper_id, origin) in enumerate(shuffled)
    )

    body = _manifest_body(
        batch_id=batch_id,
        island=island,
        source_watermark=source_watermark,
        cutoff=cutoff,
        profile_id=profile_id,
        shuffle_seed=shuffle_seed,
        entries=entries,
    )

    return DigestManifest(
        schema_version=1,
        batch_id=batch_id,
        island=island,
        source_watermark=source_watermark,
        cutoff=cutoff,
        profile_id=profile_id,
        shuffle_seed=shuffle_seed,
        entries=entries,
        digest_hash=sha256_hex(canonical_json(body)),
        control_pool_hash=controls.candidate_pool_hash,
        control_inclusion_probability=controls.inclusion_probability,
    )


def _manifest_body(
    *,
    batch_id: str,
    island: str,
    source_watermark: int,
    cutoff: str,
    profile_id: str,
    shuffle_seed: int,
    entries: Sequence[DigestEntry],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "island": island,
        "source_watermark": source_watermark,
        "cutoff": cutoff,
        "profile_id": profile_id,
        "shuffle_seed": shuffle_seed,
        "entries": [
            {
                "entry_id": entry.entry_id,
                "paper_id": entry.paper_id,
                "origin": entry.origin,
                "position": entry.position,
            }
            for entry in entries
        ],
    }


def _entry_id(
    batch_id: str, source_watermark: int, paper_id: str, profile_id: str
) -> str:
    """Content-hash a candidate's identity so replay never mints a new id."""

    return sha256_hex(
        canonical_json(
            {
                "batch_id": batch_id,
                "source_watermark": source_watermark,
                "paper_id": paper_id,
                "profile_id": profile_id,
            }
        )
    )


def _shuffle_seed(
    batch_id: str, island: str, profile_id: str, source_watermark: int
) -> int:
    """Derive the recorded blind-display seed, domain-separated from other uses."""

    digest = sha256(
        f"digest-shuffle-v1:{batch_id}:{island}:{profile_id}:{source_watermark}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big")
