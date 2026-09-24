"""The swarm dashboard over one recorded run: the three panes show the seat,
the trace and the paper, and every key binding names an action that exists."""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from textual.binding import Binding
from textual.widgets import OptionList, RichLog, Static

from research_agent.agents.tail import TailStorage
from research_agent.tui.swarm import SwarmApp

RUN = "00000000-0000-4000-8000-000000000001"
CONFIGURATION = "00000000-0000-4000-8000-0000000000c1"
BUDGETS = {"tool_calls": 10, "deep_reads": 4, "images": 2}


@dataclass
class Result:
    data: Any


def _bytes(value: object) -> dict[str, object]:
    raw = json.dumps(value).encode()
    return {"bytes": base64.b64encode(raw).decode(), "truncated": False}


class RecordedRun:
    """The owner reads of one run that called a tool once and submitted."""

    def list_owner_runs(self, **_: object) -> Result:
        return Result(
            {
                "runs": [
                    {
                        "run_id": RUN,
                        "lineage_id": "lineage-7",
                        "island": "quant-ph",
                        "created_at": "2026-09-23T10:00:00.000000Z",
                        "configuration_id": CONFIGURATION,
                    }
                ],
                "next_cursor": None,
            }
        )

    def read_owner_run(self, run_id: UUID) -> Result:
        assert str(run_id) == RUN
        return Result(
            {
                "created_at": "2026-09-23T10:00:00.000000Z",
                "paper_id": "arxiv:1706.03762",
                "configuration_id": CONFIGURATION,
                "budgets": BUDGETS,
                "ending": {
                    "ended_at": "2026-09-23T10:00:09.000000Z",
                    "reason": None,
                    "submission": {
                        "submission_id": "s-1",
                        "forecasts": [
                            {
                                "question_id": "q-1",
                                "probability": 0.7,
                                "rationale": "cited",
                            }
                        ],
                    },
                },
            }
        )

    def read_run_trace(self, run_id: UUID) -> Result:
        request = {"arguments": {"note": "reading the cards", "intent": "orient"}}
        return Result(
            {
                "calls": [
                    {
                        "call_sequence": 1,
                        "tool": "lookup",
                        "decision": "admitted",
                        "reason": None,
                        "started_at": "2026-09-23T10:00:01.000000Z",
                        "request": _bytes(request),
                        "terminal": {
                            "outcome": "response",
                            "error_code": None,
                            "ended_at": "2026-09-23T10:00:02.000000Z",
                            "budget_deltas": {"tool_calls": 1},
                            "retrieved_ids": ["c-1"],
                            "response": _bytes({"card": "Attention"}),
                        },
                    }
                ]
            }
        )

    def read_run_settlement(self, run_id: UUID) -> Result:
        return Result(
            {
                "settled_at": "2026-09-23T10:00:10.000000Z",
                "provider": "zai",
                "model": "glm-5.3-flash",
                "input_tokens": 1200,
                "output_tokens": 340,
                "usage_source": "provider",
            }
        )

    def read_genome_view(self, configuration_id: UUID) -> dict[str, object] | None:
        return {
            "lineage_id": "lineage-7",
            "island": "quant-ph",
            "founder": True,
            "emphasis": {"prompt": "evidence first"},
        }


def _text(widget: Any) -> str:
    if isinstance(widget, RichLog):
        return "\n".join(strip.text for strip in widget.lines)
    if isinstance(widget, Static):
        return str(widget.render())
    raise TypeError(widget)


def test_the_three_panes_show_the_recorded_run() -> None:
    async def scenario() -> tuple[str, str, str, str, str]:
        app = SwarmApp(
            cast(TailStorage, RecordedRun()),
            day="2026-09-23",
            front_end="https://x",
            live=False,
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            seats = app.query_one("#seats", OptionList)
            seat_lines = "\n".join(
                str(seats.get_option_at_index(i).prompt)
                for i in range(seats.option_count)
            )
            run = _text(app.query_one("#run", RichLog))
            await pilot.press("enter")
            await pilot.pause()
            expanded = _text(app.query_one("#run", RichLog))
            return (
                seat_lines,
                run,
                expanded,
                _text(app.query_one("#paper", Static)),
                _text(app.query_one("#status", Static)),
            )

    seats, run, expanded, paper, status = asyncio.run(scenario())
    assert seats.splitlines()[0] == "quant-ph"
    assert "✓ lineage-7" in seats and "1 runs" in seats
    assert 'lookup note="reading the cards" intent="orient"' in run
    assert "submitted" in run and "p=0.70" in run and "settled" in run
    assert "reading the cards" not in run.split("lookup response")[1]
    assert '{"card": "Attention"}' in expanded
    assert "arxiv:1706.03762" in paper and "founder yes" in paper
    assert "1 seats" in status and "runs today 1" in status


def test_every_binding_names_an_action() -> None:
    bindings = [b for b in SwarmApp.BINDINGS if isinstance(b, Binding)]
    assert len(bindings) == len(SwarmApp.BINDINGS)
    keys = {binding.key for binding in bindings}
    assert {"j", "k", "1", "2", "3", "slash", "enter", "p", "o", "tab"} <= keys
    for binding in bindings:
        name = binding.action.split("(")[0]
        assert callable(getattr(SwarmApp, f"action_{name}", None)), binding.key
