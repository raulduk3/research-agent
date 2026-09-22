"""Canonical conversation assembly: system prompt, first message, request materialization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from research_agent.agents.budgets import CONTEXT_TOKENS_LIMIT, BudgetExhausted
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
)

MAX_SYSTEM_PROMPT_CHARS = 16000

#: The exclusion-state vocabulary of AG-22/AG-23 (TDD-3.1.69, TDD-3.1.70):
#: naming one of these actions in a prompt would let the agent's own text
#: read as if it controlled its run's exclusion state.
EXCLUSION_ACTION_TERMS = (
    "run_quarantined",
    "configuration_quarantined",
    "authority_revoked",
    "quarantine",
    "purge",
)


@dataclass(frozen=True, slots=True)
class Message:
    """One canonical conversation message.

    ``body`` holds every wire field beyond ``role`` (for example ``content``
    for a plain turn, or ``tool_call_id`` and ``content`` for a tool
    response) exactly as the pinned transport would serialize them.
    """

    role: str
    body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, **self.body}


TokenCounter = Callable[[Sequence[Message]], int]


@dataclass(frozen=True, slots=True)
class SnapshotDescription:
    """The frozen snapshot's identity, as named in a run's initial message."""

    snapshot_hash: str
    sealed_at: str
    paper_count: int

    def __post_init__(self) -> None:
        validate_sha256(self.snapshot_hash)
        validate_utc_instant(self.sealed_at)
        validate_non_negative_int(self.paper_count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_hash": self.snapshot_hash,
            "sealed_at": self.sealed_at,
            "paper_count": self.paper_count,
        }


def assemble_system_prompt(prompt: str) -> Message:
    """Build the run's system message from the genome's immutable prompt text (AG-24).

    Accepts only the prompt text itself; it never reads exclusion events,
    score reports or future outcome projections. Prompt text naming an
    exclusion action is rejected rather than edited.
    """

    if not isinstance(prompt, str) or not prompt:
        raise ContractValidationError("prompt must be nonempty text")
    if len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
        raise ContractValidationError(
            f"prompt must be at most {MAX_SYSTEM_PROMPT_CHARS} characters"
        )
    lowered = prompt.lower()
    for term in EXCLUSION_ACTION_TERMS:
        if term in lowered:
            raise ContractValidationError(
                f"prompt must not mention the exclusion-action term {term!r}"
            )
    return Message("system", {"content": prompt})


def build_initial_message(
    *,
    paper_ids: Sequence[str],
    questions: Sequence[dict[str, Any]],
    budgets: dict[str, int],
    snapshot: SnapshotDescription,
) -> Message:
    """Build the run's first message: shard, budgets and snapshot description only (AG-25).

    No paper card, abstract, precomputed value or neighbor list is placed
    here; every paper card that later reaches the conversation is one the
    agent retrieved through its own tool call.
    """

    if not paper_ids:
        raise ContractValidationError(
            "build_initial_message requires at least one paper id"
        )
    if len(set(paper_ids)) != len(paper_ids):
        raise ContractValidationError("paper_ids must be distinct")
    body = {
        "paper_ids": list(paper_ids),
        "questions": [dict(question) for question in questions],
        "budgets": dict(budgets),
        "snapshot": snapshot.to_dict(),
    }
    return Message("user", {"content": body})


def prepare_request(
    messages: Sequence[Message], *, count_tokens: TokenCounter
) -> tuple[bytes, int]:
    """Materialize the full ordered conversation for one model request (AG-28).

    Every earlier message is included byte-equivalently in the order it
    was produced; the caller only ever appends a new message, never drops,
    shortens or reorders one. Raises :class:`BudgetExhausted` for
    ``context_tokens`` when the conversation no longer fits the context
    ceiling, rather than compacting it -- the run ends there exactly as it
    would at any other budget exhaustion (AG-15).
    """

    ordered = list(messages)
    context_tokens = count_tokens(ordered)
    if context_tokens >= CONTEXT_TOKENS_LIMIT:
        raise BudgetExhausted("context_tokens")
    payload = canonical_json([message.to_dict() for message in ordered])
    return payload, context_tokens
