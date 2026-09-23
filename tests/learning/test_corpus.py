from dataclasses import replace
from datetime import timedelta

import pytest

from research_agent.contracts import sha256_hex
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_CATEGORIES,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
    PilotCandidate,
    mature_months,
    publication_week,
    select_pilot,
    selection_hash,
    split_weeks,
)
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


def _candidates() -> tuple[PilotCandidate, ...]:
    # Eight January 2020 families; two are cross-listed, one is out of scope.
    values = []
    for number in range(1, 9):
        categories = ("cs.CV", "cs.LG") if number % 3 == 0 else ("cs.AI",)
        values.append(
            PilotCandidate(
                f"2001.{number:05d}", "2020-01-15T00:00:00.000000Z", categories
            )
        )
    values.append(
        PilotCandidate("2001.00099", "2020-01-15T00:00:00.000000Z", ("cs.CV",))
    )
    return tuple(values)


def test_pilot_ranks_arxiv_ids_retains_shortages_and_ignores_order() -> None:
    candidates = _candidates()
    freeze = "2021-06-01T00:00:00.000000Z"
    first = select_pilot(candidates, frozen_at=freeze)
    assert first == select_pilot(candidates[::-1] + (candidates[0],), frozen_at=freeze)
    assert len(first.selected) == 4 and first.shortfall_count == 96
    assert first.intended_count == 100
    assert first.seed == SELECTION_SEED
    assert first.population_rule == DEFAULT_POPULATION_RULE
    eligible = [c for c in candidates if c.family_id != "2001.00099"]
    assert first.selected == tuple(
        sorted(eligible, key=lambda item: selection_hash(item.family_id))[:4]
    )
    assert dict(first.eligible_counts)["2020-01"] == 8
    # The rank key is reproducible from the public arXiv id alone.
    assert selection_hash("2001.00001") == sha256_hex(
        b'{"paper_family_id":"2001.00001","seed":20260920}'
    )


def test_cross_listed_families_are_eligible_and_others_are_not() -> None:
    selected = select_pilot(
        tuple(c for c in _candidates() if c.categories != ("cs.AI",)),
        frozen_at="2021-06-01T00:00:00.000000Z",
    ).selected
    assert {c.family_id for c in selected} == {"2001.00003", "2001.00006"}


def test_conflicting_first_public_times_are_refused() -> None:
    candidates = _candidates()
    with pytest.raises(ValueError, match="conflicting"):
        select_pilot(
            candidates
            + (replace(candidates[0], first_public_at="2020-01-16T00:00:00.000000Z"),),
            frozen_at="2021-06-01T00:00:00.000000Z",
        )
    for bad in ("2001.00001v1", "cs/0101001"):
        with pytest.raises(ValueError):
            PilotCandidate(bad, "2020-01-15T00:00:00.000000Z", ("cs.AI",))


def test_primary_category_defaults_to_the_first_listed_category() -> None:
    candidate = PilotCandidate(
        "2001.00001", "2020-01-15T00:00:00.000000Z", ("cs.LG", "cs.CV")
    )
    assert candidate.primary_category == "cs.LG"


def test_explicit_primary_category_must_be_among_the_listed_categories() -> None:
    with pytest.raises(ValueError):
        PilotCandidate(
            "2001.00001",
            "2020-01-15T00:00:00.000000Z",
            ("cs.LG", "cs.CV"),
            "cs.AI",
        )
    candidate = PilotCandidate(
        "2001.00001", "2020-01-15T00:00:00.000000Z", ("cs.LG", "cs.CV"), "cs.CV"
    )
    assert candidate.primary_category == "cs.CV"


def test_selected_candidates_carry_their_primary_category() -> None:
    selection = select_pilot(_candidates(), frozen_at="2021-06-01T00:00:00.000000Z")
    assert all(c.primary_category in c.categories for c in selection.selected)


def test_omitted_selection_parameters_reproduce_todays_pilot_exactly() -> None:
    # Regression: the parameterized selection must still default to the
    # committed 100-family pilot rule when no selection parameter is given.
    candidates = _candidates()
    freeze = "2021-06-01T00:00:00.000000Z"
    default = select_pilot(candidates, frozen_at=freeze)
    explicit = select_pilot(
        candidates,
        frozen_at=freeze,
        seed=SELECTION_SEED,
        cap=DEFAULT_CAP,
        per_month=DEFAULT_PER_MONTH,
        population_rule=DEFAULT_POPULATION_RULE,
    )
    assert default == explicit


