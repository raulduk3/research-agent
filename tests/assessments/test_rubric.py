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
    JevRubric,
    RubricQuestion,
)
from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.primitives import ContractValidationError

_APPROVED = Path(__file__).parents[1] / "fixtures" / "jev" / "rubric-v1-questions.json"


def _approved() -> dict[str, object]:
    return json.loads(_APPROVED.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_the_outbound_schema_matches_the_approved_rubric_artifact() -> None:
    rubric = Rubric.launch()
    approved = _approved()
    assert rubric.version == approved["version"] == LAUNCH_RUBRIC_VERSION
    assert rubric.rubric_hash == approved["rubric_hash"]
    assert canonical_json(rubric.choice_questions()) == canonical_json(
        approved["questions"]
    )


def test_each_rubric_row_is_one_choice_with_its_full_criteria() -> None:
    questions = Rubric.launch().choice_questions()
    assert tuple(questions) == FIELD_IDS
    for field_id, question in questions.items():
        assert question["type"] == "choice"
        assert tuple(question["criteria"]) == FIELD_CATEGORIES[field_id]
        assert all(question["criteria"].values())


def test_no_question_gates_on_contribution_type_or_asks_for_quality() -> None:
    for question in Rubric.launch().choice_questions().values():
        text = question["instructions"].lower()
        assert "if the primary contribution" not in text
        for forbidden in ("overall quality", "novelty", "future impact", "score"):
            assert forbidden not in text


def test_every_category_carries_a_positive_and_a_boundary_example() -> None:
    for question in Rubric.launch().record.questions:
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
    question = Rubric.launch().record.questions[1]
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
    question = Rubric.launch().record.question("limitations_disclosure")
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
    record = Rubric.launch().record
    assert JevRubric.from_json(record.to_canonical_json()) == record
    assert JevRubric.from_json(record.to_canonical_json()).rubric_hash == (
        record.rubric_hash
    )
