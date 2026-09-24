"""Tests for the inference-only agent model client (TDD-3.1.37, TDD-4.1.74)."""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from research_agent.agents.model_client import (
    AGENT_MODEL_ID,
    AGENT_PROVIDER,
    REPETITION_PENALTY,
    RETRY_AFTER_SECONDS,
    TEMPERATURE,
    TOP_P,
    UNPINNED_REVISION,
    AgentDeploymentManifest,
    AmbiguousCompletion,
    ChatCompletionsTransport,
    DeploymentDrift,
    DeploymentUnqualified,
    HttpxChatCompletionsTransport,
    InferenceOnlyClient,
    ProcessorTokenCounter,
    ProviderRejected,
    derive_request_seed,
    load_token_counter,
)
from research_agent.agents.loop import ModelResponse, TokenUsage
from research_agent.agents.messages import Message
from research_agent.contracts.primitives import ContractValidationError

RUN_ID = "11111111-1111-4111-8111-111111111111"
ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"
REVISION = "a" * 40


@dataclass
class FakeTransport:
    """Replays a fixed, ordered script of raw provider responses."""

    responses: list[dict[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.responses[len(self.calls)]
        self.calls.append(payload)
        return response


def _manifest(
    *, revision: str = REVISION, qualified: bool = True
) -> AgentDeploymentManifest:
    return AgentDeploymentManifest(
        provider=AGENT_PROVIDER,
        model_id=AGENT_MODEL_ID,
        endpoint=ENDPOINT,
        revision=revision,
        qualified=qualified,
    )


def _response(
    *,
    model: str = AGENT_MODEL_ID,
    revision: str | None = REVISION,
    content: str = '{"note": "read the abstract", "intent": "scan"}',
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 100,
    cached_tokens: int = 40,
    completion_tokens: int = 20,
) -> dict[str, Any]:
    message: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    payload: dict[str, Any] = {
        "model": model,
        "choices": [{"message": message}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "prompt_cache_hit_tokens": cached_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    if revision is not None:
        payload["system_fingerprint"] = revision
    return payload


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.z.ai/api/paas/v4/fine_tuning/jobs",
        "https://api.z.ai/api/paas/v4/models/glm-5.3-flash/weights",
        "https://api.z.ai/api/paas/v4/files",
        "https://api.z.ai/api/paas/v4/chat/completions/train",
    ],
)
def test_manifest_rejects_an_endpoint_that_is_not_chat_completions(
    endpoint: str,
) -> None:
    with pytest.raises(ContractValidationError):
        AgentDeploymentManifest(
            provider=AGENT_PROVIDER,
            model_id=AGENT_MODEL_ID,
            endpoint=endpoint,
            revision=REVISION,
            qualified=True,
        )


def test_the_client_exposes_inference_and_nothing_else() -> None:
    methods = {
        name
        for name, member in inspect.getmembers(InferenceOnlyClient)
        if not name.startswith("_") and callable(member)
    }
    assert methods == {"complete"}


def test_the_transport_protocol_carries_one_inference_call() -> None:
    members = {
        name
        for name, _ in inspect.getmembers(ChatCompletionsTransport)
        if not name.startswith("_")
    }
    assert members == {"create"}


def test_every_request_is_a_chat_completion_for_the_pinned_model() -> None:
    transport = FakeTransport(responses=[_response(), _response()])
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(),
        transport=transport,
        api_key="secret",
        tool_schemas=({"name": "deep_read", "parameters": {}},),
    )

    client.complete([{"role": "user", "content": "hi"}], max_generation_tokens=64)
    client.complete([], max_generation_tokens=64)

    allowed = {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "top_p",
        "repetition_penalty",
        "seed",
        "n",
        "tools",
    }
    for payload in transport.calls:
        assert set(payload) <= allowed
        assert payload["model"] == AGENT_MODEL_ID


def test_the_earlier_module_path_is_the_same_owner() -> None:
    from research_agent.agents import client as earlier

    assert earlier.PinnedModelClient is InferenceOnlyClient
    assert earlier.AgentDeploymentManifest is AgentDeploymentManifest


def test_derive_request_seed_matches_the_shared_formula() -> None:
    expected = int.from_bytes(
        hashlib.sha256(f"{RUN_ID}:3:sampling-v1".encode("utf-8")).digest()[:4],
        "big",
    )
    assert derive_request_seed(RUN_ID, 3) == expected


def test_derive_request_seed_varies_by_turn_index() -> None:
    assert derive_request_seed(RUN_ID, 0) != derive_request_seed(RUN_ID, 1)


def test_manifest_rejects_a_provider_other_than_the_pinned_one() -> None:
    with pytest.raises(ContractValidationError):
        AgentDeploymentManifest(
            provider="openrouter",
            model_id=AGENT_MODEL_ID,
            endpoint=ENDPOINT,
            revision=REVISION,
            qualified=True,
        )


def test_manifest_rejects_a_model_other_than_the_pinned_one() -> None:
    with pytest.raises(ContractValidationError):
        AgentDeploymentManifest(
            provider=AGENT_PROVIDER,
            model_id="glm-4.6v",
            endpoint=ENDPOINT,
            revision=REVISION,
            qualified=True,
        )


def test_manifest_rejects_a_malformed_revision() -> None:
    with pytest.raises(ContractValidationError):
        _manifest(revision="not-a-revision")


def test_manifest_accepts_the_unpinned_revision_literal() -> None:
    manifest = _manifest(revision=UNPINNED_REVISION)
    assert manifest.revision == UNPINNED_REVISION


def test_client_refuses_an_unqualified_manifest_before_any_request() -> None:
    transport = FakeTransport(responses=[])
    with pytest.raises(DeploymentUnqualified):
        InferenceOnlyClient(
            run_id=RUN_ID,
            manifest=_manifest(qualified=False),
            transport=transport,
            api_key="secret",
        )
    assert transport.calls == []


def test_client_requires_a_nonempty_api_key() -> None:
    transport = FakeTransport(responses=[])
    with pytest.raises(ContractValidationError):
        InferenceOnlyClient(
            run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key=""
        )


def test_complete_sends_the_pinned_sampling_settings_and_derived_seed() -> None:
    transport = FakeTransport(responses=[_response()])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    client.complete([{"role": "user", "content": "hi"}], max_generation_tokens=512)

    assert len(transport.calls) == 1
    payload = transport.calls[0]
    assert payload["model"] == AGENT_MODEL_ID
    assert payload["max_tokens"] == 512
    assert payload["temperature"] == TEMPERATURE
    assert payload["top_p"] == TOP_P
    assert payload["repetition_penalty"] == REPETITION_PENALTY
    assert payload["n"] == 1
    assert payload["seed"] == derive_request_seed(RUN_ID, 0)


def test_complete_declares_the_given_tool_schemas() -> None:
    transport = FakeTransport(responses=[_response()])
    schema = {"name": "deep_read", "parameters": {"type": "object", "properties": {}}}
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(),
        transport=transport,
        api_key="secret",
        tool_schemas=(schema,),
    )

    client.complete([], max_generation_tokens=256)

    assert transport.calls[0]["tools"] == [{"type": "function", "function": schema}]


