import copy
import json
from pathlib import Path
from typing import Any

import pytest

from research_agent.assessments.rubric import Rubric
from research_agent.assessments.schemas import (
    InvalidResponse,
    JevAvailable,
    JevFieldResult,
    JevNoulResult,
    JevScoreResult,
    JevUnavailable,
    fields_from_dict,
    parse_field_answers,
    result_from_json,
)
from research_agent.contracts.assessments import (
    FIELD_IDS,
    V1_FIELD_IDS,
    JevProviderIdentity,
    ScoreQuestion,
)
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.primitives import ContractValidationError

_RECORDED = Path(__file__).parents[1] / "fixtures" / "jev" / "systemone-response.json"
_RECORDED_V2 = (
    Path(__file__).parents[1] / "fixtures" / "jev" / "systemone-v2-response.json"
)
_V1 = Rubric.v1().record
_V2 = Rubric.launch().record


def _answers() -> dict[str, Any]:
    body: dict[str, Any] = json.loads(_RECORDED.read_text(encoding="utf-8"))
    answers: dict[str, Any] = copy.deepcopy(body["answers"])
    return answers


def _v2_answers() -> dict[str, Any]:
    body: dict[str, Any] = json.loads(_RECORDED_V2.read_text(encoding="utf-8"))
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
    fields = parse_field_answers(_answers(), _V1)
    assert tuple(item.field_id for item in fields) == V1_FIELD_IDS
    primary = fields[0]
    assert isinstance(primary, JevFieldResult)
    assert primary.selected_category == "method_system"
    assert primary.distribution[0].probability == pytest.approx(0.72)
    assert primary.provider_confidence == pytest.approx(0.81)


def test_low_confidence_and_uncertain_categories_stay_valid_answers() -> None:
    fields = {item.field_id: item for item in parse_field_answers(_answers(), _V1)}
    assert fields["limitations_disclosure"].provider_confidence == pytest.approx(0.1)
    assert fields["limitations_disclosure"].selected_category == "not_reported"
    beyond = fields["evaluation_beyond_main_setting"]
    assert beyond.selected_category == "insufficient_information"


def test_the_provider_choice_is_kept_not_recomputed_as_argmax() -> None:
    answers = _answers()
    answers["limitations_disclosure"]["choice"] = "concrete_limitation"
    fields = {item.field_id: item for item in parse_field_answers(answers, _V1)}
    assert fields["limitations_disclosure"].selected_category == "concrete_limitation"


