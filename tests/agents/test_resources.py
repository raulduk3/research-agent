"""The runner's resources record: per-call rows that sum to the settlement (#330)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from research_agent.agents.model_client import (
    AGENT_MODEL_ID,
    InferenceOnlyClient,
    TurnUsage,
)
from research_agent.agents.resources import RunClock, resources_record
from research_agent.agents.runner import run_agent
from research_agent.storage.client import (
    RunWorkerRecord,
    SnapshotDescription,
    StorageClientError,
)
from research_agent.storage.resources import validate_resources_payload
from tests.agents.support import FixtureToolDispatcher, count_tokens
from tests.agents.test_model_client import RUN_ID, FakeTransport, _manifest, _response

SNAPSHOT = "e" * 64


@dataclass
class FakeStorage:
    """The orchestrator's storage for one run, keeping what was recorded."""

    refuse_resources: bool = False
    settlements: list[dict[str, Any]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)

    def read_run_worker(self, run_id: UUID) -> RunWorkerRecord:
        return RunWorkerRecord(
            run_id=run_id,
            configuration_id=run_id,
            attempt=0,
            genome_hash="a" * 64,
            snapshot_hash=SNAPSHOT,
            budgets={"tool_calls": 5, "deep_reads": 1, "images": 1},
            allowed_tools=frozenset({"submit"}),
            paper_id="p1",
            issued_question_ids=(),
            prompt="Read the paper.",
            scan_policy="Scan.",
            read_policy="Read.",
            probability_assignment_rule="Assign.",
        )

    def read_snapshot(self, snapshot_hash: str) -> SnapshotDescription:
        return SnapshotDescription(SNAPSHOT, "2099-01-01T00:00:00.000000Z", 3, ())

    def read_run_specification(self, run_id: UUID) -> Any:
        return SimpleNamespace(active=True)

    def append_run_event(self, **_: Any) -> None:
        return None

    def void_run(self, **_: Any) -> None:
        return None

    def record_settlement(self, **values: Any) -> None:
        self.settlements.append(values)

    def record_run_resources(self, *, run_id: UUID, resources: Any, **_: Any) -> None:
        if self.refuse_resources:
            raise StorageClientError(
                status_code=409,
                request_id="r",
                code="state_conflict",
                message="already recorded",
                retryable=False,
                evidence_ids=(),
                headers=(),
                body=b"",
            )
        self.resources.append({"run_id": str(run_id), **resources})


def execute(storage: FakeStorage, turns: list[dict[str, Any]]) -> Any:
    transport = FakeTransport(turns)
    return run_agent(
        UUID(RUN_ID),
        storage=storage,  # type: ignore[arg-type]
        specifications=storage,  # type: ignore[arg-type]
        tools=lambda _: FixtureToolDispatcher({}),
        model_client=lambda run_id: InferenceOnlyClient(
            run_id=run_id,
            manifest=_manifest(),
            transport=transport,
            api_key="key",
        ),
        count_tokens=count_tokens,
        resources=storage,
        endpoints=("https://api.example/v4/chat/completions", "in-process"),
    )


def test_the_recorded_model_calls_sum_to_the_runs_settlement() -> None:
    storage = FakeStorage()
    turns = [
        _response(prompt_tokens=100 * (index + 1), completion_tokens=7 + index)
        for index in range(8)
    ]
    outcome = execute(storage, turns)

    [settlement] = storage.settlements
    [record] = storage.resources
    validate_resources_payload("record", record)
    calls = record["model_calls"]
    assert calls, "the run made model calls"
    assert [call["turn_index"] for call in calls] == list(range(len(calls)))
    assert sum(call["input_tokens"] for call in calls) == settlement["input_tokens"]
    assert sum(call["output_tokens"] for call in calls) == settlement["output_tokens"]
    assert settlement["input_tokens"] == outcome.input_tokens
    assert {call["model"] for call in calls} == {AGENT_MODEL_ID}
    assert all(call["bytes_sent"] > 0 for call in calls)
    assert record["model_endpoint"] == "https://api.example/v4/chat/completions"


def test_a_refused_resources_record_leaves_the_outcome_as_it_was(
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = FakeStorage(refuse_resources=True)
    outcome = execute(storage, [_response() for _ in range(8)])
    assert storage.settlements and not storage.resources
    assert outcome.status in {"submitted", "void"}
    assert "resources not recorded" in capsys.readouterr().err


def test_process_usage_sums_self_and_children_and_keeps_the_larger_peak() -> None:
    usage = [
        TurnUsage(0, 1, "m", None, 10, 4, 2, started_at=1.0, latency_ms=500),
        TurnUsage(1, 2, "m", None, 20, 0, 3, started_at=2.0, latency_ms=250),
    ]
    samples = {
        0: SimpleNamespace(ru_utime=1.5, ru_stime=0.25, ru_maxrss=100),
        -1: SimpleNamespace(ru_utime=0.5, ru_stime=0.25, ru_maxrss=300),
    }
    record = resources_record(
        RunClock(started_at=0.5, load_start=[1, 2, 3]),
        usage,
        model_endpoint="https://api.example",
        tool_service="in-process",
        now=lambda: 3.0,
        load=lambda: [4, 5, 6],
        rusage=lambda who: samples[who],
    )
    process = record["process"]
    assert (process["cpu_user_ms"], process["cpu_system_ms"]) == (2000, 500)
    assert process["peak_rss_bytes"] in {300, 300 * 1024}
    assert (process["load_start"], process["load_end"]) == ([1, 2, 3], [4, 5, 6])
    assert record["first_model_call_at"] == "1970-01-01T00:00:01.000000Z"
    assert record["last_model_call_at"] == "1970-01-01T00:00:02.250000Z"
    validate_resources_payload("record", {"run_id": RUN_ID, **record})
