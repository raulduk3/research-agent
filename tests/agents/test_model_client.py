"""Tests for the inference-only agent model client (TDD-3.1.37, TDD-4.1.74)."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field
from typing import Any

import pytest

from research_agent.agents.model_client import (
    AGENT_MODEL_ID,
    AGENT_PROVIDER,
    REPETITION_PENALTY,
    TEMPERATURE,
    TOP_P,
    UNPINNED_REVISION,
    AgentDeploymentManifest,
    ChatCompletionsTransport,
    DeploymentDrift,
    DeploymentUnqualified,
    InferenceOnlyClient,
    derive_request_seed,
)
from research_agent.agents.loop import ModelResponse
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
