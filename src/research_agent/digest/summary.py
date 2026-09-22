"""Pinned summarizer: one reading per digest entry (EN-43, TDD-3.1.75).

After a digest is published, a leased job builds one entry's closed input
from its sealed claims and protected notes, then calls the pinned agent
model of TDD-3.1.37 once, with tools disabled, under a versioned system
prompt. This module owns the deterministic boundary of that call: closing
and hashing the input, sending the one request, and validating the reply
against EN-43's bound and naming refusal. Leasing, the leased job's own
retry rule, and persisting the resulting :class:`~research_agent.contracts
.summaries.Reading` through storage are a caller's concerns, not this
module's -- exactly as ``publish_digest`` (TDD-3.1.31) commits a manifest
without itself touching storage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.primitives import validate_utc_instant
from research_agent.contracts.summaries import (
    READING_LABEL,
    GenomeReading,
    Reading,
    build_summarizer_input,
    validate_reading_text,
)

__all__ = [
    "SUMMARIZER_CONTEXT_TOKENS_LIMIT",
    "SUMMARIZER_GENERATION_TOKENS_LIMIT",
    "SUMMARIZER_TIMEOUT_SECONDS",
    "SUMMARIZER_DAILY_SPEND_CAP_MICROS",
    "SummarizerResponse",
    "SummarizerModelClient",
    "UnsealedClaims",
    "SummarizerBudgetExhausted",
    "write_reading",
]

#: Appendix A: Launch profile, Summarizer (EN-43) -- one model call, sized
#: well below a run's own per-call ceilings (agents/budgets.py) because the
#: summarizer is not a run.
SUMMARIZER_CONTEXT_TOKENS_LIMIT = 16384
SUMMARIZER_GENERATION_TOKENS_LIMIT = 512
SUMMARIZER_TIMEOUT_SECONDS = 60
SUMMARIZER_DAILY_SPEND_CAP_MICROS = 1_000_000  # USD 1 per UTC day


class UnsealedClaims(Exception):
    """Raised for an entry whose genome claims are not yet sealed; no call is made."""


class SummarizerBudgetExhausted(Exception):
    """Raised when the call would exceed EN-43's bound; no reading is stored.

    ``budget`` names the exhausted ceiling, mirroring
    :class:`research_agent.agents.budgets.BudgetExhausted`.
    """

    def __init__(self, budget: str) -> None:
        super().__init__(f"summarizer budget exhausted: {budget}")
        self.budget = budget


@dataclass(frozen=True, slots=True)
class SummarizerResponse:
    """One summarizer call's plain-text reply, exactly as the client returned it.

    Distinct from ``research_agent.agents.loop.ModelResponse``: the run
    loop's client parses a JSON tool-call envelope, but the summarizer
    call has tools disabled and expects plain text back (Rules, #142).
    """

    text: str
    generated_tokens: int
    elapsed_seconds: float


class SummarizerModelClient(Protocol):
    """The pinned client of TDD-3.1.37, reached with no tool schemas declared."""

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> SummarizerResponse: ...


def write_reading(
    *,
    digest_entry_id: str,
    claims_sealed: bool,
    card_text: str,
    genome_readings: Sequence[GenomeReading],
    protected_notes: Sequence[str],
    contributing_run_ids: Sequence[str],
    client: SummarizerModelClient,
    system_prompt: str,
    model_provider: str,
    model_id: str,
    model_revision: str,
    context_tokens: int,
    already_read_this_week: bool,
    daily_spend_micros_before: int,
    reserved_spend_micros: int,
    created_at: str,
) -> Reading:
    """Build and validate one digest entry's reading (EN-43, TDD-3.1.75).

    Refuses before any model call for an entry whose claims are not
    sealed (:class:`UnsealedClaims`), for an entry already read this week,
    for a conversation that would not fit the summarizer's context
    ceiling, and for a reservation that would push the day's summarizer
    spend past its Appendix A sublimit (:class:`SummarizerBudgetExhausted`
    for the last three). The one call is then made with ``client``; a
    reply over the generation-token ceiling, over its wall-time ceiling,
    or failing :func:`~research_agent.contracts.summaries
    .validate_reading_text` (:class:`~research_agent.contracts.summaries
    .ReadingRefused`) yields no reading. ``contributing_run_ids`` names the
    runs whose protected notes were read, checked only against the reply
    text -- it is never part of the model's own input.
    """

    if not claims_sealed:
        raise UnsealedClaims(f"digest entry {digest_entry_id} claims are not sealed")
    if already_read_this_week:
        raise SummarizerBudgetExhausted("weekly_call_limit")
    if context_tokens >= SUMMARIZER_CONTEXT_TOKENS_LIMIT:
        raise SummarizerBudgetExhausted("context_tokens")
    if (
        daily_spend_micros_before + reserved_spend_micros
        > SUMMARIZER_DAILY_SPEND_CAP_MICROS
    ):
        raise SummarizerBudgetExhausted("daily_spend_micros")

    summarizer_input = build_summarizer_input(
        card_text=card_text,
        genome_readings=genome_readings,
        protected_notes=protected_notes,
    )
    prompt_hash = sha256_hex(system_prompt.encode("utf-8"))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": summarizer_input.to_dict()},
    ]

    response = client.complete(
        messages, max_generation_tokens=SUMMARIZER_GENERATION_TOKENS_LIMIT
    )
    if response.generated_tokens > SUMMARIZER_GENERATION_TOKENS_LIMIT:
        raise SummarizerBudgetExhausted("generation_tokens")
    if response.elapsed_seconds > SUMMARIZER_TIMEOUT_SECONDS:
        raise SummarizerBudgetExhausted("timeout_seconds")

    forbidden_hashes = [
        reading.genome_hash for reading in summarizer_input.genome_readings
    ]
    validated_text = validate_reading_text(
        response.text,
        forbidden_hashes=forbidden_hashes,
        forbidden_ids=contributing_run_ids,
    )

    return Reading(
        digest_entry_id=digest_entry_id,
        text=validated_text,
        label=READING_LABEL,
        model_provider=model_provider,
        model_id=model_id,
        model_revision=model_revision,
        prompt_hash=prompt_hash,
        input_hashes=summarizer_input.input_hashes(),
        created_at=validate_utc_instant(created_at),
    )
