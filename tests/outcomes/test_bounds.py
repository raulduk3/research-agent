from dataclasses import replace
from datetime import timedelta

from research_agent.contracts import ProducerVersion
from research_agent.contracts.learning import CitationFamilyRecord
from research_agent.contracts.papers import SourceInterval
from research_agent.outcomes.bounds import citation_bounds
from research_agent.outcomes.windows import instant, utc

T0 = "2020-01-01T12:00:00.000000Z"


def family(number: int, day: int, field: str = "A") -> CitationFamilyRecord:
    return CitationFamilyRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        created_at="2022-01-01T00:00:00.000000Z",
        canonical_family_id=f"family-{number}",
        provider_work_ids=(f"W{number}",),
        external_ids=(),
        identity_evidence_hashes=("d" * 64,),
        representative_work_id=f"W{number}",
        representative_rule="lowest_provider_id",
        identity_state="resolved",
        possible_identity_cluster=None,
        target_link_work_ids=("W1000",),
        publication_interval=SourceInterval(
            utc(instant(T0) + timedelta(days=day)),
            utc(instant(T0) + timedelta(days=day + 1)),
        ),
        alternative_publication_intervals=(),
        date_state="known",
        primary_subfield_id=field,
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("e" * 64,),
        is_target_family_self_link=False,
    )


def test_exact_aliases_count_once_and_self_family_links_do_not_count() -> None:
    first = family(1, 10)
    duplicate = replace(first, canonical_family_id="alias")
    self_link = replace(family(2, 20), is_target_family_self_link=True)
    evidence = citation_bounds(
        (first, duplicate, self_link), t0=T0, target_subfield="A", complete=True
    )
    assert (
        evidence.counts.year_families.lower == evidence.counts.year_families.upper == 1
    )


def test_late_windows_and_distinct_non_target_subfields() -> None:
    evidence = citation_bounds(
        (
            family(1, 200, "B"),
            family(2, 300, "C"),
            family(3, 10, "B"),
            family(4, 10, "A"),
        ),
        t0=T0,
        target_subfield="A",
        complete=True,
    )
    assert evidence.counts.year_families.lower == 4
    assert evidence.counts.late_180_270_families.lower == 1
    assert evidence.counts.late_270_365_families.lower == 1
    assert (
        evidence.counts.other_primary_subfields.lower
        == evidence.counts.other_primary_subfields.upper
        == 2
    )
    assert evidence.subfield_witnesses == (("B", "family-1"), ("C", "family-2"))


def test_possible_identity_cannot_satisfy_both_windows_or_two_subfields() -> None:
    records = tuple(
        replace(record, identity_state="ambiguous", possible_identity_cluster="cluster")
        for record in (family(1, 200, "B"), family(2, 300, "C"))
    )
    evidence = citation_bounds(records, t0=T0, target_subfield="A", complete=True)
    assert evidence.counts.year_families.lower == 1
    assert evidence.counts.year_families.upper == 2
    assert (
        evidence.counts.late_180_270_families.lower
        == evidence.counts.late_270_365_families.lower
        == 0
    )
    assert evidence.counts.other_primary_subfields.lower == 0
    assert evidence.counts.other_primary_subfields.upper == 2


def test_one_conflicting_family_can_supply_only_one_possible_subfield() -> None:
    record = replace(
        family(1, 200),
        primary_subfield_id=None,
        subfield_state="conflicting",
        alternative_subfield_ids=("B", "C"),
    )
    evidence = citation_bounds((record,), t0=T0, target_subfield="A", complete=True)
    assert evidence.counts.other_primary_subfields.lower == 0
    assert evidence.counts.other_primary_subfields.upper == 1
    record2 = replace(
        record,
        canonical_family_id="family-2",
        provider_work_ids=("W2",),
        representative_work_id="W2",
    )
    assert (
        citation_bounds(
            (record, record2), t0=T0, target_subfield="A", complete=True
        ).counts.other_primary_subfields.upper
        == 2
    )


def test_missing_dates_and_incomplete_capture_never_create_zero_upper_bounds() -> None:
    record = replace(
        family(1, 200),
        publication_interval=None,
        date_state="missing",
        primary_subfield_id=None,
        subfield_state="missing",
    )
    complete = citation_bounds((record,), t0=T0, target_subfield="A", complete=True)
    assert (
        complete.counts.year_families.lower == 0
        and complete.counts.year_families.upper == 1
    )
    assert complete.counts.other_primary_subfields.upper == 1
    partial = citation_bounds((), t0=T0, target_subfield="A", complete=False)
    assert partial.counts.year_families.upper is None
    assert partial.counts.late_180_270_families.upper is None
    assert partial.counts.other_primary_subfields.upper is None


def test_subfield_matching_handles_long_augmenting_paths_without_recursion() -> None:
    from research_agent.outcomes.bounds import _maximum_subfields

    # The last family requires displacing every preceding match.
    choices = [{f"{index:05d}", f"{index + 1:05d}"} for index in range(1100)]
    choices.append({"00000"})
    assert _maximum_subfields(choices) == 1101


def test_subfield_matching_matches_exhaustive_small_assignments() -> None:
    from itertools import product
    from research_agent.outcomes.bounds import _maximum_subfields

    candidates = [set(), {"A"}, {"B"}, {"A", "B"}, {"A", "C"}]
    for choices in product(candidates, repeat=3):
        exhaustive = max(
            len({field for field in assignment if field is not None})
            for assignment in product(*(tuple(choice) + (None,) for choice in choices))
        )
        assert _maximum_subfields(list(choices)) == exhaustive


def test_conflicting_self_link_aliases_cannot_prove_negative() -> None:
    import pytest
    from research_agent.storage.errors import IntegrityFailure

    record = family(1, 10)
    alias = replace(
        record, canonical_family_id="alias", is_target_family_self_link=True
    )
    with pytest.raises(IntegrityFailure, match="self linkage"):
        citation_bounds((record, alias), t0=T0, target_subfield="A", complete=True)
