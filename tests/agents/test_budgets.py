from __future__ import annotations

import pytest

from research_agent.agents.budgets import (
    ASK_CALLS_LIMIT,
    CONTEXT_TOKENS_LIMIT,
    DEEP_READS_LIMIT,
    GENERATION_TOKENS_LIMIT,
    IMAGES_LIMIT,
    MAX_RESERVATION_TOKENS,
    MAX_TOKENS_PER_RUN_LIMIT,
    MODEL_CALLS_LIMIT,
    RETRIES_LIMIT,
    TOOL_CALLS_LIMIT,
    WALL_TIME_SECONDS_LIMIT,
    BudgetExhausted,
    RunBudget,
    attach_remaining,
)


def test_fresh_budget_reports_full_remaining() -> None:
    budget = RunBudget()
    assert budget.remaining() == {
        "model_calls": MODEL_CALLS_LIMIT,
        "tool_calls": TOOL_CALLS_LIMIT,
        "deep_reads": DEEP_READS_LIMIT,
        "images": IMAGES_LIMIT,
        "ask_calls": ASK_CALLS_LIMIT,
        "generation_tokens": GENERATION_TOKENS_LIMIT,
        "wall_time_seconds": WALL_TIME_SECONDS_LIMIT,
        "max_tokens_per_run": MAX_TOKENS_PER_RUN_LIMIT,
        "retries": RETRIES_LIMIT,
    }


def test_a_run_pays_for_four_asks_and_not_a_fifth() -> None:
    budget = RunBudget()
    for _ in range(4):
        budget.charge_ask()
    assert ASK_CALLS_LIMIT == 4
    assert budget.remaining()["ask_calls"] == 0
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_ask()
    assert excinfo.value.budget == "ask_calls"
    assert budget.ask_calls == 4


def test_reserve_model_call_caps_at_max_reservation() -> None:
    budget = RunBudget()
    reservation = budget.reserve_model_call(context_tokens=0)
    assert reservation == MAX_RESERVATION_TOKENS
    assert budget.model_calls == 1


def test_reserve_model_call_shrinks_reservation_near_generation_ceiling() -> None:
    budget = RunBudget(generation_tokens=GENERATION_TOKENS_LIMIT - 10)
    reservation = budget.reserve_model_call(context_tokens=0)
    assert reservation == 10


def test_reserve_model_call_shrinks_reservation_near_context_ceiling() -> None:
    budget = RunBudget()
    reservation = budget.reserve_model_call(context_tokens=CONTEXT_TOKENS_LIMIT - 5)
    assert reservation == 5


def test_reserve_model_call_stops_at_the_model_calls_boundary() -> None:
    budget = RunBudget(model_calls=MODEL_CALLS_LIMIT)
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.reserve_model_call(context_tokens=0)
    assert excinfo.value.budget == "model_calls"


def test_reserve_model_call_rejects_a_full_context() -> None:
    budget = RunBudget()
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.reserve_model_call(context_tokens=CONTEXT_TOKENS_LIMIT)
    assert excinfo.value.budget == "context_tokens"


def test_reserve_model_call_rejects_a_zero_generation_allowance() -> None:
    budget = RunBudget(generation_tokens=GENERATION_TOKENS_LIMIT)
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.reserve_model_call(context_tokens=0)
    assert excinfo.value.budget == "generation_tokens"


def test_charge_generation_tokens_stops_at_the_boundary() -> None:
    budget = RunBudget(generation_tokens=GENERATION_TOKENS_LIMIT - 1)
    budget.charge_generation_tokens(1)
    assert budget.generation_tokens == GENERATION_TOKENS_LIMIT
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_generation_tokens(1)
    assert excinfo.value.budget == "generation_tokens"


def test_charge_tool_call_stops_at_the_boundary() -> None:
    budget = RunBudget(tool_calls=TOOL_CALLS_LIMIT - 1)
    budget.charge_tool_call()
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_tool_call()
    assert excinfo.value.budget == "tool_calls"


def test_charge_deep_read_stops_at_the_boundary() -> None:
    budget = RunBudget(deep_reads=DEEP_READS_LIMIT - 1)
    budget.charge_deep_read()
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_deep_read()
    assert excinfo.value.budget == "deep_reads"


def test_charge_images_stops_at_the_boundary() -> None:
    budget = RunBudget(images=IMAGES_LIMIT - 1)
    budget.charge_images(1)
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_images(1)
    assert excinfo.value.budget == "images"


def test_charge_elapsed_stops_at_the_boundary() -> None:
    budget = RunBudget()
    budget.charge_elapsed(WALL_TIME_SECONDS_LIMIT - 1)
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_elapsed(WALL_TIME_SECONDS_LIMIT)
    assert excinfo.value.budget == "wall_time_seconds"


def test_charge_elapsed_never_moves_backward() -> None:
    budget = RunBudget()
    budget.charge_elapsed(100.0)
    budget.charge_elapsed(50.0)
    assert budget.elapsed_seconds == 100.0


def test_remaining_never_increases_after_charges() -> None:
    budget = RunBudget()
    before = budget.remaining()
    budget.charge_tool_call()
    budget.charge_deep_read()
    budget.charge_images(2)
    budget.charge_generation_tokens(500)
    after = budget.remaining()
    for name in before:
        assert after[name] <= before[name]


def test_reserve_model_call_stops_at_the_max_tokens_per_run_boundary() -> None:
    budget = RunBudget(cumulative_tokens=MAX_TOKENS_PER_RUN_LIMIT - 10)
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.reserve_model_call(context_tokens=11)
    assert excinfo.value.budget == "max_tokens_per_run"


def test_reserve_model_call_charges_context_tokens_to_the_cumulative_ceiling() -> None:
    budget = RunBudget()
    budget.reserve_model_call(context_tokens=100)
    assert budget.cumulative_tokens == 100


def test_charge_generation_tokens_also_charges_the_cumulative_ceiling() -> None:
    budget = RunBudget(cumulative_tokens=MAX_TOKENS_PER_RUN_LIMIT - 1)
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_generation_tokens(2)
    assert excinfo.value.budget == "max_tokens_per_run"


def test_charge_retry_allows_exactly_one_retry() -> None:
    budget = RunBudget()
    budget.charge_retry()
    with pytest.raises(BudgetExhausted) as excinfo:
        budget.charge_retry()
    assert excinfo.value.budget == "retries"


def test_attach_remaining_reads_committed_usage_not_a_caller_counter() -> None:
    budget = RunBudget()
    budget.charge_tool_call()
    response = {"status": "ok", "data": {}}
    envelope = attach_remaining(response, budget, context_tokens=42)
    assert envelope["status"] == "ok"
    assert envelope["context_tokens"] == 42
    assert envelope["remaining_budgets"]["tool_calls"] == TOOL_CALLS_LIMIT - 1
    # The original response dict is untouched; attach_remaining returns a copy.
    assert "remaining_budgets" not in response
