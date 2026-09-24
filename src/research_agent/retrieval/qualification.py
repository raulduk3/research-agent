"""The shared retrieval qualification, drawn and scored against a published index.

Appendix A's "Shared retrieval qualification" (RD-28, Appendix C:
Qualification): 100 original papers, five per week from the latest 20
complete publication weeks, allocated across the primary categories in
proportion to their family counts in those weeks with at least one each;
five source-anchored questions per paper; 20 papers for development and 80
locked for evaluation. The locked evaluation passes only with

- top-five family recall of at least 0.80 in overview mode;
- supported-passage recall of at least 0.60: passage mode returns a span of
  the cited paper that contains a verified supporting span;
- exact span reconstruction of every indexed passage: the span re-chunked
  from the stored text hashes to the index's text hash;
- a supported-evidence gain of at least 0.05 over overview-only under an
  equal reading budget, with the paired 95% lower bound above zero.

`select_qualification_sample` draws the sample from a corpus release before
any question exists, so authors see only the papers. `score_qualification`
is pure: it folds each question's recorded outcome into the report and its
verdict. `run_retrieval` is the one step that touches the index: it ranks
every question in both modes through `search_passages`, the same ranking
the tool serves. Embedding the questions is the caller's; no paid call is
made anywhere.

The reading budget is counted in characters. The overview arm reads its
returned overviews (title and abstract); the passage arm reads its returned
passages in rank order while their running total stays within that same
count. A question's evidence is supported in the overview arm when the cited
paper is among the overviews and its overview is judged to support the
question, and in the passage arm when a passage it read contains a verified
supporting span.

An evidence judgment is verified when two different judges agree, or when
they disagree and a third judge adjudicates. An unresolved span is not
support; an unresolved overview counts as support, so a dispute can only
lower the measured gain.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..contracts.canonical import canonical_json, sha256_hex
from ..contracts.corpus import CorpusRelease
from ..contracts.learning import PRIMARY_CATEGORY_IDS
from ..contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_uuid4,
)
from ..learning.corpus import SELECTION_SEED, selection_hash
from ..measurement.bootstrap import BootstrapInterval, bootstrap_difference
from ..measurement.jev import _quotas
from ..models.batch import PaperText, paper_text_path
from ..models.embedding import overview_text
from ..outcomes.windows import instant
from ..reader.chunk import SectionTokenizer
from .passages import (
    PER_FAMILY_RESULT_LIMIT,
    SearchCandidate,
    SearchResult,
    build_passages,
    search_passages,
)

__all__ = [
    "SAMPLE_WEEKS",
    "PAPERS_PER_WEEK",
    "QUESTIONS_PER_PAPER",
    "SampledPaper",
    "QualificationSample",
    "qualification_weeks",
    "select_qualification_sample",
    "sample_from_release",
    "Judgment",
    "Evidence",
    "EvidenceSpan",
    "Question",
    "parse_questions",
    "QuestionOutcome",
    "score_question",
    "QualificationReport",
    "score_qualification",
    "IndexPool",
    "load_pool",
    "run_retrieval",
]

SAMPLE_WEEKS = 20
PAPERS_PER_WEEK = 5
QUESTIONS_PER_PAPER = 5
RESULT_LIMIT = 5
MIN_FAMILY_RECALL = 0.80
MIN_SUPPORTED_PASSAGE_RECALL = 0.60
MIN_EVIDENCE_GAIN = 0.05
_OVERVIEW_PATH = ("overview",)
# Prefix candidates are chosen by a float64 matrix product and then ranked
# by search_passages' exact cosine; this margin is far above the gap
# between the two for unit-scale vectors.
_PREFIX_MARGIN = 1e-6


class QualificationError(ValueError):
    """The release, questions or index cannot enter the qualification."""


@dataclass(frozen=True, slots=True)
class SampledPaper:
    """One original paper in the draw, with its fixed development or evaluation role."""

    family_id: str
    version_id: str
    primary_category: str
    publication_week: str
    split: str

    def __post_init__(self) -> None:
        validate_uuid4(self.family_id)
        validate_uuid4(self.version_id)
        validate_non_empty_string(self.primary_category)
        validate_non_empty_string(self.publication_week)
        if self.split not in {"development", "evaluation"}:
            raise QualificationError("split must be development or evaluation")

    def to_dict(self) -> dict[str, str]:
        return {
            "family_id": self.family_id,
            "version_id": self.version_id,
            "primary_category": self.primary_category,
            "publication_week": self.publication_week,
            "split": self.split,
        }


@dataclass(frozen=True, slots=True)
class QualificationSample:
    """The frozen draw. ``shortfall`` names each week's missing paper count."""

    weeks: tuple[str, ...]
    quotas: tuple[tuple[str, int], ...]
    papers: tuple[SampledPaper, ...]
    shortfall: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "weeks": list(self.weeks),
            "quotas": [list(item) for item in self.quotas],
            "papers": [paper.to_dict() for paper in self.papers],
            "shortfall": [list(item) for item in self.shortfall],
        }

    def sample_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


