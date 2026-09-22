from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.tools import ToolRequest

PAPER_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_PAPER_ID = "123e4567-e89b-42d3-a456-426614174001"
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174002"
EVIDENCE_HASH = "b" * 64


def _query_cards(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "paper_ids": None,
        "query": None,
        "mode": None,
        "paper_id": None,
        "limit": None,
    }
    base.update(overrides)
    return base


def test_query_cards_accepts_paper_ids_lookup() -> None:
    request = ToolRequest.parse(
        "query_cards", _query_cards(paper_ids=[PAPER_ID, OTHER_PAPER_ID])
    )
    assert request.arguments == {
        "kind": "lookup",
        "paper_ids": (PAPER_ID, OTHER_PAPER_ID),
    }


def test_query_cards_rejects_six_paper_ids() -> None:
    ids = [PAPER_ID] + [f"123e4567-e89b-42d3-a456-42661417{n:04d}" for n in range(5)]
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(paper_ids=ids))


def test_query_cards_rejects_duplicate_paper_ids() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(paper_ids=[PAPER_ID, PAPER_ID]))


def test_query_cards_rejects_both_paper_ids_and_query() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse(
            "query_cards", _query_cards(paper_ids=[PAPER_ID], query="graph neural nets")
        )


def test_query_cards_rejects_neither_paper_ids_nor_query() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards())


def test_query_cards_rejects_query_fields_alongside_paper_ids() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(paper_ids=[PAPER_ID], limit=3))


def test_query_cards_search_defaults_mode_and_limit() -> None:
    request = ToolRequest.parse("query_cards", _query_cards(query="graph neural nets"))
    assert request.arguments == {
        "kind": "search",
        "query": "graph neural nets",
        "mode": "overview",
        "paper_id": None,
        "limit": 5,
    }


def test_query_cards_search_accepts_passages_mode_and_filter() -> None:
    request = ToolRequest.parse(
        "query_cards",
        _query_cards(
            query="graph neural nets", mode="passages", paper_id=PAPER_ID, limit=2
        ),
    )
    assert request.arguments["mode"] == "passages"
    assert request.arguments["paper_id"] == PAPER_ID
    assert request.arguments["limit"] == 2


def test_query_cards_rejects_unknown_mode_and_over_limit() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(query="x", mode="fulltext"))
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(query="x", limit=6))
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(query="x", limit=True))


def test_query_cards_rejects_empty_query_and_extra_field() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", _query_cards(query=""))
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("query_cards", {**_query_cards(query="x"), "extra": 1})


def test_neighbors_defaults_limit_and_rejects_bad_paper_id() -> None:
    request = ToolRequest.parse("neighbors", {"paper_id": PAPER_ID, "limit": None})
    assert request.arguments == {"paper_id": PAPER_ID, "limit": 5}
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("neighbors", {"paper_id": "not-a-uuid", "limit": None})
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("neighbors", {"paper_id": PAPER_ID, "limit": 0})


def test_graph_defaults_direction_and_limit() -> None:
    request = ToolRequest.parse(
        "graph", {"paper_id": PAPER_ID, "direction": None, "limit": None}
    )
    assert request.arguments == {
        "paper_id": PAPER_ID,
        "direction": "references",
        "limit": 20,
    }


def test_graph_rejects_unknown_direction_and_over_limit() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse(
            "graph", {"paper_id": PAPER_ID, "direction": "coauthors", "limit": None}
        )
    with pytest.raises(ContractValidationError):
        ToolRequest.parse(
            "graph", {"paper_id": PAPER_ID, "direction": None, "limit": 21}
        )


def _deep_read(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "paper_id": PAPER_ID,
        "section_id": None,
        "pages": None,
        "next_span": None,
    }
    base.update(overrides)
    return base


def test_deep_read_accepts_exactly_one_variant() -> None:
    section = ToolRequest.parse("deep_read", _deep_read(section_id="Abstract"))
    assert section.arguments == {
        "paper_id": PAPER_ID,
        "kind": "section",
        "section_id": "Abstract",
    }
    pages = ToolRequest.parse("deep_read", _deep_read(pages=[1, 2]))
    assert pages.arguments == {"paper_id": PAPER_ID, "kind": "pages", "pages": (1, 2)}
    next_span = ToolRequest.parse("deep_read", _deep_read(next_span="span-2"))
    assert next_span.arguments == {
        "paper_id": PAPER_ID,
        "kind": "next_span",
        "next_span": "span-2",
    }


def test_deep_read_rejects_no_variant_and_multiple_variants() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("deep_read", _deep_read())
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("deep_read", _deep_read(section_id="Abstract", pages=[1]))


def test_deep_read_rejects_three_pages_and_unordered_pages() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("deep_read", _deep_read(pages=[1, 2, 3]))
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("deep_read", _deep_read(pages=[2, 1]))
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("deep_read", _deep_read(pages=[1, 1]))


def test_submit_parses_claims_through_the_shared_validator() -> None:
    claims = [
        {
            "kind": "forecast",
            "question_id": QUESTION_ID,
            "evidence_hashes": [EVIDENCE_HASH],
            "confidence": 0.5,
        }
    ]
    request = ToolRequest.parse("submit", {"claims": claims})
    assert request.arguments == {"claims": claims}


def test_unknown_tool_name_is_rejected_before_any_handler_runs() -> None:
    with pytest.raises(ContractValidationError):
        ToolRequest.parse("browse", {})