def test_default_categories_admit_all_four_owner_named_categories() -> None:
    candidates = (
        PilotCandidate("2001.00001", "2020-01-15T00:00:00.000000Z", ("cs.AI",)),
        PilotCandidate("2001.00002", "2020-01-15T00:00:00.000000Z", ("cs.LG",)),
        PilotCandidate("2001.00003", "2020-01-15T00:00:00.000000Z", ("quant-ph",)),
        PilotCandidate("2001.00004", "2020-01-15T00:00:00.000000Z", ("q-bio",)),
        PilotCandidate("2001.00005", "2020-01-15T00:00:00.000000Z", ("math.CO",)),
    )
    freeze = "2021-06-01T00:00:00.000000Z"
    selection = select_pilot(candidates, frozen_at=freeze, per_month=0, cap=10)
    assert {c.family_id for c in selection.selected} == {
        "2001.00001",
        "2001.00002",
        "2001.00003",
        "2001.00004",
    }
    assert selection.categories == tuple(sorted(DEFAULT_CATEGORIES))


def test_explicit_categories_narrow_eligibility_and_are_recorded() -> None:
    candidates = (
        PilotCandidate("2001.00001", "2020-01-15T00:00:00.000000Z", ("cs.AI",)),
        PilotCandidate("2001.00003", "2020-01-15T00:00:00.000000Z", ("quant-ph",)),
    )
    freeze = "2021-06-01T00:00:00.000000Z"
    selection = select_pilot(
        candidates,
        frozen_at=freeze,
        per_month=0,
        cap=10,
        categories=("cs.AI", "cs.LG"),
    )
    assert {c.family_id for c in selection.selected} == {"2001.00001"}
    assert selection.categories == ("cs.AI", "cs.LG")


def test_explicit_two_category_selection_reproduces_the_original_pilot() -> None:
    # Regression: explicitly requesting the original two categories selects
    # exactly what the hardcoded cs.AI/cs.LG pilot did before categories
    # became a configured value of the run.
    candidates = _candidates()
    freeze = "2021-06-01T00:00:00.000000Z"
    original_two_category = select_pilot(
        candidates, frozen_at=freeze, categories=("cs.AI", "cs.LG")
    )
    default_four_category = select_pilot(candidates, frozen_at=freeze)
    assert original_two_category.selected == default_four_category.selected
    assert original_two_category.categories == ("cs.AI", "cs.LG")


def test_zero_per_month_draws_uniformly_over_the_whole_window_capped_at_n() -> None:
    candidates = _candidates()
    freeze = "2021-06-01T00:00:00.000000Z"
    eligible = [c for c in candidates if c.family_id != "2001.00099"]
    selection = select_pilot(candidates, frozen_at=freeze, per_month=0, cap=3)
    assert selection.selected == tuple(
        sorted(eligible, key=lambda item: selection_hash(item.family_id))[:3]
    )
    assert selection.intended_count == 3
    # A pooled draw has no per-month target, so nothing is reported short.
    assert selection.shortfall_count == 0
    assert dict(selection.eligible_counts)["2020-01"] == 8


def test_cap_truncates_the_stratified_selection() -> None:
    candidates = _candidates()
    selection = select_pilot(
        candidates, frozen_at="2021-06-01T00:00:00.000000Z", per_month=4, cap=2
    )
    assert len(selection.selected) == 2
    assert selection.intended_count == 2


def test_seed_and_population_rule_are_recorded_verbatim() -> None:
    candidates = _candidates()
    rule = "every cs.AI or cs.LG family, uniform, seeded, capped at 10000"
    selection = select_pilot(
        candidates,
        frozen_at="2021-06-01T00:00:00.000000Z",
        seed=1,
        cap=10000,
        per_month=0,
        population_rule=rule,
    )
    assert selection.seed == 1
    assert selection.population_rule == rule
    assert selection.intended_count == 10000


def test_negative_cap_and_per_month_are_refused() -> None:
    candidates = _candidates()
    freeze = "2021-06-01T00:00:00.000000Z"
    with pytest.raises(ValueError, match="cap"):
        select_pilot(candidates, frozen_at=freeze, cap=-1)
    with pytest.raises(ValueError, match="per_month"):
        select_pilot(candidates, frozen_at=freeze, per_month=-1)
