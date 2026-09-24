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

:class:`HttpxChatCompletionsTransport` is the production wire transport,
and :class:`ProcessorTokenCounter` counts the loop's context with the
pinned processor's tokenizer (TDD-3.1.52).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from research_agent.agents.loop import ModelResponse, TokenUsage, ToolCall
from research_agent.agents.messages import Message
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
)
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
    "REQUEST_TIMEOUT_SECONDS",
    "RETRYABLE_STATUS_CODES",
    "RETRY_AFTER_SECONDS",
    "DeploymentDrift",
    "DeploymentUnqualified",
    "ProviderRejected",
    "AmbiguousCompletion",
    "AgentDeploymentManifest",
    "ChatCompletionsTransport",
    "HttpxChatCompletionsTransport",
    "ProcessorTokenCounter",
    "load_token_counter",
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

#: The provider request timeout, inside the run's wall limit (TDD-3.1.52).
REQUEST_TIMEOUT_SECONDS = 120.0

#: Only an explicit, non-executed rejection with one of these statuses is
#: retried, once, after :data:`RETRY_AFTER_SECONDS` (TDD-3.1.52).
RETRYABLE_STATUS_CODES = frozenset({429, 503})
RETRY_AFTER_SECONDS = 5.0

_REVISION_LENGTH = 40
_REVISION_ALPHABET = frozenset("0123456789abcdef")


class DeploymentDrift(Exception):
    """The endpoint's reported model id or revision does not match the pinned manifest."""


class DeploymentUnqualified(Exception):
    """The deployment manifest was never marked qualified; this client refuses to run."""


class ProviderRejected(Exception):
    """The provider answered a non-success status; no completion was returned."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider answered HTTP {status_code}")
        self.status_code = status_code


class AmbiguousCompletion(Exception):
    """No answer arrived for a request that may have executed.

    A timeout or a lost connection. It is never retried: the provider may
    already have run and billed the request, so the run ends void instead
    of drawing a second sample (TDD-3.1.52).
    """


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


class HttpxChatCompletionsTransport:
    """The provider's chat-completions route over HTTP, one request per turn.

    Posts the client's payload to the one pinned *endpoint* with the bearer
    key, under :data:`REQUEST_TIMEOUT_SECONDS`. An explicit 429 or 503 is
    retried once after :data:`RETRY_AFTER_SECONDS`; any other non-success
    status raises :class:`ProviderRejected`. A timeout or a transport
    failure raises :class:`AmbiguousCompletion` and is never retried. The
    returned body is the provider's own JSON object, its usage record and
    model identity untouched, for :class:`InferenceOnlyClient` to verify.
    ``last_exchange_bytes`` is what the last :meth:`create` sent and
    received on the wire, bodies only, a retry's included (#330).
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ContractValidationError("api_key must be nonempty")
        self._endpoint = endpoint
        self._api_key = api_key
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout_seconds)
        self.last_exchange_bytes: tuple[int, int] | None = None

    def create(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        sent = len(canonical_json(payload))
        response = self._post(payload)
        exchanged = (sent, len(response.content))
        if response.status_code in RETRYABLE_STATUS_CODES:
            self._sleep(RETRY_AFTER_SECONDS)
            response = self._post(payload)
            exchanged = (exchanged[0] + sent, exchanged[1] + len(response.content))
        self.last_exchange_bytes = exchanged
        if not response.is_success:
            raise ProviderRejected(response.status_code)
        try:
            body = canonical_loads(response.content)
        except CanonicalJsonError as error:
            raise ContractValidationError(
                f"provider response is not valid JSON: {error}"
            ) from error
        return _require_dict(body, "provider response")

    def close(self) -> None:
        self._client.close()

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(
                self._endpoint,
                content=canonical_json(payload),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TransportError as error:
            raise AmbiguousCompletion(str(error)) from error


class _Tokenizer(Protocol):
    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass(frozen=True, slots=True)
class ProcessorTokenCounter:
    """Counts a conversation's context tokens with the pinned processor's tokenizer.

    The count covers the exact canonical serialization of the whole ordered
    conversation, the bytes :func:`~research_agent.agents.messages.prepare_request`
    sends, so the loop reserves context from the processor's own count
    rather than an estimate (TDD-3.1.52).
    """

    tokenizer: _Tokenizer

    def __call__(self, messages: Sequence[Message]) -> int:
        text = canonical_json([message.to_dict() for message in messages])
        return len(
            self.tokenizer.encode(text.decode("utf-8"), add_special_tokens=False)
        )


def load_token_counter(processor_dir: Path) -> ProcessorTokenCounter:
    """Load the pinned processor's tokenizer from a local directory, never downloading."""

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(processor_dir), local_files_only=True)
    return ProcessorTokenCounter(tokenizer)


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
    #: When the transport call began, in seconds since the epoch, and how
    #: long it took, retries included (#330).
    started_at: float = 0.0
    latency_ms: int = 0
    bytes_sent: int = 0
    #: ``None`` when the transport does not report what it received.
    bytes_received: int | None = None


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
        started_at = time.time()
        began = time.monotonic()
        raw = self.transport.create(payload=payload)
        latency_ms = int((time.monotonic() - began) * 1000)
        exchanged = getattr(self.transport, "last_exchange_bytes", None)
        bytes_sent, bytes_received = (
            exchanged if exchanged is not None else (len(canonical_json(payload)), None)
        )
        reported_model_id, reported_revision = _read_identity(raw)
        self._verify_identity(reported_model_id, reported_revision)

        choice = _single_choice(raw)
        message = _require_dict(choice.get("message"), "choices[0].message")
        # The usage record is what the run's cost settles against; a missing
        # or unparsable one is refused, never read as zero (TDD Spending authorization).
        usage = _require_dict(raw.get("usage"), "usage")
        input_tokens = validate_non_negative_int(usage.get("prompt_tokens"))
        output_tokens = validate_non_negative_int(usage.get("completion_tokens"))
        cached_input_tokens = validate_non_negative_int(
            usage.get("prompt_cache_hit_tokens", 0)
        )
        content = _parse_content(message.get("content"))
        tool_calls = _parse_tool_calls(message.get("tool_calls"))

        self.usage.append(
            TurnUsage(
                turn_index=turn_index,
                request_seed=request_seed,
                reported_model_id=reported_model_id,
                reported_revision=reported_revision,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                started_at=started_at,
                latency_ms=latency_ms,
                bytes_sent=bytes_sent,
                bytes_received=bytes_received,
            )
        )
        self.turn_index += 1

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            generated_tokens=output_tokens,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
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
