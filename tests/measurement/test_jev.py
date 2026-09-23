"""SDD-RD-22: the Jev rubric smoke test and its activation refusals."""

import copy
import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_agent.assessments.rubric import Rubric
from research_agent.assessments.schemas import (
    JevAvailable,
    JevUnavailable,
    parse_field_answers,
)
from research_agent.contracts.assessments import (
    FIELD_CATEGORIES,
    FIELD_IDS,
    V1_FIELD_IDS,
    JevProviderIdentity,
)
from research_agent.contracts.learning import PRIMARY_CATEGORY_IDS
from research_agent.measurement import MeasurementError
from research_agent.measurement.jev import (
    NOUL_BUCKETS,
    SMOKE_VALID_FLOOR,
    OwnerReview,
    SmokeActivationRefused,
    SmokeCandidate,
    SmokeObservation,
    SmokeSample,
    check_smoke_activation,
    select_smoke_sample,
    smoke_test_rubric,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "jev"
_RECORDED = _FIXTURES / "systemone-response.json"
_RECORDED_V2 = _FIXTURES / "systemone-v2-response.json"
# The v1 path is pinned to v1 and its recorded response; v2 has its own test.
_RUBRIC = Rubric.v1().record
_RUBRIC_V2 = Rubric.launch().record
_WEEKS = tuple(f"2026-W{week:02d}" for week in range(30, 10, -1))
_REVIEW = OwnerReview("owner", "2026-09-23T12:00:00.000000Z", "e" * 64)


def _uuid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def _identity(revision: str = "jev-1.13.0") -> JevProviderIdentity:
    return JevProviderIdentity(
        "typesafe",
        "typesafeai/jev-latest",
        revision,
        revision,
        "immutable_revision",
        "c" * 64,
        "d" * 64,
    )


def _candidates(per_week: int = 8) -> list[SmokeCandidate]:
    return [
        SmokeCandidate(
            _uuid(week_index * 100 + n),
            PRIMARY_CATEGORY_IDS[(n + week_index) % 4],
            week,
        )
        for week_index, week in enumerate(_WEEKS)
        for n in range(per_week)
    ]


def _available(n: int, identity: JevProviderIdentity) -> JevAvailable:
    body: dict[str, Any] = json.loads(_RECORDED.read_text(encoding="utf-8"))
    return JevAvailable(
        fields=parse_field_answers(copy.deepcopy(body["answers"]), _RUBRIC),
        input_hash=f"{n:064x}",
        rubric_hash=_RUBRIC.rubric_hash,
        provider_identity=identity,
        sanitized_request_hash=f"{n + 1000:064x}",
        sanitized_response_hash=f"{n + 2000:064x}",
        computed_at="2026-09-23T10:00:00.000000Z",
        smoke_report_hash=None,
    )


def _unavailable(n: int, identity: JevProviderIdentity) -> JevUnavailable:
    return JevUnavailable(
        reason="provider_failure",
        input_hash=f"{n:064x}",
        rubric_hash=_RUBRIC.rubric_hash,
        provider_identity=identity,
        sanitized_request_hash=f"{n + 1000:064x}",
        sanitized_response_hash=None,
        billing_state="known_rejected",
        recorded_at="2026-09-23T10:00:00.000000Z",
    )


def _run(
    failures: int = 0, identity: JevProviderIdentity | None = None
) -> tuple[SmokeSample, list[SmokeObservation], JevProviderIdentity]:
    identity = identity or _identity()
    sample = select_smoke_sample(_candidates(), _WEEKS)
    observations = [
        SmokeObservation(
            paper.family_id,
            _unavailable(n, identity) if n < failures else _available(n, identity),
            "complete",
            latency_ms=1200 + n,
            cost_micros=50,
        )
        for n, paper in enumerate(sample.selected)
    ]
    return sample, observations, identity


def test_sample_takes_one_paper_per_week_across_all_four_categories() -> None:
    sample = select_smoke_sample(_candidates(), _WEEKS)
    assert [paper.publication_week for paper in sample.selected] == list(_WEEKS)
    assert sample.shortfall == 0
    quotas = dict(sample.quotas)
    assert sum(quotas.values()) == 20
    assert all(quota >= 1 for quota in quotas.values())
    drawn = [paper.primary_category for paper in sample.selected]
    assert {c: drawn.count(c) for c in quotas} == quotas


def test_sample_is_independent_of_candidate_order() -> None:
    pool = _candidates()
    shuffled = pool[:]
    random.Random(7).shuffle(shuffled)
    assert select_smoke_sample(pool, _WEEKS) == select_smoke_sample(shuffled, _WEEKS)


def test_a_week_without_papers_is_a_visible_shortfall_never_replaced() -> None:
    pool = [paper for paper in _candidates() if paper.publication_week != _WEEKS[3]]
    sample = select_smoke_sample(pool, _WEEKS)
    assert sample.shortfall_weeks == (_WEEKS[3],)
    assert len(sample.selected) == 19
    assert _WEEKS[3] not in {paper.publication_week for paper in sample.selected}


def test_quota_follows_family_counts_with_a_floor_of_one() -> None:
    pool = [
        SmokeCandidate(_uuid(n), "cs.AI", week) for n, week in enumerate(_WEEKS * 5)
    ] + [SmokeCandidate(_uuid(9000 + n), "q-bio", _WEEKS[n]) for n in range(2)]
    pool += [SmokeCandidate(_uuid(9500), "quant-ph", _WEEKS[0])]
    pool += [SmokeCandidate(_uuid(9600), "cs.LG", _WEEKS[1])]
    quotas = dict(select_smoke_sample(pool, _WEEKS).quotas)
    assert quotas["quant-ph"] == 1 and quotas["cs.LG"] == 1
    assert quotas["q-bio"] >= 1
    assert quotas["cs.AI"] > quotas["q-bio"]
    assert sum(quotas.values()) == 20


def test_every_field_valid_with_owner_review_passes_and_states_no_accuracy() -> None:
    sample, observations, identity = _run()
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC,
        provider_identity=identity,
        owner_review=_REVIEW,
    )
    assert report.passed
    assert [field.valid_count for field in report.fields] == [20] * len(V1_FIELD_IDS)
    assert [field.field_id for field in report.fields] == list(V1_FIELD_IDS)
    for field in report.fields:
        labels = tuple(label for label, _ in field.category_counts)
        assert labels == FIELD_CATEGORIES[field.field_id]
    assert report.latency_ms_max == 1219
    assert report.cost_micros_total == 20 * 50
    assert report.input_coverage_counts[0] == ("complete", 20)
    assert not any("accuracy" in key or "agreement" in key for key in report.to_dict())
    assert (
        check_smoke_activation(
            report, rubric_hash=_RUBRIC.rubric_hash, provider_identity=identity
        )
        == report.report_hash()
    )


