import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import uuid4

from research_agent.contracts.cards import (
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    HeadCardValue,
    JevCardAssessment,
    JevCardUnavailable,
    NeighborCardSummary,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.passages import ExtractionRecord, SourceLocator
from research_agent.reader.cards import assemble_card
from research_agent.reader.chunk import chunk_passages
from research_agent.reader.extract import extract_latex, normalize_text
from research_agent.reader.media import render_section_text
from research_agent.reader.rendering import render_card

AS_OF = "2026-06-01T00:00:00.000000Z"
ARRIVAL = "2026-05-01T00:00:00.000000Z"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def _locator() -> SourceLocator:
    return SourceLocator("a" * 64, "latex", None, None, None, None)


def _unavailable_head(target_id: str) -> HeadCardValue:
    return HeadCardValue(
        target_id,
        "b" * 64,
        "Will this paper cross the threshold?",
        None,
        "unavailable",
        "missing_source",
        None,
        None,
        None,
        None,
        "unknown_t0",
        None,
    )


def _base_input(**overrides: Any) -> CardBuildInput:
    fields: dict[str, Any] = dict(
        paper_family_id=str(uuid4()),
        paper_version_id=str(uuid4()),
        as_of=AS_OF,
        corpus_arrival_at=ARRIVAL,
        overview=CardOverview("complete", "A title", "An abstract.", ()),
        overview_available=True,
        first_public_at=ARRIVAL,
        original_source=_locator(),
        passage_coverage="unavailable",
        passage_count=0,
        extraction_hash=None,
        representation_hash=None,
        head_feature_eligible=False,
        head_feature_unavailable_reason="missing_source",
        head_predictions=tuple(_unavailable_head(t) for t in TARGET_IDS),
        neighbors=(),
        neighbor_arrivals=(),
        neighbor_embedding_distance=AvailabilityValue.unavailable("no_neighbors"),
        outcome_labels=(),
        graph_incoming_family_ids=None,
        graph_outgoing_family_ids=None,
        graph_parsed_reference_count=0,
        graph_matched_reference_ids=(),
        graph_reference_vector_count=0,
        graph_missing_reference_vector_count=0,
        graph_reference_centroid_distance=AvailabilityValue.unavailable(
            "missing_vector"
        ),
        graph_manifest_hash=None,
        author_ids=(),
        author_captures=(),
        jev=JevCardAssessment(JevCardUnavailable("missing_input", "0" * 64, None)),
        card_token_count=42,
        author_count=3,
        categories=("cs.AI",),
        version_count=1,
        title_tokens=2,
        abstract_tokens=5,
        code_link=False,
    )
    fields.update(overrides)
    return CardBuildInput(**fields)


def test_render_card_is_deterministic() -> None:
    card = assemble_card(_base_input())
    first = render_card(card)
    second = render_card(card)
    assert first == second
    assert isinstance(first, str)


def test_render_card_carries_identity_overview_and_coverage() -> None:
    card = assemble_card(_base_input())
    text = render_card(card)
    assert card.paper_family_id in text
    assert card.paper_version_id in text
    assert "A title" in text
    assert "An abstract." in text
    assert "Passage coverage: unavailable" in text


def test_render_card_keeps_hashes_and_instants_on_the_record_only() -> None:
    card = assemble_card(
        _base_input(extraction_hash="e" * 64, graph_manifest_hash="9" * 64)
    )
    text = render_card(card)
    assert card.card_token_count == 42
    assert _HEX64.findall(text) == []
    assert _INSTANT.findall(text) == [ARRIVAL]
    assert "First public at: " + ARRIVAL in text
    assert "Source: latex" in text
    assert "Card tokens" not in text


def test_render_card_shows_each_head_with_its_availability_and_reason() -> None:
    card = assemble_card(_base_input())
    text = render_card(card)
    for target_id in TARGET_IDS:
        assert target_id in text
    assert text.count("unavailable (missing_source)") >= 3


def test_render_card_reads_a_qualified_head_by_its_dates() -> None:
    heads = tuple(
        HeadCardValue(
            target_id,
            "b" * 64,
            "Will this paper cross the threshold?",
            0.5,
            "qualified",
            None,
            "2026-12-01T00:00:00.000000Z",
            "c" * 64,
            "2026-05-20T00:00:00.000000Z",
            "d" * 64,
            "eligible",
            None,
        )
        if target_id == TARGET_IDS[0]
        else _unavailable_head(target_id)
        for target_id in TARGET_IDS
    )
    card = assemble_card(_base_input(head_predictions=heads))
    text = render_card(card)
    assert (
        "  probability=0.5 horizon_end=2026-12-01 fit=2026-05-20 eligibility=eligible"
        in text
    )
    assert _HEX64.findall(text) == []
    assert _INSTANT.findall(text) == [ARRIVAL]


def test_render_card_lists_neighbors_nearest_first() -> None:
    neighbor_id = str(uuid4())
    neighbor_version_id = str(uuid4())
    build_input = _base_input(
        neighbors=(
            NeighborCardSummary(
                neighbor_id, neighbor_version_id, "A neighbor paper", 0.9, "f" * 64
            ),
        ),
        neighbor_arrivals=((neighbor_id, "2026-04-01T00:00:00.000000Z"),),
        neighbor_embedding_distance=AvailabilityValue.available(0.2),
    )
    card = assemble_card(build_input)
    text = render_card(card)
    assert "1. A neighbor paper similarity=0.9\n" in text
    assert "f" * 64 not in text
    assert "Embedding distance: 0.2" in text


def test_render_card_shows_referenced_overview_spans_instead_of_the_abstract() -> None:
    from research_agent.contracts.cards import OverviewSpan

    span = OverviewSpan(_locator(), "An excerpt of the abstract.")
    build_input = _base_input(
        overview=CardOverview("referenced", "A title", None, (span,))
    )
    card = assemble_card(build_input)
    text = render_card(card)
    assert "source spans follow" in text
    assert "  Span 1: An excerpt of the abstract." in text
    assert _HEX64.findall(text) == []


class _WhitespaceTokenizer:
    """A test tokenizer: one content token per whitespace-delimited word."""

    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]


