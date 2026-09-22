"""A fixture digest standing in for the EN-40 builder (#120).

The digest builder (EN-40) does not exist yet; this fixture supplies a
deterministic small digest so the app can be served and rated against real
storage records ahead of that builder landing (#132).
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

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
        origin="nomination",
    ),
    SourceEntry(
        paper_hash=_hash("fixture-paper-2"),
        digest_entry_id=UUID("22222222-2222-4222-8222-222222222222"),
        title="Passage retrieval for long scientific documents",
        abstract="Comparing retrieval strategies over full-length paper text.",
        genome_hash=_hash("fixture-genome-a"),
        origin="nomination",
    ),
    SourceEntry(
        paper_hash=_hash("fixture-paper-3"),
        digest_entry_id=UUID("33333333-3333-4333-8333-333333333333"),
        title="A random control paper from the daily pool",
        abstract="Included to measure selection effects, not because an agent chose it.",
        genome_hash=None,
        origin="control",
    ),
    SourceEntry(
        paper_hash=_hash("fixture-paper-4"),
        digest_entry_id=UUID("44444444-4444-4444-8444-444444444444"),
        title="A discovery-service pick from the daily pool",
        abstract="Included from the permitted discovery-service capture.",
        genome_hash=None,
        origin="service_pick",
    ),
)


@dataclass(frozen=True, slots=True)
class DigestFixture:
    """A fixed digest used until the real builder (#120) lands."""

    seed: bytes
    entries: tuple[SourceEntry, ...]


def default_fixture() -> DigestFixture:
    return DigestFixture(seed=_FIXTURE_SEED, entries=_FIXTURE_ENTRIES)