def _week_monday(week: str) -> datetime:
    return datetime.strptime(f"{week}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)


def _iso_week(value: datetime) -> str:
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def qualification_weeks(
    row_weeks: Sequence[str], frozen_at: str, count: int = SAMPLE_WEEKS
) -> tuple[str, ...]:
    """The latest ``count`` consecutive weeks, latest first, ending at the corpus's
    latest complete week.

    A week is complete once it ended at or before ``frozen_at``. The window
    is consecutive calendar weeks, so a week with no paper stays in it as a
    shortfall instead of being skipped.
    """

    freeze = instant(frozen_at)
    complete = [
        week
        for week in set(row_weeks)
        if _week_monday(week) + timedelta(days=7) <= freeze
    ]
    if not complete:
        raise QualificationError("the release has no paper in a complete week")
    anchor = max(complete, key=_week_monday)
    monday = _week_monday(anchor)
    return tuple(_iso_week(monday - timedelta(days=7 * n)) for n in range(count))


def _allocate(
    supply: Mapping[tuple[str, str], int],
    weeks: Sequence[str],
    categories: Sequence[str],
    per_week: int,
    quotas: Mapping[str, int],
) -> dict[tuple[str, str], int]:
    """How many papers each (week, category) cell gives, drawing as many as exist.

    A maximum flow from weeks (``per_week`` each) through the cells (their
    paper counts) to categories (their quotas), found by shortest augmenting
    paths searched in week and category order, so the same inputs always
    give the same allocation. A greedy week-by-week pick can spend a
    scarce category's week early and strand its quota; a maximum flow
    cannot.
    """

    source, sink = ("source", ""), ("sink", "")
    week_nodes = [("week", week) for week in weeks]
    category_nodes = [("category", category) for category in categories]
    capacity: dict[tuple[str, str], dict[tuple[str, str], int]] = {
        node: {} for node in [source, *week_nodes, *category_nodes, sink]
    }

    def edge(a: tuple[str, str], b: tuple[str, str], amount: int) -> None:
        capacity[a][b] = amount
        capacity[b].setdefault(a, 0)

    for node in week_nodes:
        edge(source, node, per_week)
    for week_node in week_nodes:
        for category_node in category_nodes:
            edge(
                week_node,
                category_node,
                supply.get((week_node[1], category_node[1]), 0),
            )
    for node in category_nodes:
        edge(node, sink, quotas[node[1]])
    residual = {a: dict(b) for a, b in capacity.items()}
    while True:
        parent: dict[tuple[str, str], tuple[str, str]] = {}
        frontier = [source]
        while frontier and sink not in parent:
            following: list[tuple[str, str]] = []
            for node in frontier:
                for neighbour, amount in residual[node].items():
                    if amount > 0 and neighbour not in parent and neighbour != source:
                        parent[neighbour] = node
                        following.append(neighbour)
            frontier = following
        if sink not in parent:
            break
        path = [sink]
        while path[-1] != source:
            path.append(parent[path[-1]])
        path.reverse()
        amount = min(residual[a][b] for a, b in zip(path, path[1:]))
        for a, b in zip(path, path[1:]):
            residual[a][b] -= amount
            residual[b][a] += amount
    return {
        (week_node[1], category_node[1]): capacity[week_node][category_node]
        - residual[week_node][category_node]
        for week_node in week_nodes
        for category_node in category_nodes
    }


def select_qualification_sample(
    candidates: Sequence[SampledPaper],
    weeks: Sequence[str],
    *,
    per_week: int = PAPERS_PER_WEEK,
    categories: Sequence[str] = PRIMARY_CATEGORY_IDS,
    seed: int = SELECTION_SEED,
) -> QualificationSample:
    """Draw ``per_week`` papers from each of ``weeks`` (latest first).

    Category quotas are proportional to the weeks' family counts, at least
    one each. The allocation draws as many papers as the weeks and quotas
    allow; each (week, category) cell then takes its first hash-ranked
    papers. A week that cannot give ``per_week`` records its missing count
    and is never refilled from another. Each week's first paper in hash
    order is a development paper and the rest are evaluation papers, so
    both sets span every week. The ``split`` of the candidates passed in is
    ignored, and so is their order.
    """

    weeks = tuple(weeks)
    if not weeks or len(set(weeks)) != len(weeks):
        raise QualificationError("sample weeks must be a nonempty list without repeats")
    categories = tuple(categories)
    ids = [candidate.family_id for candidate in candidates]
    if len(set(ids)) != len(ids):
        raise QualificationError("sample candidates must not repeat a family")
    pool = [
        candidate
        for candidate in candidates
        if candidate.publication_week in weeks
        and candidate.primary_category in categories
    ]
    counts = Counter(candidate.primary_category for candidate in pool)
    quotas = dict(_quotas(counts, categories, per_week * len(weeks)))
    cells = Counter((item.publication_week, item.primary_category) for item in pool)
    allocation = _allocate(cells, weeks, categories, per_week, quotas)

    def rank(item: SampledPaper) -> tuple[str, str]:
        return selection_hash(item.family_id, seed), item.family_id

    papers: list[SampledPaper] = []
    shortfall: list[tuple[str, int]] = []
    for week in weeks:
        chosen: list[SampledPaper] = []
        for category in categories:
            cell = sorted(
                (
                    item
                    for item in pool
                    if item.publication_week == week
                    and item.primary_category == category
                ),
                key=rank,
            )
            chosen.extend(cell[: allocation[(week, category)]])
        for position, item in enumerate(sorted(chosen, key=rank)):
            papers.append(
                SampledPaper(
                    item.family_id,
                    item.version_id,
                    item.primary_category,
                    week,
                    "development" if position == 0 else "evaluation",
                )
            )
        if len(chosen) < per_week:
            shortfall.append((week, per_week - len(chosen)))
    return QualificationSample(
        weeks=weeks,
        quotas=tuple(quotas.items()),
        papers=tuple(papers),
        shortfall=tuple(shortfall),
    )


def sample_from_release(release: CorpusRelease) -> QualificationSample:
    """Draw the sample over a release's original papers with a week and category."""

    candidates = [
        SampledPaper(
            row.paper_family_id,
            row.original_version_id,
            row.categories[0],
            row.publication_week,
            "evaluation",
        )
        for row in release.rows
        if row.publication_week is not None and row.categories
    ]
    weeks = qualification_weeks(
        [candidate.publication_week for candidate in candidates],
        release.selection_frozen_at,
    )
    return select_qualification_sample(candidates, weeks, seed=release.selection_seed)


@dataclass(frozen=True, slots=True)
class Judgment:
    """One judge's reading of whether a source supports a question."""

    judge: str
    supports: bool

    def __post_init__(self) -> None:
        validate_non_empty_string(self.judge)
        if not isinstance(self.supports, bool):
            raise QualificationError("a judgment's supports must be a boolean")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Two independent judgments and an optional third, adjudicating one."""

    judgments: tuple[Judgment, Judgment]
    adjudication: Judgment | None = None

    def __post_init__(self) -> None:
        if len(self.judgments) != 2:
            raise QualificationError("evidence carries exactly two judgments")
        judges = {judgment.judge for judgment in self.judgments}
        if len(judges) != 2:
            raise QualificationError("the two judgments come from different judges")
        if self.adjudication is not None and self.adjudication.judge in judges:
            raise QualificationError("an adjudicator did not judge the same evidence")

    @property
    def verdict(self) -> bool | None:
        """True or False once verified; None while a dispute is unresolved."""

        first, second = self.judgments
        if first.supports == second.supports:
            return first.supports
        if self.adjudication is not None:
            return self.adjudication.supports
        return None


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    """A licensed source span of the cited paper's extracted text, and its evidence."""

    char_start: int
    char_end_exclusive: int
    evidence: Evidence

    def __post_init__(self) -> None:
        validate_non_negative_int(self.char_start)
        if self.char_end_exclusive <= self.char_start:
            raise QualificationError("an evidence span must be nonempty")


@dataclass(frozen=True, slots=True)
class Question:
    """One source-anchored question about one sampled paper."""

    question_id: str
    paper_family_id: str
    text: str
    overview_evidence: Evidence
    spans: tuple[EvidenceSpan, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.question_id)
        validate_uuid4(self.paper_family_id)
        validate_non_empty_string(self.text)
        if not self.spans:
            raise QualificationError("a source-anchored question cites a span")

    @property
    def supporting_spans(self) -> tuple[EvidenceSpan, ...]:
        return tuple(span for span in self.spans if span.evidence.verdict is True)


def _judgment(value: object) -> Judgment:
    if not isinstance(value, dict) or set(value) != {"judge", "supports"}:
        raise QualificationError("a judgment has exactly judge and supports")
    return Judgment(value["judge"], value["supports"])


def _evidence(value: object) -> Evidence:
    if not isinstance(value, dict) or not set(value) <= {"judgments", "adjudication"}:
        raise QualificationError("evidence has judgments and an optional adjudication")
    judgments = value.get("judgments")
    if not isinstance(judgments, list) or len(judgments) != 2:
        raise QualificationError("evidence carries exactly two judgments")
    adjudication = value.get("adjudication")
    return Evidence(
        (_judgment(judgments[0]), _judgment(judgments[1])),
        None if adjudication is None else _judgment(adjudication),
    )


def parse_questions(raw: bytes) -> tuple[Question, ...]:
    """Read the authored question file; unknown fields and repeated ids are refused."""

    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"questions"}:
        raise QualificationError("the question file holds exactly a questions list")
    questions: list[Question] = []
    for item in value["questions"]:
        keys = {"question_id", "paper_family_id", "text", "overview_evidence", "spans"}
        if not isinstance(item, dict) or set(item) != keys:
            raise QualificationError(f"a question has exactly {sorted(keys)}")
        spans: list[EvidenceSpan] = []
        for span in item["spans"]:
            span_keys = {"char_start", "char_end_exclusive", "evidence"}
            if not isinstance(span, dict) or set(span) != span_keys:
                raise QualificationError(f"a span has exactly {sorted(span_keys)}")
            spans.append(
                EvidenceSpan(
                    span["char_start"],
                    span["char_end_exclusive"],
                    _evidence(span["evidence"]),
                )
            )
        questions.append(
            Question(
                item["question_id"],
                item["paper_family_id"],
                item["text"],
                _evidence(item["overview_evidence"]),
                tuple(spans),
            )
        )
    ids = [question.question_id for question in questions]
    if len(set(ids)) != len(ids):
        raise QualificationError("question ids must not repeat")
    return tuple(questions)


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    """What one question's two retrieval runs found, as the verdict reads it."""

    question_id: str
    family_hit: bool
    passage_family_hit: bool
    supported_passage: bool
    overview_supported: bool
    budget_supported: bool
    reading_budget: int
    verified_spans: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "family_hit": self.family_hit,
            "passage_family_hit": self.passage_family_hit,
            "supported_passage": self.supported_passage,
            "overview_supported": self.overview_supported,
            "budget_supported": self.budget_supported,
            "reading_budget": self.reading_budget,
            "verified_spans": self.verified_spans,
        }


