"""Prospective eligibility against the actual storage seal timestamp (EN-02).

``check_prospective`` evaluates a frozen target definition's own windows
against the citation family evidence preserved for a paper, using the
forecast's actual seal timestamp as the cutoff. It never treats when a
citing record was captured as a proxy for when the citation itself
happened: a family captured after sealing whose dated publication interval
definitely precedes sealing still marks the question preexisting-event,
and an interval that cannot be pinned to either side of sealing marks it
timing-ambiguous rather than silently eligible. Because a target's own
windows never start before its own start offset, a target whose windows
open only after the fixed 24-hour seal deadline -- late_citation_activity_365d's
two late windows -- can never be preexisting-event or timing-ambiguous:
no evidence dated within an unreached window can exist yet.
"""

from __future__ import annotations

from collections.abc import Sequence

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.forecasts import ProspectiveEligibility
from research_agent.contracts.learning import (
    CitationFamilyRecord,
    TargetDefinition,
    TargetWindow,
)
from research_agent.contracts.papers import SourceInterval
from research_agent.contracts.primitives import ContractValidationError
from research_agent.outcomes.windows import OutcomeWindow, forecast_deadline, instant

__all__ = ["check_prospective"]

_OBSERVATION_KINDS = frozenset({"prospective_maturity", "historical_reconstructed"})
_PRE = frozenset({"definite"})
_PRE_OR_AMBIGUOUS = frozenset({"definite", "possible"})


def _intervals(record: CitationFamilyRecord) -> tuple[SourceInterval, ...]:
    intervals = record.alternative_publication_intervals
    if record.publication_interval is not None:
        intervals = (record.publication_interval, *intervals)
    return intervals


def _clipped_window(window: TargetWindow, seal_offset: int) -> OutcomeWindow | None:
    if window.start_offset_seconds >= seal_offset:
        return None
    return OutcomeWindow(
        window.start_offset_seconds, min(window.end_offset_seconds, seal_offset)
    )


def _predicate_result(
    target: TargetDefinition,
    t0: str,
    seal_offset: int,
    records: Sequence[CitationFamilyRecord],
    allowed: frozenset[str],
) -> tuple[bool, tuple[str, ...]]:
    hits: list[dict[str, CitationFamilyRecord]] = []
    for window in target.windows:
        clipped = _clipped_window(window, seal_offset)
        bucket: dict[str, CitationFamilyRecord] = {}
        if clipped is not None:
            for record in records:
                if record.is_target_family_self_link:
                    continue
                if clipped.classify_alternatives(t0, _intervals(record)) in allowed:
                    bucket.setdefault(record.canonical_family_id, record)
        hits.append(bucket)

    chosen: list[CitationFamilyRecord]
    if target.predicate == "both_window_activity":
        if not all(hits):
            return False, ()
        chosen = [next(iter(bucket.values())) for bucket in hits]
    elif target.predicate == "distinct_family_threshold":
        combined = hits[0]
        if len(combined) < target.threshold:
            return False, ()
        chosen = list(combined.values())
    elif target.predicate == "distinct_other_subfield_threshold":
        by_subfield: dict[str, CitationFamilyRecord] = {}
        for record in hits[0].values():
            if (
                record.subfield_state == "known"
                and record.primary_subfield_id is not None
            ):
                by_subfield.setdefault(record.primary_subfield_id, record)
        if len(by_subfield) < target.threshold:
            return False, ()
        chosen = list(by_subfield.values())
    else:
        raise ContractValidationError("target predicate is not supported")

    hashes = tuple(
        sorted({sha256_hex(record.to_canonical_json()) for record in chosen})
    )
    return True, hashes


def check_prospective(
    target: TargetDefinition,
    *,
    t0: str,
    seal_at: str,
    families: Sequence[CitationFamilyRecord],
    observation_kind: str = "prospective_maturity",
) -> ProspectiveEligibility:
    """Evaluate *target* against evidence preserved as of *seal_at* (EN-02).

    ``families`` is the paper's preserved candidate citation-family
    evidence; a family need not be limited to this target's own windows,
    since window relevance is decided here per target. Resolution reuses
    this same function on later-captured evidence to recheck
    preexisting-event eligibility; ``observation_kind`` refuses a
    historical_reconstructed observation outright rather than letting it
    enter prospective resolution.
    """

    if observation_kind not in _OBSERVATION_KINDS:
        raise ContractValidationError("observation kind is invalid")
    if observation_kind == "historical_reconstructed":
        raise ContractValidationError(
            "historical_reconstructed observations cannot enter prospective resolution"
        )

    origin = instant(t0)
    seal = instant(seal_at)
    if seal < origin:
        raise ContractValidationError("seal cannot precede the target's origin")
    if seal_at > forecast_deadline(t0):
        return ProspectiveEligibility(status="missed_deadline", witness_hashes=())

    seal_offset = int((seal - origin).total_seconds())

    satisfied, hashes = _predicate_result(target, t0, seal_offset, families, _PRE)
    if satisfied:
        return ProspectiveEligibility(status="preexisting_event", witness_hashes=hashes)

    maybe_satisfied, maybe_hashes = _predicate_result(
        target, t0, seal_offset, families, _PRE_OR_AMBIGUOUS
    )
    if maybe_satisfied:
        return ProspectiveEligibility(
            status="timing_ambiguous", witness_hashes=maybe_hashes
        )

    return ProspectiveEligibility(status="eligible", witness_hashes=())
