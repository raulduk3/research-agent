import ast
import contextlib
import dataclasses
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import research_agent.reader.assessments as reader_assessments
from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.rubric import Rubric
from research_agent.assessments.schemas import (
    JevAttemptRecord,
    JevAvailable,
    JevUnavailable,
    fields_version,
    parse_field_answers,
    result_hash,
)
from research_agent.contracts.assessments import (
    FIELD_IDS,
    V1_FIELD_IDS,
    JEV_SOURCE_LABEL,
    JevAssessmentInput,
    JevProviderIdentity,
)
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.cards import (
    AvailabilityValue,
    CardBuildInput,
    CardOverview,
    HeadCardValue,
    JevCardAssessment,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.passages import SourceLocator
from research_agent.contracts.primitives import ContractValidationError
from research_agent.learning.features import card_metadata
from research_agent.reader.assessments import (
    UNQUALIFIED_NOTE,
    JevCardAvailable,
    JevCardSection,
    JevCardUnavailable,
    LaterAssessment,
    StaleCurrentPointer,
    assessment_section,
    publish_assessment_version,
    render_section,
    section_for_snapshot,
)
from research_agent.reader.cards import assemble_card
from research_agent.reader.rendering import render_card
from research_agent.scoring.baselines import CardFeatureRow
from research_agent.storage.errors import IntegrityFailure

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "jev"
_VERSION = "0f8fad5b-d9cb-469f-a165-70867728950e"
_EXTRACTION = "e" * 64
_SMOKE = "5" * 64
_COMMITTED = "2026-09-20T00:00:00.000000Z"
_SEAL = "2026-09-21T00:00:00.000000Z"
_RUBRIC = Rubric.launch()
_V1 = Rubric.v1()


def _identity() -> JevProviderIdentity:
    return JevProviderIdentity(
        "typesafe",
        "typesafeai/jev-latest",
        "jev-1.13.0",
        "jev-1.13.0",
        "immutable_revision",
        "c" * 64,
        "d" * 64,
    )


def _input(smoke: str | None = _SMOKE) -> JevAssessmentInput:
    return JevAssessmentInput(
        paper_version_id=_VERSION,
        extraction_hash=_EXTRACTION,
        supplied_text_hash="a" * 64,
        supplied_text_bytes=10,
        coverage="complete",
        coverage_reasons=(),
        rubric_hash=_RUBRIC.rubric_hash,
        provider_configuration_hash="d" * 64,
        smoke_report_hash=smoke,
    )


def _answers(name: str = "systemone-v2-response.json") -> dict[str, Any]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["answers"]  # type: ignore[no-any-return]


def _available(
    smoke: str | None = _SMOKE,
    computed_at: str = "2026-09-19T00:00:00.000000Z",
    rubric: Rubric = _RUBRIC,
) -> JevAvailable:
    recorded = (
        "systemone-v2-response.json" if rubric is _RUBRIC else "systemone-response.json"
    )
    return JevAvailable(
        fields=parse_field_answers(_answers(recorded), rubric.record),
        input_hash=_input(smoke).input_hash,
        rubric_hash=rubric.rubric_hash,
        provider_identity=_identity(),
        sanitized_request_hash="3" * 64,
        sanitized_response_hash="4" * 64,
        computed_at=computed_at,
        smoke_report_hash=smoke,
    )


def _committed(result: JevAvailable | JevUnavailable) -> tuple[bytes, bytes]:
    record = JevAttemptRecord(
        work_key="7" * 64,
        input=_input(
            result.smoke_report_hash if isinstance(result, JevAvailable) else _SMOKE
        ),
        rubric_version=(
            fields_version(result.fields)
            if isinstance(result, JevAvailable)
            else _RUBRIC.version
        ),
        result_artifact_hash=result_hash(result),
        request_artifact_hash="3" * 64,
        response_artifact_hash="4" * 64,
        requested_at="2026-09-18T23:59:59.000000Z",
        completed_at="2026-09-19T00:00:00.000000Z",
        attempts=1,
    )
    return record.to_canonical_json(), result.to_canonical_json()


def _section(
    result: JevAvailable | JevUnavailable,
    *,
    available_at: str = _COMMITTED,
    as_of: str = _SEAL,
    snapshot_smoke: str | None = _SMOKE,
    paper_version_id: str = _VERSION,
) -> JevCardSection:
    manifest, raw = _committed(result)
    return assessment_section(
        manifest=manifest,
        result=raw,
        available_at=available_at,
        paper_version_id=paper_version_id,
        extraction_hash=_EXTRACTION,
        as_of=as_of,
        snapshot_smoke_report_hash=snapshot_smoke,
        rubric_hash=_RUBRIC.rubric_hash,
    )


class _Pointers:
    def __init__(self) -> None:
        self.currents: dict[str, str] = {}
        self.pins: dict[tuple[str, str], str] = {}

    def current(self, paper_version_id: str) -> str | None:
        return self.currents.get(paper_version_id)

    def compare_and_swap(
        self, paper_version_id: str, expected: str | None, new: str
    ) -> bool:
        if self.currents.get(paper_version_id) != expected:
            return False
        self.currents[paper_version_id] = new
        return True

    def snapshot_pin(self, snapshot_id: str, paper_version_id: str) -> str | None:
        return self.pins.get((snapshot_id, paper_version_id))

    def seal(self, snapshot_id: str, paper_version_id: str) -> None:
        self.pins[(snapshot_id, paper_version_id)] = self.currents[paper_version_id]


def test_an_available_result_emits_eight_named_fields_in_a_separate_section() -> None:
    section = _section(_available())
    assert section.source_label == JEV_SOURCE_LABEL
    assessment = section.assessment
    assert isinstance(assessment, JevCardAvailable)
    assert tuple(item.field_id for item in assessment.fields) == FIELD_IDS
    assert assessment.qualification_report_hash == _SMOKE
    assert assessment.rubric_version == _RUBRIC.version
    body = section.to_dict()["assessment"]
    assert "sanitized_request_hash" not in body and "billing_state" not in body
    for derived in ("score", "rank", "quality", "aggregate"):
        assert not any(derived in key for key in body)


def test_the_rendered_section_names_its_source_and_is_marked_unqualified() -> None:
    text = render_section(_section(_available()))
    assert JEV_SOURCE_LABEL in text and UNQUALIFIED_NOTE in text
    assert f"Rubric: {_RUBRIC.version}" in text
    unavailable = render_section(
        JevCardSection(JevCardUnavailable("timeout_ambiguous", "2" * 64, None))
    )
    assert "unavailable (timeout_ambiguous)" in unavailable
    assert UNQUALIFIED_NOTE in unavailable


_HEX64 = re.compile(r"[0-9a-f]{64}")
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def test_a_v2_section_renders_each_value_with_only_what_makes_it_readable() -> None:
    text = render_section(_section(_available()))
    lines = text.splitlines()
    assert (
        "primary_contribution: method_system [method_system=0.720, "
        "dataset_resource=0.050, benchmark_evaluation_method=0.060, "
        "theoretical_result=0.020, empirical_analysis_replication=0.080, "
        "synthesis_survey=0.010, mixed_other=0.050, "
        "insufficient_information=0.010] confidence 0.810"
    ) in lines
    assert (
        'evaluation_rigor: 2.84 of 0-4, most likely 3 "Baselines and an ablation '
        'isolating a component or design choice are reported." '
        "[0=0.010, 1=0.040, 2=0.200, 3=0.600, 4=0.150] confidence 0.640"
    ) in lines
    assert (
        'claims_supported_by_evidence: 0.780 that "The headline claims are '
        'supported by the evidence the paper reports."'
    ) in lines
    assert 'open_problems_stated: 1.000 that "The paper names questions' in text
    # Hashes, instants, identity kinds and report ids stay on the record.
    assert not _HEX64.search(text)
    assert not _INSTANT.search(text)
    assert "immutable_revision" not in text and "Smoke report" not in text


def test_a_stored_v1_section_still_loads_and_renders_under_v1() -> None:
    stored = _section(_available(rubric=_V1)).to_canonical_json()
    section = JevCardSection.from_json(stored)
    assessment = section.assessment
    assert isinstance(assessment, JevCardAvailable)
    assert assessment.rubric_version == _V1.version
    assert tuple(item.field_id for item in assessment.fields) == V1_FIELD_IDS
    text = render_section(section)
    assert f"Rubric: {_V1.version}" in text
    assert "limitations_disclosure: not_reported [" in text
    assert not _HEX64.search(text)
    body = json.loads(stored)
    body["assessment"]["rubric_version"] = _RUBRIC.version
    with pytest.raises(ContractValidationError):
        JevCardSection.from_json(canonical_json(body))


def test_an_unavailable_result_keeps_its_reason_and_no_numbers() -> None:
    failed = JevUnavailable(
        reason="timeout_ambiguous",
        input_hash=_input().input_hash,
        rubric_hash=_RUBRIC.rubric_hash,
        provider_identity=None,
        sanitized_request_hash="3" * 64,
        sanitized_response_hash=None,
        billing_state="uncertain",
        recorded_at="2026-09-19T00:00:30.000000Z",
    )
    section = _section(failed)
    assert isinstance(section.assessment, JevCardUnavailable)
    assert section.assessment.reason == "timeout_ambiguous"
    assert section.assessment.assessment_id == result_hash(failed)


def test_no_committed_assessment_is_an_explicit_unavailable_state() -> None:
    section = assessment_section(
        manifest=None,
        result=None,
        available_at=None,
        paper_version_id=_VERSION,
        extraction_hash=_EXTRACTION,
        as_of=_SEAL,
        snapshot_smoke_report_hash=_SMOKE,
        rubric_hash=_RUBRIC.rubric_hash,
    )
    assert isinstance(section.assessment, JevCardUnavailable)
    assert section.assessment.reason == "missing_input"


def test_only_a_result_under_the_snapshot_pinned_smoke_report_enters_the_card() -> None:
    engineering = _section(_available(smoke=None), snapshot_smoke=_SMOKE)
    assert isinstance(engineering.assessment, JevCardUnavailable)
    assert engineering.assessment.reason == "smoke_test_required"
    unpinned = _section(_available(), snapshot_smoke=None)
    assert isinstance(unpinned.assessment, JevCardUnavailable)
    assert unpinned.assessment.reason == "smoke_test_required"
    other = _section(_available(), snapshot_smoke="6" * 64)
    assert isinstance(other.assessment, JevCardUnavailable)


def test_a_result_committed_after_the_cutoff_cannot_attach_to_the_snapshot() -> None:
    with pytest.raises(LaterAssessment):
        _section(_available(), available_at="2026-09-22T00:00:00.000000Z")


def test_a_result_for_another_paper_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        _section(_available(), paper_version_id=str(uuid4()))


def _card(jev: JevCardAssessment) -> Any:
    heads = tuple(
        HeadCardValue(
            target_id,
            "b" * 64,
            "Will it?",
            None,
            "unavailable",
            "missing_source",
            None,
            None,
            None,
            None,
            "unknown_t0",
            None,
        )
        for target_id in TARGET_IDS
    )
    return assemble_card(
        CardBuildInput(
            paper_family_id="1b4e28ba-2fa1-4d2b-883f-0016d3cca427",
            paper_version_id=_VERSION,
            as_of=_SEAL,
            corpus_arrival_at=_COMMITTED,
            overview=CardOverview("complete", "A title", "An abstract.", ()),
            overview_available=True,
            first_public_at=_COMMITTED,
            original_source=SourceLocator("a" * 64, "latex", None, None, None, None),
            passage_coverage="complete",
            passage_count=3,
            extraction_hash=_EXTRACTION,
            representation_hash=None,
            head_feature_eligible=False,
            head_feature_unavailable_reason="missing_source",
            head_predictions=heads,
            neighbors=(),
            neighbor_arrivals=(),
            neighbor_embedding_distance=AvailabilityValue.unavailable("no_neighbors"),
            outcome_labels=(),
            graph_incoming_family_ids=None,
            graph_outgoing_family_ids=None,
            graph_parsed_reference_count=0,
            graph_matched_reference_ids=(),
            graph_reference_vector_count=0,
            graph_missing_reference_vector_count=0,
            graph_reference_centroid_distance=AvailabilityValue.unavailable(
                "missing_vector"
            ),
            graph_manifest_hash=None,
            author_ids=(),
            author_captures=(),
            jev=jev,
            card_token_count=42,
            author_count=3,
            categories=("cs.AI",),
            version_count=1,
            title_tokens=2,
            abstract_tokens=5,
            code_link=False,
        )
    )


def test_changing_only_assessment_fields_leaves_downstream_inputs_unchanged() -> None:
    first = _available()
    answers = _answers()
    for field_id in FIELD_IDS:
        answer = answers[field_id]
        if answer["type"] == "choice":
            answer["choice"] = list(answer["probabilities"])[-1]
            answer["confidence"] = 0.05
        elif answer["type"] == "score":
            answer["score"] = 0
            answer["confidence"] = 0.05
        else:
            answer["noul"] = 0.5
    second = replace(first, fields=parse_field_answers(answers, _RUBRIC.record))
    sections = [_section(first), _section(second)]
    assert sections[0].section_hash != sections[1].section_hash
    cards = [_card(section) for section in sections]
    assert cards[0].jev != cards[1].jev
    assert card_metadata(cards[0]) == card_metadata(cards[1])
    assert cards[0].head_predictions == cards[1].head_predictions
    assert cards[0].neighbor_outcomes == cards[1].neighbor_outcomes
    baseline_fields = {item.name for item in dataclasses.fields(CardFeatureRow)}
    assert not any("jev" in name or "assessment" in name for name in baseline_fields)
    unavailable = _card(
        JevCardAssessment(JevCardUnavailable("provider_failure", "2" * 64, None))
    )
    assert card_metadata(unavailable) == card_metadata(cards[0])


def test_recomputation_leaves_an_earlier_snapshot_on_its_original_bytes(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    pointers = _Pointers()
    original = _section(_available())
    first = publish_assessment_version(
        artifacts,
        pointers,
        paper_version_id=_VERSION,
        section=original,
        expected_current=None,
    )
    pointers.seal("snapshot-a", _VERSION)

    recomputed = _section(
        _available(computed_at="2026-09-20T00:00:00.000000Z"),
        available_at="2026-09-21T12:00:00.000000Z",
        as_of="2026-09-22T00:00:00.000000Z",
    )
    with pytest.raises(StaleCurrentPointer):
        publish_assessment_version(
            artifacts,
            pointers,
            paper_version_id=_VERSION,
            section=recomputed,
            expected_current=None,
        )
    second = publish_assessment_version(
        artifacts,
        pointers,
        paper_version_id=_VERSION,
        section=recomputed,
        expected_current=first,
    )
    pointers.seal("snapshot-b", _VERSION)
    assert first != second and pointers.current(_VERSION) == second

    earlier = section_for_snapshot(
        artifacts, pointers, snapshot_id="snapshot-a", paper_version_id=_VERSION
    )
    later = section_for_snapshot(
        artifacts, pointers, snapshot_id="snapshot-b", paper_version_id=_VERSION
    )
    assert earlier.to_canonical_json() == original.to_canonical_json()
    assert later.to_canonical_json() == recomputed.to_canonical_json()
    with pytest.raises(LookupError):
        section_for_snapshot(
            artifacts, pointers, snapshot_id="snapshot-c", paper_version_id=_VERSION
        )


def test_a_referenced_section_blob_cannot_be_overwritten(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    pointers = _Pointers()
    original = _section(_available())
    pinned = publish_assessment_version(
        artifacts,
        pointers,
        paper_version_id=_VERSION,
        section=original,
        expected_current=None,
    )
    pointers.seal("snapshot-a", _VERSION)
    other = _section(_available(computed_at="2026-09-19T01:00:00.000000Z"))
    forged = other.to_canonical_json()
    with contextlib.suppress(IntegrityFailure):
        artifacts.commit(
            (forged,),
            expected_hash=pinned,
            expected_length=len(forged),
            maximum_length=len(forged),
        )
    replayed = section_for_snapshot(
        artifacts, pointers, snapshot_id="snapshot-a", paper_version_id=_VERSION
    )
    assert replayed.to_canonical_json() == original.to_canonical_json()


def test_a_recorded_section_replays_to_identical_bytes() -> None:
    section = _section(_available())
    raw = section.to_canonical_json()
    assert JevCardSection.from_json(raw).to_canonical_json() == raw


def test_the_rendered_card_shows_all_eight_fields_and_the_rubric_version() -> None:
    text = render_card(_card(_section(_available())))
    for field_id in FIELD_IDS:
        assert f"{field_id}: " in text
    assert _RUBRIC.version in text


def test_the_reader_has_no_provider_route() -> None:
    source = Path(reader_assessments.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("research_agent.ingest", "urllib", "http", "socket", "httpx")
    assert not [name for name in imported if name.startswith(forbidden)]
