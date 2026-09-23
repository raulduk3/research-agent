"""Fixed-task neighbor-retrieval qualification (SDD MD-12, TDD-4.1.68).

`reference_rank_evaluation` is a pure function over an already-assembled
corpus snapshot: original overview vectors, corpus arrival instants and
citation-graph references (MD-07, MD-08). It draws no forecast, resolves no
lineage and calls no storage; a caller supplies the fixed sample (the
profile's locked source-anchored papers) and the already-fetched corpus
rows it was drawn from. A sampled paper whose own arrival instant is
unknown, that has no reference, whose reference set cannot be confirmed to
have entirely arrived before it, or for which the corpus does not hold
enough earlier candidates left over for a matched random control group, is
left out and the omission is recorded rather than silently dropped or
padded. For every included paper, the exact reference and control ids are
recorded before any similarity is computed, so the draw cannot be read back
into itself; two independent metrics follow from that fixed set: whether
references win more reference/control pairs than chance, and relevance@5,
the share of actual references among the up to five candidates (from that
same reference-plus-control set) nearest the paper.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from research_agent.contracts.primitives import (
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)
from research_agent.measurement import MeasurementError

CONTROLS_PER_PAPER = 5
RELEVANCE_AT = 5
_EXCLUSION_REASONS: frozenset[str] = frozenset(
    {
        "unknown_arrival_day",
        "no_references",
        "reference_not_confirmed_earlier",
        "insufficient_earlier_candidates",
    }
)


@dataclass(frozen=True, slots=True)
class CorpusPaper:
    """One paper's snapshot-visible arrival instant, vector and references.

    ``reference_family_ids`` names the matched citation-graph references
    (MD-07, MD-08) already resolved for this paper; an unmatched or
    unparsed reference names no family here and cannot enter a comparison.
    """

    family_id: str
    corpus_arrival_at: str
    vector: tuple[float, ...]
    reference_family_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        validate_utc_instant(self.corpus_arrival_at)
        if not isinstance(self.vector, tuple) or not self.vector:
            raise MeasurementError("a corpus paper's vector must be a nonempty tuple")
        if any(isinstance(value, bool) for value in self.vector) or not all(
            math.isfinite(value) for value in self.vector
        ):
            raise MeasurementError("a corpus paper's vector must hold finite numbers")
        if not isinstance(self.reference_family_ids, tuple):
            raise MeasurementError("reference_family_ids must be an immutable tuple")
        if len(set(self.reference_family_ids)) != len(self.reference_family_ids):
            raise MeasurementError("reference_family_ids must not repeat a family")
        for reference in self.reference_family_ids:
            validate_uuid4(reference)


@dataclass(frozen=True, slots=True)
class PaperRankOutcome:
    """One sampled paper's recorded reference/control ids and their comparison.

    ``reference_family_ids`` and ``control_family_ids`` are the exact,
    already-fixed ids the ranking and relevance metrics below are computed
    from; an excluded outcome carries neither, since it is not a member of
    either metric's denominator.
    """

    family_id: str
    status: str
    reason: str | None
    reference_family_ids: tuple[str, ...]
    control_family_ids: tuple[str, ...]
    compared_pairs: int
    winning_pairs: int
    relevant_in_top: int
    relevance_at_five: float | None

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        if self.status not in {"included", "excluded"}:
            raise MeasurementError("paper rank outcome status is invalid")
        if self.status == "excluded":
            if self.reason not in _EXCLUSION_REASONS:
                raise MeasurementError(
                    "an excluded outcome requires a recognized reason"
                )
            if (
                self.reference_family_ids
                or self.control_family_ids
                or self.compared_pairs != 0
                or self.winning_pairs != 0
                or self.relevant_in_top != 0
                or self.relevance_at_five is not None
            ):
                raise MeasurementError(
                    "an excluded outcome carries no recorded ids or metrics"
                )
            return
        if self.reason is not None:
            raise MeasurementError("an included outcome carries no exclusion reason")
        reference_count = len(self.reference_family_ids)
        control_count = len(self.control_family_ids)
        if reference_count == 0 or control_count == 0:
            raise MeasurementError(
                "an included outcome requires at least one reference and control"
            )
        if len(set(self.reference_family_ids) & set(self.control_family_ids)) != 0:
            raise MeasurementError("a paper cannot be both a reference and a control")
        if self.compared_pairs != reference_count * control_count:
            raise MeasurementError(
                "compared pairs must cover every reference/control pair once"
            )
        if not 0 <= self.winning_pairs <= self.compared_pairs:
            raise MeasurementError("winning pairs must fall within the compared pairs")
        top_size = min(RELEVANCE_AT, reference_count + control_count)
        if not 0 <= self.relevant_in_top <= min(top_size, reference_count):
            raise MeasurementError("relevant_in_top must fall within the top slots")
        if self.relevance_at_five != self.relevant_in_top / top_size:
            raise MeasurementError(
                "relevance_at_five must equal relevant_in_top over the top size"
            )


@dataclass(frozen=True, slots=True)
class ReferenceRankReport:
    """MD-12's stored result: named representation, sample size and rank outcome."""

    representation_hash: str
    sample_size: int
    outcomes: tuple[PaperRankOutcome, ...]
    included_count: int
    compared_pairs: int
    winning_pairs: int
    win_rate: float | None
    mean_relevance_at_five: float | None

    def __post_init__(self) -> None:
        validate_sha256(self.representation_hash)
        validate_positive_int(self.sample_size)
        if len(self.outcomes) != self.sample_size:
            raise MeasurementError("report must cover every sampled paper exactly once")
        if len({outcome.family_id for outcome in self.outcomes}) != self.sample_size:
            raise MeasurementError("report must not repeat a sampled paper")
        included = tuple(
            outcome for outcome in self.outcomes if outcome.status == "included"
        )
        if len(included) != self.included_count:
            raise MeasurementError("included_count must match the included outcomes")
        if self.compared_pairs != sum(outcome.compared_pairs for outcome in included):
            raise MeasurementError("compared_pairs must sum the included outcomes")
        if self.winning_pairs != sum(outcome.winning_pairs for outcome in included):
            raise MeasurementError("winning_pairs must sum the included outcomes")
        if self.compared_pairs == 0:
            if self.win_rate is not None:
                raise MeasurementError("an empty comparison carries no win rate")
        elif self.win_rate != self.winning_pairs / self.compared_pairs:
            raise MeasurementError(
                "win_rate must equal winning pairs over compared pairs"
            )
        if not included:
            if self.mean_relevance_at_five is not None:
                raise MeasurementError("an empty comparison carries no mean relevance")
        else:
            expected = math.fsum(
                cast(float, outcome.relevance_at_five) for outcome in included
            ) / len(included)
            if self.mean_relevance_at_five != expected:
                raise MeasurementError(
                    "mean_relevance_at_five must average the included outcomes"
                )


