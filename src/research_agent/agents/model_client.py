"""The inference-only agent model client (AG-01, FT-07, TDD-3.1.37, TDD-4.1.74).

One named provider, one pinned model, one endpoint: ``glm-5.3-flash``
served per-token by Z.ai's first-party API (Appendix A: Launch profile,
Pinned model choices; decision 0015). This client has no fallback URL,
provider or model. Before it will return a generated turn, it compares
the endpoint's own reported model id and revision against the qualified
deployment it was constructed with and refuses to proceed on drift or a
manifest that was never marked qualified; a failed check ends the run
rather than silently accepting output from a different deployment.

The client is inference only. Its one public operation is
:meth:`InferenceOnlyClient.complete`, its transport carries one call
(``create``) and the manifest refuses any endpoint that is not the
chat-completions route, so a training, fine-tuning or weight-access
request has no path through it. The request payload is built from a
fixed set of fields and never from caller-supplied keys.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from research_agent.agents.loop import ModelResponse, ToolCall
from research_agent.contracts.canonical import CanonicalJsonError, canonical_loads
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_https_url,
    validate_non_negative_int,
)

__all__ = [
    "AGENT_PROVIDER",
    "AGENT_MODEL_ID",
    "UNPINNED_REVISION",
    "CHAT_COMPLETIONS_PATH_SUFFIX",
    "SAMPLING_DOMAIN",
    "TEMPERATURE",
    "TOP_P",
    "REPETITION_PENALTY",
    "DeploymentDrift",
    "DeploymentUnqualified",
    "AgentDeploymentManifest",
    "ChatCompletionsTransport",
    "TurnUsage",
    "InferenceOnlyClient",
    "derive_request_seed",
]

# Decision 0015 (#129): the pinned launch agent model and its one named
# provider. Facts are read from the provider's own published API and model
# card, not from local execution (Appendix A).
AGENT_PROVIDER = "zai"
AGENT_MODEL_ID = "glm-5.3-flash"

#: Recorded when the provider exposes a mutable alias rather than an
#: immutable revision; never replaced by a fabricated hash (RD-19).
UNPINNED_REVISION = "unpinned"

#: The only route this client may address; a training, fine-tuning or
#: model-management route ends in something else (FT-07).
CHAT_COMPLETIONS_PATH_SUFFIX = "/chat/completions"

#: The literal domain Shared implementation rules mixes into every
#: request seed, alongside run_id and turn_index.
SAMPLING_DOMAIN = "sampling-v1"

TEMPERATURE = 0.7
TOP_P = 0.9
REPETITION_PENALTY = 1.0

_REVISION_LENGTH = 40
_REVISION_ALPHABET = frozenset("0123456789abcdef")


class DeploymentDrift(Exception):
    """The endpoint's reported model id or revision does not match the pinned manifest."""


class DeploymentUnqualified(Exception):
    """The deployment manifest was never marked qualified; this client refuses to run."""


