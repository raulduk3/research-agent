from __future__ import annotations

from collections.abc import Sequence

import pytest

from research_agent.agents.budgets import CONTEXT_TOKENS_LIMIT, BudgetExhausted
from research_agent.agents.messages import (
    MAX_SYSTEM_PROMPT_CHARS,
    Message,
    SnapshotDescription,
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


def test_build_initial_message_holds_only_shard_budgets_and_snapshot() -> None:
    message = build_initial_message(
        paper_ids=["paper-a", "paper-b"],
        questions=[{"question_id": "q-1"}],
        budgets={"tool_calls": 40},
        snapshot=SNAPSHOT,
    )
    assert message.role == "user"
    content = message.body["content"]
    assert set(content) == {"paper_ids", "questions", "budgets", "snapshot"}
    assert content["paper_ids"] == ["paper-a", "paper-b"]
    assert content["snapshot"] == SNAPSHOT.to_dict()
    # No paper card, abstract or other content leaks into the first message.
    serialized = str(content)
    assert "abstract" not in serialized
    assert "card" not in serialized


def test_build_initial_message_rejects_duplicate_paper_ids() -> None:
    with pytest.raises(ContractValidationError):
        build_initial_message(
            paper_ids=["paper-a", "paper-a"],
            questions=[],
            budgets={},
            snapshot=SNAPSHOT,
        )


def test_build_initial_message_rejects_no_papers() -> None:
    with pytest.raises(ContractValidationError):
        build_initial_message(paper_ids=[], questions=[], budgets={}, snapshot=SNAPSHOT)


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