def reference_rank_evaluation(
    corpus: Sequence[CorpusPaper],
    sample_family_ids: Sequence[str],
    *,
    representation_hash: str,
    controls_per_paper: int = CONTROLS_PER_PAPER,
    control_draw_seed: str = "md-12-neighbor-quality",
) -> ReferenceRankReport:
    """Check whether each sampled paper's references outrank random earlier papers.

    For each id in ``sample_family_ids``, in the given order: resolve the
    paper in ``corpus``; find every other corpus paper with a strictly
    earlier ``corpus_arrival_at`` ("earlier" per SDD Appendix A); confirm
    every one of its references is among those earlier papers; then draw
    ``controls_per_paper`` of the remaining earlier papers by a fixed hash
    rank of ``control_draw_seed``, the sampled paper's id and each
    candidate's id, so the same corpus and sample always draw the same
    controls regardless of ``corpus``' order -- this fixed reference/control
    set is recorded on the outcome before either metric below reads it.
    Every reference/control pair is compared by float64 cosine similarity to
    the sampled paper's own vector; a reference "wins" a pair when its
    similarity is strictly greater than the control's. Separately, the
    combined reference-plus-control set is ranked by that same similarity
    and relevance@5 is the share of references among the top five. A paper
    missing any of the preconditions above is excluded with a reason instead
    of silently narrowing its comparison.
    """

    validate_sha256(representation_hash)
    validate_positive_int(controls_per_paper)
    if not sample_family_ids:
        raise MeasurementError("sample_family_ids must be nonempty")
    if len(set(sample_family_ids)) != len(sample_family_ids):
        raise MeasurementError("sample_family_ids must not repeat a family")
    by_family: dict[str, CorpusPaper] = {}
    for paper in corpus:
        if paper.family_id in by_family:
            raise MeasurementError("corpus must not repeat a family id")
        by_family[paper.family_id] = paper

    outcomes = tuple(
        _evaluate_paper(
            family_id,
            by_family,
            controls_per_paper=controls_per_paper,
            control_draw_seed=control_draw_seed,
        )
        for family_id in sample_family_ids
    )

    included = tuple(outcome for outcome in outcomes if outcome.status == "included")
    compared_pairs = sum(outcome.compared_pairs for outcome in included)
    winning_pairs = sum(outcome.winning_pairs for outcome in included)
    win_rate = None if compared_pairs == 0 else winning_pairs / compared_pairs
    mean_relevance_at_five = (
        None
        if not included
        else math.fsum(cast(float, outcome.relevance_at_five) for outcome in included)
        / len(included)
    )
    return ReferenceRankReport(
        representation_hash=representation_hash,
        sample_size=len(sample_family_ids),
        outcomes=outcomes,
        included_count=len(included),
        compared_pairs=compared_pairs,
        winning_pairs=winning_pairs,
        win_rate=win_rate,
        mean_relevance_at_five=mean_relevance_at_five,
    )