def test_a_confidence_the_interface_does_not_return_is_null_not_invented() -> None:
    answers = _answers()
    del answers["comparative_evaluation"]["confidence"]
    fields = {item.field_id: item for item in parse_field_answers(answers, _V1)}
    assert fields["comparative_evaluation"].provider_confidence is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a["uncertainty_reporting"]["probabilities"].update(
            {"reported": float("nan")}
        ),
        lambda a: a["uncertainty_reporting"]["probabilities"].pop("not_applicable"),
        lambda a: a["uncertainty_reporting"]["probabilities"].update(
            {"reported": 0.65}
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
        "sum_1_10",
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
        parse_field_answers(answers, _V1)


def test_available_and_unavailable_results_round_trip_and_stay_closed() -> None:
    available = JevAvailable(
        fields=parse_field_answers(_answers(), _V1),
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


def test_a_live_shaped_answer_decodes_and_a_non_choice_type_is_refused() -> None:
    """Checked against the live service on 2026-09-23: every field answer
    carries ``type: "choice"`` beside choice, confidence and probabilities.
    The prohibited alternative is the exact key set without ``type``, which
    refused every real response as "answer keys differ"."""
    import copy
    import json
    from pathlib import Path

    from research_agent.assessments.schemas import InvalidResponse, parse_field_answers

    fixture = json.loads(Path("tests/fixtures/jev/systemone-response.json").read_text())
    answers = fixture["answers"]
    assert all(answer["type"] == "choice" for answer in answers.values())
    parsed = parse_field_answers(answers, _V1)
    assert len(parsed) == 8
    untyped = {
        k: {kk: vv for kk, vv in v.items() if kk != "type"} for k, v in answers.items()
    }
    assert len(parse_field_answers(untyped, _V1)) == 8
    wrong = copy.deepcopy(answers)
    next(iter(wrong.values()))["type"] = "score"
    with pytest.raises(InvalidResponse, match="not a choice"):
        parse_field_answers(wrong, _V1)


def test_a_two_decimal_distribution_summing_to_0_99_decodes_and_is_not_renormalized() -> (
    None
):
    """Checked live 2026-09-23: the provider rounds each probability to two
    decimals, so a five-way distribution came back summing to 0.99. The
    prohibited alternatives are refusing it (1e-6 tolerance refused six of
    sixty real papers) and renormalizing it (the contract records what was
    sent)."""
    import json
    from pathlib import Path

    from research_agent.assessments.schemas import InvalidResponse, parse_field_answers

    answers = json.loads(
        Path("tests/fixtures/jev/systemone-response.json").read_text()
    )["answers"]
    field = "uncertainty_reporting"
    cats = list(answers[field]["probabilities"])
    rounded = {c: 0.0 for c in cats}
    rounded[cats[0]] = 0.97
    rounded[cats[1]] = 0.02  # sums to 0.99
    answers[field]["probabilities"] = rounded
    answers[field]["choice"] = cats[0]
    parsed = {f.field_id: f for f in parse_field_answers(answers, _V1)}
    recorded = {c.category_id: c.probability for c in parsed[field].distribution}
    assert recorded[cats[0]] == 0.97 and recorded[cats[1]] == 0.02
    assert abs(sum(recorded.values()) - 0.99) < 1e-9, (
        "recorded as sent, not renormalized"
    )
    answers[field]["probabilities"][cats[0]] = 0.5  # sums to 0.52: not rounding
    with pytest.raises(InvalidResponse, match="sum to one"):
        parse_field_answers(answers, _V1)


def test_the_calibrated_counter_over_counts_every_measured_input() -> None:
    from research_agent.assessments.tokens import CalibratedCounter

    counter = CalibratedCounter()
    # 42,067 bytes of real paper cost 14,398 tokens at the gateway; the counter must say more.
    assert counter.count("x" * 42_067) >= 14_398
    assert counter.count("") == 0


def test_a_v2_response_decodes_each_field_in_its_primitive() -> None:
    fields = parse_field_answers(_v2_answers(), _V2)
    assert tuple(item.field_id for item in fields) == FIELD_IDS
    primary, rigor = fields[0], fields[1]
    assert isinstance(primary, JevFieldResult)
    assert primary.selected_category == "method_system"
    assert isinstance(rigor, JevScoreResult)
    assert rigor.score == 3
    assert rigor.distribution == (0.01, 0.04, 0.2, 0.6, 0.15)
    assert rigor.provider_confidence == pytest.approx(0.64)
    question = _V2.question("evaluation_rigor")
    assert isinstance(question, ScoreQuestion)
    assert rigor.legend == question.criteria
    stated = fields[-1]
    assert isinstance(stated, JevNoulResult)
    assert stated.probability == 1.0
    assert stated.statement in _V2.question("open_problems_stated").question


def test_a_v1_response_is_refused_under_v2_and_v2_under_v1() -> None:
    with pytest.raises(InvalidResponse):
        parse_field_answers(_answers(), _V2)
    with pytest.raises(InvalidResponse):
        parse_field_answers(_v2_answers(), _V1)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a["evaluation_rigor"]["legend"].update({"2": "Some baselines."}),
        lambda a: a["evaluation_rigor"]["legend"].pop("4"),
        lambda a: a["limitations_candor"].update({"score": 4}),
        lambda a: a["limitations_candor"].update({"score": 1.0}),
        lambda a: a["limitations_candor"].update({"score": True}),
        lambda a: a["novelty_as_claimed"]["probabilities"].update({"1": 0.2}),
        lambda a: a["novelty_as_claimed"]["probabilities"].pop("3"),
        lambda a: a["evaluation_rigor"].update({"type": "choice"}),
        lambda a: a["claims_supported_by_evidence"].update({"noul": 1.2}),
        lambda a: a["claims_supported_by_evidence"].update({"noul": -0.01}),
        lambda a: a["claims_supported_by_evidence"].update({"noul": float("nan")}),
        lambda a: a["claims_supported_by_evidence"].update({"noul": "0.5"}),
        lambda a: a["reproducible_from_materials"].update({"confidence": 0.5}),
        lambda a: a["reproducible_from_materials"].pop("type"),
        lambda a: a.update({"open_problems_stated": {"type": "noul", "choice": "yes"}}),
        lambda a: a.pop("generalizes_beyond_main_setting"),
    ],
    ids=[
        "legend_differs",
        "legend_missing_point",
        "score_off_scale",
        "score_not_int",
        "score_bool",
        "score_sum_off",
        "score_missing_point",
        "score_as_choice",
        "noul_above_one",
        "noul_below_zero",
        "noul_nan",
        "noul_string",
        "noul_extra_key",
        "noul_untyped",
        "noul_wrong_key",
        "missing_field",
    ],
)
def test_a_malformed_v2_answer_invalidates_the_whole_assessment(mutate: Any) -> None:
    answers = _v2_answers()
    mutate(answers)
    with pytest.raises(InvalidResponse):
        parse_field_answers(answers, _V2)


def test_a_v2_result_round_trips_and_a_stored_v1_result_still_loads() -> None:
    def available(fields: Any) -> JevAvailable:
        return JevAvailable(
            fields=fields,
            input_hash="1" * 64,
            rubric_hash="2" * 64,
            provider_identity=_identity(),
            sanitized_request_hash="3" * 64,
            sanitized_response_hash="4" * 64,
            computed_at="2026-09-23T00:00:00.000000Z",
            smoke_report_hash=None,
        )

    v2 = available(parse_field_answers(_v2_answers(), _V2))
    assert result_from_json(v2.to_canonical_json()) == v2
    v1 = available(parse_field_answers(_answers(), _V1))
    raw = v1.to_canonical_json()
    # A v1 choice field is stored without a `type` key, exactly as before v2.
    assert b'"type"' not in raw
    assert result_from_json(raw) == v1
    mixed = dict(v1.to_dict()["fields"])
    mixed["primary_contribution"] = v2.to_dict()["fields"]["evaluation_rigor"]
    with pytest.raises(ContractValidationError):
        fields_from_dict(mixed)
    with pytest.raises(ContractValidationError):
        fields_from_dict(v1.to_dict()["fields"], "jev-rubric-v2")