def test_complete_omits_tools_when_no_schemas_are_given() -> None:
    transport = FakeTransport(responses=[_response()])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    client.complete([], max_generation_tokens=256)

    assert "tools" not in transport.calls[0]


def test_complete_parses_structured_content_and_tool_calls() -> None:
    transport = FakeTransport(
        responses=[
            _response(
                content='{"note": "checking the figure", "intent": "inspect"}',
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "deep_read",
                            "arguments": '{"paper_id": "paper-a", "section_id": "results"}',
                        },
                    }
                ],
            )
        ]
    )
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    response = client.complete([], max_generation_tokens=256)

    assert isinstance(response, ModelResponse)
    assert response.content == {"note": "checking the figure", "intent": "inspect"}
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.tool_call_id == "call-1"
    assert call.name == "deep_read"
    assert call.arguments == {"paper_id": "paper-a", "section_id": "results"}
    assert response.generated_tokens == 20


def test_complete_records_usage_including_cached_input_tokens() -> None:
    transport = FakeTransport(
        responses=[
            _response(prompt_tokens=400, cached_tokens=340, completion_tokens=64)
        ]
    )
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    client.complete([], max_generation_tokens=256)

    assert len(client.usage) == 1
    usage = client.usage[0]
    assert usage.turn_index == 0
    assert usage.request_seed == derive_request_seed(RUN_ID, 0)
    assert usage.reported_model_id == AGENT_MODEL_ID
    assert usage.reported_revision == REVISION
    assert usage.input_tokens == 400
    assert usage.cached_input_tokens == 340
    assert usage.output_tokens == 64


def test_turn_index_and_request_seed_advance_across_calls() -> None:
    transport = FakeTransport(responses=[_response(), _response()])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    client.complete([], max_generation_tokens=256)
    client.complete([], max_generation_tokens=256)

    assert transport.calls[0]["seed"] == derive_request_seed(RUN_ID, 0)
    assert transport.calls[1]["seed"] == derive_request_seed(RUN_ID, 1)
    assert [usage.turn_index for usage in client.usage] == [0, 1]


