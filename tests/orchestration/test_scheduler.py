from __future__ import annotations

from datetime import datetime, timezone

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.scheduler import (
    QueuedSlot,
    SlotOutcome,
    draw_coverage_sample,
    order_queue,
    schedule_slots,
)
from research_agent.orchestration.slots import Slot, build_slot

BATCH_ID = "a" * 64
CONFIGURATION_A = "123e4567-e89b-42d3-a456-426614174000"
CONFIGURATION_B = "123e4567-e89b-42d3-a456-426614174001"
FAMILY_IDS = tuple(f"family-{i}" for i in range(10))


# -- draw_coverage_sample (AG-05) -----------------------------------------


def test_draw_coverage_sample_takes_the_largest_covered_prefix() -> None:
    sample = draw_coverage_sample(
        batch_id=BATCH_ID,
        island="cs",
        family_ids=FAMILY_IDS,
        seed=1,
        remaining_spend_micros=3_000_000,
        cost_per_run_micros=1_000_000,
    )
    assert sample.coverage == 3
    assert len(sample.sampled_family_ids) == 3
    assert len(sample.excluded_family_ids) == 7
    assert set(sample.sampled_family_ids) | set(sample.excluded_family_ids) == set(
        FAMILY_IDS
    )
    assert sample.island == "cs"
    assert sample.seed == 1


def test_draw_coverage_sample_is_identical_across_two_genomes_for_a_fixed_seed() -> (
    None
):
    # The draw takes no genome-specific input, so calling it once per island
    # per day already gives every genome the identical sample; this test
    # documents that guarantee by drawing twice and comparing.
    first = draw_coverage_sample(
        batch_id=BATCH_ID,
        island="cs",
        family_ids=FAMILY_IDS,
        seed=7,
        remaining_spend_micros=5_000_000,
        cost_per_run_micros=1_000_000,
    )
    second = draw_coverage_sample(
        batch_id=BATCH_ID,
        island="cs",
        family_ids=FAMILY_IDS,
        seed=7,
        remaining_spend_micros=5_000_000,
        cost_per_run_micros=1_000_000,
    )
    assert first.sampled_family_ids == second.sampled_family_ids
    assert first.coverage == 5


def test_draw_coverage_sample_changes_order_with_a_different_seed() -> None:
    low_budget = dict(
        batch_id=BATCH_ID,
        island="cs",
        family_ids=FAMILY_IDS,
        remaining_spend_micros=1_000_000,
        cost_per_run_micros=1_000_000,
    )
    first = draw_coverage_sample(seed=1, **low_budget)
    second = draw_coverage_sample(seed=2, **low_budget)
    assert first.sampled_family_ids != second.sampled_family_ids


def test_draw_coverage_sample_zero_spend_covers_nothing() -> None:
    sample = draw_coverage_sample(
        batch_id=BATCH_ID,
        island="cs",
        family_ids=FAMILY_IDS,
        seed=1,
        remaining_spend_micros=0,
        cost_per_run_micros=1_000_000,
    )
    assert sample.coverage == 0
    assert sample.sampled_family_ids == ()
    assert len(sample.excluded_family_ids) == len(FAMILY_IDS)


def test_draw_coverage_sample_full_spend_covers_the_whole_stream() -> None:
    sample = draw_coverage_sample(
        batch_id=BATCH_ID,
        island="cs",
        family_ids=FAMILY_IDS,
        seed=1,
        remaining_spend_micros=100_000_000,
        cost_per_run_micros=1_000_000,
    )
    assert sample.coverage == len(FAMILY_IDS)


def test_draw_coverage_sample_rejects_an_unadmitted_island() -> None:
    with pytest.raises(ContractValidationError):
        draw_coverage_sample(
            batch_id=BATCH_ID,
            island="physics",
            family_ids=FAMILY_IDS,
            seed=1,
            remaining_spend_micros=1_000_000,
            cost_per_run_micros=1_000_000,
        )


def test_draw_coverage_sample_rejects_duplicate_family_ids() -> None:
    with pytest.raises(ContractValidationError):
        draw_coverage_sample(
            batch_id=BATCH_ID,
            island="cs",
            family_ids=(*FAMILY_IDS, FAMILY_IDS[0]),
            seed=1,
            remaining_spend_micros=1_000_000,
            cost_per_run_micros=1_000_000,
        )


# -- order_queue and schedule_slots (AG-05) --------------------------------


def _slot(paper_id: str, configuration_id: str = CONFIGURATION_A) -> Slot:
    return build_slot(BATCH_ID, paper_id, configuration_id)


def test_order_queue_orders_by_deadline_then_slot_id() -> None:
    entries = [
        QueuedSlot(_slot("paper-b"), "2027-01-02T00:00:00.000000Z"),
        QueuedSlot(_slot("paper-a"), "2027-01-01T00:00:00.000000Z"),
        QueuedSlot(_slot("paper-c"), "2027-01-01T00:00:00.000000Z"),
    ]
    ordered = order_queue(entries)
    assert [entry.slot.paper_id for entry in ordered] == [
        "paper-a",
        "paper-c",
        "paper-b",
    ]


def test_schedule_slots_dispatches_every_entry_and_records_its_outcome() -> None:
    entries = [
        QueuedSlot(_slot("paper-a"), "2027-01-01T00:00:00.000000Z"),
        QueuedSlot(_slot("paper-b"), "2027-01-02T00:00:00.000000Z"),
    ]
    dispatched: list[str] = []

    def dispatch(entry: QueuedSlot) -> SlotOutcome:
        dispatched.append(entry.slot.paper_id)
        return "completed"

    results = schedule_slots(
        entries,
        dispatch=dispatch,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert dispatched == ["paper-a", "paper-b"]
    assert all(result.outcome == "completed" for result in results)


def test_schedule_slots_records_missed_deadline_without_dispatching() -> None:
    entries = [QueuedSlot(_slot("paper-a"), "2020-01-01T00:00:00.000000Z")]
    calls: list[str] = []

    def dispatch(entry: QueuedSlot) -> SlotOutcome:
        calls.append(entry.slot.paper_id)
        return "completed"

    results = schedule_slots(
        entries,
        dispatch=dispatch,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert calls == []
    assert results[0].outcome == "missed_deadline"


def test_schedule_slots_reports_a_void_outcome_from_the_dispatcher() -> None:
    entries = [QueuedSlot(_slot("paper-a"), "2027-01-01T00:00:00.000000Z")]
    results = schedule_slots(
        entries,
        dispatch=lambda entry: "void",
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert results[0].outcome == "void"


def test_schedule_slots_rejects_a_non_positive_concurrency_bound() -> None:
    with pytest.raises(ContractValidationError):
        schedule_slots([], dispatch=lambda entry: "completed", max_concurrent=0)


def test_schedule_slots_no_entries_produces_no_results() -> None:
    assert schedule_slots([], dispatch=lambda entry: "completed") == ()
