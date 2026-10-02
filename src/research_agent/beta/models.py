"""The model seam: one protocol the harness calls, one wire client behind it.

The harness builds messages and tool schemas in the chat-completions shape
and reads back text, tool calls and token usage. The shipped client posts to
the one configured endpoint; tests pass a scripted client instead.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from research_agent.beta.config import ModelProvider

Message = dict[str, Any]
ToolSchema = dict[str, Any]


class ModelCallFailed(Exception):
    """The provider did not return a usable completion."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    #: ``None`` when the provider's argument text was not a JSON object.
    arguments: dict[str, Any] | None
    raw_arguments: str


@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: int
    output_tokens: int
    #: False when the provider sent no usage and the counts are estimates.
    usage_reported: bool
    model: str
    finish_reason: str
    #: The provider's own account of its reasoning, when it returns one. It
    #: is kept for the trace and never sent back to the model.
    reasoning: str = ""


class ModelClient(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ModelResponse: ...


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> ToolSchema:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def assistant_message(response: ModelResponse) -> Message:
    """The assistant turn to carry forward, tool calls included verbatim."""
    message: Message = {"role": "assistant", "content": response.text}
    if response.tool_calls:
        if not response.text:
            message["content"] = None
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.raw_arguments},
            }
            for call in response.tool_calls
        ]
    return message


def _characters(messages: Sequence[Message]) -> int:
    return sum(len(json.dumps(message)) for message in messages)


class ChatCompletionsClient:
    """Posts one completion request to the configured chat-completions route."""

    def __init__(
        self, provider: ModelProvider, transport: httpx.BaseTransport | None = None
    ):
        self._provider = provider
        self._http = httpx.Client(timeout=provider.timeout_seconds, transport=transport)

    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self._provider.model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = list(tools)
        if self._provider.send_max_tokens:
            payload["max_tokens"] = max_output_tokens
        try:
            reply = self._http.post(
                self._provider.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {self._provider.api_key}"},
            )
            reply.raise_for_status()
            body = reply.json()
            choice = body["choices"][0]
            message = choice["message"]
        except httpx.HTTPStatusError as exc:
            raise ModelCallFailed(
                f"provider answered {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelCallFailed(
                f"provider call failed: {type(exc).__name__}"
            ) from exc

        calls: list[ToolCall] = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            function = raw.get("function") or {}
            text = function.get("arguments") or "{}"
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            calls.append(
                ToolCall(
                    id=str(raw.get("id") or f"call-{index}"),
                    name=str(function.get("name") or ""),
                    arguments=parsed if isinstance(parsed, dict) else None,
                    raw_arguments=str(text),
                )
            )
        content = message.get("content") or ""
        usage = body.get("usage") or {}
        reported = "prompt_tokens" in usage and "completion_tokens" in usage
        return ModelResponse(
            text=content if isinstance(content, str) else json.dumps(content),
            tool_calls=tuple(calls),
            # Without reported usage the counts are a high estimate from length.
            input_tokens=int(usage["prompt_tokens"])
            if reported
            else -(-_characters(messages) // 3),
            output_tokens=int(usage["completion_tokens"])
            if reported
            else -(-len(json.dumps(message)) // 3),
            usage_reported=reported,
            model=str(body.get("model") or self._provider.model),
            finish_reason=str(choice.get("finish_reason") or ""),
            reasoning=str(message.get("reasoning_content") or ""),
        )
