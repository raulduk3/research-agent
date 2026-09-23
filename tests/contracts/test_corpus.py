"""The card fields a corpus row records for the metadata block (#278)."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    canonical_json,
)
from research_agent.contracts.corpus import CorpusRelease, CorpusRow

# A Monday, so the first-availability weekday is 0.
STAMP = "2026-09-21T00:00:00.000000Z"
CARD = {
    "abstract_tokens": 180,
    "title_tokens": 9,
    "first_available_weekday": 0,
    "code_link": True,
}


def _row(**card: object) -> CorpusRow:
    return CorpusRow(
        str(uuid4()),
        str(uuid4()),
        STAMP,
        "2026-W39",
        "cs.AI",
        0,
        "d" * 64,
        (None, None, None),
        (False, False, False),
        "pilot",
        (),
        3,
        ("cs.AI",),
        1,
        **card,  # type: ignore[arg-type]
    )


def test_an_unrecorded_row_keeps_the_bytes_it_had_before_card_fields() -> None:
    row = _row()
    body = json.loads(row.to_canonical_json())
    assert not set(CARD) & set(body)
    assert CorpusRow.from_json(row.to_canonical_json()) == row
    release = CorpusRelease(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        STAMP,
        "acquisition_pilot",
        "1" * 64,
        "2" * 64,
        20260920,
        STAMP,
        STAMP,
        100,
        "3" * 64,
        (row,),
        99,
        "4" * 64,
        "5" * 64,
        (),
        None,
    )
    # The release serializes each row exactly as the row does.
    assert json.loads(release.to_canonical_json())["rows"] == [body]
    assert CorpusRelease.from_json(release.to_canonical_json()) == release


def test_recorded_card_fields_round_trip() -> None:
    row = _row(**CARD)
    body = json.loads(row.to_canonical_json())
    assert {name: body[name] for name in CARD} == CARD
    assert CorpusRow.from_json(row.to_canonical_json()) == row


def test_card_fields_are_all_present_or_all_omitted_and_never_all_null() -> None:
    body = json.loads(_row(**CARD).to_canonical_json())
    partial = {key: value for key, value in body.items() if key != "code_link"}
    with pytest.raises(ContractValidationError, match="fields"):
        CorpusRow.from_json(canonical_json(partial))
    nulls = {**body, **{name: None for name in CARD}}
    with pytest.raises(ContractValidationError, match="omitted, never null"):
        CorpusRow.from_json(canonical_json(nulls))


def test_card_field_values_are_checked_against_the_row() -> None:
    with pytest.raises(ContractValidationError, match="differs from t0"):
        _row(**{**CARD, "first_available_weekday": 3})
    with pytest.raises(ContractValidationError, match="weekday is invalid"):
        _row(**{**CARD, "first_available_weekday": 7})
    with pytest.raises(ContractValidationError, match="boolean"):
        _row(**{**CARD, "code_link": 1})
    with pytest.raises(ValueError):
        _row(**{**CARD, "title_tokens": -1})
    # A weekday needs a known first-public time.
    with pytest.raises(ContractValidationError, match="differs from t0"):
        replace(_row(**CARD), t0=None, publication_week=None)