def test_a_field_at_seventeen_valid_results_refuses_activation() -> None:
    sample, observations, identity = _run(failures=3)
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC,
        provider_identity=identity,
        owner_review=_REVIEW,
    )
    assert {field.valid_count for field in report.fields} == {17}
    assert not report.passed
    assert dict(report.fields[0].unavailable_reasons) == {"provider_failure": 3}
    with pytest.raises(SmokeActivationRefused) as refused:
        check_smoke_activation(
            report, rubric_hash=_RUBRIC.rubric_hash, provider_identity=identity
        )
    assert f"field_below_floor:{V1_FIELD_IDS[0]}" in refused.value.reasons


def test_the_floor_itself_passes() -> None:
    sample, observations, identity = _run(failures=20 - SMOKE_VALID_FLOOR)
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC,
        provider_identity=identity,
        owner_review=_REVIEW,
    )
    assert report.passed


def test_a_missing_owner_review_refuses_activation() -> None:
    sample, observations, identity = _run()
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC,
        provider_identity=identity,
        owner_review=None,
    )
    assert report.fields_passed and not report.passed
    with pytest.raises(SmokeActivationRefused) as refused:
        check_smoke_activation(
            report, rubric_hash=_RUBRIC.rubric_hash, provider_identity=identity
        )
    assert refused.value.reasons == ("owner_review_missing",)