def _supports(result: SearchResult, question: Question) -> bool:
    candidate = result.candidate
    return candidate.paper_family_id == question.paper_family_id and any(
        candidate.char_start <= span.char_start
        and span.char_end_exclusive <= candidate.char_end_exclusive
        for span in question.supporting_spans
    )


def score_question(
    question: Question,
    overview: Sequence[SearchResult],
    passages: Sequence[SearchResult],
) -> QuestionOutcome:
    """Score one question from its overview-mode and passage-mode results."""

    family_hit = any(
        result.candidate.paper_family_id == question.paper_family_id
        for result in overview
    )
    budget = sum(len(result.candidate.text) for result in overview)
    read: list[SearchResult] = []
    spent = 0
    for result in passages:
        if spent + len(result.candidate.text) > budget:
            break
        read.append(result)
        spent += len(result.candidate.text)
    # An unresolved overview judgment counts as support: it can only lower the gain.
    overview_supported = family_hit and question.overview_evidence.verdict is not False
    return QuestionOutcome(
        question_id=question.question_id,
        family_hit=family_hit,
        passage_family_hit=any(
            result.candidate.paper_family_id == question.paper_family_id
            for result in passages
        ),
        supported_passage=any(_supports(result, question) for result in passages),
        overview_supported=overview_supported,
        budget_supported=any(_supports(result, question) for result in read),
        reading_budget=budget,
        verified_spans=len(question.supporting_spans),
    )


