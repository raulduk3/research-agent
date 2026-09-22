from research_agent.digest.services import (
    SERVICE_ENTRY_LIMIT,
    ServicePick,
    allocate_service_entries,
)


def test_no_services_yields_full_shortfall():
    allocation = allocate_service_entries({}, already_selected=set())
    assert allocation.selected == ()
    assert allocation.omitted == ()
    assert allocation.shortfall == SERVICE_ENTRY_LIMIT


def test_lexical_service_order_and_preserved_capture_order():
    picks = {
        "b_service": [ServicePick("b-ref-1", "b-family-1")],
        "a_service": [ServicePick("a-ref-1", "a-family-1")],
    }
    allocation = allocate_service_entries(picks, already_selected=set())
    # a_service sorts before b_service, so its family wins the first slot.
    assert allocation.selected == ("a-family-1", "b-family-1")


def test_unmatched_reference_is_recorded_omitted_not_a_second_corpus():
    picks = {
        "svc": [
            ServicePick("unmatched-ref", None),
            ServicePick("ref-1", "family-1"),
        ]
    }
    allocation = allocate_service_entries(picks, already_selected=set())
    assert allocation.selected == ("family-1",)
    assert allocation.omitted == ("unmatched-ref",)


def test_control_overlap_is_skipped_without_a_slot_or_omission():
    picks = {
        "svc": [ServicePick("ref-1", "family-1"), ServicePick("ref-2", "family-2")]
    }
    allocation = allocate_service_entries(picks, already_selected={"family-1"})
    assert allocation.selected == ("family-2",)
    assert allocation.omitted == ()


def test_source_outage_leaves_other_services_readable():
    picks = {
        "dead_service": [],
        "live_service": [ServicePick("ref-1", "family-1")],
    }
    allocation = allocate_service_entries(picks, already_selected=set())
    assert allocation.selected == ("family-1",)
    assert allocation.shortfall == 1


def test_one_hundred_offered_picks_never_exceed_the_limit():
    picks = {"svc": [ServicePick(f"ref-{i}", f"family-{i}") for i in range(100)]}
    allocation = allocate_service_entries(picks, already_selected=set())
    assert len(allocation.selected) == SERVICE_ENTRY_LIMIT
    assert allocation.selected == ("family-0", "family-1")
