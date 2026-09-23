"""Fixed-task neighbor-retrieval qualification (SDD MD-12).

TDD-4.1.68: a paper whose references cannot be confirmed to have all
arrived before it is left out of the sample entirely, not narrowed to its
confirmed references; a paper with a full, confirmed comparison set is
never omitted; the random control draw is a fixed hash rank, so it is
stable no matter what order the corpus arrives in; the exact reference and
control ids are recorded on the outcome, and relevance@5 is computed
separately from the pairwise reference-vs-control ranking.
"""

from __future__ import annotations

import math
from hashlib import sha256

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.retrieval import (
    CorpusPaper,
    PaperRankOutcome,
    ReferenceRankReport,
    reference_rank_evaluation,
)

REPRESENTATION_HASH = sha256(b"representation").hexdigest()


def _family(label: str) -> str:
    return f"00000000-0000-4000-8000-0000000000{label}"


TARGET = _family("d0")
REF_A = _family("a1")
REF_B = _family("a2")
EARLY_1 = _family("e1")
EARLY_2 = _family("e2")
EARLY_3 = _family("e3")
EARLY_4 = _family("e4")
LATE = _family("99")


def _paper(
    family_id: str,
    arrival_day: int,
    vector: tuple[float, ...],
    references: tuple[str, ...] = (),
) -> CorpusPaper:
    return CorpusPaper(
        family_id=family_id,
        corpus_arrival_at=f"2026-01-{arrival_day:02d}T00:00:00.000000Z",
        vector=vector,
        reference_family_ids=references,
    )


def _base_corpus() -> tuple[CorpusPaper, ...]:
    return (
        _paper(REF_A, 1, (1.0, 0.0)),
        _paper(REF_B, 1, (0.9, 0.1)),
        _paper(EARLY_1, 1, (0.0, 1.0)),
        _paper(EARLY_2, 2, (-1.0, 0.0)),
        _paper(EARLY_3, 2, (0.0, -1.0)),
        _paper(EARLY_4, 2, (-0.9, -0.1)),
        _paper(TARGET, 10, (1.0, 0.0), references=(REF_A, REF_B)),
    )


