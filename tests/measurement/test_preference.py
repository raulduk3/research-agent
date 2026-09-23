"""SDD-IN-43: a rating's credit divides among the genomes that nominated its paper."""

from __future__ import annotations

import pytest

from research_agent.measurement import MeasurementError
from research_agent.measurement.preference import (
    GAP_OTHER_ISLAND,
    GAP_UNREADABLE,
    GAP_ZERO_PROBABILITY,
    RatingEvent,
    SealedNomination,
    credit_ratings,
)

GENOME_A = "a" * 64
GENOME_B = "b" * 64
GENOME_C = "c" * 64
WEEK = "2026-W38"


def uid(number: int) -> str:
    return f"{number:08d}-0000-4000-8000-000000000000"


def event(
    number: int,
    *,
    value: str = "like",
    origin: str = "population",
    island: str = "cs",
    nominations: tuple[SealedNomination, ...] | None = (),
) -> RatingEvent:
    return RatingEvent(
        rating_id=uid(number),
        entry_id=uid(number + 100),
        island=island,
        iso_week=WEEK,
        value=value,
        origin=origin,
        nominations=nominations,
    )


def nominated(genome: str, probability: float, island: str = "cs") -> SealedNomination:
    return SealedNomination(genome, island, probability)


def test_two_nominators_split_a_like_by_their_sealed_probabilities() -> None:
    outcome = credit_ratings(
        [event(1, nominations=(nominated(GENOME_A, 0.6), nominated(GENOME_B, 0.2)))]
    )
    shares = {credit.genome_hash: credit.share for credit in outcome.credits}
    assert shares == {GENOME_A: pytest.approx(0.75), GENOME_B: pytest.approx(0.25)}
    assert {credit.sealed_probability for credit in outcome.credits} == {0.6, 0.2}
    assert outcome.gaps == ()


def test_a_dislike_credits_the_same_shares_negatively() -> None:
    outcome = credit_ratings(
        [
            event(
                1,
                value="dislike",
                nominations=(nominated(GENOME_A, 0.6), nominated(GENOME_B, 0.2)),
            )
        ]
    )
    assert [credit.share for credit in outcome.credits] == [
        pytest.approx(-0.75),
        pytest.approx(-0.25),
    ]


def test_a_skip_credits_nothing_and_records_no_gap() -> None:
    outcome = credit_ratings(
        [event(1, value="skip", nominations=(nominated(GENOME_A, 0.6),))]
    )
    assert outcome.credits == ()
    assert outcome.gaps == ()


@pytest.mark.parametrize("origin", ["random_control", "service"])
def test_a_control_or_service_entry_credits_nobody(origin: str) -> None:
    outcome = credit_ratings([event(1, origin=origin, nominations=None)])
    assert outcome.credits == ()
    assert outcome.gaps == ()


def test_a_genome_of_another_island_never_receives_credit() -> None:
    outcome = credit_ratings(
        [
            event(
                1,
                nominations=(
                    nominated(GENOME_A, 0.5),
                    nominated(GENOME_B, 0.5, island="quant-ph"),
                ),
            )
        ]
    )
    assert [(credit.genome_hash, credit.share) for credit in outcome.credits] == [
        (GENOME_A, pytest.approx(1.0))
    ]


@pytest.mark.parametrize(
    ("nominations", "reason"),
    [
        (None, GAP_UNREADABLE),
        ((), GAP_UNREADABLE),
        ((nominated(GENOME_A, 0.5, island="quant-ph"),), GAP_OTHER_ISLAND),
        ((nominated(GENOME_A, 0.0),), GAP_ZERO_PROBABILITY),
    ],
    ids=["unreadable", "none", "other-island", "zero"],
)
def test_an_uncreditable_population_rating_is_a_recorded_gap(
    nominations: tuple[SealedNomination, ...] | None, reason: str
) -> None:
    outcome = credit_ratings([event(1, nominations=nominations)])
    assert outcome.credits == ()
    assert [(gap.rating_id, gap.reason) for gap in outcome.gaps] == [(uid(1), reason)]


def test_a_rating_appears_once_and_a_genome_nominates_once() -> None:
    with pytest.raises(MeasurementError):
        credit_ratings([event(1), event(1)])
    with pytest.raises(MeasurementError):
        event(1, nominations=(nominated(GENOME_A, 0.1), nominated(GENOME_A, 0.2)))


def test_the_result_does_not_depend_on_the_order_of_nominators() -> None:
    forward = credit_ratings(
        [event(1, nominations=(nominated(GENOME_A, 0.3), nominated(GENOME_C, 0.1)))]
    )
    reverse = credit_ratings(
        [event(1, nominations=(nominated(GENOME_C, 0.1), nominated(GENOME_A, 0.3)))]
    )
    assert forward == reverse


def test_from_record_reads_a_storage_row_and_keeps_an_unreadable_entry_none() -> None:
    row = {
        "rating_id": uid(1),
        "entry_id": uid(101),
        "island": "cs",
        "iso_week": WEEK,
        "value": "like",
        "origin": "population",
        "nominations": [
            {"genome_hash": GENOME_A, "island": "cs", "sealed_probability": 0.4}
        ],
    }
    assert RatingEvent.from_record(row).nominations == (nominated(GENOME_A, 0.4),)
    assert RatingEvent.from_record({**row, "nominations": None}).nominations is None
