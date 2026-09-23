import copy
import json
from pathlib import Path
from typing import Any

import pytest

from research_agent.assessments.schemas import (
    InvalidResponse,
    JevAvailable,
    JevUnavailable,
    parse_field_answers,
    result_from_json,
)
from research_agent.contracts.assessments import FIELD_IDS, JevProviderIdentity
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.primitives import ContractValidationError

_RECORDED = Path(__file__).parents[1] / "fixtures" / "jev" / "systemone-response.json"


def _answers() -> dict[str, Any]:
    body: dict[str, Any] = json.loads(_RECORDED.read_text(encoding="utf-8"))
    answers: dict[str, Any] = copy.deepcopy(body["answers"])
    return answers


def _identity() -> JevProviderIdentity:
    return JevProviderIdentity(
        "typesafe",
        "typesafeai/jev-latest",
        "jev-1.13.0",
        "jev-1.13.0",
        "immutable_revision",
        "c" * 64,
        "d" * 64,
    )


def test_a_recorded_response_parses_with_every_distribution_in_registry_order() -> None:
    fields = parse_field_answers(_answers())
    assert tuple(item.field_id for item in fields) == FIELD_IDS
    primary = fields[0]
    assert primary.selected_category == "method_system"
    assert primary.distribution[0].probability == pytest.approx(0.72)
    assert primary.provider_confidence == pytest.approx(0.81)


def test_low_confidence_and_uncertain_categories_stay_valid_answers() -> None:
    fields = {item.field_id: item for item in parse_field_answers(_answers())}
    assert fields["limitations_disclosure"].provider_confidence == pytest.approx(0.1)
    assert fields["limitations_disclosure"].selected_category == "not_reported"
    beyond = fields["evaluation_beyond_main_setting"]
    assert beyond.selected_category == "insufficient_information"


def test_the_provider_choice_is_kept_not_recomputed_as_argmax() -> None:
    answers = _answers()
    answers["limitations_disclosure"]["choice"] = "concrete_limitation"
    fields = {item.field_id: item for item in parse_field_answers(answers)}
    assert fields["limitations_disclosure"].selected_category == "concrete_limitation"


def test_a_confidence_the_interface_does_not_return_is_null_not_invented() -> None:
    answers = _answers()
    del answers["comparative_evaluation"]["confidence"]
    fields = {item.field_id: item for item in parse_field_answers(answers)}
    assert fields["comparative_evaluation"].provider_confidence is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a["uncertainty_reporting"]["probabilities"].update(
            {"reported": float("nan")}
        ),
        lambda a: a["uncertainty_reporting"]["probabilities"].pop("not_applicable"),
        lambda a: a["uncertainty_reporting"]["probabilities"].update(
            {"reported": 0.56}
        ),
        lambda a: a["uncertainty_reporting"]["probabilities"].update(
            {"reported": -0.05, "not_reported": 0.9}
        ),
        lambda a: a["uncertainty_reporting"].update({"confidence": 1.5}),
        lambda a: a["uncertainty_reporting"]["probabilities"].update(
            {"reported": "0.55"}
        ),
        lambda a: a["limitations_disclosure"]["probabilities"].update(
            {"not_applicable": 0.0}
        ),
        lambda a: a["limitations_disclosure"].update({"choice": "not_applicable"}),
        lambda a: a.pop("theoretical_support"),
        lambda a: a.update({"overall_quality": a["comparative_evaluation"]}),
        lambda a: a["primary_contribution"].update({"rationale": "because"}),
    ],
    ids=[
        "nan",
        "missing_category",
        "sum_1_01",
        "negative",
        "confidence_out_of_range",
        "string_probability",
        "borrowed_category",
        "borrowed_choice",
        "missing_field",
        "extra_field",
        "extra_key",
    ],
)
def test_a_malformed_answer_invalidates_the_whole_assessment(mutate: Any) -> None:
    answers = _answers()
    mutate(answers)
    with pytest.raises(InvalidResponse):
        parse_field_answers(answers)


def test_available_and_unavailable_results_round_trip_and_stay_closed() -> None:
    available = JevAvailable(
        fields=parse_field_answers(_answers()),
        input_hash="1" * 64,
        rubric_hash="2" * 64,
        provider_identity=_identity(),
        sanitized_request_hash="3" * 64,
        sanitized_response_hash="4" * 64,
        computed_at="2026-09-23T00:00:00.000000Z",
        smoke_report_hash=None,
    )
    assert result_from_json(available.to_canonical_json()) == available
    timeout = JevUnavailable(
        reason="timeout_ambiguous",
        input_hash="1" * 64,
        rubric_hash="2" * 64,
        provider_identity=None,
        sanitized_request_hash="3" * 64,
        sanitized_response_hash=None,
        billing_state="uncertain",
        recorded_at="2026-09-23T00:00:30.000000Z",
    )
    assert result_from_json(timeout.to_canonical_json()) == timeout
    raw = canonical_loads(timeout.to_canonical_json())
    assert isinstance(raw, dict)
    raw["fields"] = available.to_dict()["fields"]
    with pytest.raises(ContractValidationError):
        result_from_json(canonical_json(raw))


def test_an_unavailable_result_has_no_categories_or_numbers() -> None:
    with pytest.raises(ContractValidationError):
        JevUnavailable(
            reason="not_a_reason",
            input_hash=None,
            rubric_hash="2" * 64,
            provider_identity=None,
            sanitized_request_hash=None,
            sanitized_response_hash=None,
            billing_state="no_attempt",
            recorded_at="2026-09-23T00:00:00.000000Z",
        )
    assert "fields" not in JevUnavailable.__slots__
