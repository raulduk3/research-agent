"""Tests for the inference qualification battery (bin/qualify-inference).

Loads the script by path -- it has no ``.py`` suffix, matching this
repository's other self-contained ``bin/`` scripts -- and exercises its
pure functions with an in-process fake transport. No network call is
made and no cost is incurred; the module's own ``if __name__ ==
"__main__"`` bootstrap never runs under this import.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCRIPT_PATH = Path(__file__).resolve().parents[3] / "bin" / "qualify-inference"


def _load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("qualify_inference", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location(
        "qualify_inference", SCRIPT_PATH, loader=loader
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qi = _load_module()


@dataclass
class FakeTransport:
    """Replays a fixed, ordered script of raw provider responses."""

    responses: list[dict[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.responses[len(self.calls)]
        self.calls.append(payload)
        return response


def _turn(*, content: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": qi.AGENT_MODEL_ID,
        "choices": [{"message": {"content": content, "tool_calls": tool_calls}}],
        "usage": {
            "prompt_tokens": 200,
            "prompt_cache_hit_tokens": 50,
            "completion_tokens": 30,
        },
    }


def _deep_read_call(*, call_id: str, paper_id: str, **locator: str) -> dict[str, Any]:
    arguments = {"paper_id": paper_id, **locator}
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "deep_read", "arguments": json.dumps(arguments)},
    }


def _submit_call(*, call_id: str = "call-submit") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "submit",
            "arguments": json.dumps(
                {
                    "submission_id": "11111111-1111-4111-8111-111111111111",
                    "answers": [],
                    "nominations": [],
                }
            ),
        },
    }


def _forbidden_call(*, call_id: str = "call-forbidden") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "delete_everything", "arguments": json.dumps({})},
    }


def _manifest() -> Any:
    return qi.AgentDeploymentManifest(
        provider=qi.AGENT_PROVIDER,
        model_id=qi.AGENT_MODEL_ID,
        endpoint="https://api.z.ai/api/paas/v4/chat/completions",
        revision=qi.UNPINNED_REVISION,
        qualified=True,
    )


def _reservation() -> Any:
    return qi.SpendReservation(day_cap_usd=8.0, month_cap_usd=200.0)


def test_worst_case_cost_exceeds_the_typical_measured_cost() -> None:
    usage = [
        qi.TurnUsage(
            turn_index=0,
            request_seed=0,
            reported_model_id=qi.AGENT_MODEL_ID,
            reported_revision=None,
            input_tokens=50_000,
            cached_input_tokens=42_500,
            output_tokens=8_000,
        )
    ]
    assert qi.worst_case_run_cost_usd() > qi.actual_run_cost_usd(usage)


def test_actual_run_cost_prices_cached_input_below_uncached() -> None:
    cheap = [
        qi.TurnUsage(
            0,
            0,
            qi.AGENT_MODEL_ID,
            None,
            input_tokens=1000,
            cached_input_tokens=1000,
            output_tokens=0,
        )
    ]
    expensive = [
        qi.TurnUsage(
            0,
            0,
            qi.AGENT_MODEL_ID,
            None,
            input_tokens=1000,
            cached_input_tokens=0,
            output_tokens=0,
        )
    ]
    assert qi.actual_run_cost_usd(cheap) < qi.actual_run_cost_usd(expensive)


def test_spend_reservation_refuses_past_the_tighter_cap() -> None:
    reservation = qi.SpendReservation(day_cap_usd=1.0, month_cap_usd=200.0)
    assert reservation.try_reserve(0.6) is True
    assert reservation.try_reserve(0.5) is False
    assert reservation.reserved_usd == 0.6


def test_spend_reservation_release_lowers_the_outstanding_amount() -> None:
    reservation = qi.SpendReservation(day_cap_usd=1.0, month_cap_usd=200.0)
    reservation.try_reserve(0.6)
    reservation.release(0.4)
    assert reservation.reserved_usd == pytest.approx(0.2)


def test_fixture_dispatcher_reads_a_known_section() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    dispatcher = qi.FixtureToolDispatcher(corpus=corpus)
    outcome = dispatcher.dispatch(
        qi.ToolCall(
            "call-1",
            "deep_read",
            {"paper_id": "fixture-paper-1", "section_id": "results"},
        ),
        run_id="run-1",
    )
    assert outcome.status == "ok"
    assert "fixture accuracy" in outcome.data["text"]
    assert outcome.deep_reads == 1


def test_fixture_dispatcher_reports_unavailable_for_an_unknown_section() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    dispatcher = qi.FixtureToolDispatcher(corpus=corpus)
    outcome = dispatcher.dispatch(
        qi.ToolCall(
            "call-1", "deep_read", {"paper_id": "fixture-paper-1", "section_id": "nope"}
        ),
        run_id="run-1",
    )
    assert outcome.status == "error"


def test_fixture_dispatcher_accepts_a_well_formed_submit() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    dispatcher = qi.FixtureToolDispatcher(corpus=corpus)
    outcome = dispatcher.dispatch(
        qi.ToolCall(
            "call-1",
            "submit",
            {"submission_id": "11111111-1111-4111-8111-111111111111"},
        ),
        run_id="run-1",
    )
    assert outcome.status == "ok"
    assert outcome.accepted_submit is True


def test_run_one_conversation_grades_as_submitted_on_a_clean_two_turn_script() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    transport = FakeTransport(
        responses=[
            _turn(
                content='{"note": "reading", "intent": "inspect"}',
                tool_calls=[
                    _deep_read_call(
                        call_id="call-1",
                        paper_id="fixture-paper-1",
                        section_id="results",
                    )
                ],
            ),
            _turn(
                content='{"note": "submitting", "intent": "submit"}',
                tool_calls=[_submit_call()],
            ),
        ]
    )
    result = qi.run_one_conversation(
        scenario_id="scenario-1",
        paper_ids=["fixture-paper-1"],
        questions=[],
        corpus=corpus,
        manifest=_manifest(),
        api_key="secret",
        transport_factory=lambda: transport,
        reservation=_reservation(),
    )
    assert result.ran
    assert result.status == "submitted"
    assert result.forbidden_tool_attempts == 0
    assert qi.grade_five_tool(result) is True
    assert result.cost_usd > 0


def test_a_forbidden_tool_attempt_is_recorded_and_never_dispatched() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    transport = FakeTransport(
        responses=[
            _turn(
                content='{"note": "trying", "intent": "inspect"}',
                tool_calls=[_forbidden_call()],
            ),
            _turn(
                content='{"note": "submitting", "intent": "submit"}',
                tool_calls=[_submit_call()],
            ),
        ]
    )
    result = qi.run_one_conversation(
        scenario_id="scenario-1",
        paper_ids=["fixture-paper-1"],
        questions=[],
        corpus=corpus,
        manifest=_manifest(),
        api_key="secret",
        transport_factory=lambda: transport,
        reservation=_reservation(),
    )
    assert result.forbidden_tool_attempts == 1
    assert not any(call.name == "delete_everything" for call in result.dispatched)
    assert qi.grade_five_tool(result) is False


def test_run_one_conversation_is_not_run_when_the_reservation_is_exhausted() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    reservation = qi.SpendReservation(day_cap_usd=0.0, month_cap_usd=0.0)
    result = qi.run_one_conversation(
        scenario_id="scenario-1",
        paper_ids=["fixture-paper-1"],
        questions=[],
        corpus=corpus,
        manifest=_manifest(),
        api_key="secret",
        transport_factory=lambda: FakeTransport(responses=[]),
        reservation=reservation,
    )
    assert result.ran is False
    assert result.skip_reason == "spend_cap_reached"
    assert result.status == "not_run"


def test_grade_figure_table_requires_the_specific_figure_not_just_the_paper() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    transport = FakeTransport(
        responses=[
            _turn(
                content='{"note": "reading", "intent": "inspect"}',
                tool_calls=[
                    _deep_read_call(
                        call_id="call-1",
                        paper_id="fixture-paper-1",
                        section_id="results",
                    )
                ],
            ),
            _turn(
                content='{"note": "submitting", "intent": "submit"}',
                tool_calls=[_submit_call()],
            ),
        ]
    )
    result = qi.run_one_conversation(
        scenario_id="figure-table-001",
        paper_ids=["fixture-paper-1"],
        questions=[{"question_id": "figure-table-001", "text": "irrelevant"}],
        corpus=corpus,
        manifest=_manifest(),
        api_key="secret",
        transport_factory=lambda: transport,
        reservation=_reservation(),
    )
    assert (
        qi.grade_figure_table(result, paper_id="fixture-paper-1", figure_id="figure-1")
        is False
    )


def test_grade_figure_table_passes_when_the_right_figure_was_retrieved() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    transport = FakeTransport(
        responses=[
            _turn(
                content='{"note": "reading the figure", "intent": "inspect"}',
                tool_calls=[
                    _deep_read_call(
                        call_id="call-1",
                        paper_id="fixture-paper-1",
                        figure_id="figure-1",
                    )
                ],
            ),
            _turn(
                content='{"note": "submitting", "intent": "submit"}',
                tool_calls=[_submit_call()],
            ),
        ]
    )
    result = qi.run_one_conversation(
        scenario_id="figure-table-001",
        paper_ids=["fixture-paper-1"],
        questions=[{"question_id": "figure-table-001", "text": "irrelevant"}],
        corpus=corpus,
        manifest=_manifest(),
        api_key="secret",
        transport_factory=lambda: transport,
        reservation=_reservation(),
    )
    assert (
        qi.grade_figure_table(result, paper_id="fixture-paper-1", figure_id="figure-1")
        is True
    )


def test_build_evidence_location_corpus_places_the_gold_paper_by_position() -> None:
    question = {
        "question_id": "evidence-location-test",
        "shard_size": 4,
        "position_bucket": "late",
        "gold_clue": "the fixture password is zed",
    }
    corpus, gold_paper_id, paper_ids = qi._build_evidence_location_corpus(question)
    assert gold_paper_id == paper_ids[-1]
    assert corpus.papers[gold_paper_id]["sections"]["evidence"] == question["gold_clue"]
    assert len(paper_ids) == 4


def test_suite_verdict_is_insufficient_population_below_the_required_n() -> None:
    summary = qi.SuiteSummary(
        name="five_tool_conversations",
        required_n=100,
        denominator=3,
        successes=3,
        not_run=0,
        forbidden_tool_attempts=0,
        total_cost_usd=0.01,
        total_input_tokens=100,
        total_cached_input_tokens=0,
        total_output_tokens=10,
        mean_wall_seconds=0.0,
    )
    assert summary.verdict(min_rate=0.99) == "insufficient_population"


def test_suite_verdict_passes_at_full_population_above_threshold() -> None:
    summary = qi.SuiteSummary(
        name="five_tool_conversations",
        required_n=2,
        denominator=2,
        successes=2,
        not_run=0,
        forbidden_tool_attempts=0,
        total_cost_usd=0.01,
        total_input_tokens=100,
        total_cached_input_tokens=0,
        total_output_tokens=10,
        mean_wall_seconds=0.0,
    )
    assert summary.verdict(min_rate=0.99) == "pass"


def test_suite_verdict_fails_at_full_population_below_threshold() -> None:
    summary = qi.SuiteSummary(
        name="five_tool_conversations",
        required_n=2,
        denominator=2,
        successes=1,
        not_run=0,
        forbidden_tool_attempts=0,
        total_cost_usd=0.01,
        total_input_tokens=100,
        total_cached_input_tokens=0,
        total_output_tokens=10,
        mean_wall_seconds=0.0,
    )
    assert summary.verdict(min_rate=0.99) == "fail"


def test_render_report_names_the_verdict_and_denominator() -> None:
    summary = qi.SuiteSummary(
        name="five_tool_conversations",
        required_n=100,
        denominator=3,
        successes=3,
        not_run=0,
        forbidden_tool_attempts=0,
        total_cost_usd=0.01,
        total_input_tokens=100,
        total_cached_input_tokens=0,
        total_output_tokens=10,
        mean_wall_seconds=0.0,
    )
    report = qi.render_report(
        generated_at="2026-09-22T00:00:00.000000Z",
        manifest=_manifest(),
        suites=[(summary, 0.99)],
        reservation=_reservation(),
        dry_run=True,
    )
    assert "five_tool_conversations" in report
    assert "insufficient_population" in report
    assert "DRY RUN" in report
    assert "measured: 3" in report


def test_dry_run_transport_reads_the_first_listed_paper_then_submits() -> None:
    transport = qi._DryRunTransport()
    first = transport.create(
        payload={
            "messages": [
                {"role": "user", "content": {"paper_ids": ["paper-x", "paper-y"]}}
            ]
        }
    )
    assert first["model"] == qi.AGENT_MODEL_ID
    message = first["choices"][0]["message"]
    assert '"paper-x"' in message["tool_calls"][0]["function"]["arguments"]

    second = transport.create(payload={"messages": []})
    assert (
        second["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "submit"
    )


def test_end_to_end_five_tool_suite_reports_insufficient_population() -> None:
    corpus = qi.FixtureCorpus.load(FIXTURES_DIR / "corpus.json")
    scenarios = [
        {"scenario_id": "s1", "paper_ids": ["fixture-paper-1"], "questions": []}
    ]

    def transport_factory() -> Any:
        return FakeTransport(
            responses=[
                _turn(
                    content='{"note": "reading", "intent": "inspect"}',
                    tool_calls=[
                        _deep_read_call(
                            call_id="call-1",
                            paper_id="fixture-paper-1",
                            section_id="results",
                        )
                    ],
                ),
                _turn(
                    content='{"note": "submitting", "intent": "submit"}',
                    tool_calls=[_submit_call()],
                ),
            ]
        )

    summary = qi.run_five_tool_suite(
        scenarios=scenarios,
        corpus=corpus,
        manifest=_manifest(),
        api_key="secret",
        transport_factory=transport_factory,
        reservation=_reservation(),
    )
    assert summary.denominator == 1
    assert summary.successes == 1
    assert summary.verdict(min_rate=qi.FIVE_TOOL_MIN_RATE) == "insufficient_population"
