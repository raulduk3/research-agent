from __future__ import annotations

from typing import Any

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.preference import validate_preference_payload

RATING = "11111111-1111-4111-8111-111111111111"
ENTRY = "22222222-2222-4222-8222-222222222222"
GENOME_A = "a" * 64
GENOME_B = "b" * 64


def credit(
    genome: str, probability: float, share: float, **over: Any
) -> dict[str, Any]:
    return {
        "rating_id": RATING,
        "genome_hash": genome,
        "island": "cs",
        "entry_id": ENTRY,
        "sealed_probability": probability,
        "share": share,
        "iso_week": "2026-W38",
        **over,
    }


def test_a_rating_credit_with_proportional_shares_is_accepted() -> None:
    payload = {"credits": [credit(GENOME_A, 0.6, 0.75), credit(GENOME_B, 0.2, 0.25)]}
    assert validate_preference_payload("record", payload) == payload


def test_a_dislike_carries_negative_shares() -> None:
    payload = {"credits": [credit(GENOME_A, 0.5, -1.0)]}
    assert validate_preference_payload("record", payload) == payload


@pytest.mark.parametrize(
    "credits",
    [
        [credit(GENOME_A, 0.6, 0.5), credit(GENOME_B, 0.2, 0.5)],
        [credit(GENOME_A, 0.6, 0.75), credit(GENOME_B, 0.2, -0.25)],
        [credit(GENOME_A, 0.0, 0.0)],
        [credit(GENOME_A, 0.5, 1.0), credit(GENOME_A, 0.5, 1.0)],
        [credit(GENOME_A, 0.5, 0.5), credit(GENOME_B, 0.5, 0.5, entry_id=RATING)],
        [credit(GENOME_A, 0.5, 1.0, iso_week="2026-W54")],
        [credit(GENOME_A, 0.5, 1.0, island="cs-ml")],
        [],
    ],
    ids=[
        "shares-not-proportional",
        "mixed-signs",
        "zero-share",
        "duplicate-genome",
        "two-entries",
        "bad-week",
        "bad-island",
        "empty",
    ],
)
def test_a_malformed_credit_set_is_refused(credits: list[dict[str, Any]]) -> None:
    with pytest.raises(ContractValidationError):
        validate_preference_payload("record", {"credits": credits})


def test_a_gap_names_the_rating_week_and_reason() -> None:
    payload = {"rating_id": RATING, "iso_week": "2026-W38", "reason": "unreadable"}
    assert validate_preference_payload("record_gap", payload) == payload
    with pytest.raises(ContractValidationError):
        validate_preference_payload("record_gap", {**payload, "reason": ""})
    with pytest.raises(ContractValidationError):
        validate_preference_payload("record_gap", {**payload, "extra": 1})


def test_an_unknown_operation_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        validate_preference_payload("delete", {})