_INTRODUCTION_WORDS = " ".join(f"intro{index}" for index in range(500))
_PAPER = rf"""
\begin{{abstract}}
This paper studies section maps.
\end{{abstract}}
\section{{Introduction}}
{_INTRODUCTION_WORDS}
\subsection{{Motivation}}
Why a map matters.
\section{{Limitations}}
The method assumes clean headings and fails on scanned pages.
\section{{Future work}}
Extend the map to figures.
\section{{References}}
\begin{{thebibliography}}{{9}}
\bibitem{{a}} Some Author, Some Title, 2020.
\end{{thebibliography}}
"""
_EXTRACTION_HASH = "e" * 64


def _paper_input(latex: str) -> tuple[CardBuildInput, ExtractionRecord, str]:
    version_id = str(uuid4())
    extraction = extract_latex(
        version_id, "a" * 64, "b" * 64, latex, "2026-01-01T00:00:00.000000Z"
    )
    canonical = normalize_text(latex)
    passages = chunk_passages(
        extraction, canonical, _EXTRACTION_HASH, _WhitespaceTokenizer()
    )
    build_input = _base_input(
        paper_version_id=version_id,
        passage_coverage="complete",
        passage_count=len(passages),
        extraction_hash=_EXTRACTION_HASH,
        passages=passages,
    )
    return build_input, extraction, canonical


def _sections_block(text: str) -> str:
    return next(block for block in text.split("\n\n") if block.startswith("# Sections"))


def test_render_card_maps_the_fixture_paper_sections_in_order() -> None:
    build_input, extraction, canonical = _paper_input(_PAPER)
    text = render_card(assemble_card(build_input))
    assert _sections_block(text) == "\n".join(
        [
            "# Sections",
            "- Abstract: passages 1-1 (1)",
            "- Introduction: passages 2-4 (3)",
            "- Limitations: passages 5-5 (1)",
            "- Future work: passages 6-6 (1)",
        ]
    )
    assert any(
        block.section_path == ("References",) and not block.included_in_passages
        for block in extraction.blocks
    )
    assert "- References" not in text
    assert "Some Author" not in text

    ordered = sorted(
        build_input.passages, key=lambda p: (p.section_order, p.passage_order)
    )
    limitations = ordered[5 - 1 : 5]
    assert {passage.section_path for passage in limitations} == {("Limitations",)}
    read = render_section_text(
        blocks=extraction.blocks,
        canonical_text=canonical,
        section_path=limitations[0].section_path,
        paper_version_id=build_input.paper_version_id,
        extraction_hash=_EXTRACTION_HASH,
        tokenizer=_WhitespaceTokenizer(),
    )
    assert "fails on scanned pages" in read.text
    assert all(p.section_path[0] == "Introduction" for p in ordered[1:4])


def test_render_card_says_in_one_line_when_a_paper_has_no_sections() -> None:
    build_input, _, _ = _paper_input("Just plain prose, no markup.")
    assert build_input.passage_count == 1
    text = render_card(assemble_card(build_input))
    assert _sections_block(text) == "# Sections\n(no section structure)"


def test_render_card_counts_the_sections_past_the_first_forty() -> None:
    latex = "".join(
        f"\\section{{Part {index}}}\nWords of part {index}.\n" for index in range(43)
    )
    build_input, _, _ = _paper_input(latex)
    lines = _sections_block(render_card(assemble_card(build_input))).split("\n")
    assert len(lines) == 1 + 40 + 1
    assert lines[40] == "- Part 39: passages 40-40 (1)"
    assert lines[-1] == "(and 3 more sections)"


def test_render_card_grows_only_by_the_section_map() -> None:
    build_input, _, _ = _paper_input(_PAPER)
    mapped = render_card(assemble_card(build_input))
    unmapped = render_card(assemble_card(replace(build_input, passages=())))
    map_block = _sections_block(mapped)
    assert mapped.replace(map_block, "# Sections\n(no section structure)") == unmapped
    assert len(mapped.splitlines()) - len(unmapped.splitlines()) == (
        len(map_block.splitlines()) - 2
    )
