"""Parse a LaTeX bibliography into exact identified references (MD-07).

A regex scan only: no TeX macro is expanded and no external command runs,
so a malicious ``\\input`` or ``\\write18`` inside a ``\\bibitem`` is inert
text, never a fuzzy title match and never an executed instruction. Only an
exact, explicitly versioned DOI or arXiv identifier that the caller's
identity index already resolves to a family becomes an edge; everything
else -- an identifier the index does not recognize, or a ``\\bibitem`` with
no identifier at all -- is preserved as an unmatched entry with its source
span, never guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.graph import GraphEdge, UnmatchedReference, merge_edges
from research_agent.contracts.papers import ExternalIdentifier, normalize_identifier
from research_agent.contracts.passages import SourceLocator
from research_agent.contracts.primitives import ContractValidationError, validate_uuid4
from research_agent.reader.extract import normalize_text

_BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{[^}]*\}")
_END_BIBLIOGRAPHY = re.compile(r"\\end\{thebibliography\}")
_ARXIV = re.compile(
    r"(?:arxiv:\s*)?(?P<body>\d{4}\.\d{4,5}|[a-z-]+/\d{7})v(?P<version>[1-9]\d*)",
    re.IGNORECASE,
)
_DOI = re.compile(r"10\.\d{4,9}/[^\s,;\]\}\)]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class BibliographyParseResult:
    """The exact edges and unmatched entries of one bibliography parse."""

    edges: tuple[GraphEdge, ...]
    unmatched: tuple[UnmatchedReference, ...]


def _extract_identifiers(text: str) -> tuple[ExternalIdentifier, ...]:
    identifiers: list[ExternalIdentifier] = []
    for match in _ARXIV.finditer(text):
        raw = f"{match.group('body')}v{match.group('version')}"
        try:
            canonical = normalize_identifier("arxiv", raw)
        except ContractValidationError:
            continue
        identifiers.append(ExternalIdentifier("arxiv", canonical))
    for match in _DOI.finditer(text):
        raw = match.group(0).rstrip(".,;")
        try:
            canonical = normalize_identifier("doi", raw)
        except ContractValidationError:
            continue
        identifiers.append(ExternalIdentifier("doi", canonical))
    seen: set[ExternalIdentifier] = set()
    unique: list[ExternalIdentifier] = []
    for identifier in identifiers:
        if identifier not in seen:
            seen.add(identifier)
            unique.append(identifier)
    return tuple(unique)


def _trim(text: str, start: int, end: int) -> tuple[str, int, int]:
    entry = text[start:end]
    stripped = entry.strip()
    if not stripped:
        return "", start, start
    lead = entry.index(stripped)
    return stripped, start + lead, start + lead + len(stripped)


def parse_identified_references(
    source_text: str,
    *,
    source_hash: str,
    citing_family_id: str,
    identity_index: Mapping[ExternalIdentifier, str],
    captured_at: str,
) -> BibliographyParseResult:
    """Extract exact bibliography edges and unmatched entries (MD-07, TDD-4.1.69).

    ``source_text`` is the bibliography block's own text (or a full LaTeX
    document containing a ``thebibliography`` environment); missing or
    empty text yields an empty result rather than a failure, so a caller
    combining this with other graph evidence is not blocked by an absent
    bibliography. ``identity_index`` is the shared identity service: a
    plain mapping from an already-canonical external identifier to the
    family id it names. Two identifiers in one ``\\bibitem`` that resolve
    to the same family (a preprint and its later journal DOI, say) collapse
    into one edge carrying both as evidence, never two edges.
    """

    validate_uuid4(citing_family_id)
    text = normalize_text(source_text)
    markers = list(_BIBITEM.finditer(text))
    if not markers:
        return BibliographyParseResult((), ())

    end_match = _END_BIBLIOGRAPHY.search(text)
    document_end = end_match.start() if end_match else len(text)
    locator = SourceLocator(source_hash, "latex", None, None, None, None)

    edges: dict[tuple[str, str], GraphEdge] = {}
    unmatched: list[UnmatchedReference] = []
    for index, marker in enumerate(markers):
        entry_start = marker.end()
        entry_end = (
            markers[index + 1].start() if index + 1 < len(markers) else document_end
        )
        if entry_end <= entry_start:
            continue
        raw_text, span_start, span_end = _trim(text, entry_start, entry_end)
        if not raw_text:
            continue

        identifiers = _extract_identifiers(raw_text)
        evidence_by_family: dict[str, list[str]] = {}
        for identifier in identifiers:
            family_id = identity_index.get(identifier)
            if family_id is None:
                continue
            evidence_by_family.setdefault(family_id, []).append(
                sha256_hex(identifier.to_canonical_json())
            )

        if not evidence_by_family:
            reason = "unresolved_identifier" if identifiers else "no_identifier"
            unmatched.append(
                UnmatchedReference(
                    source_family_id=citing_family_id,
                    raw_text=raw_text,
                    locator=locator,
                    char_start=span_start,
                    char_end_exclusive=span_end,
                    reason=reason,
                )
            )
            continue

        for family_id, evidence_hashes in evidence_by_family.items():
            hashes = tuple(sorted(set(evidence_hashes)))
            edge = GraphEdge(
                source_family_id=citing_family_id,
                target_family_id=family_id,
                sources=("bibliography_parse",),
                evidence_hashes=hashes,
                available_ats=tuple(captured_at for _ in hashes),
            )
            key = (citing_family_id, family_id)
            edges[key] = edge if key not in edges else merge_edges(edges[key], edge)

    ordered_edges = tuple(edges[key] for key in sorted(edges))
    return BibliographyParseResult(ordered_edges, tuple(unmatched))