@dataclass(slots=True)
class _Paired:
    """One question's passage-minus-overview supported evidence.

    Not frozen: `bootstrap.ClusteredDifference` declares its fields settable.
    """

    publication_week: str
    family_id: str
    difference: float


def _interval_dict(interval: BootstrapInterval) -> dict[str, Any]:
    return {
        "method": interval.method,
        "resamples": interval.resamples,
        "seed": interval.seed,
        "lower_tail": interval.lower_tail,
        "upper_tail": interval.upper_tail,
        "support_count": interval.support_count,
        "estimate": interval.estimate,
        "low": interval.low,
        "high": interval.high,
        "disposition": interval.disposition,
    }


def _measures(
    papers: Sequence[SampledPaper],
    questions: Sequence[Question],
    outcomes: Mapping[str, QuestionOutcome],
) -> tuple[dict[str, Any], BootstrapInterval]:
    count = len(questions)
    by_family = {paper.family_id: paper for paper in papers}

    def rate(field: str) -> float | None:
        if not count:
            return None
        hits = sum(bool(getattr(outcomes[q.question_id], field)) for q in questions)
        return hits / count

    rows = [
        _Paired(
            by_family[q.paper_family_id].publication_week,
            q.paper_family_id,
            float(outcomes[q.question_id].budget_supported)
            - float(outcomes[q.question_id].overview_supported),
        )
        for q in questions
    ]
    clusters: dict[str, set[str]] = {}
    for paper in papers:
        clusters.setdefault(paper.publication_week, set()).add(paper.family_id)
    interval = bootstrap_difference(
        rows,
        {week: frozenset(ids) for week, ids in clusters.items()},
        lower_tail=2.5,
        upper_tail=97.5,
    )
    return (
        {
            "papers": len(papers),
            "questions": count,
            "questions_without_verified_span": sum(
                1 for q in questions if not outcomes[q.question_id].verified_spans
            ),
            "family_recall": rate("family_hit"),
            "passage_family_recall": rate("passage_family_hit"),
            "supported_passage_recall": rate("supported_passage"),
            "overview_supported_rate": rate("overview_supported"),
            "passage_supported_rate": rate("budget_supported"),
            "evidence_gain": _interval_dict(interval),
        },
        interval,
    )


