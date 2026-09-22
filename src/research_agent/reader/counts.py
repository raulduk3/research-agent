"""Snapshot-time author citation counts on a paper card (RD-12).

Reads only explicitly captured public prior-author citation counts; a missing
author or a count captured after the snapshot yields an explicit unavailable
value rather than a fabricated zero. Repository, Hugging Face, download and
discussion counters are disabled at launch and never read here.
"""

from __future__ import annotations

from ..contracts.cards import AuthorCitationCapture, AuthorCitationValue
from ..contracts.primitives import ContractValidationError

__all__ = ["author_counts"]


def author_counts(
    *,
    author_ids: tuple[str, ...],
    captures: tuple[AuthorCitationCapture, ...],
    as_of: str,
) -> tuple[AuthorCitationValue, ...]:
    """Return one `AuthorCitationValue` per unique declared author, in order."""

    by_author: dict[str, AuthorCitationCapture] = {}
    for capture in captures:
        if capture.author_id in by_author:
            raise ContractValidationError("captures name an author twice")
        by_author[capture.author_id] = capture

    seen: set[str] = set()
    results: list[AuthorCitationValue] = []
    for author_id in author_ids:
        if author_id in seen:
            continue
        seen.add(author_id)
        found = by_author.get(author_id)
        if found is None:
            results.append(
                AuthorCitationValue(author_id, None, None, None, "missing_source")
            )
        elif found.captured_at > as_of:
            results.append(
                AuthorCitationValue(author_id, None, None, None, "not_available_as_of")
            )
        else:
            results.append(
                AuthorCitationValue(
                    author_id,
                    found.count,
                    found.source_capture_hash,
                    found.captured_at,
                    None,
                )
            )
    return tuple(results)