def test_a_different_provider_identity_or_rubric_refuses_activation() -> None:
    sample, observations, identity = _run()
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC,
        provider_identity=identity,
        owner_review=_REVIEW,
    )
    with pytest.raises(SmokeActivationRefused) as refused:
        check_smoke_activation(
            report,
            rubric_hash=_RUBRIC.rubric_hash,
            provider_identity=_identity("jev-1.14.0"),
        )
    assert refused.value.reasons == ("identity_changed",)
    with pytest.raises(SmokeActivationRefused) as changed:
        check_smoke_activation(report, rubric_hash="f" * 64, provider_identity=identity)
    assert changed.value.reasons == ("rubric_changed",)
    with pytest.raises(SmokeActivationRefused) as absent:
        check_smoke_activation(
            None, rubric_hash=_RUBRIC.rubric_hash, provider_identity=identity
        )
    assert absent.value.reasons == ("smoke_test_missing",)


def test_a_shortfall_sample_cannot_reach_the_floor_by_padding() -> None:
    pool = [
        paper for paper in _candidates() if paper.publication_week not in _WEEKS[:3]
    ]
    sample = select_smoke_sample(pool, _WEEKS)
    identity = _identity()
    observations = [
        SmokeObservation(paper.family_id, _available(n, identity), "complete", 100, 10)
        for n, paper in enumerate(sample.selected)
    ]
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC,
        provider_identity=identity,
        owner_review=_REVIEW,
    )
    assert report.sample_size == 17
    assert report.shortfall_weeks == _WEEKS[:3]
    assert not report.passed


def test_observations_must_match_the_sample_and_the_run_under_test() -> None:
    sample, observations, identity = _run()
    with pytest.raises(MeasurementError):
        smoke_test_rubric(
            sample,
            observations[:-1],
            rubric=_RUBRIC,
            provider_identity=identity,
            owner_review=_REVIEW,
        )
    other = _identity("jev-9.9.9")
    foreign = replace(observations[0], result=_available(0, other))
    with pytest.raises(MeasurementError):
        smoke_test_rubric(
            sample,
            [foreign, *observations[1:]],
            rubric=_RUBRIC,
            provider_identity=identity,
            owner_review=_REVIEW,
        )


def test_a_v2_report_counts_score_points_and_noul_deciles() -> None:
    identity = _identity()
    sample = select_smoke_sample(_candidates(), _WEEKS)
    body: dict[str, Any] = json.loads(_RECORDED_V2.read_text(encoding="utf-8"))
    observations = []
    for n, paper in enumerate(sample.selected):
        answers = copy.deepcopy(body["answers"])
        answers["limitations_candor"]["score"] = n % 4
        # 0.0, 0.05, ..., 0.9, then 1.0: two papers per decile, 0.3 and 0.35
        # in [0.3,0.4), and 1.0 in the last, closed decile beside 0.9.
        answers["open_problems_stated"]["noul"] = 1.0 if n == 19 else n / 20
        observations.append(
            SmokeObservation(
                paper.family_id,
                replace(
                    _available(n, identity),
                    fields=parse_field_answers(answers, _RUBRIC_V2),
                    rubric_hash=_RUBRIC_V2.rubric_hash,
                ),
                "complete",
                100,
                10,
            )
        )
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=_RUBRIC_V2,
        provider_identity=identity,
        owner_review=_REVIEW,
    )
    assert report.passed
    fields = {field.field_id: field for field in report.fields}
    assert tuple(fields) == FIELD_IDS
    assert dict(fields["primary_contribution"].category_counts)["method_system"] == 20
    assert fields["limitations_candor"].category_counts == (
        ("0", 5),
        ("1", 5),
        ("2", 5),
        ("3", 5),
    )
    assert fields["evaluation_rigor"].category_counts == (
        ("0", 0),
        ("1", 0),
        ("2", 0),
        ("3", 20),
        ("4", 0),
    )
    assert fields["open_problems_stated"].category_counts == tuple(
        (bucket, 2) for bucket in NOUL_BUCKETS
    )
    unanimous = dict(fields["reproducible_from_materials"].category_counts)
    assert unanimous == {
        bucket: 20 if bucket == "[0.4,0.5)" else 0 for bucket in NOUL_BUCKETS
    }