def test_included_paper_records_the_exact_reference_and_control_ids() -> None:
    report = reference_rank_evaluation(
        _base_corpus(),
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "included"
    assert set(outcome.reference_family_ids) == {REF_A, REF_B}
    assert len(outcome.control_family_ids) == 2
    assert set(outcome.control_family_ids) <= {EARLY_1, EARLY_2, EARLY_3, EARLY_4}
    assert outcome.compared_pairs == 4
    assert report.included_count == 1


def test_references_more_similar_than_controls_win_every_pair() -> None:
    # Both references sit close to the target's vector; every earlier
    # non-reference paper is far away, so every reference/control pair
    # should have the reference strictly more similar.
    report = reference_rank_evaluation(
        _base_corpus(),
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    outcome = report.outcomes[0]
    assert outcome.winning_pairs == outcome.compared_pairs
    assert report.win_rate == 1.0


def test_paper_with_a_full_confirmed_comparison_set_is_never_omitted() -> None:
    report = reference_rank_evaluation(
        _base_corpus(),
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    assert report.outcomes[0].status == "included"
    assert report.included_count == 1


def test_a_reference_that_had_not_yet_arrived_excludes_the_whole_paper() -> None:
    corpus = _base_corpus() + (_paper(LATE, 20, (1.0, 0.0)),)
    late_referencing = _paper(_family("b1"), 10, (1.0, 0.0), references=(REF_A, LATE))
    report = reference_rank_evaluation(
        corpus + (late_referencing,),
        (late_referencing.family_id,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "excluded"
    assert outcome.reason == "reference_not_confirmed_earlier"
    assert outcome.reference_family_ids == ()
    assert outcome.compared_pairs == 0
    assert report.included_count == 0


def test_an_unmatched_reference_id_excludes_the_whole_paper() -> None:
    unmatched = _family("77")
    paper = _paper(_family("b2"), 10, (1.0, 0.0), references=(REF_A, unmatched))
    report = reference_rank_evaluation(
        _base_corpus() + (paper,),
        (paper.family_id,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "excluded"
    assert outcome.reason == "reference_not_confirmed_earlier"


def test_a_paper_with_no_references_is_excluded() -> None:
    paper = _paper(_family("b3"), 10, (1.0, 0.0))
    report = reference_rank_evaluation(
        _base_corpus() + (paper,),
        (paper.family_id,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "excluded"
    assert outcome.reason == "no_references"


def test_too_few_earlier_candidates_excludes_the_paper() -> None:
    report = reference_rank_evaluation(
        _base_corpus(),
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=5,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "excluded"
    assert outcome.reason == "insufficient_earlier_candidates"


def test_a_paper_absent_from_the_corpus_is_excluded_as_unknown_arrival_day() -> None:
    report = reference_rank_evaluation(
        _base_corpus(),
        (_family("00"),),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "excluded"
    assert outcome.reason == "unknown_arrival_day"


def test_control_draw_is_independent_of_corpus_order() -> None:
    corpus = _base_corpus()
    forward = reference_rank_evaluation(
        corpus,
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    reversed_corpus = tuple(reversed(corpus))
    backward = reference_rank_evaluation(
        reversed_corpus,
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    assert forward.outcomes == backward.outcomes


def test_report_aggregates_across_every_sampled_paper_in_order() -> None:
    second = _paper(_family("b4"), 10, (0.0, 1.0), references=(EARLY_1,))
    report = reference_rank_evaluation(
        _base_corpus() + (second,),
        (TARGET, second.family_id),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=2,
    )
    assert report.sample_size == 2
    assert [outcome.family_id for outcome in report.outcomes] == [
        TARGET,
        second.family_id,
    ]
    assert report.compared_pairs == sum(o.compared_pairs for o in report.outcomes)
    assert report.winning_pairs == sum(o.winning_pairs for o in report.outcomes)


def _angle_vector(degrees: float) -> tuple[float, float]:
    radians = math.radians(degrees)
    return (math.cos(radians), math.sin(radians))


def test_relevance_at_five_excludes_the_least_similar_member_of_a_larger_pool() -> None:
    reference = _family("c0")
    controls = [_family(f"c{index}") for index in range(1, 6)]
    corpus = (
        _paper(reference, 1, _angle_vector(0.0)),
        _paper(controls[0], 1, _angle_vector(30.0)),
        _paper(controls[1], 1, _angle_vector(60.0)),
        _paper(controls[2], 1, _angle_vector(90.0)),
        _paper(controls[3], 1, _angle_vector(120.0)),
        _paper(controls[4], 1, _angle_vector(150.0)),
        _paper(TARGET, 10, (1.0, 0.0), references=(reference,)),
    )
    report = reference_rank_evaluation(
        corpus,
        (TARGET,),
        representation_hash=REPRESENTATION_HASH,
        controls_per_paper=5,
    )
    outcome = report.outcomes[0]
    assert outcome.status == "included"
    assert set(outcome.control_family_ids) == set(controls)
    # The reference sits at cosine 1.0, ahead of every 30-150 degree
    # control; only the 150-degree control (the least similar of six) falls
    # outside the top five, so the reference is one of the five kept.
    assert outcome.relevant_in_top == 1
    assert outcome.relevance_at_five == pytest.approx(0.2)
    assert outcome.winning_pairs == outcome.compared_pairs == 5
    assert report.win_rate == 1.0
    assert report.mean_relevance_at_five == pytest.approx(0.2)


def test_rejects_an_empty_sample() -> None:
    with pytest.raises(MeasurementError):
        reference_rank_evaluation(
            _base_corpus(), (), representation_hash=REPRESENTATION_HASH
        )


def test_rejects_a_repeated_sample_family() -> None:
    with pytest.raises(MeasurementError):
        reference_rank_evaluation(
            _base_corpus(),
            (TARGET, TARGET),
            representation_hash=REPRESENTATION_HASH,
        )


def test_rejects_a_corpus_with_a_repeated_family_id() -> None:
    corpus = _base_corpus() + (_paper(REF_A, 1, (1.0, 0.0)),)
    with pytest.raises(MeasurementError):
        reference_rank_evaluation(
            corpus, (TARGET,), representation_hash=REPRESENTATION_HASH
        )


def test_corpus_paper_rejects_a_duplicate_reference() -> None:
    with pytest.raises(MeasurementError):
        CorpusPaper(
            family_id=TARGET,
            corpus_arrival_at="2026-01-10T00:00:00.000000Z",
            vector=(1.0, 0.0),
            reference_family_ids=(REF_A, REF_A),
        )


def test_corpus_paper_rejects_a_nonfinite_vector() -> None:
    with pytest.raises(MeasurementError):
        CorpusPaper(
            family_id=TARGET,
            corpus_arrival_at="2026-01-10T00:00:00.000000Z",
            vector=(float("nan"), 0.0),
            reference_family_ids=(),
        )


def test_corpus_paper_rejects_an_empty_vector() -> None:
    with pytest.raises(MeasurementError):
        CorpusPaper(
            family_id=TARGET,
            corpus_arrival_at="2026-01-10T00:00:00.000000Z",
            vector=(),
            reference_family_ids=(),
        )


def test_paper_rank_outcome_rejects_an_excluded_outcome_with_recorded_ids() -> None:
    with pytest.raises(MeasurementError):
        PaperRankOutcome(
            family_id=TARGET,
            status="excluded",
            reason="no_references",
            reference_family_ids=(REF_A,),
            control_family_ids=(),
            compared_pairs=0,
            winning_pairs=0,
            relevant_in_top=0,
            relevance_at_five=None,
        )


def test_paper_rank_outcome_rejects_an_included_outcome_carrying_a_reason() -> None:
    with pytest.raises(MeasurementError):
        PaperRankOutcome(
            family_id=TARGET,
            status="included",
            reason="no_references",
            reference_family_ids=(REF_A,),
            control_family_ids=(EARLY_1,),
            compared_pairs=1,
            winning_pairs=0,
            relevant_in_top=0,
            relevance_at_five=0.0,
        )


def test_paper_rank_outcome_rejects_a_paper_named_as_both_reference_and_control() -> (
    None
):
    with pytest.raises(MeasurementError):
        PaperRankOutcome(
            family_id=TARGET,
            status="included",
            reason=None,
            reference_family_ids=(REF_A,),
            control_family_ids=(REF_A,),
            compared_pairs=1,
            winning_pairs=0,
            relevant_in_top=1,
            relevance_at_five=0.5,
        )


def test_reference_rank_report_rejects_a_win_rate_mismatch() -> None:
    outcome = PaperRankOutcome(
        family_id=TARGET,
        status="included",
        reason=None,
        reference_family_ids=(REF_A,),
        control_family_ids=(EARLY_1,),
        compared_pairs=1,
        winning_pairs=1,
        relevant_in_top=1,
        relevance_at_five=0.5,
    )
    with pytest.raises(MeasurementError):
        ReferenceRankReport(
            representation_hash=REPRESENTATION_HASH,
            sample_size=1,
            outcomes=(outcome,),
            included_count=1,
            compared_pairs=1,
            winning_pairs=1,
            win_rate=0.5,
            mean_relevance_at_five=0.5,
        )
