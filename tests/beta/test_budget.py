"""Budget governance: the month's state, the four modes and admission."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from research_agent.beta import spec as specs
from research_agent.beta.budget import (
    admit_paid_chat,
    admit_run,
    banded,
    budget_state,
    estimate_run_micros,
    fit_run_to_cap,
    levers_from,
    price_micros,
)
from research_agent.beta.costs import record_cost_receipt
from research_agent.beta.errors import Conflict, Invalid, Unavailable
from tests.beta.helpers import PROVIDER, FakeClock

# September has thirty days: fifty dollars a month is 1,666,666 micro-dollars a day.
SOFT = 50_000_000 // 30
HARD = 2 * SOFT


def _spend(
    db: sqlite3.Connection,
    clock: FakeClock,
    micros: int,
    island: str = "cs",
    settled: bool = True,
) -> None:
    record_cost_receipt(
        db,
        action="model_call",
        owner_kind="run",
        owner_id="R-test",
        parent_kind="paper",
        parent_id="P-test",
        unit_type="tokens",
        quantity=1,
        amount_micros=micros,
        now=clock(),
        island_id=island,
        settled=settled,
    )


def _state(db: sqlite3.Connection, clock: FakeClock, configured: bool = True):
    return budget_state(db, specs.current_spec(db)[1], clock(), configured)


def test_the_default_budget_is_fifty_dollars_with_derived_daily_limits(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    state = _state(db, clock)

    assert state.levers.monthly_budget_micros == 50_000_000
    assert (state.daily_soft_micros, state.daily_hard_micros) == (SOFT, HARD)
    assert state.plan.mode == "normal" and state.plan.runs_allowed
    assert state.compact("cs")["island"]["share"] == 0.4
    assert state.islands["cs"].daily_allowance_micros == int(HARD * 0.4)


def test_month_to_date_counts_settled_spend_and_projects_the_month_end(
    db: sqlite3.Connection,
) -> None:
    clock = FakeClock(datetime(2026, 9, 3, 9, 0, tzinfo=UTC))
    _spend(db, clock, 300_000)
    clock.advance(days=1)
    _spend(db, clock, 500_000)
    _spend(db, clock, 100_000, settled=False)
    # A receipt from the month before is outside this month's totals.
    record_august = FakeClock(datetime(2026, 8, 31, 23, 0, tzinfo=UTC))
    _spend(db, record_august, 9_000_000)
    clock.advance(days=1)

    state = _state(db, clock)

    assert state.month_settled_micros == 800_000
    assert state.month_unsettled_micros == 100_000
    assert state.month_unsettled_count == 1
    assert state.today_micros == 0
    # Day 5 of 30: 900,000 so far, a daily mean of 180,000, 25 days left.
    assert state.projected_month_micros == 900_000 + 180_000 * 25
    assert state.full()["projected_over_budget"] is False


def test_soft_mode_cuts_agents_islands_calls_and_low_priority_islands(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    wide = specs.patch_budget(
        spec, {"agents_per_paper": 3, "islands_per_paper": 3, "papers_per_pass": 10}
    )
    specs.apply_spec(db, wide, actor="operator", now=clock())
    assert _state(db, clock).plan.agents_per_paper == 3
    _spend(db, clock, SOFT)

    state = _state(db, clock)
    plan = state.plan

    assert plan.mode == "conserving" and plan.runs_allowed and plan.paid_chat_allowed
    assert (plan.agents_per_paper, plan.islands_per_paper) == (1, 1)
    assert plan.max_tool_calls == 3 and plan.max_model_calls == 2
    assert plan.papers_per_pass == 5
    general = specs.find_island(specs.current_spec(db)[1], "general")
    with pytest.raises(Conflict, match="island_paused_by_budget"):
        admit_run(state, general)


def test_hard_mode_stops_runs_and_paid_chat_and_keeps_metadata_ingestion(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _spend(db, clock, HARD)

    state = _state(db, clock)

    assert state.plan.mode == "hard_stop"
    assert state.plan.runs_refusal == "daily_hard_budget_reached"
    assert state.plan.ingest_mode == "metadata_only"
    assert admit_paid_chat(state, 100) == "budget_mode_hard_stop"
    cs = specs.find_island(specs.current_spec(db)[1], "cs")
    with pytest.raises(Conflict, match="daily_hard_budget_reached"):
        admit_run(state, cs)
    # The next day's spend starts from zero again.
    clock.advance(days=1)
    assert _state(db, clock).plan.mode == "normal"


def test_monthly_mode_stops_paid_work_for_the_rest_of_the_month(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _spend(db, clock, 50_000_000)
    clock.advance(days=2)

    state = _state(db, clock)

    assert state.plan.mode == "stored_data_only"
    assert state.plan.runs_refusal == "monthly_budget_reached"
    assert not state.plan.paid_chat_allowed
    assert state.compact()["runs_allowed"] is False


def test_unsettled_spend_is_held_against_the_budget(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _spend(db, clock, HARD, settled=False)

    state = _state(db, clock)

    assert state.compact()["month_to_date_micros"] == 0
    assert state.plan.mode == "hard_stop"


def test_an_island_at_its_share_is_refused_while_another_is_admitted(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    # quant holds a quarter of the daily hard budget; this stays under soft.
    _spend(db, clock, int(HARD * 0.25), island="quant")
    state = _state(db, clock)
    spec = specs.current_spec(db)[1]

    assert state.plan.mode == "normal"
    with pytest.raises(Conflict, match="island_over_share"):
        admit_run(state, specs.find_island(spec, "quant"))
    admit_run(state, specs.find_island(spec, "cs"))


def test_a_budget_line_stops_runs_once_reached_and_not_before(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    """A run under the line starts whatever it may cost; what it spends is gone
    from the runs after it. The prohibited alternative is refusing a run whose
    worst-case estimate would cross a line nothing has reached."""
    _spend(db, clock, int(HARD * 0.25) - 1, island="quant")
    state = _state(db, clock)
    spec = specs.current_spec(db)[1]
    quant = specs.find_island(spec, "quant")

    # One micro-dollar of room admits a run however large its estimate.
    admit_run(state, quant)
    assert state.runs_remaining_today("quant") == 1

    # The run went far past the island's share: the next one is refused.
    _spend(db, clock, 400_000, island="quant")
    state = _state(db, clock)
    assert state.islands["quant"].over_share
    assert state.runs_remaining_today("quant") == 0
    with pytest.raises(Conflict, match="island_over_share"):
        admit_run(state, quant)
    # The swarm as a whole stops the same way, at the daily hard budget.
    _spend(db, clock, HARD, island="cs")
    with pytest.raises(Conflict, match="daily_hard_budget_reached"):
        admit_run(_state(db, clock), specs.find_island(spec, "cs"))


def test_paused_islands_and_the_pause_lever_refuse_runs(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    _, spec = specs.current_spec(db)
    proposed = specs.patch_island(spec, "cs", {"paused": True})
    proposed = specs.patch_budget(proposed, {"pause_new_runs": False})
    specs.apply_spec(db, proposed, actor="operator", now=clock())
    state = _state(db, clock)
    spec = specs.current_spec(db)[1]

    with pytest.raises(Conflict, match="island_paused"):
        admit_run(state, specs.find_island(spec, "cs"))

    paused = specs.patch_budget(spec, {"pause_new_runs": True})
    specs.apply_spec(db, paused, actor="operator", now=clock())
    assert _state(db, clock).plan.runs_refusal == "runs_paused"


def test_without_a_model_provider_runs_are_unavailable(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    state = _state(db, clock, configured=False)
    cs = specs.find_island(specs.current_spec(db)[1], "cs")

    assert state.plan.runs_refusal == "model_provider_not_configured"
    with pytest.raises(Unavailable):
        admit_run(state, cs)
    assert admit_paid_chat(state, 100) == "model_provider_not_configured"


def test_the_run_estimate_is_the_worst_case_and_the_cap_cuts_model_calls() -> None:
    # 0.25 USD in and 1.25 USD out per million tokens.
    assert price_micros(PROVIDER, 1_000, 200) == 500
    one = estimate_run_micros(PROVIDER, 500, 1, 900)
    assert one == (500 + 500) // 4 + 900 * 5 // 4
    four = estimate_run_micros(PROVIDER, 500, 4, 900)
    assert four > 4 * one

    calls, estimate = fit_run_to_cap(PROVIDER, 500, 4, 900, cap_micros=four - 1)
    assert calls == 3 and estimate <= four - 1
    # A cap under one call still gets its reading: one call, estimated over the cap.
    assert fit_run_to_cap(PROVIDER, 500, 4, 900, cap_micros=one - 1) == (1, one)


def test_the_band_is_a_share_of_each_limit_and_a_lever_like_any_other(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    assert banded(4, 50) == 6
    assert banded(6, 50) == 9
    assert banded(50_000, 50) == 75_000
    assert banded(3, 0) == 3
    assert banded(1, 10) == 2

    assert _state(db, clock).plan.band_percent == 50
    _, spec = specs.current_spec(db)
    specs.apply_spec(
        db, specs.patch_budget(spec, {"band_percent": 0}), actor="operator", now=clock()
    )
    assert _state(db, clock).plan.band_percent == 0
    with pytest.raises(Invalid, match="band_percent"):
        levers_from({"band_percent": -1})


def test_the_estimate_holds_room_for_the_submission_retry() -> None:
    plain = estimate_run_micros(PROVIDER, 500, 4, 2500, 4000)
    with_retry = estimate_run_micros(PROVIDER, 500, 4, 2500, 4000, final_calls=2)

    # One more call at the submission's output, carrying the whole history.
    assert with_retry > plain
    assert with_retry - plain >= price_micros(PROVIDER, 500, 4000)
    # With no separate submission allowance there is nothing to retry into.
    assert estimate_run_micros(PROVIDER, 500, 4, 900, final_calls=2) == (
        estimate_run_micros(PROVIDER, 500, 4, 900)
    )


def test_a_paid_chat_answer_over_its_cap_is_refused(
    db: sqlite3.Connection, clock: FakeClock
) -> None:
    state = _state(db, clock)

    assert admit_paid_chat(state, state.levers.per_chat_max_micros) is None
    assert (
        admit_paid_chat(state, state.levers.per_chat_max_micros + 1)
        == "chat_estimate_over_cap"
    )


def test_levers_are_validated() -> None:
    assert levers_from({"daily_soft_micros": None}).daily_soft_micros is None
    for doc, field in (
        ({"papers_per_pass": 0}, "budget.papers_per_pass"),
        ({"max_model_calls": "4"}, "budget.max_model_calls"),
        ({"pause_new_runs": 1}, "budget.pause_new_runs"),
        ({"surprise": 1}, "budget.surprise"),
        ({"daily_soft_micros": 10, "daily_hard_micros": 5}, "budget.daily_hard_micros"),
    ):
        with pytest.raises(Invalid) as refused:
            levers_from(doc)
        assert refused.value.field == field


def test_default_activity_caps_preserve_explicit_operator_limits() -> None:
    defaults = levers_from({})
    assert (
        defaults.papers_per_pass,
        defaults.max_runs_per_day,
        defaults.runs_per_island_per_hour,
    ) == (4, 120, 6)
    configured = levers_from(
        {"papers_per_pass": 1, "max_runs_per_day": 25, "runs_per_island_per_hour": 1}
    )
    assert (
        configured.papers_per_pass,
        configured.max_runs_per_day,
        configured.runs_per_island_per_hour,
    ) == (1, 25, 1)
    assert configured.monthly_budget_micros == 50_000_000
