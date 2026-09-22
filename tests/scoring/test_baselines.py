from uuid import uuid4

from research_agent.contracts.learning import TARGET_IDS
from research_agent.scoring.baselines import (
    AuthorCountExample,
    AuthorCountRow,
    BaselineAnswerSet,
    BaselineQuestion,
    CardFeatureExample,
    CardFeatureRow,
    FittingBundle,
    base_rate_baseline_answers,
    card_regression_baseline_answers,
    popularity_baseline_answers,
)

TARGET_ID = TARGET_IDS[0]
OTHER_TARGET_ID = TARGET_IDS[1]
TARGET_HASH = "d" * 64
OTHER_TARGET_HASH = "e" * 64
BEFORE_SEAL = "2025-06-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
AFTER_SEAL = "2026-01-15T00:00:00.000000Z"


def question() -> BaselineQuestion:
    return BaselineQuestion(question_id=str(uuid4()), forecast_id=str(uuid4()))


# --- IN-07: popularity baseline ----------------------------------------------


def popularity_training() -> tuple[AuthorCountExample, ...]:
    return (
        AuthorCountExample(str(uuid4()), str(uuid4()), (0, 1), BEFORE_SEAL, False),
        AuthorCountExample(str(uuid4()), str(uuid4()), (1, 0), BEFORE_SEAL, False),
        AuthorCountExample(str(uuid4()), str(uuid4()), (200, 300), BEFORE_SEAL, True),
        AuthorCountExample(str(uuid4()), str(uuid4()), (250, 400), BEFORE_SEAL, True),
    )


def popularity_answers(
    training: tuple[AuthorCountExample, ...], batch: tuple[AuthorCountRow, ...]
) -> BaselineAnswerSet:
    return popularity_baseline_answers(
        training,
        batch,
        target_id=TARGET_ID,
        target_definition_hash=TARGET_HASH,
        batch_sealed_at=SEALED_AT,
    )


def test_popularity_baseline_orders_probability_by_author_count() -> None:
    low = question()
    high = question()
    batch = (
        AuthorCountRow(low.question_id, low.forecast_id, (0, 2), BEFORE_SEAL),
        AuthorCountRow(high.question_id, high.forecast_id, (220, 350), BEFORE_SEAL),
    )
    answers = popularity_answers(popularity_training(), batch).answers
    by_question = {answer.question_id: answer.probability for answer in answers}
    assert len(answers) == 2
    assert by_question[high.question_id] > by_question[low.question_id]


def test_popularity_baseline_refuses_a_count_captured_after_the_seal() -> None:
    late = question()
    batch = (AuthorCountRow(late.question_id, late.forecast_id, (5,), AFTER_SEAL),)
    result = popularity_answers(popularity_training(), batch)
    assert result.answers == ()
    assert result.gaps[0].reason == "late_capture"


def test_popularity_baseline_refuses_a_missing_author_count() -> None:
    missing = question()
    batch = (
        AuthorCountRow(missing.question_id, missing.forecast_id, None, BEFORE_SEAL),
    )
    result = popularity_answers(popularity_training(), batch)
    assert result.answers == ()
    assert result.gaps[0].reason == "missing_author_count"


def test_popularity_baseline_excludes_a_late_training_row_and_reports_it() -> None:
    late_row = AuthorCountExample(str(uuid4()), str(uuid4()), (999,), AFTER_SEAL, True)
    training = popularity_training() + (late_row,)
    target = question()
    batch = (AuthorCountRow(target.question_id, target.forecast_id, (5,), BEFORE_SEAL),)
    result = popularity_answers(training, batch)
    assert any(item.input_id == late_row.forecast_id for item in result.excluded_inputs)


def test_popularity_baseline_is_deterministic() -> None:
    target = question()
    batch = (
        AuthorCountRow(target.question_id, target.forecast_id, (220, 350), BEFORE_SEAL),
    )
    first = popularity_answers(popularity_training(), batch)
    second = popularity_answers(popularity_training(), batch)
    assert first.answers == second.answers


def test_popularity_baseline_is_unqualified_with_a_single_class() -> None:
    single_class_training = (
        AuthorCountExample(str(uuid4()), str(uuid4()), (0, 1), BEFORE_SEAL, False),
        AuthorCountExample(str(uuid4()), str(uuid4()), (10, 1), BEFORE_SEAL, False),
    )
    target = question()
    batch = (AuthorCountRow(target.question_id, target.forecast_id, (5,), BEFORE_SEAL),)
    result = popularity_answers(single_class_training, batch)
    assert result.answers == ()
    assert result.gaps[0].reason == "baseline_unqualified"


# --- IN-08: base-rate baseline ------------------------------------------------


def base_rate_answers(
    bundle: FittingBundle, batch: tuple[BaselineQuestion, ...]
) -> BaselineAnswerSet:
    return base_rate_baseline_answers(
        bundle,
        batch,
        target_id=TARGET_ID,
        target_definition_hash=TARGET_HASH,
        batch_sealed_at=SEALED_AT,
    )


