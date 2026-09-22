from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from research_agent.web.projections import (
    BlindedPaperView,
    OriginBlindEntry,
    SourceEntry,
    blind_digest,
)

SEED = b"a-recorded-digest-seed"


def entry(label: str, *, origin: str, genome_hash: str | None) -> SourceEntry:
    return SourceEntry(
        paper_hash=sha256(label.encode()).hexdigest(),
        digest_entry_id=UUID(bytes=sha256(f"entry-{label}".encode()).digest()[:16]),
        title="a fixed title",
        abstract="a fixed abstract",
        genome_hash=genome_hash,
        origin=origin,
    )


def test_origin_blind_entry_is_the_same_type_as_the_blinded_paper_view() -> None:
    assert OriginBlindEntry is BlindedPaperView


def test_nominations_controls_and_service_picks_serialize_identically() -> None:
    nomination = entry(
        "a", origin="nomination", genome_hash=sha256(b"genome").hexdigest()
    )
    control = entry("b", origin="control", genome_hash=None)
    service_pick = entry("c", origin="service_pick", genome_hash=None)

    (nomination_view,) = blind_digest([nomination], seed=SEED)
    (control_view,) = blind_digest([control], seed=SEED)
    (service_view,) = blind_digest([service_pick], seed=SEED)

    def without_identity(view: BlindedPaperView) -> dict[str, str]:
        payload = view.to_dict()
        del payload["paper_hash"]
        del payload["digest_entry_id"]
        return payload

    assert (
        without_identity(nomination_view)
        == without_identity(control_view)
        == without_identity(service_view)
    )
    assert (
        set(nomination_view.to_dict())
        == set(control_view.to_dict())
        == set(service_view.to_dict())
    )


def test_shuffling_does_not_reserve_a_fixed_position_block_for_any_origin() -> None:
    entries = [
        entry(str(index), origin="control", genome_hash=None)
        if index % 2 == 0
        else entry(
            str(index), origin="nomination", genome_hash=sha256(b"genome").hexdigest()
        )
        for index in range(10)
    ]
    control_hashes = {
        entry_.paper_hash for entry_ in entries if entry_.origin == "control"
    }

    def positions(seed: bytes) -> tuple[int, ...]:
        rows = blind_digest(entries, seed=seed)
        return tuple(
            position
            for position, row in enumerate(rows)
            if row.paper_hash in control_hashes
        )

    observed = {positions(f"seed-{index}".encode()) for index in range(5)}
    assert len(observed) > 1, (
        "several recorded-seed orders must not share one fixed block"
    )
