"""Refuse a genome that carries a corpus paper's identifier in any part (AG-31).

Admission reads every part of a genome and looks for the identifier of a
paper already in the corpus. A genome that carries one in any part is
refused whole, so no lineage carries a named paper -- and with it a settled
outcome -- forward into a later run. Which identifiers are in the corpus is
a caller's job to supply, the same boundary ``evolution/genome.py`` draws
for a genome's measured standing: nothing here reads storage itself.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping


def reject_paper_identifiers(
    parts: Mapping[str, str], *, corpus_identifiers: Collection[str]
) -> tuple[str, ...]:
    """Return the names of every part in *parts* that carries a corpus identifier.

    Checks each part's text for every identifier in *corpus_identifiers* as
    a literal substring of the identifier's exact wire form, not a guessed
    pattern, so a genome is refused whole -- an empty result admits it --
    whenever any part carries one, and the refusal can name the offending
    part (AG-31). Order of the returned tuple follows *parts* iteration
    order; a part with no offending identifier is never named.
    """

    identifiers = tuple(corpus_identifiers)
    offending: list[str] = []
    for part, text in parts.items():
        if any(identifier in text for identifier in identifiers):
            offending.append(part)
    return tuple(offending)