def _validate_revision(value: object) -> str:
    if value == UNPINNED_REVISION:
        return UNPINNED_REVISION
    if (
        not isinstance(value, str)
        or len(value) != _REVISION_LENGTH
        or not _REVISION_ALPHABET.issuperset(value)
    ):
        raise ContractValidationError(
            f"revision must be {_REVISION_LENGTH} lowercase hexadecimal characters "
            f"or the literal {UNPINNED_REVISION!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class AgentDeploymentManifest:
    """The one qualified deployment :class:`InferenceOnlyClient` is pinned to.

    ``provider`` and ``model_id`` are fixed to the launch decision; only
    ``endpoint`` (the provider's actual wire route, a deployment binding)
    and ``revision`` (what the provider reported when this manifest was
    last confirmed) vary. ``qualified`` records whether this manifest's
    identity has itself been confirmed against the provider, mirroring
    :class:`research_agent.models.manifest.RepresentationManifest`.
    """

    provider: str
    model_id: str
    endpoint: str
    revision: str
    qualified: bool

    def __post_init__(self) -> None:
        if self.provider != AGENT_PROVIDER:
            raise ContractValidationError("provider must be the pinned launch provider")
        if self.model_id != AGENT_MODEL_ID:
            raise ContractValidationError("model_id must be the pinned launch model")
        validate_https_url(self.endpoint)
        if not urlsplit(self.endpoint).path.endswith(CHAT_COMPLETIONS_PATH_SUFFIX):
            raise ContractValidationError(
                "endpoint must be the chat-completions route; the agent model "
                "client has no route to training, fine-tuning or weights"
            )
        _validate_revision(self.revision)
        if not isinstance(self.qualified, bool):
            raise ContractValidationError("qualified must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "revision": self.revision,
            "qualified": self.qualified,
        }


class ChatCompletionsTransport(Protocol):
    """The provider's OpenAI-compatible chat-completions HTTP transport."""

    def create(self, *, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class TurnUsage:
    """Actual server-reported identity and token accounting for one turn.

    Recorded so a caller (the qualification battery, cost measurement)
    can read exactly what the provider billed and reported, rather than
    an estimate (Appendix A: Launch profile, Hosts/spend).
    """

    turn_index: int
    request_seed: int
    reported_model_id: str
    reported_revision: str | None
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


def derive_request_seed(run_id: str, turn_index: int) -> int:
    """The exact per-turn sampling seed (Shared implementation rules).

    First unsigned 32 bits of SHA-256 over ``run_id``, ``turn_index`` and
    the literal ``sampling-v1`` domain, colon-joined.
    """

    digest = hashlib.sha256(
        f"{run_id}:{turn_index}:{SAMPLING_DOMAIN}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big")


@dataclass(slots=True)
class InferenceOnlyClient:
    """The pinned agent model, reached only through Z.ai's chat-completions API.

    One instance serves one run: ``run_id`` is fixed at construction and
    an internal turn index advances by one on every :meth:`complete`
    call, exactly as the request-seed derivation above expects. The
    manifest must already be ``qualified``; otherwise construction refuses
    immediately rather than letting a run start against an unconfirmed
    deployment. Every response's reported model id and revision are then
    compared against the manifest before a
    :class:`~research_agent.agents.loop.ModelResponse` is produced, so a
    changed model id or revision fails before that turn's generation ever
    reaches the run. ``tool_schemas``, when given, is declared on every
    request exactly as received; the run's own allowlist (AG-14) still
    decides which of the model's resulting calls are ever dispatched.
    """

    run_id: str
    manifest: AgentDeploymentManifest
    transport: ChatCompletionsTransport
    api_key: str
    tool_schemas: tuple[dict[str, Any], ...] = ()
    turn_index: int = field(default=0, init=False)
    usage: list[TurnUsage] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if not self.manifest.qualified:
            raise DeploymentUnqualified(
                f"deployment {self.manifest.provider}/{self.manifest.model_id} "
                "is not marked qualified"
            )
        if not self.api_key:
            raise ContractValidationError("api_key must be nonempty")

    def complete(
        self, messages: list[dict[str, Any]], *, max_generation_tokens: int
    ) -> ModelResponse:
        turn_index = self.turn_index
        request_seed = derive_request_seed(self.run_id, turn_index)
        payload: dict[str, Any] = {
            "model": self.manifest.model_id,
            "messages": messages,
            "max_tokens": max_generation_tokens,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "repetition_penalty": REPETITION_PENALTY,
            "seed": request_seed,
            "n": 1,
        }
        if self.tool_schemas:
            payload["tools"] = [
                {"type": "function", "function": schema} for schema in self.tool_schemas
            ]
        raw = self.transport.create(payload=payload)
        reported_model_id, reported_revision = _read_identity(raw)
        self._verify_identity(reported_model_id, reported_revision)

        choice = _single_choice(raw)
        message = _require_dict(choice.get("message"), "choices[0].message")
        usage = raw.get("usage")
        usage = _require_dict(usage, "usage") if usage is not None else {}
        output_tokens = validate_non_negative_int(
            int(usage.get("completion_tokens", 0))
        )

        self.usage.append(
            TurnUsage(
                turn_index=turn_index,
                request_seed=request_seed,
                reported_model_id=reported_model_id,
                reported_revision=reported_revision,
                input_tokens=validate_non_negative_int(
                    int(usage.get("prompt_tokens", 0))
                ),
                cached_input_tokens=validate_non_negative_int(
                    int(usage.get("prompt_cache_hit_tokens", 0))
                ),
                output_tokens=output_tokens,
            )
        )
        self.turn_index += 1

        return ModelResponse(
            content=_parse_content(message.get("content")),
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            generated_tokens=output_tokens,
        )

    def _verify_identity(
        self, reported_model_id: str, reported_revision: str | None
    ) -> None:
        if reported_model_id != self.manifest.model_id:
            raise DeploymentDrift(
                f"endpoint reported model {reported_model_id!r}, "
                f"pinned deployment is {self.manifest.model_id!r}"
            )
        if self.manifest.revision != UNPINNED_REVISION and (
            reported_revision != self.manifest.revision
        ):
            raise DeploymentDrift(
                f"endpoint reported revision {reported_revision!r}, "
                f"pinned deployment is {self.manifest.revision!r}"
            )


def _read_identity(raw: dict[str, Any]) -> tuple[str, str | None]:
    model_id = raw.get("model")
    if not isinstance(model_id, str) or not model_id:
        raise DeploymentDrift("endpoint response is missing its model identity")
    revision = raw.get("system_fingerprint")
    if revision is not None and not isinstance(revision, str):
        raise ContractValidationError(
            "system_fingerprint must be a string when present"
        )
    return model_id, revision or None


def _single_choice(raw: dict[str, Any]) -> dict[str, Any]:
    choices = raw.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ContractValidationError("response must carry exactly one choice")
    return _require_dict(choices[0], "choices[0]")


def _require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{name} must be a JSON object")
    return value


def _parse_content(raw_content: object) -> dict[str, Any]:
    if raw_content is None:
        return {}
    if not isinstance(raw_content, str):
        raise ContractValidationError("message content must be a JSON string")
    try:
        parsed = canonical_loads(raw_content.encode("utf-8"))
    except CanonicalJsonError as error:
        raise ContractValidationError(
            f"message content is not valid JSON: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise ContractValidationError("message content must decode to a JSON object")
    return parsed


def _parse_tool_calls(raw_tool_calls: object) -> tuple[ToolCall, ...]:
    if raw_tool_calls is None:
        return ()
    if not isinstance(raw_tool_calls, list):
        raise ContractValidationError("message tool_calls must be a JSON array")
    calls = []
    for entry in raw_tool_calls:
        entry = _require_dict(entry, "tool_calls[]")
        tool_call_id = entry.get("id")
        function = _require_dict(entry.get("function"), "tool_calls[].function")
        name = function.get("name")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise ContractValidationError("tool_calls[].id must be a nonempty string")
        if not isinstance(name, str) or not name:
            raise ContractValidationError(
                "tool_calls[].function.name must be a nonempty string"
            )
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise ContractValidationError(
                "tool_calls[].function.arguments must be a JSON string"
            )
        try:
            parsed_arguments = canonical_loads(arguments.encode("utf-8"))
        except CanonicalJsonError as error:
            raise ContractValidationError(
                f"tool_calls[].function.arguments is not valid JSON: {error}"
            ) from error
        if not isinstance(parsed_arguments, dict):
            raise ContractValidationError(
                "tool_calls[].function.arguments must decode to a JSON object"
            )
        calls.append(ToolCall(tool_call_id, name, parsed_arguments))
    return tuple(calls)