def test_a_changed_model_id_fails_before_generation() -> None:
    transport = FakeTransport(responses=[_response(model="glm-4.6v")])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    with pytest.raises(DeploymentDrift):
        client.complete([], max_generation_tokens=256)

    assert client.usage == []
    assert client.turn_index == 0


def test_a_changed_revision_fails_when_the_manifest_pins_one() -> None:
    transport = FakeTransport(responses=[_response(revision="b" * 40)])
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(revision=REVISION),
        transport=transport,
        api_key="secret",
    )

    with pytest.raises(DeploymentDrift):
        client.complete([], max_generation_tokens=256)

    assert client.usage == []


def test_an_unpinned_manifest_accepts_whatever_revision_the_provider_reports() -> None:
    transport = FakeTransport(responses=[_response(revision="whatever-alias-today")])
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(revision=UNPINNED_REVISION),
        transport=transport,
        api_key="secret",
    )

    client.complete([], max_generation_tokens=256)

    assert client.usage[0].reported_revision == "whatever-alias-today"


def test_an_unpinned_manifest_still_refuses_a_changed_model_id() -> None:
    transport = FakeTransport(responses=[_response(model="glm-4.6v")])
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(revision=UNPINNED_REVISION),
        transport=transport,
        api_key="secret",
    )

    with pytest.raises(DeploymentDrift):
        client.complete([], max_generation_tokens=256)


def test_malformed_tool_call_arguments_are_rejected() -> None:
    transport = FakeTransport(
        responses=[
            _response(
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "deep_read", "arguments": "not json"},
                    }
                ]
            )
        ]
    )
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    with pytest.raises(ContractValidationError):
        client.complete([], max_generation_tokens=256)


def test_content_that_is_not_a_json_object_is_rejected() -> None:
    transport = FakeTransport(responses=[_response(content="plain text, not json")])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    with pytest.raises(ContractValidationError):
        client.complete([], max_generation_tokens=256)


def test_a_response_missing_its_model_identity_is_treated_as_drift() -> None:
    response = _response()
    del response["model"]
    transport = FakeTransport(responses=[response])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    with pytest.raises(DeploymentDrift):
        client.complete([], max_generation_tokens=256)


def test_a_response_without_exactly_one_choice_is_rejected() -> None:
    response = _response()
    response["choices"] = []
    transport = FakeTransport(responses=[response])
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    with pytest.raises(ContractValidationError):
        client.complete([], max_generation_tokens=256)


def test_the_response_carries_the_provider_usage_record() -> None:
    transport = FakeTransport(
        responses=[
            _response(prompt_tokens=400, cached_tokens=340, completion_tokens=64)
        ]
    )
    client = InferenceOnlyClient(
        run_id=RUN_ID, manifest=_manifest(), transport=transport, api_key="secret"
    )

    response = client.complete([], max_generation_tokens=256)

    assert response.usage == TokenUsage(input_tokens=400, output_tokens=64)


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"completion_tokens": 20},
        {"prompt_tokens": 100},
        {"prompt_tokens": "100", "completion_tokens": 20},
        {"prompt_tokens": 100, "completion_tokens": 20.5},
    ],
)
def test_a_missing_or_unparsable_usage_record_is_refused_not_read_as_zero(
    usage: dict[str, Any] | None,
) -> None:
    response = _response()
    if usage is None:
        del response["usage"]
    else:
        response["usage"] = usage
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(),
        transport=FakeTransport(responses=[response]),
        api_key="secret",
    )

    with pytest.raises(ContractValidationError):
        client.complete([], max_generation_tokens=256)

    assert client.usage == []
    assert client.turn_index == 0


@dataclass
class _Stub:
    """A local chat-completions stub: scripted replies, recorded requests."""

    replies: list[tuple[int, dict[str, Any], float]]
    requests: list[tuple[dict[str, str], bytes]] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def stub() -> Iterator[_Stub]:
    state = _Stub(replies=[])

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state.requests.append((dict(self.headers.items()), body))
            status, reply, delay = state.replies[len(state.requests) - 1]
            time.sleep(delay)
            encoded = json.dumps(reply).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except OSError:
                pass

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}/api/paas/v4/chat/completions"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def _transport(
    stub: _Stub, sleeps: list[float], *, timeout_seconds: float = 5.0
) -> HttpxChatCompletionsTransport:
    return HttpxChatCompletionsTransport(
        endpoint=stub.url,
        api_key="stub-key",
        timeout_seconds=timeout_seconds,
        sleep=sleeps.append,
    )


