"""Budget governance: what the month has cost and what may still be spent.

The levers are part of the editable swarm spec. From the receipts ledger this
module derives the month's state, picks one of four modes and turns the
levers into the plan the rest of the system obeys:

- ``normal``            below the daily soft budget: the levers as written.
- ``conserving``        at or above it: one agent and one island per paper,
                        half the tool and model calls, half the papers per
                        pass, low-priority islands paused.
- ``hard_stop``         at or above the daily hard budget: no new runs and no
                        paid chat; ingestion stores and assigns metadata and
                        starts nothing.
- ``stored_data_only``  at or above the monthly budget: no paid work at all;
                        browsing and retrieval-only chat stay up.

Days and months are UTC.
"""

from __future__ import annotations

import calendar
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from research_agent.beta.config import ModelProvider
from research_agent.beta.db import Json, iso
from research_agent.beta.errors import Conflict, Invalid, Unavailable

PRIORITIES = ("high", "normal", "low")

#: Tokens assumed for a tool result and for the tool schemas when a run's
#: cost is estimated before it starts.
ESTIMATE_TOOL_RESULT_TOKENS = 1000
ESTIMATE_SCHEMA_TOKENS = 500


@dataclass(frozen=True)
class Levers:
    """Every budget lever a person may edit. Money is micro-dollars."""

    monthly_budget_micros: int = 50_000_000
    #: ``None`` derives the figure: monthly budget over the days of the month.
    daily_soft_micros: int | None = None
    #: ``None`` derives the figure: twice the daily soft budget.
    daily_hard_micros: int | None = None
    per_run_max_micros: int = 50_000
    per_chat_max_micros: int = 5_000
    papers_per_pass: int = 10
    agents_per_paper: int = 1
    islands_per_paper: int = 2
    max_tool_calls: int = 6
    max_model_calls: int = 4
    max_output_tokens: int = 900
    pause_new_runs: bool = False
    auto_run_on_ingest: bool = True


_MINIMUM = {
    "monthly_budget_micros": 0,
    "per_run_max_micros": 0,
    "per_chat_max_micros": 0,
    "papers_per_pass": 1,
    "agents_per_paper": 1,
    "islands_per_paper": 1,
    "max_tool_calls": 0,
    "max_model_calls": 1,
    "max_output_tokens": 64,
}


def levers_from(doc: Mapping[str, Any]) -> Levers:
    """Validate the budget block of a spec; absent levers take the defaults."""
    known = {item.name: item for item in fields(Levers)}
    unknown = sorted(set(doc) - set(known))
    if unknown:
        raise Invalid(f"unknown budget lever {unknown[0]}", f"budget.{unknown[0]}")
    values: dict[str, Any] = {}
    for name, value in doc.items():
        where = f"budget.{name}"
        if name in ("pause_new_runs", "auto_run_on_ingest"):
            if not isinstance(value, bool):
                raise Invalid(f"{name} must be true or false", where)
        elif value is None:
            if name not in ("daily_soft_micros", "daily_hard_micros"):
                raise Invalid(f"{name} must be a whole number", where)
        elif isinstance(value, bool) or not isinstance(value, int):
            raise Invalid(f"{name} must be a whole number", where)
        elif value < _MINIMUM.get(name, 0):
            raise Invalid(f"{name} must be at least {_MINIMUM.get(name, 0)}", where)
        values[name] = value
    levers = Levers(**values)
    soft, hard = levers.daily_soft_micros, levers.daily_hard_micros
    if soft is not None and hard is not None and hard < soft:
        raise Invalid(
            "the daily hard budget is below the soft one", "budget.daily_hard_micros"
        )
    return levers


@dataclass(frozen=True)
class Plan:
    """The limits in force right now: the levers after the mode has cut them."""

    mode: str
    runs_allowed: bool
    runs_refusal: str | None
    paid_chat_allowed: bool
    ingest_mode: str
    papers_per_pass: int
    agents_per_paper: int
    islands_per_paper: int
    max_tool_calls: int
    max_model_calls: int
    max_output_tokens: int
    paused_priorities: tuple[str, ...]


