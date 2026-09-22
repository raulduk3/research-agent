from research_agent.digest.controls import CONTROL_LIMIT, _rank_key, sample_controls

BATCH_HASH = "batch-hash-1"
ISLAND = "cs"
RUBRIC_VERSION = "v1"


def test_replay_reproduces_the_same_draw():
    eligible = ["p1", "p2", "p3", "p4", "p5"]
    first = sample_controls(
        eligible,
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    second = sample_controls(
        eligible,
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert first == second


def test_empty_pool_yields_no_selection_and_no_probability():
    draw = sample_controls(
        [],
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert draw.selected == ()
    assert draw.inclusion_probability is None
    assert draw.shortfall == CONTROL_LIMIT


def test_population_entries_are_excluded_without_duplication():
    draw = sample_controls(
        ["p1", "p2", "p3"],
        population_family_ids={"p1", "p2"},
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert draw.selected == ("p3",)
    assert "p1" not in draw.selected
    assert "p2" not in draw.selected


def test_draw_does_not_depend_on_input_order_or_any_score():
    forward = sample_controls(
        ["p1", "p2", "p3", "p4"],
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    reversed_input = sample_controls(
        ["p4", "p3", "p2", "p1"],
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert forward == reversed_input


def test_explicit_conditional_inclusion_probabilities():
    five = sample_controls(
        ["p1", "p2", "p3", "p4", "p5"],
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert five.inclusion_probability == CONTROL_LIMIT / 5

    exact = sample_controls(
        ["p1", "p2", "p3"],
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert exact.inclusion_probability == 1.0

    fewer = sample_controls(
        ["p1", "p2"],
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert fewer.inclusion_probability == 1.0


def test_selection_matches_hand_computed_rank_order():
    eligible = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
    draw = sample_controls(
        eligible,
        population_family_ids=set(),
        batch_hash=BATCH_HASH,
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    expected = sorted(
        eligible,
        key=lambda family_id: (
            _rank_key(BATCH_HASH, ISLAND, RUBRIC_VERSION, family_id),
            family_id,
        ),
    )[:CONTROL_LIMIT]
    assert list(draw.selected) == expected


def test_different_batch_hash_changes_the_draw():
    eligible = ["p1", "p2", "p3", "p4", "p5"]
    one = sample_controls(
        eligible,
        population_family_ids=set(),
        batch_hash="batch-a",
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    other = sample_controls(
        eligible,
        population_family_ids=set(),
        batch_hash="batch-b",
        island=ISLAND,
        control_rubric_version=RUBRIC_VERSION,
    )
    assert one.selected != other.selected
