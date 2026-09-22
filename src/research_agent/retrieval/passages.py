"""Passage building, search and publication (SDD RD-25 to RD-28, Appendix C).

``build_passages`` is the public entry point named by TDD-1.1.25; it chunks
one extraction to the fixed passage policy through the private
``reader.chunk.chunk_passages`` helper (TDD's implementation interface map).
``search_passages``, ``attach_evidence`` and ``publish_index`` have no
shipped implementation anywhere in the codebase yet: they raise until their
owning slices land.
"""

from __future__ import annotations

from typing import NoReturn

from ..contracts.passages import ExtractionRecord, PassageRecord
from ..reader.chunk import SectionTokenizer, chunk_passages

__all__ = ["build_passages", "search_passages", "attach_evidence", "publish_index"]


def build_passages(
    extraction: ExtractionRecord,
    canonical_text: str,
    extraction_hash: str,
    tokenizer: SectionTokenizer,
) -> tuple[PassageRecord, ...]:
    """Chunk one extraction's included text into ordered, source-linked passages."""

    return chunk_passages(extraction, canonical_text, extraction_hash, tokenizer)


def search_passages(*args: object, **kwargs: object) -> NoReturn:
    """RD-26 passage search. No implementation exists; #70 owns it."""

    raise NotImplementedError("search_passages has no owning slice yet; see #70")


def attach_evidence(*args: object, **kwargs: object) -> NoReturn:
    """RD-27 query-attached evidence on a paper card. #116 owns it."""

    raise NotImplementedError("attach_evidence has no owning slice yet; see #116")


def publish_index(*args: object, **kwargs: object) -> NoReturn:
    """RD-28 atomic passage-index publication. #112 owns it."""

    raise NotImplementedError("publish_index has no owning slice yet; see #112")
