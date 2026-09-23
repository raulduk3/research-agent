import ast
import contextlib
import dataclasses
import json
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
    parse_field_answers,
    result_hash,
)
from research_agent.contracts.assessments import (
    FIELD_IDS,
    JEV_SOURCE_LABEL,
    JevAssessmentInput,
    JevProviderIdentity,
)
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
    card_reference,
    publish_assessment_version,
    render_section,
    section_for_snapshot,
)
from research_agent.reader.cards import assemble_card
from research_agent.scoring.baselines import CardFeatureRow
from research_agent.storage.errors import IntegrityFailure

_RECORDED = Path(__file__).parents[1] / "fixtures" / "jev" / "systemone-response.json"
_VERSION = "0f8fad5b-d9cb-469f-a165-70867728950e"
_EXTRACTION = "e" * 64
_SMOKE = "5" * 64
_COMMITTED = "2026-09-20T00:00:00.000000Z"
_SEAL = "2026-09-21T00:00:00.000000Z"
_RUBRIC = Rubric.launch()


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


def _answers() -> dict[str, Any]:
    return json.loads(_RECORDED.read_text(encoding="utf-8"))["answers"]  # type: ignore[no-any-return]


def _available(
    smoke: str | None = _SMOKE, computed_at: str = "2026-09-19T00:00:00.000000Z"
) -> JevAvailable:
    return JevAvailable(
        fields=parse_field_answers(_answers()),
        input_hash=_input(smoke).input_hash,
        rubric_hash=_RUBRIC.rubric_hash,
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
        rubric_version=_RUBRIC.version,
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
    body = section.to_dict()["assessment"]
    assert "sanitized_request_hash" not in body and "billing_state" not in body
    for derived in ("score", "rank", "quality", "aggregate"):
        assert not any(derived in key for key in body)


def test_the_rendered_section_names_its_source_and_is_marked_unqualified() -> None:
    text = render_section(_section(_available()))
    assert JEV_SOURCE_LABEL in text and UNQUALIFIED_NOTE in text
    assert "limitations_disclosure: not_reported" in text
    assert "jev-1.13.0 (immutable_revision)" in text
    unavailable = render_section(
        JevCardSection(JevCardUnavailable("timeout_ambiguous", "2" * 64, None))
    )
    assert "unavailable (timeout_ambiguous)" in unavailable
    assert UNQUALIFIED_NOTE in unavailable


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
    assert card_reference(section) == JevCardAssessment.unavailable("timeout_ambiguous")


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
        options = list(answer["probabilities"])
        answer["choice"] = options[-1]
        answer["confidence"] = 0.05
    second = replace(first, fields=parse_field_answers(answers))
    sections = [_section(first), _section(second)]
    assert sections[0].section_hash != sections[1].section_hash
    cards = [_card(card_reference(section)) for section in sections]
    assert cards[0].jev != cards[1].jev
    assert card_metadata(cards[0]) == card_metadata(cards[1])
    assert cards[0].head_predictions == cards[1].head_predictions
    assert cards[0].neighbor_outcomes == cards[1].neighbor_outcomes
    baseline_fields = {item.name for item in dataclasses.fields(CardFeatureRow)}
    assert not any("jev" in name or "assessment" in name for name in baseline_fields)
    unavailable = _card(JevCardAssessment.unavailable("provider_failure"))
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
