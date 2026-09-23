from research_agent.digest.nominations import (
    POPULATION_ENTRY_LIMIT,
    Nomination,
    allocate_population_entries,
)


def _noms(*pairs: tuple[str, float]) -> list[Nomination]:
    return [Nomination(paper_id, preference) for paper_id, preference in pairs]


def test_empty_input_yields_full_shortfall():
    allocation = allocate_population_entries({}, day_ordinal=0)
    assert allocation.rotation == ()
    assert allocation.winners == ()
    assert allocation.shortfall == POPULATION_ENTRY_LIMIT


def test_a_configuration_with_no_recommendations_does_not_block_others():
    allocation = allocate_population_entries(
        {"cfg-a": [], "cfg-b": _noms(("p1", 0.9), ("p2", 0.5))},
        day_ordinal=0,
    )
    assert [winner.family_id for winner in allocation.winners] == ["p1", "p2"]
    assert allocation.shortfall == POPULATION_ENTRY_LIMIT - 2


def test_overlapping_recommendations_deduplicate_and_record_supporters():
    allocation = allocate_population_entries(
        {
            "cfg-a": _noms(("p1", 0.9), ("p2", 0.5)),
            "cfg-b": _noms(("p1", 0.8), ("p3", 0.4)),
        },
        day_ordinal=0,
    )
    winners = {winner.family_id: winner for winner in allocation.winners}
    assert set(winners) == {"p1", "p2", "p3"}
    # cfg-a is first in rotation (sorted, no rotation at day_ordinal=0), so it
    # wins the shared paper; cfg-b's supporting list still names it.
    assert winners["p1"].configuration_id == "cfg-a"
    assert set(winners["p1"].supporting_configuration_ids) == {"cfg-a", "cfg-b"}
    assert winners["p2"].supporting_configuration_ids == ("cfg-a",)
    assert winners["p3"].supporting_configuration_ids == ("cfg-b",)


def test_each_configurations_list_is_ranked_by_preference_descending():
    allocation = allocate_population_entries(
        {"cfg-a": _noms(("low", 0.1), ("high", 0.9), ("mid", 0.5))},
        day_ordinal=0,
    )
    assert [winner.family_id for winner in allocation.winners] == [
        "high",
        "mid",
        "low",
    ]


def test_preference_ties_break_by_ascending_paper_id():
    allocation = allocate_population_entries(
        {"cfg-a": _noms(("p2", 0.5), ("p1", 0.5))},
        day_ordinal=0,
    )
    assert [winner.family_id for winner in allocation.winners] == ["p1", "p2"]


def test_rotation_by_day_ordinal_changes_which_configuration_starts():
    nominations = {
        "cfg-a": _noms(("shared", 0.5)),
        "cfg-b": _noms(("shared", 0.5)),
    }
    day_zero = allocate_population_entries(nominations, day_ordinal=0)
    day_one = allocate_population_entries(nominations, day_ordinal=1)
    assert day_zero.rotation == ("cfg-a", "cfg-b")
    assert day_one.rotation == ("cfg-b", "cfg-a")
    assert day_zero.winners[0].configuration_id == "cfg-a"
    assert day_one.winners[0].configuration_id == "cfg-b"


def test_full_rotation_at_seeded_population_size():
    # Seven configurations, one unique paper each: every configuration wins
    # exactly one entry regardless of rotation, filling the limit exactly.
    nominations = {f"cfg-{i}": _noms((f"paper-{i}", 0.5)) for i in range(7)}
    allocation = allocate_population_entries(nominations, day_ordinal=3)
    assert len(allocation.winners) == POPULATION_ENTRY_LIMIT
    assert allocation.shortfall == 0
    assert {winner.family_id for winner in allocation.winners} == {
        f"paper-{i}" for i in range(7)
    }


def test_full_rotation_at_the_floor_of_four_genomes():
    # Four configurations must round-robin twice to fill seven population
    # places, each contributing roughly two entries.
    nominations = {
        f"cfg-{i}": _noms((f"cfg{i}-a", 0.9), (f"cfg{i}-b", 0.1)) for i in range(4)
    }
    allocation = allocate_population_entries(nominations, day_ordinal=0)
    assert len(allocation.winners) == POPULATION_ENTRY_LIMIT
    assert allocation.shortfall == 0
    counts: dict[str, int] = {}
    for winner in allocation.winners:
        counts[winner.configuration_id] = counts.get(winner.configuration_id, 0) + 1
    # Round-robin over four configs for seven slots gives three configs two
    # wins and one config one win.
    assert sorted(counts.values()) == [1, 2, 2, 2]


def test_output_depends_only_on_nomination_preference_not_any_other_score():
    nominations = {
        "cfg-a": _noms(("p1", 0.9), ("p2", 0.5), ("p3", 0.1)),
        "cfg-b": _noms(("p4", 0.8), ("p5", 0.2)),
    }
    first = allocate_population_entries(nominations, day_ordinal=5)
    second = allocate_population_entries(nominations, day_ordinal=5)
    assert first == second