def test_the_transport_posts_the_payload_with_the_bearer_key(stub: _Stub) -> None:
    stub.replies = [(200, _response(), 0.0)]
    sleeps: list[float] = []
    payload = {"model": AGENT_MODEL_ID, "messages": [], "temperature": TEMPERATURE}

    body = _transport(stub, sleeps).create(payload=payload)

    assert body == _response()
    ((headers, sent),) = stub.requests
    assert headers["Authorization"] == "Bearer stub-key"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(sent) == payload
    assert sleeps == []


@pytest.mark.parametrize("status", [429, 503])
def test_an_explicit_429_or_503_is_retried_once_after_five_seconds(
    stub: _Stub, status: int
) -> None:
    stub.replies = [(status, {"error": "busy"}, 0.0), (200, _response(), 0.0)]
    sleeps: list[float] = []

    body = _transport(stub, sleeps).create(payload={"messages": []})

    assert body["usage"] == _response()["usage"]
    assert len(stub.requests) == 2
    assert sleeps == [RETRY_AFTER_SECONDS] == [5.0]


def test_a_second_rejection_is_not_retried_again(stub: _Stub) -> None:
    stub.replies = [(429, {}, 0.0), (503, {}, 0.0), (200, _response(), 0.0)]
    sleeps: list[float] = []

    with pytest.raises(ProviderRejected) as rejected:
        _transport(stub, sleeps).create(payload={"messages": []})

    assert rejected.value.status_code == 503
    assert len(stub.requests) == 2
    assert sleeps == [5.0]


@pytest.mark.parametrize("status", [400, 401, 500, 502])
def test_any_other_rejection_is_never_retried(stub: _Stub, status: int) -> None:
    stub.replies = [(status, {}, 0.0), (200, _response(), 0.0)]
    sleeps: list[float] = []

    with pytest.raises(ProviderRejected):
        _transport(stub, sleeps).create(payload={"messages": []})

    assert len(stub.requests) == 1
    assert sleeps == []


def test_a_timeout_is_ambiguous_and_never_retried(stub: _Stub) -> None:
    stub.replies = [(200, _response(), 1.0), (200, _response(), 0.0)]
    sleeps: list[float] = []

    with pytest.raises(AmbiguousCompletion):
        _transport(stub, sleeps, timeout_seconds=0.2).create(payload={"messages": []})

    assert len(stub.requests) == 1
    assert sleeps == []


def test_the_client_over_the_transport_records_the_returned_identity_and_usage(
    stub: _Stub,
) -> None:
    stub.replies = [
        (
            200,
            _response(prompt_tokens=300, cached_tokens=120, completion_tokens=40),
            0.0,
        )
    ]
    client = InferenceOnlyClient(
        run_id=RUN_ID,
        manifest=_manifest(),
        transport=_transport(stub, []),
        api_key="stub-key",
    )

    response = client.complete(
        [{"role": "user", "content": "hi"}], max_generation_tokens=64
    )

    assert response.usage == TokenUsage(input_tokens=300, output_tokens=40)
    (usage,) = client.usage
    assert (usage.reported_model_id, usage.reported_revision) == (
        AGENT_MODEL_ID,
        REVISION,
    )
    assert usage.cached_input_tokens == 120
    ((_, sent),) = stub.requests
    assert json.loads(sent)["seed"] == derive_request_seed(RUN_ID, 0)


@pytest.fixture
def processor_dir(tmp_path: Path) -> Path:
    """A local word-level tokenizer: one token per word or punctuation run."""

    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast

    tokenizer = Tokenizer(models.WordLevel(vocab={"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    fast = PreTrainedTokenizerFast(  # type: ignore[no-untyped-call]
        tokenizer_object=tokenizer, unk_token="[UNK]"
    )
    fast.save_pretrained(tmp_path)
    return tmp_path


def test_the_counter_counts_the_whole_serialized_conversation(
    processor_dir: Path,
) -> None:
    counter = load_token_counter(processor_dir)
    first = Message("user", {"content": "a b"})
    second = Message("assistant", {"content": "c"})

    # The first message serializes to ten word and punctuation runs; the
    # second adds eight.
    assert counter([first]) == 10
    assert counter([first, second]) == 18


def test_the_counter_is_the_processor_count_not_a_word_count() -> None:
    class Characters:
        def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
            assert add_special_tokens is False
            return [ord(character) for character in text]

    counter = ProcessorTokenCounter(Characters())
    message = Message("user", {"content": "a b"})

    assert counter([message]) == len('[{"content":"a b","role":"user"}]')


def test_the_counter_never_downloads_a_processor(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_token_counter(tmp_path / "absent")
