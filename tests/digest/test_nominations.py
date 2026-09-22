from research_agent.digest.nominations import (
    POPULATION_ENTRY_LIMIT,
    allocate_population_entries,
)


def test_empty_input_yields_full_shortfall():
    allocation = allocate_population_entries({}, day_ordinal=0)
    assert allocation.rotation == ()
    assert allocation.winners == ()
    assert allocation.shortfall == POPULATION_ENTRY_LIMIT


def test_empty_shard_does_not_block_other_configurations():
    allocation = allocate_population_entries(
        {"cfg-a": [[]], "cfg-b": [["p1", "p2"]]},
        day_ordinal=0,
    )
    assert [winner.family_id for winner in allocation.winners] == ["p1", "p2"]
    assert allocation.shortfall == POPULATION_ENTRY_LIMIT - 2


def test_overlapping_lists_deduplicate_and_record_supporters():
    allocation = allocate_population_entries(
        {
            "cfg-a": [["p1", "p2"]],
            "cfg-b": [["p1", "p3"]],
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


def test_rotation_by_day_ordinal_changes_which_configuration_starts():
    shard_nominations = {
        "cfg-a": [["shared"]],
        "cfg-b": [["shared"]],
    }
    day_zero = allocate_population_entries(shard_nominations, day_ordinal=0)
    day_one = allocate_population_entries(shard_nominations, day_ordinal=1)
    assert day_zero.rotation == ("cfg-a", "cfg-b")
    assert day_one.rotation == ("cfg-b", "cfg-a")
    assert day_zero.winners[0].configuration_id == "cfg-a"
    assert day_one.winners[0].configuration_id == "cfg-b"


def test_full_rotation_at_seeded_population_size():
    # Seven configurations, one unique paper each: every configuration wins
    # exactly one entry regardless of rotation, filling the limit exactly.
    shard_nominations = {f"cfg-{i}": [[f"paper-{i}"]] for i in range(7)}
    allocation = allocate_population_entries(shard_nominations, day_ordinal=3)
    assert len(allocation.winners) == POPULATION_ENTRY_LIMIT
    assert allocation.shortfall == 0
    assert {winner.family_id for winner in allocation.winners} == {
        f"paper-{i}" for i in range(7)
    }


def test_full_rotation_at_the_floor_of_four_genomes():
    # Four configurations must round-robin twice to fill seven population
    # places, each contributing roughly two entries.
    shard_nominations = {f"cfg-{i}": [[f"cfg{i}-a", f"cfg{i}-b"]] for i in range(4)}
    allocation = allocate_population_entries(shard_nominations, day_ordinal=0)
    assert len(allocation.winners) == POPULATION_ENTRY_LIMIT
    assert allocation.shortfall == 0
    counts: dict[str, int] = {}
    for winner in allocation.winners:
        counts[winner.configuration_id] = counts.get(winner.configuration_id, 0) + 1
    # Round-robin over four configs for seven slots gives three configs two
    # wins and one config one win.
    assert sorted(counts.values()) == [1, 2, 2, 2]


def test_shard_boundary_merge_is_round_robin_not_shard_exhaustive():
    long_shard = [f"long-{i}" for i in range(20)]
    short_shard = ["short-1", "short-2"]
    allocation = allocate_population_entries(
        {"cfg-a": [long_shard, short_shard]},
        day_ordinal=0,
    )
    winners = [winner.family_id for winner in allocation.winners]
    # Round-robin across the two shards interleaves, so the second shard's
    # first paper appears before the long shard is exhausted.
    assert winners[:4] == ["long-0", "short-1", "long-1", "short-2"]


def test_output_depends_only_on_nomination_bytes_not_any_score():
    shard_nominations = {
        "cfg-a": [["p1", "p2", "p3"]],
        "cfg-b": [["p4", "p5"]],
    }
    first = allocate_population_entries(shard_nominations, day_ordinal=5)
    second = allocate_population_entries(shard_nominations, day_ordinal=5)
    assert first == second
