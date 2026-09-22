from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from uuid import UUID

from research_agent.web.projections import (
    BlindedPaperView,
    SourceEntry,
    assign_run_labels,
    blind_digest,
)

GENOME = sha256(b"one-known-genome").hexdigest()
SEED = b"a-recorded-digest-seed"


def entry(label: str, *, genome_hash: str | None = GENOME) -> SourceEntry:
    return SourceEntry(
        paper_hash=sha256(label.encode()).hexdigest(),
        digest_entry_id=UUID(bytes=sha256(f"entry-{label}".encode()).digest()[:16]),
        title=f"title-{label}",
        abstract=f"abstract-{label}",
        genome_hash=genome_hash,
        origin="nomination",
    )


def test_blinded_views_carry_no_genome_run_slot_or_lineage_field() -> None:
    rows = blind_digest([entry("a"), entry("b")], seed=SEED)
    for row in rows:
        assert isinstance(row, BlindedPaperView)
        payload = json.dumps(row.to_dict())
        assert GENOME not in payload
        for forbidden in ("genome", "run", "slot", "lineage"):
            assert forbidden not in payload

    fields = {field for row in rows for field in asdict(row)}
    assert fields == {"paper_hash", "digest_entry_id", "title", "abstract"}


def test_two_papers_from_the_same_genome_get_different_run_labels() -> None:
    run_a, run_b = UUID(int=1), UUID(int=2)
    taken: set[str] = set()
    labels_for_paper_one = assign_run_labels([run_a], taken=taken)
    labels_for_paper_two = assign_run_labels([run_b], taken=taken)

    assert labels_for_paper_one[run_a] != labels_for_paper_two[run_b]
    assert len(taken) == 2


def test_the_analyst_side_provenance_join_still_resolves_to_the_genome() -> None:
    source = entry("a")
    (row,) = blind_digest([source], seed=SEED)
    assert row.paper_hash == source.paper_hash
    assert source.genome_hash == GENOME


def test_selection_ordering_is_shuffled_from_the_persisted_seed() -> None:
    entries = [entry(str(index)) for index in range(8)]
    first = blind_digest(entries, seed=SEED)
    again = blind_digest(entries, seed=SEED)
    reordered_input = blind_digest(list(reversed(entries)), seed=SEED)
    assert first == again == reordered_input

    other_seed = blind_digest(entries, seed=b"a-different-seed")
    assert [row.paper_hash for row in first] != [row.paper_hash for row in other_seed]
