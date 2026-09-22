"""Strict wire contracts for the pinned summarizer's reading (EN-43, TDD-3.1.75).

``Reading`` is the one model-written field a rater ever receives (SR-26):
a bounded plain-text account of what the island's genomes claimed about a
digest entry's paper, stored with its provenance and never scored or fed
back. The input schema this module closes is exactly {card text, each
genome's sealed probability and rationale, protected run notes} -- never
nominations, origin or the paper's own text (TDD-3.1.75).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_json, sha256_hex
from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_probability,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from .tools import bounded_word_text

__all__ = [
    "READING_LABEL",
    "READING_MAXIMUM_WORDS",
    "PROTECTED_NOTE_MAXIMUM_CHARS",
    "RATIONALE_MAXIMUM_CHARS",
    "FORBIDDEN_READING_TERMS",
    "GenomeReading",
    "SummarizerInput",
    "Reading",
    "ReadingRefused",
    "build_summarizer_input",
    "validate_reading_text",
]

READING_LABEL = "automated_output"
READING_MAXIMUM_WORDS = 200
PROTECTED_NOTE_MAXIMUM_CHARS = 1000
RATIONALE_MAXIMUM_CHARS = 2000

#: The naming refusal of TDD-3.1.75: a reading is refused whole for
#: mentioning any of these words, beside a literal genome hash or run id
#: checked separately.
FORBIDDEN_READING_TERMS = ("control", "service", "nomination")


class ReadingRefused(Exception):
    """Raised when a candidate reading fails EN-43's bound or naming check."""


@dataclass(frozen=True, slots=True)
class GenomeReading:
    """One island genome's sealed forecast for the entry's paper (EN-43 input)."""

    genome_hash: str
    probability: float
    rationale: str

    def __post_init__(self) -> None:
        validate_sha256(self.genome_hash)
        validate_probability(self.probability)
        rationale = validate_non_empty_string(self.rationale)
        if len(rationale) > RATIONALE_MAXIMUM_CHARS:
            raise ContractValidationError("rationale exceeds its bound")

    def to_dict(self) -> dict[str, Any]:
        return {
            "genome_hash": self.genome_hash,
            "probability": self.probability,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class SummarizerInput:
    """The summarizer's closed input for one digest entry (TDD-3.1.75).

    ``genome_readings`` is stored in ascending ``genome_hash`` order
    regardless of the order given, so two callers assembling the same
    facts in a different order hash the same input. ``protected_notes``
    keeps the given order, which is the run order its notes were recorded
    in (AG-39).
    """

    card_text: str
    genome_readings: tuple[GenomeReading, ...]
    protected_notes: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.card_text)
        if not self.genome_readings:
            raise ContractValidationError("genome_readings must be nonempty")
        genome_hashes = [reading.genome_hash for reading in self.genome_readings]
        if len(set(genome_hashes)) != len(genome_hashes):
            raise ContractValidationError("genome_readings must name distinct genomes")
        ordered = tuple(sorted(self.genome_readings, key=lambda r: r.genome_hash))
        object.__setattr__(self, "genome_readings", ordered)
        for note in self.protected_notes:
            note_text = validate_non_empty_string(note)
            if len(note_text) > PROTECTED_NOTE_MAXIMUM_CHARS:
                raise ContractValidationError("protected note exceeds its bound")

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_text": self.card_text,
            "genome_readings": [reading.to_dict() for reading in self.genome_readings],
            "protected_notes": list(self.protected_notes),
        }

    def input_hashes(self) -> tuple[str, ...]:
        """The ordered content hashes stored with the reading (TDD-3.1.75).

        One hash for the card text, then one per genome reading in
        ``genome_hash`` order, then one per protected note in the order
        given.
        """

        hashes = [sha256_hex(canonical_json({"card_text": self.card_text}))]
        hashes.extend(
            sha256_hex(canonical_json(reading.to_dict()))
            for reading in self.genome_readings
        )
        hashes.extend(
            sha256_hex(canonical_json({"protected_note": note}))
            for note in self.protected_notes
        )
        return tuple(hashes)


def build_summarizer_input(
    *,
    card_text: str,
    genome_readings: Sequence[GenomeReading],
    protected_notes: Sequence[str],
) -> SummarizerInput:
    """Close the summarizer's input over exactly its admitted fields.

    Nominations, origin and the paper's own text have no parameter here:
    a caller cannot pass them in by construction (TDD-3.1.75).
    """

    return SummarizerInput(
        card_text=card_text,
        genome_readings=tuple(genome_readings),
        protected_notes=tuple(protected_notes),
    )


def validate_reading_text(
    text: object,
    *,
    forbidden_hashes: Sequence[str],
    forbidden_ids: Sequence[str],
) -> str:
    """Validate a candidate reply as EN-43's stored reading text, or refuse.

    Refuses non-string content, more than 200 words, any of the words in
    :data:`FORBIDDEN_READING_TERMS`, and a literal occurrence of any hash
    in ``forbidden_hashes`` (the island's genome hashes) or id in
    ``forbidden_ids`` (the entry's contributing run ids). Every refusal
    raises :class:`ReadingRefused`; the caller stores no reading.
    """

    if not isinstance(text, str):
        raise ReadingRefused("reading must be plain text")
    try:
        bounded = bounded_word_text(text, READING_MAXIMUM_WORDS, "reading text")
    except ContractValidationError as error:
        raise ReadingRefused(str(error)) from error
    lowered = bounded.lower()
    for term in FORBIDDEN_READING_TERMS:
        if term in lowered:
            raise ReadingRefused(f"reading names the forbidden term {term!r}")
    for value in (*forbidden_hashes, *forbidden_ids):
        if value and value in bounded:
            raise ReadingRefused("reading names a genome hash or run id")
    return bounded


@dataclass(frozen=True, slots=True)
class Reading:
    """One digest entry's stored summarizer output (EN-43).

    Never scored, never fed back into selection or mutation; rendered to
    a rater only after that rater has rated the entry (SR-25, IN-36).
    """

    digest_entry_id: str
    text: str
    label: str
    model_provider: str
    model_id: str
    model_revision: str
    prompt_hash: str
    input_hashes: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        validate_uuid4(self.digest_entry_id)
        bounded_word_text(self.text, READING_MAXIMUM_WORDS, "reading text")
        if self.label != READING_LABEL:
            raise ContractValidationError("label must be the automated-output label")
        validate_non_empty_string(self.model_provider)
        validate_non_empty_string(self.model_id)
        validate_non_empty_string(self.model_revision)
        validate_sha256(self.prompt_hash)
        if not self.input_hashes:
            raise ContractValidationError("input_hashes must be nonempty")
        for value in self.input_hashes:
            validate_sha256(value)
        validate_utc_instant(self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest_entry_id": self.digest_entry_id,
            "text": self.text,
            "label": self.label,
            "model_provider": self.model_provider,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "prompt_hash": self.prompt_hash,
            "input_hashes": list(self.input_hashes),
            "created_at": self.created_at,
        }