@dataclass(frozen=True, slots=True)
class QualificationReport:
    """The scored qualification. Only the locked evaluation set carries the verdict."""

    verdict: str
    reasons: tuple[str, ...]
    body: Mapping[str, Any]

    def to_canonical_json(self) -> bytes:
        return canonical_json(
            {"verdict": self.verdict, "reasons": list(self.reasons), **self.body}
        )


def score_qualification(
    sample: QualificationSample,
    questions: Sequence[Question],
    outcomes: Mapping[str, QuestionOutcome],
    *,
    reconstructed_passages: int,
    indexed_passages: int,
    identity: Mapping[str, Any],
) -> QualificationReport:
    """Fold every question's outcome into the report and its pass or fail.

    The verdict is ``incomplete`` while any sampled paper lacks its five
    questions: a missing question is unauthored work, never a zero. A
    question for a paper outside the sample is refused.
    """

    papers = {paper.family_id: paper for paper in sample.papers}
    for question in questions:
        if question.paper_family_id not in papers:
            raise QualificationError(
                f"question {question.question_id} names a paper outside the sample"
            )
        if question.question_id not in outcomes:
            raise QualificationError(f"question {question.question_id} has no outcome")
    per_paper = Counter(question.paper_family_id for question in questions)
    over = sorted(family for family, n in per_paper.items() if n > QUESTIONS_PER_PAPER)
    if over:
        raise QualificationError(f"papers with more than five questions: {over}")
    missing = sum(
        QUESTIONS_PER_PAPER - per_paper[paper.family_id] for paper in sample.papers
    )

    split_measures: dict[str, dict[str, Any]] = {}
    evaluation_interval: BootstrapInterval | None = None
    for split in ("development", "evaluation"):
        split_papers = [paper for paper in sample.papers if paper.split == split]
        split_questions = [
            q for q in questions if papers[q.paper_family_id].split == split
        ]
        measures, interval = _measures(split_papers, split_questions, outcomes)
        split_measures[split] = measures
        if split == "evaluation":
            evaluation_interval = interval
    assert evaluation_interval is not None

    reconstruction = (
        reconstructed_passages / indexed_passages if indexed_passages else None
    )
    evaluation = split_measures["evaluation"]
    reasons: list[str] = []
    if missing:
        reasons.append(f"{missing} sampled questions are not authored")
    if not evaluation["questions"]:
        reasons.append("no evaluation question exists")
    else:
        if evaluation["family_recall"] < MIN_FAMILY_RECALL:
            reasons.append("top-five family recall is below 0.80")
        if evaluation["supported_passage_recall"] < MIN_SUPPORTED_PASSAGE_RECALL:
            reasons.append("supported-passage recall is below 0.60")
        if (
            evaluation_interval.estimate is None
            or evaluation_interval.low is None
            or evaluation_interval.estimate < MIN_EVIDENCE_GAIN
            or evaluation_interval.low <= 0
        ):
            reasons.append(
                "supported-evidence gain is below 0.05 or its 95% lower bound "
                "is not above zero"
            )
    if reconstruction != 1.0:
        reasons.append("not every indexed passage reconstructs its exact span")
    verdict = "incomplete" if missing else ("fail" if reasons else "pass")
    body = {
        "identity": dict(identity),
        "thresholds": {
            "family_recall": MIN_FAMILY_RECALL,
            "supported_passage_recall": MIN_SUPPORTED_PASSAGE_RECALL,
            "span_reconstruction": 1.0,
            "evidence_gain": MIN_EVIDENCE_GAIN,
            "evidence_gain_lower_bound_above": 0.0,
            "reading_budget_unit": "characters",
        },
        "sample": sample.to_dict(),
        "sample_hash": sample.sample_hash(),
        "questions_missing": missing,
        "span_reconstruction": {
            "reconstructed": reconstructed_passages,
            "indexed": indexed_passages,
            "rate": reconstruction,
        },
        "development": split_measures["development"],
        "evaluation": evaluation,
        "outcomes": [
            outcomes[q.question_id].to_dict()
            for q in sorted(questions, key=lambda q: q.question_id)
        ],
    }
    return QualificationReport(verdict, tuple(reasons), body)


