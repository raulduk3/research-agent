from __future__ import annotations

from collections.abc import Sequence

import pytest

from research_agent.agents.budgets import CONTEXT_TOKENS_LIMIT, BudgetExhausted
from research_agent.agents.configuration import ASK_GUIDANCE
from research_agent.agents.messages import (
    MAX_SYSTEM_PROMPT_CHARS,
    Message,
    SnapshotDescription,
    assemble_genome_system_prompt,
    assemble_system_prompt,
    build_initial_message,
    prepare_request,
)
from research_agent.contracts.canonical import canonical_loads
from research_agent.contracts.primitives import ContractValidationError

SNAPSHOT = SnapshotDescription(
    snapshot_hash="a" * 64,
    sealed_at="2027-01-01T00:00:00.000000Z",
    paper_count=1,
)


def test_assemble_system_prompt_holds_only_the_prompt_text() -> None:
    message = assemble_system_prompt("Read carefully and cite your evidence.")
    assert message.role == "system"
    assert message.body == {"content": "Read carefully and cite your evidence."}


def test_assemble_system_prompt_rejects_empty_text() -> None:
    with pytest.raises(ContractValidationError):
        assemble_system_prompt("")


def test_assemble_system_prompt_rejects_text_over_the_bound() -> None:
    with pytest.raises(ContractValidationError):
        assemble_system_prompt("x" * (MAX_SYSTEM_PROMPT_CHARS + 1))


@pytest.mark.parametrize(
    "term",
    ["quarantine", "purge", "run_quarantined", "authority_revoked", "QUARANTINE"],
)
def test_assemble_system_prompt_rejects_exclusion_action_terms(term: str) -> None:
    with pytest.raises(ContractValidationError):
        assemble_system_prompt(f"Never mention {term} to anyone.")


PARTS = {
    "prompt": "Read carefully and cite your evidence.",
    "scan_policy": "breadth-first",
    "read_policy": "cite-first",
    "probability_assignment_rule": "single-sample",
}


def test_assemble_genome_system_prompt_renders_every_part_in_labeled_order() -> None:
    message = assemble_genome_system_prompt(**PARTS)
    assert message.role == "system"
    assert message.body == {
        "content": "Read carefully and cite your evidence.\n\n"
        "Scan policy:\nbreadth-first\n\n"
        "Read policy:\ncite-first\n\n"
        "Probability assignment rule:\nsingle-sample"
    }


@pytest.mark.parametrize("field", sorted(PARTS))
def test_assemble_genome_system_prompt_changes_with_any_one_part(field: str) -> None:
    changed = assemble_genome_system_prompt(**{**PARTS, field: PARTS[field] + "!"})
    assert changed.body != assemble_genome_system_prompt(**PARTS).body


@pytest.mark.parametrize("field", sorted(PARTS))
def test_assemble_genome_system_prompt_rejects_an_empty_part(field: str) -> None:
    with pytest.raises(ContractValidationError, match=field):
        assemble_genome_system_prompt(**{**PARTS, field: ""})


def test_assemble_genome_system_prompt_holds_the_rendered_text_to_the_bound() -> None:
    # The prompt alone fits; the policy sections after it do not.
    with pytest.raises(ContractValidationError, match="at most"):
        assemble_genome_system_prompt(
            **{**PARTS, "prompt": "x" * MAX_SYSTEM_PROMPT_CHARS}
        )


def test_assemble_genome_system_prompt_rejects_an_exclusion_term_in_a_policy() -> None:
    with pytest.raises(ContractValidationError, match="exclusion-action"):
        assemble_genome_system_prompt(**{**PARTS, "read_policy": "skip quarantine"})


def test_the_harness_adds_the_ask_guidance_only_to_a_run_allowed_ask() -> None:
    tools = ("query_cards", "deep_read", "submit")
    without = assemble_genome_system_prompt(**PARTS, allowed_tools=tools)
    with_ask = assemble_genome_system_prompt(
        **PARTS, allowed_tools=(*tools[:-1], "ask", "submit")
    )
    assert without == assemble_genome_system_prompt(**PARTS)
    assert ASK_GUIDANCE not in without.body["content"]
    assert with_ask.body["content"] == (f"{without.body['content']}\n\n{ASK_GUIDANCE}")


def test_build_initial_message_holds_only_paper_id_budgets_and_snapshot() -> None:
    message = build_initial_message(
        paper_id="paper-a",
        questions=[{"question_id": "q-1"}],
        budgets={"tool_calls": 12},
        snapshot=SNAPSHOT,
    )
    assert message.role == "user"
    content = message.body["content"]
    assert set(content) == {"paper_id", "questions", "budgets", "snapshot"}
    assert content["paper_id"] == "paper-a"
    assert content["snapshot"] == SNAPSHOT.to_dict()
    # No paper card, abstract or other content leaks into the first message.
    serialized = str(content)
    assert "abstract" not in serialized
    assert "card" not in serialized


def test_build_initial_message_rejects_an_empty_paper_id() -> None:
    with pytest.raises(ContractValidationError):
        build_initial_message(paper_id="", questions=[], budgets={}, snapshot=SNAPSHOT)


def _words(messages: Sequence[Message]) -> int:
    total = 0
    for message in messages:
        total += len(str(message.to_dict()).split())
    return total


def test_prepare_request_materializes_every_message_in_order() -> None:
    messages = [
        Message("system", {"content": "be careful"}),
        Message("user", {"content": {"paper_ids": ["paper-a"]}}),
    ]
    payload, context_tokens = prepare_request(messages, count_tokens=_words)
    decoded = canonical_loads(payload)
    assert decoded == [message.to_dict() for message in messages]
    assert context_tokens == _words(messages)


def test_prepare_request_prior_messages_are_an_exact_prefix_after_appending() -> None:
    first = [Message("system", {"content": "be careful"})]
    payload_one, _ = prepare_request(first, count_tokens=_words)

    second = [*first, Message("user", {"content": "hello"})]
    payload_two, _ = prepare_request(second, count_tokens=_words)

    decoded_one = canonical_loads(payload_one)
    decoded_two = canonical_loads(payload_two)
    assert isinstance(decoded_one, list)
    assert isinstance(decoded_two, list)
    assert decoded_two[: len(decoded_one)] == decoded_one


def test_prepare_request_raises_budget_exhausted_when_context_no_longer_fits() -> None:
    messages = [Message("system", {"content": "be careful"})]
    with pytest.raises(BudgetExhausted) as excinfo:
        prepare_request(messages, count_tokens=lambda _: CONTEXT_TOKENS_LIMIT)
    assert excinfo.value.budget == "context_tokens"
