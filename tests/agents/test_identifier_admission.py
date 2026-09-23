"""reject_paper_identifiers: no corpus paper's identifier in any genome part (AG-31)."""

from __future__ import annotations

import json

from research_agent.agents.admission import reject_paper_identifiers

CORPUS = ("2301.12345v1", "10.1000/xyz123")


def parts(**overrides: str) -> dict[str, str]:
    base = {
        "prompt": "read the paper closely",
        "scan_policy": "breadth first",
        "read_policy": "cite first",
        "probability_assignment_rule": "one sample",
    }
    base.update(overrides)
    return base


def test_a_clean_genome_is_admitted() -> None:
    assert reject_paper_identifiers(parts(), corpus_identifiers=CORPUS) == ()


def test_a_prompt_naming_a_paper_is_refused_and_names_the_part() -> None:
    result = reject_paper_identifiers(
        parts(prompt="Recall that 2301.12345v1 settled this."),
        corpus_identifiers=CORPUS,
    )
    assert result == ("prompt",)


def test_a_schema_field_description_naming_a_paper_is_refused() -> None:
    schema = json.dumps(
        {"claim": {"description": "as shown in 10.1000/xyz123, the effect holds"}}
    )
    result = reject_paper_identifiers(
        {**parts(), "output_schema": schema}, corpus_identifiers=CORPUS
    )
    assert result == ("output_schema",)


def test_every_offending_part_is_named() -> None:
    result = reject_paper_identifiers(
        parts(read_policy="see 10.1000/xyz123", scan_policy="start at 2301.12345v1"),
        corpus_identifiers=CORPUS,
    )
    assert set(result) == {"read_policy", "scan_policy"}


def test_an_identifier_outside_the_corpus_is_not_a_refusal() -> None:
    assert (
        reject_paper_identifiers(
            parts(prompt="see 9999.99999v1"), corpus_identifiers=CORPUS
        )
        == ()
    )


def test_an_empty_corpus_refuses_nothing() -> None:
    assert (
        reject_paper_identifiers(parts(prompt="2301.12345v1"), corpus_identifiers=())
        == ()
    )