@dataclass(frozen=True, slots=True)
class _Locator:
    """Where a pooled vector's text lives: its version and span, never the text."""

    family_id: str
    version_id: str
    section_order: int
    section_path: tuple[str, ...]
    char_start: int
    char_end_exclusive: int
    text_hash: str
    source_locators: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class _Mode:
    """One retrieval mode's vectors, their unit rows and where each one's text is."""

    matrix: np.ndarray
    units: np.ndarray
    families: np.ndarray
    locators: tuple[_Locator, ...]


def _mode(rows: list[list[float]], locators: list[_Locator]) -> _Mode:
    matrix = np.asarray(rows, dtype=np.float64)
    if not rows:
        return _Mode(matrix, matrix, np.zeros(0, dtype=np.int64), ())
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    families = sorted({locator.family_id for locator in locators})
    codes = {family: code for code, family in enumerate(families)}
    return _Mode(
        matrix,
        matrix / np.where(norms == 0.0, 1.0, norms),
        np.asarray([codes[item.family_id] for item in locators], dtype=np.int64),
        tuple(locators),
    )


@dataclass(frozen=True, slots=True)
class IndexPool:
    """The searchable original versions of a namespace, one matrix per mode."""

    overview: _Mode
    passages: _Mode
    reconstructed_passages: int
    indexed_passages: int
    coverage: Mapping[str, str]
    namespace_hash: str
    unsearchable: Mapping[str, str]


def load_pool(
    namespace_dir: Path,
    text_dir: Path,
    families: Mapping[str, str],
    tokenizer: SectionTokenizer,
) -> IndexPool:
    """Read every published entry for an original version in ``families``.

    ``families`` maps original version id to family id. Each entry's passages
    are re-chunked from the stored text and matched by order; a passage
    whose span does not hash to the index's text hash is counted as not
    reconstructed and left out of search, never served with guessed text.
    A version without its text is unsearchable and every passage it indexed
    counts as not reconstructed.
    """

    overview_rows: list[list[float]] = []
    overview_locators: list[_Locator] = []
    passage_rows: list[list[float]] = []
    passage_locators: list[_Locator] = []
    reconstructed = indexed = 0
    coverage: dict[str, str] = {}
    unsearchable: dict[str, str] = {}
    entry_hashes: list[list[str]] = []
    for path in sorted(namespace_dir.glob("*.json")):
        version_id = path.stem
        family_id = families.get(version_id)
        if family_id is None:
            continue
        raw = path.read_bytes()
        entry_hashes.append([version_id, sha256_hex(raw)])
        entry = json.loads(raw)
        indexed += len(entry["passages"])
        if not paper_text_path(text_dir, version_id).exists():
            unsearchable[version_id] = "no extracted text"
            continue
        text = PaperText.from_json(paper_text_path(text_dir, version_id).read_bytes())
        if text.extraction_hash != entry["extraction_hash"]:
            unsearchable[version_id] = "index entry is another extraction's"
            continue
        coverage[version_id] = entry["coverage"]
        overview = overview_text(text.title, text.abstract)
        overview_rows.append([float(v) for v in entry["overview_vector"]])
        overview_locators.append(
            _Locator(
                family_id,
                version_id,
                0,
                _OVERVIEW_PATH,
                0,
                len(overview),
                sha256_hex(overview.encode("utf-8")),
                (),
            )
        )
        records = build_passages(
            text.extraction, text.canonical_text, text.extraction_hash, tokenizer
        )
        for passage in entry["passages"]:
            order = passage["passage_order"]
            record = records[order] if 0 <= order < len(records) else None
            if record is None:
                continue
            span = text.canonical_text[record.char_start : record.char_end_exclusive]
            if sha256_hex(span.encode("utf-8")) != passage["text_hash"]:
                continue
            reconstructed += 1
            passage_rows.append([float(v) for v in passage["vector"]])
            passage_locators.append(
                _Locator(
                    family_id,
                    version_id,
                    record.section_order,
                    record.section_path,
                    record.char_start,
                    record.char_end_exclusive,
                    passage["text_hash"],
                    record.source_locators,
                )
            )
    return IndexPool(
        overview=_mode(overview_rows, overview_locators),
        passages=_mode(passage_rows, passage_locators),
        reconstructed_passages=reconstructed,
        indexed_passages=indexed,
        coverage=coverage,
        namespace_hash=sha256_hex(canonical_json(entry_hashes)),
        unsearchable=unsearchable,
    )


