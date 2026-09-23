"""Rater-safe projections that blind genome identity and paper origin (SR-21, SR-22)."""

from __future__ import annotations

import random
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """A digest candidate as storage holds it, including fields a rater never sees.

    ``genome_hash`` and ``origin`` stay attached here so an analyst-side join
    from paper back to genome or origin remains possible; neither field is
    part of :class:`BlindedPaperView`, so neither reaches a rater endpoint.
    """

    paper_hash: str
    digest_entry_id: UUID
    title: str
    abstract: str
    genome_hash: str | None
    origin: str


@dataclass(frozen=True, slots=True)
class BlindedPaperView:
    """The positive list of fields a rater's pre-rating digest row may ever carry.

    No genome, run, slot, lineage, origin or selection-reason field exists on
    this type, so there is nothing here for a serializer to leak by accident.
    """

    paper_hash: str
    digest_entry_id: str
    title: str
    abstract: str

    def to_dict(self) -> dict[str, str]:
        return {
            "paper_hash": self.paper_hash,
            "digest_entry_id": self.digest_entry_id,
            "title": self.title,
            "abstract": self.abstract,
        }


# Nominations, random controls (SR-22) and service picks are projected through
# this identical type, so no array shape, field or absent attribute in a
# rater's digest can encode which of the three kinds an entry came from.
OriginBlindEntry = BlindedPaperView


def blind_digest(
    entries: Sequence[SourceEntry], *, seed: bytes
) -> tuple[BlindedPaperView, ...]:
    """Project a merged digest selection into the rater-safe positive list.

    Ordering starts from a canonical sort of the merged selection and is then
    shuffled from the persisted digest seed, so neither a genome's papers
    (SR-21) nor a control or service pick (SR-22) keeps a fixed or
    origin-linked position; no range of positions is reserved for any origin.
    """
    canonical = sorted(entries, key=lambda entry: str(entry.digest_entry_id))
    shuffled = list(canonical)
    random.Random(seed).shuffle(shuffled)
    return tuple(_project(entry) for entry in shuffled)


def _project(entry: SourceEntry) -> BlindedPaperView:
    return BlindedPaperView(
        paper_hash=entry.paper_hash,
        digest_entry_id=str(entry.digest_entry_id),
        title=entry.title,
        abstract=entry.abstract,
    )


class DuplicateRunLabelError(ValueError):
    """Raised when label assignment would reuse an opaque label across papers."""


def assign_run_labels(run_ids: Sequence[UUID], *, taken: set[str]) -> dict[UUID, str]:
    """Draw one fresh opaque label per run id, unique within the presented digest.

    Labels are drawn from secure randomness for this view alone and are never
    persisted, so no identity carries from one paper's runs to the next, even
    when two papers were surfaced by the same genome (SR-21). ``taken``
    accumulates labels already drawn for other papers in the same digest so a
    label can never repeat across them.
    """
    labels: dict[UUID, str] = {}
    for run_id in run_ids:
        label = _draw_unused_label(taken)
        labels[run_id] = label
    return labels


def _draw_unused_label(taken: set[str]) -> str:
    for _ in range(1000):
        candidate = secrets.token_hex(4)
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise DuplicateRunLabelError("could not draw an unused opaque run label")


@dataclass(frozen=True, slots=True)
class RatedEntryDetail:
    """The fields a digest entry discloses only once the rater has rated it.

    Origin never appears here: SR-21/SR-22 blinding is permanent and plays
    no part in this projection, rated or not (SR-25).
    """

    probability: float | None
    rationale: str | None
    popularity_count: int | None
    jev: dict[str, Any] | None
    reading: str | None


class RatingDisclosure:
    """Gate a digest entry's probability, rationale, popularity, Jev and reading on rating status (SR-25).

    Before the authenticated rater has an accepted rating for this entry,
    every gated field is omitted from the projection entirely -- not
    nulled, not hidden by styling -- so nothing about them reaches the
    client. Once rated, all five are disclosed together.
    """

    def project(self, detail: RatedEntryDetail, *, rated: bool) -> dict[str, Any]:
        if not rated:
            return {}
        return {
            "probability": detail.probability,
            "rationale": detail.rationale,
            "popularity_count": detail.popularity_count,
            "jev": detail.jev,
            "reading": detail.reading,
        }