def _evaluate_paper(
    family_id: str,
    by_family: dict[str, CorpusPaper],
    *,
    controls_per_paper: int,
    control_draw_seed: str,
) -> PaperRankOutcome:
    paper = by_family.get(family_id)
    if paper is None:
        return _excluded(family_id, "unknown_arrival_day")
    if not paper.reference_family_ids:
        return _excluded(family_id, "no_references")

    earlier = tuple(
        candidate
        for candidate in by_family.values()
        if candidate.family_id != family_id
        and candidate.corpus_arrival_at < paper.corpus_arrival_at
    )
    earlier_ids = {candidate.family_id for candidate in earlier}
    if not all(reference in earlier_ids for reference in paper.reference_family_ids):
        return _excluded(family_id, "reference_not_confirmed_earlier")

    reference_set = set(paper.reference_family_ids)
    control_pool = tuple(
        candidate for candidate in earlier if candidate.family_id not in reference_set
    )
    if len(control_pool) < controls_per_paper:
        return _excluded(family_id, "insufficient_earlier_candidates")

    controls = _draw_controls(
        control_pool, family_id, controls_per_paper, control_draw_seed
    )
    references = tuple(by_family[reference] for reference in paper.reference_family_ids)

    similarities: dict[str, float] = {}
    winning_pairs = 0
    compared_pairs = 0
    for reference in references:
        reference_similarity = _cosine(paper.vector, reference.vector)
        similarities[reference.family_id] = reference_similarity
        for control in controls:
            control_similarity = similarities.setdefault(
                control.family_id, _cosine(paper.vector, control.vector)
            )
            compared_pairs += 1
            if reference_similarity > control_similarity:
                winning_pairs += 1

    pool_ids = tuple(reference.family_id for reference in references) + tuple(
        control.family_id for control in controls
    )
    ranked = sorted(
        pool_ids,
        key=lambda candidate_id: (-similarities[candidate_id], candidate_id),
    )
    top_size = min(RELEVANCE_AT, len(ranked))
    relevant_in_top = sum(
        1 for candidate_id in ranked[:top_size] if candidate_id in reference_set
    )

    return PaperRankOutcome(
        family_id=family_id,
        status="included",
        reason=None,
        reference_family_ids=tuple(reference.family_id for reference in references),
        control_family_ids=tuple(control.family_id for control in controls),
        compared_pairs=compared_pairs,
        winning_pairs=winning_pairs,
        relevant_in_top=relevant_in_top,
        relevance_at_five=relevant_in_top / top_size,
    )


def _excluded(family_id: str, reason: str) -> PaperRankOutcome:
    return PaperRankOutcome(
        family_id=family_id,
        status="excluded",
        reason=reason,
        reference_family_ids=(),
        control_family_ids=(),
        compared_pairs=0,
        winning_pairs=0,
        relevant_in_top=0,
        relevance_at_five=None,
    )


def _draw_controls(
    pool: Sequence[CorpusPaper], family_id: str, count: int, seed: str
) -> tuple[CorpusPaper, ...]:
    ranked = sorted(
        pool,
        key=lambda candidate: (
            _draw_rank_key(seed, family_id, candidate.family_id),
            candidate.family_id,
        ),
    )
    return tuple(ranked[:count])


def _draw_rank_key(seed: str, family_id: str, candidate_id: str) -> str:
    return sha256(f"{seed}:{family_id}:{candidate_id}".encode()).hexdigest()


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise MeasurementError("compared vectors must share one dimension")
    dot = math.fsum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(math.fsum(float(b) * float(b) for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise MeasurementError("compared vectors must be nonzero")
    return dot / (left_norm * right_norm)
