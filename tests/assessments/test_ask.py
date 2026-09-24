"""One ask as a Jev question and its answer, against recorded answers (#300).

Each kind's answer is taken from a recorded live response in
``tests/fixtures/jev/``, re-keyed to the one question an ask sends, so the
parser is held to the wire shape Jev returns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_agent.assessments.ask import (
    ask_question,
    ask_request_body,
    ask_sentence,
    ask_work_key,
    ask_worst_case_micros,
    parse_ask_response,
)
from research_agent.assessments.schemas import InvalidResponse
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.tools import ToolRequest

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "jev"


def _recorded(name: str) -> dict[str, Any]:
    body = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    return dict(body["answers"])


_ANSWERS = _recorded("systemone-v2-response.json")
_NOVELTY = _ANSWERS["novelty_as_claimed"]
# A recorded four-option choice; an ask admits 2 to 6 options.
_LIMITATIONS = _recorded("systemone-response.json")["limitations_disclosure"]
RUN = "123e4567-e89b-42d3-a456-426614174000"
PAPER = "123e4567-e89b-42d3-a456-426614174001"


def _arguments(kind: str, **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "kind": kind,
        "question": "Does the passage support the claim?",
        "options": None,
        "scale": None,
        "about": {
            "paper_id": PAPER,
            "section": "abstract",
            "passage_id": None,
            "self": None,
        },
        "claim": None,
        **overrides,
    }
    return dict(ToolRequest.parse("ask", raw).arguments)


def _response(answer: dict[str, Any]) -> bytes:
    return canonical_json(
        {
            "model": "jev-1.13.0",
            "answers": {"q": answer},
            "usage": {"input_tokens": 412, "output_tokens": 9},
        }
    )


def _choose() -> dict[str, Any]:
    return _arguments(
        "choose",
        options=[
            {"name": name, "criterion": f"The limitations are {name}."}
            for name in sorted(_LIMITATIONS["probabilities"])
        ],
    )


def _rate() -> dict[str, Any]:
    legend = _NOVELTY["legend"]
    return _arguments("rate", scale=[legend[str(i)] for i in range(len(legend))])


def test_yes_no_is_a_noul_and_round_trips_the_recorded_answer() -> None:
    arguments = _arguments("yes_no", claim="Sparse probes recover syntax.")
    question = ask_question(arguments)
    assert question == {
        "type": "noul",
        "instructions": "Does the passage support the claim?\n"
        "Claim under test: Sparse probes recover syntax.",
    }

    model, answer = parse_ask_response(
        arguments, _response(_ANSWERS["claims_supported_by_evidence"])
    )

    assert model == "jev-1.13.0"
    assert answer == {"answer": "yes", "p_yes": 0.78}
    assert ask_sentence("yes_no", answer) == "Jev answers yes (p_yes 0.78)."
    _, low = parse_ask_response(
        arguments, _response(_ANSWERS["generalizes_beyond_main_setting"])
    )
    assert low["answer"] == "no"


def test_choose_is_a_choice_over_the_named_options() -> None:
    arguments = _choose()
    question = ask_question(arguments)
    assert question["type"] == "choice"
    assert set(question["criteria"]) == set(_LIMITATIONS["probabilities"])
    assert question["instructions"] == "Does the passage support the claim?"

    _, answer = parse_ask_response(arguments, _response(_LIMITATIONS))

    assert answer == {
        "answer": "not_reported",
        "confidence": 0.1,
        "probabilities": _LIMITATIONS["probabilities"],
    }
    assert (
        ask_sentence("choose", answer)
        == "Jev chooses not_reported with confidence 0.10."
    )


def test_rate_is_a_score_whose_answer_is_the_nearest_scale_point() -> None:
    arguments = _rate()
    question = ask_question(arguments)
    assert question["type"] == "score"
    assert question["criteria"] == list(arguments["scale"])

    _, answer = parse_ask_response(arguments, _response(_NOVELTY))

    # 1.03 is nearest point 1, which is also the most probable one.
    assert answer["answer"] == 1
    assert answer["label"] == _NOVELTY["legend"]["1"]
    assert answer["confidence"] == 0.7
    assert answer["probabilities"] == [0.15, 0.7, 0.12, 0.03]
    assert ask_sentence("rate", answer).startswith("Jev rates it 1, ")


@pytest.mark.parametrize(
    ("arguments", "answer"),
    [
        # A yes/no answered as another primitive.
        (lambda: _arguments("yes_no"), _LIMITATIONS),
        # A choice naming an option the ask never offered.
        (lambda: _choose(), {**_LIMITATIONS, "choice": "a_new_option"}),
        # A choice whose probabilities miss an option.
        (
            lambda: _choose(),
            {**_LIMITATIONS, "probabilities": {"not_reported": 1.0}},
        ),
        # A score whose legend is not the ask's scale.
        (
            lambda: _rate(),
            {**_NOVELTY, "legend": {**_NOVELTY["legend"], "0": "something else"}},
        ),
        # A score off the scale.
        (lambda: _rate(), {**_NOVELTY, "score": 3.5}),
        # An extra key.
        (lambda: _arguments("yes_no"), {"type": "noul", "noul": 0.5, "why": "x"}),
    ],
)
def test_an_answer_that_is_not_the_asked_shape_is_invalid(
    arguments: Any, answer: dict[str, Any]
) -> None:
    with pytest.raises(InvalidResponse):
        parse_ask_response(arguments(), _response(answer))


def test_a_response_answering_another_question_is_invalid() -> None:
    body = canonical_json({"model": "jev-1.13.0", "answers": _ANSWERS})
    with pytest.raises(InvalidResponse):
        parse_ask_response(_arguments("yes_no"), body)


def test_the_request_sends_the_resolved_state_and_one_question() -> None:
    question = ask_question(_arguments("yes_no"))
    body = ask_request_body("typesafeai/jev-latest", "The abstract.", question)

    assert canonical_loads(body) == {
        "model": "typesafeai/jev-latest",
        "state": "The abstract.",
        "questions": {"q": question},
    }
    # No more input tokens than request bytes, rounded up.
    assert ask_worst_case_micros(body, 50_000) == -(-len(body) * 50_000 // 1_000_000)


def test_the_work_key_is_one_runs_ask_of_exactly_these_bytes() -> None:
    body = ask_request_body("m", "state", ask_question(_arguments("yes_no")))
    other = ask_request_body("m", "other state", ask_question(_arguments("yes_no")))
    config = "c" * 64

    key = ask_work_key(RUN, body, config)

    assert key == ask_work_key(RUN, body, config)
    assert key != ask_work_key(RUN, other, config)
    assert key != ask_work_key("123e4567-e89b-42d3-a456-426614174999", body, config)
    assert key != ask_work_key(RUN, body, "d" * 64)
