"""One run-time ask as a Jev question and its answer (decision 0031, #300).

The ``ask`` tool's three kinds are Jev's three primitives under names the
agent sees: ``yes_no`` is a ``noul``, ``choose`` a ``choice`` over the
agent's named options and ``rate`` a ``score`` over its ordered scale. One
ask is one question, keyed ``q``, over the state the tool service resolved
from the run's own snapshot (or the agent's own bounded words), with the
optional claim stated in the question's instructions.

The answer is validated as strictly as a card assessment's (RD-19): the
primitive the response names, a probability for every option or scale
point within the provider's rounding, and nothing else. Each answer also
renders as one sentence the agent reads beside it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from research_agent.assessments.schemas import PROBABILITY_TOLERANCE, InvalidResponse
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
    sha256_hex,
)

__all__ = [
    "ASK_PRIMITIVES",
    "ask_question",
    "ask_request_body",
    "ask_work_key",
    "ask_worst_case_micros",
    "parse_ask_response",
    "ask_sentence",
]

#: The agent's kind and the Jev primitive it is sent as.
ASK_PRIMITIVES = {"yes_no": "noul", "choose": "choice", "rate": "score"}

_QUESTION_KEY = "q"


def ask_question(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """The one wire question an admitted ask's arguments make."""

    instructions: str = arguments["question"]
    if arguments["claim"] is not None:
        instructions = f"{instructions}\nClaim under test: {arguments['claim']}"
    kind = arguments["kind"]
    question: dict[str, Any] = {
        "type": ASK_PRIMITIVES[kind],
        "instructions": instructions,
    }
    if kind == "choose":
        question["criteria"] = dict(arguments["options"])
    elif kind == "rate":
        question["criteria"] = list(arguments["scale"])
    return question


def ask_request_body(model: str, state: str, question: Mapping[str, Any]) -> bytes:
    """The exact request: the configured model, the resolved state, one question."""

    return canonical_json(
        {"model": model, "state": state, "questions": {_QUESTION_KEY: dict(question)}}
    )


def ask_work_key(run_id: str, body: bytes, provider_config_hash: str) -> str:
    """One run's ask of exactly these request bytes under this configuration."""

    return sha256_hex(
        f"ask:{run_id}:{sha256_hex(body)}:{provider_config_hash}".encode()
    )


def ask_worst_case_micros(body: bytes, price_micros_per_million_tokens: int) -> int:
    """The most one ask can cost: no more input tokens than request bytes."""

    return -(-len(body) * price_micros_per_million_tokens // 1_000_000)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidResponse("a probability is not a number")
    if not math.isfinite(value):
        raise InvalidResponse("a probability is not finite")
    return float(value)


def _probability(value: object) -> float:
    number = _number(value)
    if not 0 <= number <= 1:
        raise InvalidResponse("a probability is outside [0, 1]")
    return number


def _distribution(value: object, keys: tuple[str, ...]) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise InvalidResponse("probabilities must name every option")
    distribution = {key: _probability(value[key]) for key in keys}
    if abs(sum(distribution.values()) - 1.0) > PROBABILITY_TOLERANCE:
        raise InvalidResponse("probabilities must sum to one")
    return distribution


def _confidence(answer: Mapping[str, Any]) -> float | None:
    value = answer.get("confidence")
    return None if value is None else _probability(value)


def _keys(answer: object, primitive: str, required: set[str]) -> dict[str, Any]:
    if not isinstance(answer, dict):
        raise InvalidResponse("answer must be an object")
    if answer.get("type") != primitive:
        raise InvalidResponse(f"answer is not a {primitive}")
    if not required <= set(answer) <= required | {"confidence"}:
        raise InvalidResponse("answer keys differ")
    return answer


def parse_ask_response(
    arguments: Mapping[str, Any], response: bytes
) -> tuple[str | None, dict[str, Any]]:
    """The returned model identity and the ask's answer, or InvalidResponse.

    ``yes_no`` answers ``{answer, p_yes}``; ``choose`` answers ``{answer,
    confidence, probabilities}`` keyed by option name; ``rate`` answers
    ``{answer, label, confidence, probabilities}`` with the scale point
    nearest the provider's probability-weighted score as ``answer``.
    """

    try:
        value = canonical_loads(response)
    except CanonicalJsonError as error:
        raise InvalidResponse("response is not JSON") from error
    if not isinstance(value, dict):
        raise InvalidResponse("response must be an object")
    model = value.get("model")
    if model is not None and not isinstance(model, str):
        raise InvalidResponse("model must be a string")
    answers = value.get("answers")
    if not isinstance(answers, dict) or set(answers) != {_QUESTION_KEY}:
        raise InvalidResponse("answers must name exactly the one question")
    raw = answers[_QUESTION_KEY]
    kind = arguments["kind"]
    if kind == "yes_no":
        answer = _keys(raw, "noul", {"type", "noul"})
        if "confidence" in answer:
            raise InvalidResponse("answer keys differ")
        p_yes = _probability(answer["noul"])
        return model, {"answer": "yes" if p_yes >= 0.5 else "no", "p_yes": p_yes}
    if kind == "choose":
        names = tuple(name for name, _ in arguments["options"])
        answer = _keys(raw, "choice", {"type", "choice", "probabilities"})
        if answer["choice"] not in names:
            raise InvalidResponse("choice is not one of the options")
        return model, {
            "answer": answer["choice"],
            "confidence": _confidence(answer),
            "probabilities": _distribution(answer["probabilities"], names),
        }
    scale: tuple[str, ...] = arguments["scale"]
    points = tuple(str(point) for point in range(len(scale)))
    answer = _keys(raw, "score", {"type", "score", "legend", "probabilities"})
    legend = answer["legend"]
    if not isinstance(legend, dict) or tuple(legend.get(p) for p in points) != scale:
        raise InvalidResponse("legend differs from the scale")
    score = _number(answer["score"])
    if not 0 <= score <= len(scale) - 1:
        raise InvalidResponse("score must lie on the scale")
    distribution = _distribution(answer["probabilities"], points)
    index = math.floor(score + 0.5)
    return model, {
        "answer": index,
        "label": scale[index],
        "confidence": _confidence(answer),
        "probabilities": [distribution[point] for point in points],
    }


def ask_sentence(kind: str, answer: Mapping[str, Any]) -> str:
    """The answer as the one sentence appended to the tool result."""

    if kind == "yes_no":
        return f"Jev answers {answer['answer']} (p_yes {answer['p_yes']:.2f})."
    confidence = answer["confidence"]
    held = "" if confidence is None else f" with confidence {confidence:.2f}"
    if kind == "choose":
        return f"Jev chooses {answer['answer']}{held}."
    return f"Jev rates it {answer['answer']}, {answer['label']!r}{held}."
