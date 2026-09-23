from datetime import timedelta

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import CitationFamilyRecord
from research_agent.contracts.papers import SourceInterval
from research_agent.outcomes.windows import instant, utc

T0 = "2020-01-01T12:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, T0)


def _build(
    number: int,
    field: str,
    date_state: str,
    publication_interval: SourceInterval | None,
    alternative_intervals: tuple[SourceInterval, ...],
) -> CitationFamilyRecord:
    return CitationFamilyRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=META.producer_version,
        config_hash=META.config_hash,
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
        publication_interval=publication_interval,
        alternative_publication_intervals=alternative_intervals,
        date_state=date_state,
        primary_subfield_id=field,
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("e" * 64,),
        is_target_family_self_link=False,
    )


def family(number: int, day: int, field: str = "A") -> CitationFamilyRecord:
    """A resolved citing family whose publication interval starts *day* after T0."""

    return family_between(number, field, day * 24, day * 24 + 24)


def family_between(
    number: int, field: str, start_hours: float, end_hours: float
) -> CitationFamilyRecord:
    """A resolved citing family dated to an exact, non-day-aligned interval."""

    interval = SourceInterval(
        utc(instant(T0) + timedelta(hours=start_hours)),
        utc(instant(T0) + timedelta(hours=end_hours)),
    )
    return _build(number, field, "known", interval, ())
