from datetime import timedelta

import pytest

from research_agent.learning.corpus import mature_months, publication_week, split_weeks
from research_agent.outcomes.windows import instant, utc


def test_latest_month_is_fully_mature_not_just_its_first_day() -> None:
    # February 2020 ends at March 1 minus one microsecond; 455 days later
    # is May 30, 2021 minus one microsecond.
    boundary = utc(instant("2020-03-01T00:00:00.000000Z") + timedelta(days=455))
    months = mature_months(boundary)
    assert len(months) == 25
    assert months[-1] == "2020-02"
    assert (
        mature_months(utc(instant(boundary) - timedelta(microseconds=1)))[-1]
        == "2020-01"
    )
    assert months == tuple(sorted(months))


def test_split_enforces_forty_weeks_and_preserves_partition_chronology() -> None:
    weeks = tuple(
        publication_week(
            utc(instant("2020-01-06T00:00:00.000000Z") + timedelta(weeks=index))
        )
        for index in range(40)
    )
    result = split_weeks(weeks)
    assert tuple(
        map(
            len,
            (
                result.fit,
                result.development,
                result.calibration,
                result.locked_evaluation,
            ),
        )
    ) == (24, 6, 4, 6)
    assert (
        result.fit + result.development + result.calibration + result.locked_evaluation
        == weeks
    )
    for invalid in (
        weeks[:39],
        weeks[::-1],
        weeks[:-1] + (weeks[0],),
        weeks[:-1] + ("2020-W99",),
    ):
        with pytest.raises(ValueError):
            split_weeks(invalid)


def test_pilot_retains_shortages_and_is_invariant_to_input_order() -> None:
    from dataclasses import replace
    from uuid import uuid4
    from research_agent.contracts import ProducerVersion
    from research_agent.contracts.papers import ExternalIdentifier, PaperVersionRecord
    from research_agent.learning.corpus import select_pilot, selection_hash

    template = PaperVersionRecord(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2021-01-01T00:00:00.000000Z",
        str(uuid4()),
        str(uuid4()),
        (ExternalIdentifier("arxiv", "2001.00001v1"),),
        True,
        "2020-01-15T00:00:00.000000Z",
        None,
        ("d" * 64,),
        ("e" * 64,),
        "Title",
        "Abstract",
        (),
        "cs.AI",
        "f" * 64,
        "metadata",
        "v1",
    )
    candidates = tuple(
        replace(template, family_id=str(uuid4()), version_id=str(uuid4()))
        for _ in range(8)
    )
    freeze = "2021-06-01T00:00:00.000000Z"
    first = select_pilot(candidates, frozen_at=freeze)
    assert first == select_pilot(candidates[::-1] + (candidates[0],), frozen_at=freeze)
    assert len(first.selected) == 4 and first.shortfall_count == 96
    assert first.intended_count == 100
    assert first.selected == tuple(
        sorted(candidates, key=lambda paper: selection_hash(paper.family_id))[:4]
    )
    # Metadata-only original source is not replaced based on unavailable features.
    assert all(paper.text_source_kind == "metadata" for paper in first.selected)
    with pytest.raises(ValueError, match="conflicting"):
        select_pilot(
            candidates + (replace(candidates[0], version_id=str(uuid4())),),
            frozen_at=freeze,
        )
    with pytest.raises(ValueError, match="after"):
        select_pilot(
            (replace(template, created_at="2022-01-01T00:00:00.000000Z"),),
            frozen_at=freeze,
        )
