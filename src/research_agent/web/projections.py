"""Rater-safe projections that blind genome identity and paper origin (SR-21, SR-22)."""

from __future__ import annotations

import random
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
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
