from __future__ import annotations

from uuid import uuid4

from research_agent.contracts.papers import ExternalIdentifier
from research_agent.ingest.bibliography import (
    BibliographyParseResult,
    parse_identified_references,
)
from research_agent.reader.extract import normalize_text

CITING_FAMILY_ID = str(uuid4())
TARGET_A = str(uuid4())
TARGET_B = str(uuid4())
SOURCE_HASH = "a" * 64
CAPTURED_AT = "2026-09-23T00:00:00.000000Z"

IDENTITY_INDEX = {
    ExternalIdentifier("arxiv", "2101.00001v2"): TARGET_A,
    ExternalIdentifier("arxiv", "2101.00001v3"): TARGET_A,
    ExternalIdentifier("arxiv", "2103.00002v1"): TARGET_B,
    ExternalIdentifier("doi", "10.1000/xyz123"): TARGET_B,
}

BIBLIOGRAPHY = r"""
\begin{thebibliography}{9}
\bibitem{alpha} A. One. Some Title. arXiv:2101.00001v2, 2021.
\bibitem{beta} B. Two. A Later Version Of The Same Work. arXiv:2101.00001v3, 2021.
\bibitem{gamma} C. Three. Preprint And Its Journal Version. arXiv:2103.00002v1 and doi:10.1000/xyz123.
\bibitem{delta} D. Four. \input{/etc/passwd} \immediate\write18{echo pwned}
\bibitem{epsilon} E. Five. A Paper With No Identifier At All.
\bibitem{zeta} F. Six. An Uncatalogued Preprint. arXiv:2199.99999v1, 2021.
\end{thebibliography}
"""


def _parse() -> BibliographyParseResult:
    return parse_identified_references(
        BIBLIOGRAPHY,
        source_hash=SOURCE_HASH,
        citing_family_id=CITING_FAMILY_ID,
        identity_index=IDENTITY_INDEX,
        captured_at=CAPTURED_AT,
    )


def test_repeated_versions_collapse_to_one_family_edge() -> None:
    """alpha (v2) and beta (v3) both alias the same family; they merge into
    one edge rather than two (SDD-MD-07)."""

    result = _parse()
    matches = [edge for edge in result.edges if edge.target_family_id == TARGET_A]
    assert len(matches) == 1
    edge = matches[0]
    assert edge.source_family_id == CITING_FAMILY_ID
    assert edge.sources == ("bibliography_parse",)
    assert len(edge.evidence_hashes) == 2
    assert len(edge.available_ats) == 2


def test_duplicate_preprint_and_journal_identifiers_in_one_entry_merge() -> None:
    """gamma cites both a preprint id and a DOI for the same work in one
    ``\\bibitem``; both become evidence for a single edge (TDD-4.1.69)."""

    result = _parse()
    matches = [edge for edge in result.edges if edge.target_family_id == TARGET_B]
    assert len(matches) == 1
    assert len(matches[0].evidence_hashes) == 2


def test_malicious_tex_is_never_executed_and_produces_no_edge() -> None:
    """delta contains an ``\\input`` and a ``\\write18``; both are inert
    text, never a filesystem or shell action, and yield no identifier."""

    result = _parse()
    delta = [entry for entry in result.unmatched if "write18" in entry.raw_text]
    assert len(delta) == 1
    assert delta[0].reason == "no_identifier"
    assert "\\input{/etc/passwd}" in delta[0].raw_text


def test_ambiguous_text_with_no_identifier_is_unmatched_never_guessed() -> None:
    result = _parse()
    epsilon = [
        entry for entry in result.unmatched if "No Identifier At All" in entry.raw_text
    ]
    assert len(epsilon) == 1
    assert epsilon[0].reason == "no_identifier"
    assert epsilon[0].source_family_id == CITING_FAMILY_ID


def test_uncatalogued_identifier_is_unmatched_as_unresolved() -> None:
    """zeta has an exact, well-formed arXiv identifier, but the identity
    index does not recognize it: it stays unmatched, never guessed into an
    edge, and is distinguished from having no identifier at all."""

    result = _parse()
    zeta = [entry for entry in result.unmatched if "Uncatalogued" in entry.raw_text]
    assert len(zeta) == 1
    assert zeta[0].reason == "unresolved_identifier"


def test_unmatched_entries_preserve_their_exact_source_span() -> None:
    normalized = normalize_text(BIBLIOGRAPHY)
    result = _parse()
    for entry in result.unmatched:
        assert normalized[entry.char_start : entry.char_end_exclusive] == entry.raw_text


def test_missing_bibliography_yields_an_empty_result_not_a_failure() -> None:
    result = parse_identified_references(
        "",
        source_hash=SOURCE_HASH,
        citing_family_id=CITING_FAMILY_ID,
        identity_index=IDENTITY_INDEX,
        captured_at=CAPTURED_AT,
    )
    assert result.edges == ()
    assert result.unmatched == ()


def test_edges_are_ordered_by_source_then_target_family_id() -> None:
    result = _parse()
    pairs = [(edge.source_family_id, edge.target_family_id) for edge in result.edges]
    assert pairs == sorted(pairs)