def _search(
    mode: _Mode,
    query: tuple[float, ...],
    text_of: Callable[[_Locator], str],
) -> tuple[SearchResult, ...]:
    """``search_passages`` over the smallest ranked prefix that decides its answer.

    A float64 product orders the pool; ``search_passages`` then ranks a
    prefix by exact cosine. Its answer equals the whole pool's once it names
    five families, each holding its full share or with no vector left
    outside the prefix, and every result lies above the prefix's margin:
    nothing later can join. Otherwise the prefix doubles.
    """

    if not mode.locators:
        return ()
    q = np.asarray(query, dtype=np.float64)
    scores = mode.units @ (q / np.linalg.norm(q))
    order = np.argsort(-scores, kind="stable")
    size = RESULT_LIMIT * PER_FAMILY_RESULT_LIMIT
    while True:
        size = min(size, len(order))
        floor = scores[order[size - 1]]
        prefix = order[scores[order] >= floor - _PREFIX_MARGIN]
        results = search_passages(
            candidates=[
                _candidate(mode.locators[i], mode.matrix[i], text_of) for i in prefix
            ],
            query_vector=query,
            paper_filter=None,
            limit=RESULT_LIMIT,
        )
        if len(prefix) == len(order):
            return results
        per_family = Counter(result.candidate.paper_family_id for result in results)
        short = [
            index
            for index in prefix
            if per_family.get(mode.locators[index].family_id, PER_FAMILY_RESULT_LIMIT)
            < PER_FAMILY_RESULT_LIMIT
        ]
        open_families = np.isin(
            mode.families[order[len(prefix) :]], mode.families[short]
        ).any()
        if (
            len(per_family) == RESULT_LIMIT
            and not open_families
            and min(result.similarity for result in results) >= floor
        ):
            return results
        size = 2 * len(prefix)


def _candidate(
    locator: _Locator, vector: np.ndarray, text_of: Callable[[_Locator], str]
) -> SearchCandidate:
    return SearchCandidate(
        paper_family_id=locator.family_id,
        paper_version_id=locator.version_id,
        section_order=locator.section_order,
        section_path=locator.section_path,
        char_start=locator.char_start,
        char_end_exclusive=locator.char_end_exclusive,
        text=text_of(locator),
        text_hash=locator.text_hash,
        source_locators=locator.source_locators,
        vector=tuple(float(v) for v in vector),
    )


def run_retrieval(
    pool: IndexPool,
    text_dir: Path,
    questions: Sequence[Question],
    query_vectors: Sequence[tuple[float, ...]],
) -> dict[str, QuestionOutcome]:
    """Rank every question in overview and passage mode and score it.

    Each supporting span must lie inside the cited paper's stored text; a
    span past its end was authored against another text and is refused.
    """

    texts: dict[str, PaperText] = {}

    def paper(version_id: str) -> PaperText:
        if version_id not in texts:
            texts[version_id] = PaperText.from_json(
                paper_text_path(text_dir, version_id).read_bytes()
            )
        return texts[version_id]

    def overview_of(locator: _Locator) -> str:
        source = paper(locator.version_id)
        return overview_text(source.title, source.abstract)

    def passage_of(locator: _Locator) -> str:
        source = paper(locator.version_id)
        return source.canonical_text[locator.char_start : locator.char_end_exclusive]

    versions = {
        locator.family_id: locator.version_id for locator in pool.overview.locators
    }
    outcomes: dict[str, QuestionOutcome] = {}
    for question, vector in zip(questions, query_vectors, strict=True):
        version_id = versions.get(question.paper_family_id)
        if version_id is not None:
            length = len(paper(version_id).canonical_text)
            if any(span.char_end_exclusive > length for span in question.spans):
                raise QualificationError(
                    f"question {question.question_id} cites a span past its text"
                )
        overview = _search(pool.overview, vector, overview_of)
        passages = _search(pool.passages, vector, passage_of)
        outcomes[question.question_id] = score_question(question, overview, passages)
    return outcomes