def test_base_rate_baseline_answers_with_the_frozen_ratio() -> None:
    bundle = FittingBundle("bundle-1", TARGET_ID, TARGET_HASH, 3, 12, BEFORE_SEAL)
    batch = (question(), question())
    result = base_rate_answers(bundle, batch)
    assert {answer.probability for answer in result.answers} == {0.25}
    assert len(result.answers) == 2
    assert result.gaps == ()


def test_base_rate_baseline_refuses_a_zero_denominator() -> None:
    bundle = FittingBundle("bundle-1", TARGET_ID, TARGET_HASH, 0, 0, BEFORE_SEAL)
    result = base_rate_answers(bundle, (question(),))
    assert result.answers == ()
    assert result.gaps[0].reason == "unqualified_reference_partition"


def test_base_rate_baseline_refuses_a_bundle_frozen_after_the_seal() -> None:
    bundle = FittingBundle("bundle-1", TARGET_ID, TARGET_HASH, 3, 12, AFTER_SEAL)
    result = base_rate_answers(bundle, (question(),))
    assert result.answers == ()
    assert result.gaps[0].reason == "unqualified_reference_partition"


def test_base_rate_baseline_refuses_a_mismatched_target() -> None:
    bundle = FittingBundle(
        "bundle-1", OTHER_TARGET_ID, OTHER_TARGET_HASH, 3, 12, BEFORE_SEAL
    )
    result = base_rate_answers(bundle, (question(),))
    assert result.answers == ()
    assert result.gaps[0].reason == "unqualified_reference_partition"


def test_base_rate_baseline_is_byte_identical_for_an_unchanged_bundle() -> None:
    bundle = FittingBundle("bundle-1", TARGET_ID, TARGET_HASH, 3, 12, BEFORE_SEAL)
    batch = (question(),)
    first = base_rate_answers(bundle, batch)
    second = base_rate_answers(bundle, batch)
    assert first.answers == second.answers


# --- IN-09: card-feature regression baseline ----------------------------------


def card_training() -> tuple[CardFeatureExample, ...]:
    return (
        CardFeatureExample(str(uuid4()), str(uuid4()), -3.0, 0.9, BEFORE_SEAL, False),
        CardFeatureExample(str(uuid4()), str(uuid4()), -2.5, 0.8, BEFORE_SEAL, False),
        CardFeatureExample(str(uuid4()), str(uuid4()), 3.0, 0.1, BEFORE_SEAL, True),
        CardFeatureExample(str(uuid4()), str(uuid4()), 2.5, 0.2, BEFORE_SEAL, True),
    )


def card_answers(
    training: tuple[CardFeatureExample, ...], batch: tuple[CardFeatureRow, ...]
) -> BaselineAnswerSet:
    return card_regression_baseline_answers(
        training,
        batch,
        target_id=TARGET_ID,
        target_definition_hash=TARGET_HASH,
        batch_sealed_at=SEALED_AT,
    )


def test_card_regression_baseline_refuses_a_row_with_no_signal() -> None:
    empty = question()
    batch = (
        CardFeatureRow(empty.question_id, empty.forecast_id, None, None, BEFORE_SEAL),
    )
    result = card_answers(card_training(), batch)
    assert result.answers == ()
    assert result.gaps[0].reason == "no_signal"


def test_card_regression_baseline_answers_with_partial_signal() -> None:
    partial = question()
    batch = (
        CardFeatureRow(
            partial.question_id, partial.forecast_id, 2.8, None, BEFORE_SEAL
        ),
    )
    result = card_answers(card_training(), batch)
    assert len(result.answers) == 1
    assert result.answers[0].probability > 0.5


def test_card_regression_baseline_refuses_a_row_captured_after_the_seal() -> None:
    late = question()
    batch = (CardFeatureRow(late.question_id, late.forecast_id, 2.8, 0.1, AFTER_SEAL),)
    result = card_answers(card_training(), batch)
    assert result.answers == ()
    assert result.gaps[0].reason == "late_capture"


def test_card_regression_baseline_excludes_late_training_rows() -> None:
    late_row = CardFeatureExample(
        str(uuid4()), str(uuid4()), 3.0, 0.1, AFTER_SEAL, True
    )
    training = card_training() + (late_row,)
    target = question()
    batch = (
        CardFeatureRow(target.question_id, target.forecast_id, 2.8, 0.1, BEFORE_SEAL),
    )
    result = card_answers(training, batch)
    assert any(item.input_id == late_row.forecast_id for item in result.excluded_inputs)


def test_card_regression_baseline_orders_probability_by_signal_direction() -> None:
    low = question()
    high = question()
    batch = (
        CardFeatureRow(low.question_id, low.forecast_id, -2.8, 0.85, BEFORE_SEAL),
        CardFeatureRow(high.question_id, high.forecast_id, 2.8, 0.15, BEFORE_SEAL),
    )
    answers = card_answers(card_training(), batch).answers
    by_question = {answer.question_id: answer.probability for answer in answers}
    assert by_question[high.question_id] > by_question[low.question_id]
