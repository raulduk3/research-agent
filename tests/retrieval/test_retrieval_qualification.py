"""The shared retrieval qualification's draw, scoring and index run (Appendix A, RD-28)."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.corpus import CorpusRelease
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.models.batch import PaperText
from research_agent.models.embedding import overview_text
from research_agent.retrieval.passages import (
    IndexEntry,
    PublishedPassage,
    SearchCandidate,
    SearchResult,
    build_passages,
    publish_index,
    search_passages,
)
from research_agent.retrieval.qualification import (
    Evidence,
    EvidenceSpan,
    Judgment,
    QualificationError,
    QualificationSample,
    Question,
    QuestionOutcome,
    SampledPaper,
    _Locator,
    _mode,
    _search,
    load_pool,
    parse_questions,
    qualification_weeks,
    run_retrieval,
    sample_from_release,
    score_qualification,
    score_question,
    select_qualification_sample,
)


def _uuid(n: int) -> str:
    return str(UUID(int=n, version=4))


class _WhitespaceTokenizer:
    """One content token per whitespace-delimited word."""

    def encode_offsets(self, text: str) -> Sequence[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        index = 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break
            start = index
            while index < len(text) and not text[index].isspace():
                index += 1
            offsets.append((start, index))
        return offsets


# --- the draw ---------------------------------------------------------------


def _weeks(count: int) -> list[str]:
    return [f"2026-W{week:02d}" for week in range(30, 30 - count, -1)]


def _candidates(per_week: dict[str, list[str]]) -> list[SampledPaper]:
    items: list[SampledPaper] = []
    n = 1
    for week, categories in per_week.items():
        for category in categories:
            items.append(
                SampledPaper(_uuid(n), _uuid(10_000 + n), category, week, "evaluation")
            )
            n += 1
    return items


def test_draw_takes_five_per_week_with_proportional_quotas() -> None:
    weeks = _weeks(20)
    # cs.LG holds three times cs.AI's families; quant-ph and q-bio are rare.
    per_week = {
        week: ["cs.LG"] * 9 + ["cs.AI"] * 3 + (["quant-ph", "q-bio"] if i < 2 else [])
        for i, week in enumerate(weeks)
    }
    sample = select_qualification_sample(_candidates(per_week), weeks)

    assert len(sample.papers) == 100
    assert sample.shortfall == ()
    assert Counter(p.publication_week for p in sample.papers) == {w: 5 for w in weeks}
    quotas = dict(sample.quotas)
    assert sum(quotas.values()) == 100
    assert quotas["quant-ph"] >= 1 and quotas["q-bio"] >= 1
    assert quotas["cs.LG"] > 2 * quotas["cs.AI"]
    assert Counter(p.primary_category for p in sample.papers) == quotas
    assert len({p.family_id for p in sample.papers}) == 100


def test_each_weeks_first_pick_is_development_and_the_rest_are_locked() -> None:
    weeks = _weeks(20)
    per_week = {week: ["cs.LG"] * 6 + ["cs.AI"] * 6 for week in weeks}
    per_week[weeks[0]] += ["quant-ph", "q-bio"]
    sample = select_qualification_sample(_candidates(per_week), weeks)

    development = [p for p in sample.papers if p.split == "development"]
    assert len(development) == 20
    assert {p.publication_week for p in development} == set(weeks)
    assert sum(p.split == "evaluation" for p in sample.papers) == 80
    for week in weeks:
        in_week = [p for p in sample.papers if p.publication_week == week]
        assert in_week[0].split == "development"


def test_a_short_week_records_its_shortfall_and_is_never_refilled() -> None:
    weeks = _weeks(3)
    per_week = {weeks[0]: ["cs.LG"] * 8, weeks[1]: ["cs.LG"] * 2, weeks[2]: []}
    per_week[weeks[0]] += ["cs.AI", "quant-ph", "q-bio"]
    sample = select_qualification_sample(_candidates(per_week), weeks)

    assert dict(sample.shortfall) == {weeks[1]: 3, weeks[2]: 5}
    assert Counter(p.publication_week for p in sample.papers) == {
        weeks[0]: 5,
        weeks[1]: 2,
    }


def test_a_category_without_papers_keeps_its_quota_as_a_shortfall() -> None:
    weeks = _weeks(20)
    per_week = {week: ["cs.LG"] * 6 + ["cs.AI"] * 6 for week in weeks}
    sample = select_qualification_sample(_candidates(per_week), weeks)

    assert dict(sample.quotas)["quant-ph"] == 1
    assert dict(sample.quotas)["q-bio"] == 1
    assert len(sample.papers) == 98
    assert sum(n for _, n in sample.shortfall) == 2


def test_draw_does_not_depend_on_candidate_order() -> None:
    weeks = _weeks(4)
    items = _candidates({week: ["cs.LG"] * 7 + ["cs.AI"] * 4 for week in weeks})
    shuffled = list(items)
    random.Random(7).shuffle(shuffled)

    first = select_qualification_sample(items, weeks)
    assert select_qualification_sample(shuffled, weeks) == first
    assert select_qualification_sample(items, weeks, seed=1) != first


def test_the_window_ends_at_the_latest_complete_week_and_keeps_empty_weeks() -> None:
    # 2026-W30 runs 2026-07-20 to 2026-07-26; a freeze inside it leaves W29.
    weeks = qualification_weeks(
        ["2026-W30", "2026-W29", "2026-W20"], "2026-07-22T00:00:00.000000Z", count=5
    )
    assert weeks == ("2026-W29", "2026-W28", "2026-W27", "2026-W26", "2026-W25")
    with pytest.raises(QualificationError):
        qualification_weeks(["2026-W30"], "2026-07-22T00:00:00.000000Z")


def test_the_release_supplies_original_versions_and_primary_categories() -> None:
    rows = [
        SimpleNamespace(
            paper_family_id=_uuid(n),
            original_version_id=_uuid(500 + n),
            publication_week="2026-W10",
            categories=(category, "cs.AI"),
        )
        for n, category in enumerate(["cs.LG", "cs.LG", "quant-ph", "q-bio"], 1)
    ]
    rows.append(
        SimpleNamespace(
            paper_family_id=_uuid(9),
            original_version_id=_uuid(509),
            publication_week=None,
            categories=("cs.AI",),
        )
    )
    release = SimpleNamespace(
        rows=rows, selection_frozen_at="2026-03-20T00:00:00.000000Z", selection_seed=3
    )
    sample = sample_from_release(cast(CorpusRelease, release))

    assert sample.weeks[0] == "2026-W10"
    assert {p.version_id for p in sample.papers} <= {_uuid(500 + n) for n in range(5)}
    assert {p.primary_category for p in sample.papers} == {"cs.LG", "quant-ph", "q-bio"}


# --- evidence and questions ---------------------------------------------------


def _evidence(first: bool, second: bool, adjudicated: bool | None = None) -> Evidence:
    return Evidence(
        (Judgment("j1", first), Judgment("j2", second)),
        None if adjudicated is None else Judgment("j3", adjudicated),
    )


def test_evidence_is_verified_by_agreement_or_a_third_judge() -> None:
    assert _evidence(True, True).verdict is True
    assert _evidence(False, False).verdict is False
    assert _evidence(True, False).verdict is None
    assert _evidence(True, False, adjudicated=False).verdict is False
    with pytest.raises(QualificationError):
        Evidence((Judgment("j1", True), Judgment("j1", True)))
    with pytest.raises(QualificationError):
        Evidence((Judgment("j1", True), Judgment("j2", False)), Judgment("j2", True))


def _question_json(**overrides: Any) -> dict[str, Any]:
    judgments = [{"judge": "j1", "supports": True}, {"judge": "j2", "supports": True}]
    value: dict[str, Any] = {
        "question_id": "q1",
        "paper_family_id": _uuid(1),
        "text": "What does the method bound?",
        "overview_evidence": {"judgments": judgments},
        "spans": [
            {
                "char_start": 0,
                "char_end_exclusive": 5,
                "evidence": {"judgments": judgments, "adjudication": None},
            }
        ],
    }
    value.update(overrides)
    return value


def test_question_file_refuses_unknown_fields_and_repeated_ids() -> None:
    (question,) = parse_questions(
        json.dumps({"questions": [_question_json()]}).encode()
    )
    assert question.supporting_spans[0].char_end_exclusive == 5

    extra = _question_json(answer="leaked")
    with pytest.raises(QualificationError):
        parse_questions(json.dumps({"questions": [extra]}).encode())
    with pytest.raises(QualificationError):
        parse_questions(
            json.dumps({"questions": [_question_json(), _question_json()]}).encode()
        )
    with pytest.raises(QualificationError):
        parse_questions(json.dumps({"questions": [_question_json(spans=[])]}).encode())


# --- one question's score ---------------------------------------------------


def _result(family: int, start: int, end: int, text_length: int) -> SearchResult:
    candidate = SearchCandidate(
        paper_family_id=_uuid(family),
        paper_version_id=_uuid(500 + family),
        section_order=0,
        section_path=("Body",),
        char_start=start,
        char_end_exclusive=end,
        text="x" * text_length,
        text_hash="a" * 64,
        source_locators=(),
        vector=(1.0,),
    )
    return SearchResult(candidate, 0.5)


def _question(
    family: int | str = 1,
    spans: tuple[tuple[int, int], ...] = ((100, 120),),
    overview: Evidence | None = None,
    question_id: str = "q1",
) -> Question:
    return Question(
        question_id,
        _uuid(family) if isinstance(family, int) else family,
        "question",
        overview or _evidence(False, False),
        tuple(EvidenceSpan(a, b, _evidence(True, True)) for a, b in spans),
    )


def test_a_passage_supports_only_when_it_contains_a_verified_span() -> None:
    question = Question(
        "q1",
        _uuid(1),
        "question",
        _evidence(False, False),
        (
            EvidenceSpan(100, 120, _evidence(True, True)),
            EvidenceSpan(300, 320, _evidence(True, False)),
        ),
    )
    overview = [_result(1, 0, 10, 400)]
    # Overlapping the verified span is not containing it.
    assert not score_question(
        question, overview, [_result(1, 110, 200, 90)]
    ).supported_passage
    # Containing only the unresolved span is not support.
    assert not score_question(
        question, overview, [_result(1, 290, 330, 40)]
    ).supported_passage
    # Another paper's passage at the same offsets is not the cited paper's.
    assert not score_question(
        question, overview, [_result(2, 90, 130, 40)]
    ).supported_passage
    assert score_question(
        question, overview, [_result(1, 90, 130, 40)]
    ).supported_passage


def test_the_passage_arm_reads_only_what_the_overview_arm_read() -> None:
    question = _question()
    overview = [_result(1, 0, 10, 100), _result(2, 0, 10, 100)]
    far = [_result(3, 0, 50, 150), _result(1, 90, 130, 60)]
    outcome = score_question(question, overview, far)

    assert outcome.reading_budget == 200
    assert outcome.supported_passage is True
    assert outcome.budget_supported is False  # 150 + 60 exceeds 200
    near = [_result(3, 0, 50, 140), _result(1, 90, 130, 60)]
    assert score_question(question, overview, near).budget_supported is True


def test_overview_support_needs_the_cited_family_and_is_conservative_in_dispute() -> (
    None
):
    supported = _question(overview=_evidence(True, True))
    disputed = _question(overview=_evidence(True, False))
    rejected = _question(overview=_evidence(False, False))
    hit = [_result(1, 0, 10, 100)]
    miss = [_result(2, 0, 10, 100)]

    assert score_question(supported, hit, []).overview_supported is True
    assert score_question(disputed, hit, []).overview_supported is True
    assert score_question(rejected, hit, []).overview_supported is False
    assert score_question(supported, miss, []).overview_supported is False


# --- the verdict ------------------------------------------------------------


def _sample(weeks: int = 4, per_week: int = 5) -> QualificationSample:
    papers = []
    n = 1
    for week in _weeks(weeks):
        for pick in range(per_week):
            papers.append(
                SampledPaper(
                    _uuid(n),
                    _uuid(500 + n),
                    "cs.LG",
                    week,
                    "development" if pick == 0 else "evaluation",
                )
            )
            n += 1
    return QualificationSample(
        tuple(_weeks(weeks)), (("cs.LG", n - 1),), tuple(papers), ()
    )


def _outcome(
    question_id: str,
    *,
    hit: bool = True,
    supported: bool = True,
    overview: bool = False,
    budget: bool = True,
) -> QuestionOutcome:
    return QuestionOutcome(question_id, hit, hit, supported, overview, budget, 100, 1)


def _all_questions(sample: QualificationSample) -> list[Question]:
    return [
        _question(paper.family_id, question_id=f"{paper.family_id}-{k}")
        for paper in sample.papers
        for k in range(5)
    ]


def _identity() -> dict[str, Any]:
    return {"release_hash": "a" * 64}


def _score(
    sample: QualificationSample,
    questions: list[Question],
    outcomes: dict[str, QuestionOutcome],
    reconstructed: int = 10,
) -> Any:
    return score_qualification(
        sample,
        questions,
        outcomes,
        reconstructed_passages=reconstructed,
        indexed_passages=10,
        identity=_identity(),
    )


def test_a_qualification_meeting_every_measure_passes() -> None:
    sample = _sample()
    questions = _all_questions(sample)
    outcomes = {q.question_id: _outcome(q.question_id) for q in questions}
    report = _score(sample, questions, outcomes)

    assert report.verdict == "pass", report.reasons
    assert report.body["evaluation"]["questions"] == 80
    assert report.body["development"]["questions"] == 20
    assert report.body["evaluation"]["evidence_gain"]["estimate"] == 1.0


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"hit": False}, "top-five family recall"),
        ({"supported": False}, "supported-passage recall"),
        ({"overview": True}, "supported-evidence gain"),
    ],
)
def test_each_measure_below_its_threshold_fails(
    change: dict[str, bool], reason: str
) -> None:
    sample = _sample()
    questions = _all_questions(sample)
    evaluation = {p.family_id for p in sample.papers if p.split == "evaluation"}
    outcomes = {
        q.question_id: _outcome(
            q.question_id, **(change if q.paper_family_id in evaluation else {})
        )
        for q in questions
    }
    report = _score(sample, questions, outcomes)

    assert report.verdict == "fail"
    assert any(reason in item for item in report.reasons)


def test_development_questions_never_move_the_verdict() -> None:
    sample = _sample()
    questions = _all_questions(sample)
    development = {p.family_id for p in sample.papers if p.split == "development"}
    outcomes = {
        q.question_id: _outcome(
            q.question_id,
            **(
                {"hit": False, "supported": False, "budget": False}
                if q.paper_family_id in development
                else {}
            ),
        )
        for q in questions
    }
    report = _score(sample, questions, outcomes)

    assert report.verdict == "pass"
    assert report.body["development"]["family_recall"] == 0.0


def test_one_unreconstructed_passage_fails_the_qualification() -> None:
    sample = _sample()
    questions = _all_questions(sample)
    outcomes = {q.question_id: _outcome(q.question_id) for q in questions}
    report = _score(sample, questions, outcomes, reconstructed=9)

    assert report.verdict == "fail"
    assert report.body["span_reconstruction"]["rate"] == 0.9


def test_an_unauthored_question_leaves_the_qualification_incomplete() -> None:
    sample = _sample()
    questions = _all_questions(sample)[:-1]
    outcomes = {q.question_id: _outcome(q.question_id) for q in questions}
    report = _score(sample, questions, outcomes)

    assert report.verdict == "incomplete"
    assert report.body["questions_missing"] == 1


def test_a_question_outside_the_sample_is_refused() -> None:
    sample = _sample()
    stray = _question(family=9_999, question_id="stray")
    with pytest.raises(QualificationError):
        _score(sample, [stray], {"stray": _outcome("stray")})


# --- the ranked prefix ------------------------------------------------------


def test_prefix_search_equals_search_over_the_whole_pool() -> None:
    rng = random.Random(11)
    locators: list[_Locator] = []
    rows: list[list[float]] = []
    for family in range(1, 41):
        for order in range(rng.randint(1, 6)):
            # Half the passages overlap their predecessor, so some are skipped.
            start = order * 50 - (25 if order % 2 else 0)
            start = max(start, 0)
            locators.append(
                _Locator(
                    _uuid(family),
                    _uuid(500 + family),
                    0,
                    ("Body",),
                    start,
                    start + 60,
                    "a" * 64,
                    (),
                )
            )
            rows.append([rng.gauss(0, 1) for _ in range(8)])
    mode = _mode(rows, locators)

    def text_of(locator: _Locator) -> str:
        return "t" * (locator.char_end_exclusive - locator.char_start)

    whole = [
        SearchCandidate(
            loc.family_id,
            loc.version_id,
            0,
            ("Body",),
            loc.char_start,
            loc.char_end_exclusive,
            text_of(loc),
            "a" * 64,
            (),
            tuple(row),
        )
        for loc, row in zip(locators, rows)
    ]
    for _ in range(25):
        query = tuple(rng.gauss(0, 1) for _ in range(8))
        expected = search_passages(
            candidates=whole, query_vector=query, paper_filter=None, limit=5
        )
        assert _search(mode, query, text_of) == expected


# --- the index run ----------------------------------------------------------


def _paper_text(version_id: str, words: int) -> PaperText:
    body = " ".join(f"w{version_id[:4]}-{i}" for i in range(words))
    locator = SourceLocator("a" * 64, "latex", None, None, None, None)
    extraction = ExtractionRecord(
        paper_version_id=version_id,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash=sha256_hex(body.encode("utf-8")),
        text_codepoints=len(body),
        blocks=(
            ExtractedBlock(
                block_id="b0",
                section_path=("Body",),
                section_order=0,
                block_order=0,
                kind="body",
                char_start=0,
                char_end_exclusive=len(body),
                included_in_passages=True,
                omission_reason=None,
                locator=locator,
            ),
        ),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=1,
        omitted_block_count=0,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    return PaperText(version_id, "Title", "Abstract", "c" * 64, body, extraction)


def _publish(
    namespace: Path,
    text_dir: Path,
    version_id: str,
    vectors: list[tuple[float, ...]],
    *,
    corrupt: int | None = None,
) -> PaperText:
    text = _paper_text(version_id, 700)
    (text_dir / f"{version_id}.json").write_bytes(text.to_canonical_json())
    records = build_passages(
        text.extraction,
        text.canonical_text,
        text.extraction_hash,
        _WhitespaceTokenizer(),
    )
    assert len(records) == len(vectors) - 1
    publish_index(
        namespace,
        IndexEntry(
            paper_version_id=version_id,
            extraction_hash=text.extraction_hash,
            chunk_policy="passages-384-64-v1",
            coverage="complete",
            coverage_reasons=(),
            overview_vector=vectors[0],
            passages=tuple(
                PublishedPassage(
                    order, "f" * 64 if order == corrupt else record.text_hash, vector
                )
                for order, (record, vector) in enumerate(zip(records, vectors[1:]))
            ),
            platform={"device": "cpu"},
            equivalence=None,
        ),
    )
    return text


def test_the_index_run_ranks_both_modes_and_counts_unreconstructed_spans(
    tmp_path: Path,
) -> None:
    namespace, text_dir = tmp_path / "ns", tmp_path / "text"
    text_dir.mkdir()
    cited, other, outside = _uuid(501), _uuid(502), _uuid(503)
    text = _publish(
        namespace, text_dir, cited, [(1.0, 0.0, 0.0), (0.1, 1.0, 0.0), (0.0, 0.0, 1.0)]
    )
    _publish(
        namespace,
        text_dir,
        other,
        [(0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.1, 0.0, 1.0)],
        corrupt=0,
    )
    _publish(
        namespace,
        text_dir,
        outside,
        [(1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
    )
    families = {cited: _uuid(1), other: _uuid(2)}
    pool = load_pool(namespace, text_dir, families, _WhitespaceTokenizer())

    assert pool.indexed_passages == 4
    assert pool.reconstructed_passages == 3
    assert {loc.version_id for loc in pool.overview.locators} == {cited, other}

    records = build_passages(
        text.extraction,
        text.canonical_text,
        text.extraction_hash,
        _WhitespaceTokenizer(),
    )
    first = records[0]
    question = _question(
        spans=((first.char_start + 10, first.char_start + 30),),
        overview=_evidence(True, True),
    )
    outcomes = run_retrieval(pool, text_dir, [question], [(0.0, 1.0, 0.0)])
    outcome = outcomes["q1"]

    # The other paper's corrupt passage would rank first; it is never served.
    assert outcome.supported_passage is True
    assert outcome.family_hit is True
    assert outcome.reading_budget == 2 * len(overview_text("Title", "Abstract"))
    assert outcome.budget_supported is False


def test_a_span_past_the_cited_text_is_refused(tmp_path: Path) -> None:
    namespace, text_dir = tmp_path / "ns", tmp_path / "text"
    text_dir.mkdir()
    version = _uuid(501)
    _publish(namespace, text_dir, version, [(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)])
    pool = load_pool(namespace, text_dir, {version: _uuid(1)}, _WhitespaceTokenizer())
    with pytest.raises(QualificationError):
        run_retrieval(pool, text_dir, [_question(spans=((0, 10**7),))], [(1.0, 0.0)])