def plan_for(levers: Levers, mode: str, provider_configured: bool) -> Plan:
    reduced = mode != "normal"
    stopped = mode in ("hard_stop", "stored_data_only")
    refusal: str | None = None
    if mode == "stored_data_only":
        refusal = "monthly_budget_reached"
    elif mode == "hard_stop":
        refusal = "daily_hard_budget_reached"
    elif levers.pause_new_runs:
        refusal = "runs_paused"
    elif not provider_configured:
        refusal = "model_provider_not_configured"
    calls = levers.max_model_calls
    return Plan(
        mode=mode,
        runs_allowed=refusal is None,
        runs_refusal=refusal,
        paid_chat_allowed=provider_configured and not stopped,
        ingest_mode="metadata_only" if stopped else "metadata_and_runs",
        papers_per_pass=max(1, levers.papers_per_pass // 2)
        if reduced
        else levers.papers_per_pass,
        agents_per_paper=1 if reduced else levers.agents_per_paper,
        islands_per_paper=1 if reduced else levers.islands_per_paper,
        max_tool_calls=levers.max_tool_calls // 2 if reduced else levers.max_tool_calls,
        max_model_calls=min(calls, max(2, calls // 2)) if reduced else calls,
        max_output_tokens=levers.max_output_tokens,
        paused_priorities=("low",) if reduced else (),
    )


@dataclass(frozen=True)
class IslandBudget:
    island_id: str
    share: float
    today_micros: int
    month_micros: int
    reserved_micros: int
    daily_allowance_micros: int
    monthly_allowance_micros: int

    @property
    def over_share(self) -> bool:
        return self.today_micros >= self.daily_allowance_micros


@dataclass(frozen=True)
class BudgetState:
    levers: Levers
    plan: Plan
    month: str
    day_of_month: int
    days_in_month: int
    daily_soft_micros: int
    daily_hard_micros: int
    month_settled_micros: int
    month_unsettled_micros: int
    month_unsettled_count: int
    today_micros: int
    reserved_micros: int
    projected_month_micros: int
    provider_configured: bool
    islands: dict[str, IslandBudget]

    @property
    def month_committed_micros(self) -> int:
        """Settled and unsettled together: what budgets are held against."""
        return self.month_settled_micros + self.month_unsettled_micros

    def runs_remaining_today(self, island_id: str) -> int:
        """Runs an island can still start today if each cost the per-run cap.

        A floor, not a forecast: most runs cost less than their cap.
        """
        island = self.islands.get(island_id)
        cap = self.levers.per_run_max_micros
        if island is None or not self.plan.runs_allowed or cap <= 0:
            return 0
        room = min(
            island.daily_allowance_micros
            - island.today_micros
            - island.reserved_micros,
            self.daily_hard_micros - self.today_micros - self.reserved_micros,
            self.levers.monthly_budget_micros
            - self.month_committed_micros
            - self.reserved_micros,
        )
        return max(0, room // cap)

    def compact(self, island_id: str | None = None) -> Json:
        """The block every response carries beside its data."""
        block: Json = {
            "mode": self.plan.mode,
            "target_micros": self.levers.monthly_budget_micros,
            "month_to_date_micros": self.month_settled_micros,
            "month_unsettled_micros": self.month_unsettled_micros,
            "projected_month_micros": self.projected_month_micros,
            "daily_soft_micros": self.daily_soft_micros,
            "daily_hard_micros": self.daily_hard_micros,
            "today_micros": self.today_micros,
            "runs_allowed": self.plan.runs_allowed,
            "runs_refusal": self.plan.runs_refusal,
            "paid_chat_allowed": self.plan.paid_chat_allowed,
        }
        if island_id is not None and island_id in self.islands:
            island = self.islands[island_id]
            block["island"] = {
                **asdict(island),
                "over_share": island.over_share,
                "runs_remaining_today": self.runs_remaining_today(island_id),
            }
        return block

    def full(self) -> Json:
        return {
            **self.compact(),
            "month": self.month,
            "day_of_month": self.day_of_month,
            "days_in_month": self.days_in_month,
            "month_unsettled_count": self.month_unsettled_count,
            "reserved_micros": self.reserved_micros,
            "projection_basis": "month to date plus the mean daily spend of the"
            " last seven days for each day left",
            "projected_over_budget": self.projected_month_micros
            > self.levers.monthly_budget_micros,
            "provider_configured": self.provider_configured,
            "levers": asdict(self.levers),
            "plan": asdict(self.plan),
            "islands": [
                {**asdict(island), "over_share": island.over_share}
                for island in self.islands.values()
            ],
        }


def budget_state(
    db: sqlite3.Connection,
    spec: Mapping[str, Any],
    now: datetime,
    provider_configured: bool,
) -> BudgetState:
    """Derive the month's budget state from the receipts ledger."""
    levers = levers_from(spec["budget"])
    days = calendar.monthrange(now.year, now.month)[1]
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = iso(now)[:10]
    window = min(7, now.day)
    window_start = iso(now - timedelta(days=window - 1))[:10]

    settled = unsettled = unsettled_count = today_total = trailing = 0
    island_today: dict[str, int] = {}
    island_month: dict[str, int] = {}
    for row in db.execute(
        "SELECT substr(created_at, 1, 10) AS day, island_id, settlement,"
        " SUM(amount_micros) AS total, COUNT(*) AS n FROM cost_receipts"
        " WHERE created_at >= ? AND created_at <= ? GROUP BY 1, 2, 3",
        (iso(month_start), iso(now)),
    ):
        total = int(row["total"])
        if row["settlement"] == "settled":
            settled += total
        else:
            unsettled += total
            unsettled_count += int(row["n"])
        if row["day"] == today:
            today_total += total
        if row["day"] >= window_start:
            trailing += total
        if row["island_id"] is not None:
            island = str(row["island_id"])
            island_month[island] = island_month.get(island, 0) + total
            if row["day"] == today:
                island_today[island] = island_today.get(island, 0) + total

    # A queued or running run holds the part of its estimate it has not spent.
    reserved: dict[str, int] = {}
    for row in db.execute(
        "SELECT r.island_id, SUM(MAX(0, r.estimate_micros - COALESCE((SELECT"
        " SUM(c.amount_micros) FROM cost_receipts c WHERE c.run_id = r.id), 0)))"
        " FROM runs r WHERE r.status IN ('queued', 'running') GROUP BY r.island_id"
    ):
        reserved[str(row[0])] = int(row[1])

    soft = levers.daily_soft_micros
    if soft is None:
        soft = levers.monthly_budget_micros // days
    hard = levers.daily_hard_micros
    if hard is None:
        hard = 2 * soft
    committed = settled + unsettled
    if committed >= levers.monthly_budget_micros:
        mode = "stored_data_only"
    elif today_total >= hard:
        mode = "hard_stop"
    elif today_total >= soft:
        mode = "conserving"
    else:
        mode = "normal"

    active = [island for island in spec["islands"] if not island["archived"]]
    share_sum = sum(float(island["budget_share"]) for island in active)
    islands: dict[str, IslandBudget] = {}
    for island in active:
        share = float(island["budget_share"]) / share_sum if share_sum else 0.0
        island_id = str(island["id"])
        islands[island_id] = IslandBudget(
            island_id=island_id,
            share=round(share, 4),
            today_micros=island_today.get(island_id, 0),
            month_micros=island_month.get(island_id, 0),
            reserved_micros=reserved.get(island_id, 0),
            daily_allowance_micros=int(hard * share),
            monthly_allowance_micros=int(levers.monthly_budget_micros * share),
        )

    return BudgetState(
        levers=levers,
        plan=plan_for(levers, mode, provider_configured),
        month=today[:7],
        day_of_month=now.day,
        days_in_month=days,
        daily_soft_micros=soft,
        daily_hard_micros=hard,
        month_settled_micros=settled,
        month_unsettled_micros=unsettled,
        month_unsettled_count=unsettled_count,
        today_micros=today_total,
        reserved_micros=sum(reserved.values()),
        projected_month_micros=committed + (trailing // window) * (days - now.day),
        provider_configured=provider_configured,
        islands=islands,
    )


def price_micros(provider: ModelProvider, input_tokens: int, output_tokens: int) -> int:
    """The charge for one model call, rounded up to a whole micro-dollar."""
    amount = (
        Decimal(input_tokens) * provider.input_usd_per_mtok
        + Decimal(output_tokens) * provider.output_usd_per_mtok
    )
    return math.ceil(amount)


def estimate_tokens(text: str) -> int:
    """A deliberately high token estimate for text whose count is unknown."""
    return math.ceil(len(text) / 3)


def estimate_run_micros(
    provider: ModelProvider,
    prompt_tokens: int,
    model_calls: int,
    max_output_tokens: int,
    final_output_tokens: int | None = None,
) -> int:
    """The most a run can cost: every call at full output, history resent.

    ``final_output_tokens`` is the output allowed on the last call, which
    submits the reading and is given more room than the calls before it.
    """
    total = 0
    base = prompt_tokens + ESTIMATE_SCHEMA_TOKENS
    for call in range(model_calls):
        carried = call * (max_output_tokens + ESTIMATE_TOOL_RESULT_TOKENS)
        output = max_output_tokens
        if final_output_tokens is not None and call == model_calls - 1:
            output = final_output_tokens
        total += price_micros(provider, base + carried, output)
    return total


def fit_run_to_cap(
    provider: ModelProvider,
    prompt_tokens: int,
    model_calls: int,
    max_output_tokens: int,
    cap_micros: int,
    final_output_tokens: int | None = None,
) -> tuple[int, int]:
    """Cut model calls until the estimate fits the per-run cap.

    Returns the call count and its estimate; refuses when even one call
    exceeds the cap.
    """
    for calls in range(model_calls, 0, -1):
        estimate = estimate_run_micros(
            provider, prompt_tokens, calls, max_output_tokens, final_output_tokens
        )
        if estimate <= cap_micros:
            return calls, estimate
    raise Conflict(
        "run_estimate_over_cap: one model call is estimated above the per-run"
        f" maximum of {cap_micros} micro-dollars"
    )


def admit_run(
    state: BudgetState, island: Mapping[str, Any], estimate_micros: int
) -> None:
    """Refuse a new run the budget, a pause or the island's share forbids."""
    plan = state.plan
    if plan.runs_refusal == "model_provider_not_configured":
        raise Unavailable(
            "model_provider_not_configured: no model endpoint is configured"
        )
    if plan.runs_refusal is not None:
        raise Conflict(
            f"{plan.runs_refusal}: new runs are stopped in budget mode {plan.mode}"
        )
    island_id = str(island["id"])
    if island["archived"] or island["paused"]:
        raise Conflict(f"island_paused: island {island_id} takes no new runs")
    if island["priority"] in plan.paused_priorities:
        raise Conflict(
            f"island_paused_by_budget: {island['priority']}-priority islands are"
            f" paused in budget mode {plan.mode}"
        )
    held = state.reserved_micros + estimate_micros
    if state.month_committed_micros + held > state.levers.monthly_budget_micros:
        raise Conflict(
            "monthly_budget_exhausted: this run would pass the monthly budget"
        )
    if state.today_micros + held > state.daily_hard_micros:
        raise Conflict(
            "daily_hard_budget_exhausted: this run would pass the daily hard budget"
        )
    share = state.islands[island_id]
    if (
        share.today_micros + share.reserved_micros + estimate_micros
        > share.daily_allowance_micros
    ):
        raise Conflict(
            f"island_over_share: island {island_id} has used its share of today's budget"
        )


def admit_paid_chat(state: BudgetState, estimate_micros: int) -> str | None:
    """Why a paid chat answer is refused, or ``None`` when it may proceed."""
    if not state.provider_configured:
        return "model_provider_not_configured"
    if not state.plan.paid_chat_allowed:
        return f"budget_mode_{state.plan.mode}"
    if estimate_micros > state.levers.per_chat_max_micros:
        return "chat_estimate_over_cap"
    held = state.reserved_micros + estimate_micros
    if state.month_committed_micros + held > state.levers.monthly_budget_micros:
        return "monthly_budget_exhausted"
    if state.today_micros + held > state.daily_hard_micros:
        return "daily_hard_budget_exhausted"
    return None
