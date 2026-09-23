import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_agent.assessments.rubric import (
    LAUNCH_RUBRIC_VERSION,
    Rubric,
    RubricRejected,
)
from research_agent.contracts.assessments import (
    FIELD_CATEGORIES,
    FIELD_IDS,
    SCORE_POINTS,
    V1_FIELD_IDS,
    JevRubric,
    NoulQuestion,
    RubricQuestion,
    ScoreQuestion,
)
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.primitives import ContractValidationError

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "jev"


def _approved(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_the_outbound_schema_matches_the_approved_rubric_artifact() -> None:
    rubric = Rubric.launch()
    approved = _approved("rubric-v2-questions.json")
    assert rubric.version == approved["version"] == LAUNCH_RUBRIC_VERSION
    assert LAUNCH_RUBRIC_VERSION == "jev-rubric-v2"
    assert rubric.rubric_hash == approved["rubric_hash"]
    assert canonical_json(rubric.request_questions()) == canonical_json(
        approved["questions"]
    )


def test_v1_keeps_its_approved_body_and_hash() -> None:
    """Stored v1 assessments name v1's hash; a v1 body that moved with v2
    would orphan every one of them."""
    rubric = Rubric.v1()
    approved = _approved("rubric-v1-questions.json")
    assert rubric.version == approved["version"] == "jev-rubric-v1"
    assert rubric.rubric_hash == approved["rubric_hash"]
    assert canonical_json(rubric.request_questions()) == canonical_json(
        approved["questions"]
    )
    assert rubric.rubric_hash != Rubric.launch().rubric_hash


def test_a_v2_request_carries_exactly_the_eight_fields_in_their_primitives() -> None:
    questions = Rubric.launch().request_questions()
    assert tuple(questions) == FIELD_IDS
    assert {field: question["type"] for field, question in questions.items()} == {
        "primary_contribution": "choice",
        "evaluation_rigor": "score",
        "limitations_candor": "score",
        "novelty_as_claimed": "score",
        "claims_supported_by_evidence": "noul",
        "reproducible_from_materials": "noul",
        "generalizes_beyond_main_setting": "noul",
        "open_problems_stated": "noul",
    }
    primary = questions["primary_contribution"]
    assert tuple(primary["criteria"]) == FIELD_CATEGORIES["primary_contribution"]
    for field_id, points in SCORE_POINTS.items():
        # The provider refuses an object here: criteria is an ordered list.
        assert isinstance(questions[field_id]["criteria"], list)
        assert len(questions[field_id]["criteria"]) == points
        assert all(questions[field_id]["criteria"])
    for field_id in FIELD_IDS[4:]:
        assert set(questions[field_id]) == {"type", "instructions"}


def test_each_v1_rubric_row_is_one_choice_with_its_full_criteria() -> None:
    questions = Rubric.v1().request_questions()
    assert tuple(questions) == V1_FIELD_IDS
    for field_id, question in questions.items():
        assert question["type"] == "choice"
        assert tuple(question["criteria"]) == FIELD_CATEGORIES[field_id]
        assert all(question["criteria"].values())


def test_no_question_gates_on_contribution_type_or_asks_for_quality() -> None:
    for rubric in (Rubric.v1(), Rubric.launch()):
        for field_id, question in rubric.request_questions().items():
            text = question["instructions"].lower()
            assert "if the primary contribution" not in text
            for forbidden in ("overall quality", "future impact"):
                assert forbidden not in text
            if "novelty" in text:
                # Novelty is asked only as the paper claims it (#267).
                assert field_id == "novelty_as_claimed"
                assert "do not judge whether it holds" in text


def test_a_score_or_noul_question_is_refused_under_the_wrong_shape() -> None:
    rigor = Rubric.launch().record.question("evaluation_rigor")
    assert isinstance(rigor, ScoreQuestion)
    with pytest.raises(ContractValidationError):
        replace(rigor, criteria=rigor.criteria[:-1])
    with pytest.raises(ContractValidationError):
        ScoreQuestion("primary_contribution", rigor.question, rigor.criteria)
    stated = Rubric.launch().record.question("open_problems_stated")
    assert isinstance(stated, NoulQuestion)
    with pytest.raises(ContractValidationError):
        replace(stated, statement="Something the instructions never ask.")
    with pytest.raises(ContractValidationError):
        NoulQuestion("evaluation_rigor", stated.question, stated.statement)


def test_every_category_carries_a_positive_and_a_boundary_example() -> None:
    for question in Rubric.v1().record.questions + Rubric.launch().record.questions:
        if not isinstance(question, RubricQuestion):
            continue
        pairs = {(example.category_id, example.kind) for example in question.examples}
        assert pairs == {
            (category, kind)
            for category in question.category_ids
            for kind in ("positive", "boundary")
        }


def test_an_extra_quality_question_is_rejected() -> None:
    record = Rubric.launch().record
    extra = replace(record.questions[0])
    with pytest.raises(ContractValidationError):
        JevRubric(record.version, (*record.questions, extra), record.created_at)
    raw = canonical_loads(record.to_canonical_json())
    assert isinstance(raw, dict) and isinstance(raw["questions"], list)
    quality = dict(raw["questions"][1])  # type: ignore[arg-type]
    quality["field_id"] = "overall_quality"
    raw["questions"][1] = quality
    with pytest.raises(ContractValidationError):
        JevRubric.from_json(canonical_json(raw))


def test_a_missing_field_is_rejected() -> None:
    record = Rubric.launch().record
    with pytest.raises(ContractValidationError):
        JevRubric(record.version, record.questions[:-1], record.created_at)


def test_missing_criteria_and_unknown_keys_are_rejected() -> None:
    question = Rubric.v1().record.questions[1]
    with pytest.raises(ContractValidationError):
        replace(question, category_criteria=question.category_criteria[:-1])
    with pytest.raises(ContractValidationError):
        replace(question, category_criteria=("",) + question.category_criteria[1:])
    raw = canonical_loads(Rubric.launch().record.to_canonical_json())
    assert isinstance(raw, dict)
    raw["weight"] = 1
    with pytest.raises(ContractValidationError):
        JevRubric.from_json(canonical_json(raw))


def test_a_borrowed_category_is_rejected() -> None:
    question = Rubric.v1().record.question("limitations_disclosure")
    assert isinstance(question, RubricQuestion)
    with pytest.raises(ContractValidationError):
        RubricQuestion(
            question.field_id,
            question.question,
            (*question.category_ids[:-1], "not_applicable"),
            question.category_criteria,
            question.examples,
        )


def test_an_altered_body_under_the_reused_version_is_refused() -> None:
    launch = Rubric.launch()
    approved = {launch.version: launch.rubric_hash}
    assert Rubric.admit(launch.record, writer_role="operator", approved=approved)
    first = launch.record.questions[0]
    altered = replace(
        launch.record,
        questions=(
            replace(first, question=first.question + " Prefer methods."),
            *launch.record.questions[1:],
        ),
    )
    with pytest.raises(RubricRejected) as refused:
        Rubric.admit(altered, writer_role="operator", approved=approved)
    assert refused.value.reason == "altered_rubric_version"


def test_a_genome_supplied_rubric_change_is_denied() -> None:
    launch = Rubric.launch()
    approved = {launch.version: launch.rubric_hash}
    for role in ("agent", "jev", "ingest"):
        with pytest.raises(RubricRejected) as refused:
            Rubric.admit(launch.record, writer_role=role, approved=approved)
        assert refused.value.reason == "rubric_mutation_denied"


def test_the_rubric_hash_is_stable_across_a_round_trip() -> None:
    for record in (Rubric.v1().record, Rubric.launch().record):
        assert JevRubric.from_json(record.to_canonical_json()) == record
        assert JevRubric.from_json(record.to_canonical_json()).rubric_hash == (
            record.rubric_hash
        )


def test_a_rubric_must_ask_its_own_versions_fields() -> None:
    v1 = Rubric.v1().record
    with pytest.raises(ContractValidationError):
        JevRubric("jev-rubric-v2", v1.questions, v1.created_at)
    with pytest.raises(ContractValidationError):
        JevRubric("jev-rubric-v3", v1.questions, v1.created_at)
