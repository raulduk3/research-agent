"""Configuration, the model wire client, the heartbeat and the operator commands."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from research_agent.beta import __main__ as cli
from research_agent.beta.config import ConfigError, load_config
from research_agent.beta.db import connect
from research_agent.beta.ingest import SourceFailed
from research_agent.beta.models import ChatCompletionsClient, ModelCallFailed
from research_agent.beta.service import Swarm
from tests.beta.helpers import (
    PROVIDER,
    FakeClock,
    ScriptedClient,
    call,
    config,
    entry,
    feed,
    reading,
    reply,
)

PROVIDER_ENV = {
    "RESEARCH_AGENT_MODEL_ENDPOINT": "https://models.invalid/v1/chat/completions",
    "RESEARCH_AGENT_MODEL_API_KEY": "key",
    "RESEARCH_AGENT_MODEL_ID": "some-model",
    "RESEARCH_AGENT_MODEL_INPUT_USD_PER_MTOK": "0.25",
    "RESEARCH_AGENT_MODEL_OUTPUT_USD_PER_MTOK": "1.5",
}


def test_configuration_reads_the_environment_and_has_no_price_defaults() -> None:
    loaded = load_config(
        {
            **PROVIDER_ENV,
            "RESEARCH_AGENT_BETA_DB": "/data/swarm.sqlite3",
            "RESEARCH_AGENT_ISLAND_PASSWORDS": "cs:one, quant:two",
            "RESEARCH_AGENT_ALLOWED_ORIGINS": "https://a.example/, https://b.example",
            "RESEARCH_AGENT_TICK_SECONDS": "300",
        }
    )

    assert loaded.database == Path("/data/swarm.sqlite3")
    assert loaded.island_passwords == {"cs": "one", "quant": "two"}
    assert loaded.allowed_origins == ("https://a.example", "https://b.example")
    assert loaded.provider is not None
    assert loaded.provider.input_usd_per_mtok == Decimal("0.25")
    # The ingestion cadence paces itself unless set; zero switches it off.
    assert (loaded.tick_seconds, loaded.ingest_seconds) == (300, 600)
    off = load_config({**PROVIDER_ENV, "RESEARCH_AGENT_INGEST_SECONDS": "0"})
    assert (off.tick_seconds, off.ingest_seconds) == (60, 0)
    # Nothing about the model is assumed when the environment is silent.
    assert load_config({}).provider is None


@pytest.mark.parametrize(
    ("env", "message"),
    [
        (
            {k: v for k, v in PROVIDER_ENV.items() if "OUTPUT" not in k},
            "half configured; set RESEARCH_AGENT_MODEL_OUTPUT_USD_PER_MTOK",
        ),
        (
            {**PROVIDER_ENV, "RESEARCH_AGENT_MODEL_ENDPOINT": "http://plain.example"},
            "must be an https URL",
        ),
        ({"RESEARCH_AGENT_ISLAND_PASSWORDS": "cs:same,quant:same"}, "its own password"),
        (
            {
                "RESEARCH_AGENT_ISLAND_PASSWORDS": "cs:same",
                "RESEARCH_AGENT_OPERATOR_TOKEN": "same",
            },
            "must differ from every island password",
        ),
        ({"RESEARCH_AGENT_ALLOWED_ORIGINS": "*"}, "forbid a wildcard"),
        ({"RESEARCH_AGENT_TICK_SECONDS": "often"}, "whole number of seconds"),
    ],
)
def test_configuration_refuses_what_it_cannot_run_with(
    env: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(env)


def _wire(handler: Any) -> ChatCompletionsClient:
    return ChatCompletionsClient(PROVIDER, transport=httpx.MockTransport(handler))


def test_the_wire_client_sends_one_completion_request_and_reads_tool_calls() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "served-model",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "paper_text",
                                        "arguments": '{"passage_id": "p:abstract"}',
                                    },
                                },
                                {
                                    "id": "call-2",
                                    "type": "function",
                                    "function": {"name": "x", "arguments": "not json"},
                                },
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 321, "completion_tokens": 45},
            },
        )

    tools = [{"type": "function", "function": {"name": "paper_text"}}]
    answer = _wire(handler).complete(
        [{"role": "user", "content": "read"}],
        tools,
        max_output_tokens=900,
        temperature=0.7,
    )

    assert seen["url"] == PROVIDER.endpoint
    assert seen["authorization"] == "Bearer test-key"
    assert seen["body"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "read"}],
        "temperature": 0.7,
        "tools": tools,
        "max_tokens": 900,
    }
    assert (answer.input_tokens, answer.output_tokens) == (321, 45)
    assert answer.usage_reported and answer.model == "served-model"
    first, second = answer.tool_calls
    assert first.arguments == {"passage_id": "p:abstract"}
    # Arguments that are not JSON are kept as text and never guessed at.
    assert second.arguments is None and second.raw_arguments == "not json"


def test_the_wire_client_estimates_when_usage_is_missing_and_names_failures() -> None:
    silent = _wire(
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "twelve chars"}}]}
        )
    ).complete(
        [{"role": "user", "content": "read"}], [], max_output_tokens=10, temperature=0
    )
    assert silent.usage_reported is False
    assert silent.input_tokens > 0 and silent.output_tokens > 0

    for handler, message in (
        (lambda request: httpx.Response(429, json={}), "provider answered 429"),
        (lambda request: httpx.Response(200, json={"choices": []}), "IndexError"),
        (lambda request: httpx.Response(200, text="<html>"), "provider call failed"),
    ):
        with pytest.raises(ModelCallFailed, match=message):
            _wire(handler).complete([], [], max_output_tokens=10, temperature=0)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"choices": {}},
        {"choices": ["invalid"]},
        {"choices": [{"message": "invalid"}]},
        {"choices": [{"message": {"tool_calls": "invalid"}}]},
        {"choices": [{"message": {"tool_calls": ["invalid"]}}]},
        {"choices": [{"message": {"tool_calls": [{"function": "invalid"}]}}]},
        {"choices": [{"message": {"tool_calls": [{"function": {"arguments": {}}}]}}]},
        {"choices": [{"message": {}}], "usage": []},
        *[
            {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {token: value, other: 1},
            }
            for token, other in (
                ("prompt_tokens", "completion_tokens"),
                ("completion_tokens", "prompt_tokens"),
            )
            for value in ("invalid", "123", None, -1, 1.5, True)
        ],
    ],
)
def test_invalid_provider_shapes_raise_a_typed_failure(body: Any) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    with pytest.raises(ModelCallFailed, match="provider call failed"):
        _wire(handler).complete([], [], max_output_tokens=10, temperature=0)

    assert len(requests) == 1


def _swarm(tmp_path: Path, clock: FakeClock, script: list[Any], **overrides: Any):
    feeds = {"cs.AI": feed(entry("2609.00001"))}

    def fetch(category: str, limit: int) -> str:
        if category not in feeds:
            raise SourceFailed(f"no answer for {category}")
        return feeds[category]

    swarm = Swarm(
        config(tmp_path, **overrides),
        ScriptedClient(script),
        clock,
        fetch,
        sleep=lambda _: None,
    )
    swarm.prepare()
    return swarm


def test_the_heartbeat_ingests_when_due_and_agents_read_without_being_asked(
    tmp_path: Path, clock: FakeClock
) -> None:
    swarm = _swarm(
        tmp_path,
        clock,
        [reply(call("submit_reading", reading()))],
        ingest_seconds=3600,
        tick_seconds=300,
    )

    swarm.heartbeat()

    with connect(swarm.config.database) as db:
        assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
        run = db.execute("SELECT genome_id, status FROM runs").fetchone()
        assert tuple(run) == ("cs-reader", "completed")
        passes = db.execute("SELECT COUNT(*) FROM ingest_passes").fetchone()[0]
    assert passes == 1

    # Inside the interval a beat ingests nothing more; past it, it does.
    clock.advance(minutes=30)
    swarm.heartbeat()
    with connect(swarm.config.database) as db:
        assert db.execute("SELECT COUNT(*) FROM ingest_passes").fetchone()[0] == 1
    clock.advance(minutes=31)
    swarm.heartbeat()
    with connect(swarm.config.database) as db:
        assert db.execute("SELECT COUNT(*) FROM ingest_passes").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1


def test_a_swarm_with_no_intervals_does_nothing_on_a_beat(
    tmp_path: Path, clock: FakeClock
) -> None:
    swarm = _swarm(tmp_path, clock, [])

    swarm.heartbeat()

    with connect(swarm.config.database) as db:
        assert db.execute("SELECT COUNT(*) FROM ingest_passes").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_the_operator_commands_export_and_apply_the_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_BETA_DB", str(tmp_path / "swarm.sqlite3"))
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)

    assert cli.main(["spec", "export"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["revision"] == 1

    exported["spec"]["budget"] = {"agents_per_paper": 2}
    edited = tmp_path / "spec.json"
    edited.write_text(json.dumps(exported), encoding="utf-8")
    assert cli.main(["spec", "apply", str(edited), "--note", "two readers"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert (applied["revision"], applied["applied"]) == (2, True)

    assert cli.main(["budget"]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state["levers"]["agents_per_paper"] == 2
    assert state["runs_refusal"] == "model_provider_not_configured"

    exported["spec"]["budget"] = {"agents_per_paper": 0}
    edited.write_text(json.dumps(exported), encoding="utf-8")
    assert cli.main(["spec", "apply", str(edited)]) == 1
    assert "agents_per_paper must be at least 1" in capsys.readouterr().err