def _read_release(state: Path, release_hash: str) -> CorpusRelease:
    from ..artifacts.store import ArtifactStore

    validate_sha256(release_hash)
    with ArtifactStore(state / "artifacts").open_verified(release_hash) as handle:
        return CorpusRelease.from_json(handle.read())


def _store(state: Path, body: bytes) -> str:
    from ..artifacts.store import ArtifactStore

    artifact_hash = sha256_hex(body)
    ArtifactStore(state / "artifacts").commit(
        [body],
        expected_hash=artifact_hash,
        expected_length=len(body),
        maximum_length=len(body),
    )
    return artifact_hash


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qualify-retrieval",
        description="Draw and score the shared retrieval qualification (Appendix A).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    sample_parser = commands.add_parser("sample", help="draw and store the sample")
    score_parser = commands.add_parser("score", help="score the questions")
    for sub in (sample_parser, score_parser):
        sub.add_argument("--state", type=Path, required=True)
        sub.add_argument("--release", required=True, help="CorpusRelease content hash")
    score_parser.add_argument("--namespace", type=Path, required=True)
    score_parser.add_argument("--text", type=Path, required=True)
    score_parser.add_argument("--questions", type=Path, required=True)
    score_parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        release = _read_release(args.state, args.release)
        sample = sample_from_release(release)
    except (QualificationError, ContractValidationError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    if args.command == "sample":
        body = canonical_json(sample.to_dict())
        stored = _store(args.state, body)
        short = sum(n for _, n in sample.shortfall)
        print(f"sample {stored}: {len(sample.papers)} papers, {short} short")
        for item in sample.papers:
            print(
                f"{item.split}\t{item.publication_week}\t"
                f"{item.primary_category}\t{item.family_id}"
            )
        return 0

    # Imported here: drawing the sample needs no model.
    from ..models.backend import load_frozen_embedder_and_backend
    from ..models.batch import OffsetTokenizer

    raw_questions = args.questions.read_bytes()
    try:
        questions = parse_questions(raw_questions)
        embedder, backend = load_frozen_embedder_and_backend(args.cache_dir)
        families = {
            row.original_version_id: row.paper_family_id for row in release.rows
        }
        pool = load_pool(
            args.namespace, args.text, families, OffsetTokenizer(backend.tokenizer)
        )
        vectors = embedder.embed_queries([question.text for question in questions])
        outcomes = run_retrieval(pool, args.text, questions, vectors)
        sampled_versions = [paper.version_id for paper in sample.papers]
        report = score_qualification(
            sample,
            questions,
            outcomes,
            reconstructed_passages=pool.reconstructed_passages,
            indexed_passages=pool.indexed_passages,
            identity={
                "release_hash": args.release,
                "namespace_hash": pool.namespace_hash,
                "representation_hash": embedder.manifest.representation_hash,
                "questions_hash": sha256_hex(raw_questions),
                "searched_versions": len(pool.overview.locators),
                "unsearchable_versions": dict(sorted(pool.unsearchable.items())),
                "sampled_coverage": dict(
                    sorted(
                        Counter(
                            pool.coverage.get(version, "unavailable")
                            for version in sampled_versions
                        ).items()
                    )
                ),
            },
        )
    except (QualificationError, ContractValidationError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    stored = _store(args.state, report.to_canonical_json())
    evaluation = report.body["evaluation"]
    gain = evaluation["evidence_gain"]
    print(f"{report.verdict} (report {stored})")
    print(
        f"evaluation: {evaluation['questions']} questions; "
        f"family recall {evaluation['family_recall']}; "
        f"supported-passage recall {evaluation['supported_passage_recall']}; "
        f"evidence gain {gain['estimate']} (95% {gain['low']} to {gain['high']}); "
        f"span reconstruction {report.body['span_reconstruction']['rate']}"
    )
    for reason in report.reasons:
        print(f"- {reason}")
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
