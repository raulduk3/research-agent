"""Hard per-run resource budgets, enforced by the loop and outside the agent's control.

Decision 0022 rescales AG-12's per-run ceilings for a run bound to one
paper rather than a twenty-paper shard: 6 model calls, 12 total tool calls
(including refusals), 3 deep reads, 6 images, 4096 generated tokens and 5
minutes wall time, plus a 32768-token context ceiling used to size each
model-call reservation and a 64000-token ``max_tokens_per_run`` ceiling on
cumulative context and generated tokens across the whole run. These are
launch constants, not a per-genome setting; ``RunBudget`` enforces exactly
them (AG-12, TDD-3.1.52).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MODEL_CALLS_LIMIT = 6
TOOL_CALLS_LIMIT = 12
DEEP_READS_LIMIT = 3
IMAGES_LIMIT = 6
CONTEXT_TOKENS_LIMIT = 32768
GENERATION_TOKENS_LIMIT = 4096
WALL_TIME_SECONDS_LIMIT = 5 * 60
MAX_RESERVATION_TOKENS = 2048
MAX_TOKENS_PER_RUN_LIMIT = 64000
RETRIES_LIMIT = 1


class BudgetExhausted(Exception):
    """Raised when a run's usage would exceed one of its hard budgets.

    ``budget`` names the exhausted ceiling; the loop ends the run there
    with no further model or tool call (AG-12, AG-15).
    """

    def __init__(self, budget: str) -> None:
        super().__init__(f"budget exhausted: {budget}")
        self.budget = budget


@dataclass(slots=True)
class RunBudget:
    """Monotonically increasing usage against a run's hard resource ceilings.

    Nothing the agent model does raises or resets a ceiling: every
    ``charge_*``/``reserve_*`` method only ever increases recorded usage,
    and each raises :class:`BudgetExhausted` rather than letting usage pass
    its fixed limit.
    """

    model_calls: int = 0
    tool_calls: int = 0
    deep_reads: int = 0
    images: int = 0
    generation_tokens: int = 0
    elapsed_seconds: float = 0.0
    cumulative_tokens: int = 0
    retries: int = 0

    def remaining(self) -> dict[str, int]:
        """The remaining amount against each ceiling, for AG-27's envelope."""

        return {
            "model_calls": MODEL_CALLS_LIMIT - self.model_calls,
            "tool_calls": TOOL_CALLS_LIMIT - self.tool_calls,
            "deep_reads": DEEP_READS_LIMIT - self.deep_reads,
            "images": IMAGES_LIMIT - self.images,
            "generation_tokens": GENERATION_TOKENS_LIMIT - self.generation_tokens,
            "wall_time_seconds": max(
                0, WALL_TIME_SECONDS_LIMIT - int(self.elapsed_seconds)
            ),
            "max_tokens_per_run": MAX_TOKENS_PER_RUN_LIMIT - self.cumulative_tokens,
            "retries": RETRIES_LIMIT - self.retries,
        }

    def reserve_model_call(self, context_tokens: int) -> int:
        """Reserve a generation allowance before sending a model request.

        Reserves ``min(2048, remaining generation allowance)`` within the
        32768-token context ceiling, and charges ``context_tokens`` (the
        full resent conversation) against the run's 64000-token
        ``max_tokens_per_run`` ceiling (TDD-3.1.52). Raises
        :class:`BudgetExhausted` for a run with no model calls, no
        generation allowance, a conversation that no longer fits the
        context ceiling, or one that would exceed the cumulative ceiling.
        """

        if self.model_calls >= MODEL_CALLS_LIMIT:
            raise BudgetExhausted("model_calls")
        if context_tokens >= CONTEXT_TOKENS_LIMIT:
            raise BudgetExhausted("context_tokens")
        if self.cumulative_tokens + context_tokens > MAX_TOKENS_PER_RUN_LIMIT:
            self.cumulative_tokens = MAX_TOKENS_PER_RUN_LIMIT
            raise BudgetExhausted("max_tokens_per_run")
        remaining_generation = GENERATION_TOKENS_LIMIT - self.generation_tokens
        if remaining_generation <= 0:
            raise BudgetExhausted("generation_tokens")
        reservation = min(
            MAX_RESERVATION_TOKENS,
            remaining_generation,
            CONTEXT_TOKENS_LIMIT - context_tokens,
            MAX_TOKENS_PER_RUN_LIMIT - self.cumulative_tokens - context_tokens,
        )
        if reservation <= 0:
            raise BudgetExhausted("context_tokens")
        self.model_calls += 1
        self.cumulative_tokens += context_tokens
        return reservation

    def charge_generation_tokens(self, generated_tokens: int) -> None:
        if generated_tokens < 0:
            raise ValueError("generated_tokens must not be negative")
        if self.generation_tokens + generated_tokens > GENERATION_TOKENS_LIMIT:
            self.generation_tokens = GENERATION_TOKENS_LIMIT
            raise BudgetExhausted("generation_tokens")
        if self.cumulative_tokens + generated_tokens > MAX_TOKENS_PER_RUN_LIMIT:
            self.cumulative_tokens = MAX_TOKENS_PER_RUN_LIMIT
            raise BudgetExhausted("max_tokens_per_run")
        self.generation_tokens += generated_tokens
        self.cumulative_tokens += generated_tokens

    def charge_retry(self) -> None:
        """Charge one retry of an explicitly non-executed 429/503 request.

        Only one retry is permitted per run, and it fits the same deadline
        as any other call (TDD-3.1.52); the caller is responsible for the
        five-second wait before retrying.
        """

        if self.retries >= RETRIES_LIMIT:
            raise BudgetExhausted("retries")
        self.retries += 1

    def charge_tool_call(self) -> None:
        """Charge one tool attempt, refused calls included (TDD-3.1.52)."""

        if self.tool_calls >= TOOL_CALLS_LIMIT:
            raise BudgetExhausted("tool_calls")
        self.tool_calls += 1

    def charge_deep_read(self) -> None:
        if self.deep_reads >= DEEP_READS_LIMIT:
            raise BudgetExhausted("deep_reads")
        self.deep_reads += 1

    def charge_images(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must not be negative")
        if self.images + count > IMAGES_LIMIT:
            raise BudgetExhausted("images")
        self.images += count

    def charge_elapsed(self, elapsed_seconds: float) -> None:
        """Record wall-clock time elapsed since the run started.

        ``elapsed_seconds`` is the total elapsed since the run started, not
        an increment, so a clock that goes backward cannot lower recorded
        usage.
        """

        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must not be negative")
        self.elapsed_seconds = max(self.elapsed_seconds, elapsed_seconds)
        if self.elapsed_seconds >= WALL_TIME_SECONDS_LIMIT:
            raise BudgetExhausted("wall_time_seconds")


def attach_remaining(
    response: dict[str, Any],
    budget: RunBudget,
    *,
    context_tokens: int,
) -> dict[str, Any]:
    """Attach the run's remaining budgets to a tool response (AG-27).

    Computed after charging the attempt that produced ``response``, from
    the committed usage recorded on ``budget`` -- never from a
    caller-supplied counter. ``context_tokens`` is the conversation's
    current size, which is reported separately because it can grow, unlike
    the consumable allowances that only ever decrease within a run.
    """

    return {
        **response,
        "remaining_budgets": budget.remaining(),
        "context_tokens": context_tokens,
    }
