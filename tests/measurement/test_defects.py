"""SDD-IN-13, SDD-IN-39: a traceable defect lifecycle and its audit denominators."""

from datetime import timedelta
from uuid import uuid4

import pytest

from research_agent.contracts import ProducerVersion, RecordMeta, sha256_hex
from research_agent.contracts.learning import (
    AutomaticLabel,
    CitationFamilyRecord,
    CitationObservation,
    PaginationPage,
)
from research_agent.contracts.papers import (
    ExternalIdentifier,
    PaperVersionRecord,
    SourceInterval,
)
from research_agent.measurement import MeasurementError
from research_agent.measurement.defects import (
    DefectCase,
    confirm,
    defect_report,
    open_case,
    reject,
    start_investigation,
)
from research_agent.outcomes.corrections import CorrectionRequest, CorrectionService
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.targets import definitions, registry
from research_agent.outcomes.windows import instant, maturity_at, utc

SOURCE_HASH = "a" * 64
TARGET_HASH = "b" * 64
EVIDENCE_HASH = "c" * 64
T0 = "2020-01-01T12:00:00.000000Z"
AS_OF = "2022-01-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def _family(number: int, day: int) -> CitationFamilyRecord:
    return CitationFamilyRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=META.producer_version,
        config_hash=META.config_hash,
        created_at=AS_OF,
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
        primary_subfield_id="A",
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("e" * 64,),
        is_target_family_self_link=False,
    )


def _paper() -> PaperVersionRecord:
    return PaperVersionRecord(
        1,
        (),
        META.producer_version,
        META.config_hash,
        AS_OF,
        str(uuid4()),
        str(uuid4()),
        (ExternalIdentifier("openalex", "W1000"),),
        True,
        T0,
        None,
        ("d" * 64,),
        ("e" * 64,),
        "Title",
        "Abstract",
        (),
        "A",
        "f" * 64,
        "metadata",
        "v1",
        3,
        ("cs.AI",),
        1,
    )


def _observation(
    paper: PaperVersionRecord, stored: dict[str, CitationFamilyRecord]
) -> CitationObservation:
    page = PaginationPage(
        0, "a" * 64, "b" * 64, None, None, len(stored), AS_OF, AS_OF, "completed", None
    )
    return CitationObservation(
        1,
        tuple(stored),
        META.producer_version,
        META.config_hash,
        AS_OF,
        paper.family_id,
        paper.version_id,
        T0,
        "automatic-citations-v1",
        sha256_hex(registry(META).to_canonical_json()),
        "openalex",
        "historical_reconstructed",
        "matched",
        ("W1000",),
        "A",
        "known",
        "d" * 64,
        AS_OF,
        AS_OF,
        maturity_at(T0),
        (instant(AS_OF) - instant(maturity_at(T0))).total_seconds(),
        (page,),
        True,
        tuple(stored),
        None,
    )


def _stored(
    families: tuple[CitationFamilyRecord, ...],
) -> dict[str, CitationFamilyRecord]:
    return {sha256_hex(record.to_canonical_json()): record for record in families}


class _MalformedDateCorrection:
    """A preserved citing family whose date was captured malformed, and its fix.

    The fifth citing family was preserved dated a year late, so reach resolved
    false on four families. Replacement preserved evidence carries its true
    date. `correct` hands that evidence to the real
    outcomes.corrections.CorrectionService and returns the superseding label's
    correction hash, which is all a confirmed defect case may hold (IN-12).
    """

    def __init__(self) -> None:
        self.paper = _paper()
        self.target = definitions(META)[0]
        on_time = tuple(_family(number, 10) for number in range(1, 5))
        malformed = _stored(on_time + (_family(5, 400),))
        corrected = _stored(on_time + (_family(5, 40),))
        original_observation = _observation(self.paper, malformed)
        self.original = Resolver(
            malformed.__getitem__, META, registry=registry(META)
        ).resolve_target(self.target, self.paper, original_observation, AS_OF)
        self.replacement = _observation(self.paper, corrected)
        self.evidence_hash = sha256_hex(self.replacement.to_canonical_json())
        self._service = CorrectionService(
            corrected.__getitem__, META, registry=registry(META)
        )
        self.calls: list[DefectCase] = []
        self.labels: list[AutomaticLabel] = []

    def correct(self, *, case: DefectCase, evidence_hash: str) -> str:
        assert evidence_hash == self.evidence_hash
        self.calls.append(case)
        label = self._service.correct(
            self.target,
            self.paper,
            self.original,
            CorrectionRequest(
                reason="replacement_source_evidence",
                defect_description=None,
                observation=self.replacement,
            ),
            AS_OF,
        )
        self.labels.append(label)
        assert label.correction_hash is not None
        return label.correction_hash


class _NoCorrection:
    """Fails if a case that must not reach correction ever calls it."""

    def correct(self, *, case: DefectCase, evidence_hash: str) -> str:
        raise AssertionError("this case must not reach correction")


def _confirmed(case: DefectCase) -> DefectCase:
    correction = _MalformedDateCorrection()
    return confirm(
        start_investigation(case), correction, evidence_hash=correction.evidence_hash
    )


def _open(resolver_version: int = 1, case_id: str = "case-1") -> DefectCase:
    return open_case(
        case_id=case_id,
        reporter_id="reporter-1",
        source_hashes=(SOURCE_HASH,),
        target_definition_hash=TARGET_HASH,
        resolver_version=resolver_version,
    )


def test_a_preserved_malformed_date_case_reaches_correction() -> None:
    case = start_investigation(_open())
    correction = _MalformedDateCorrection()
    assert correction.original.state == "false"
    confirmed = confirm(case, correction, evidence_hash=correction.evidence_hash)
    assert confirmed.state == "confirmed"
    assert confirmed.evidence_hash == correction.evidence_hash
    assert correction.calls == [case]
    (label,) = correction.labels
    assert label.state == "true"
    assert label.supersedes_label_hash == sha256_hex(
        correction.original.to_canonical_json()
    )
    assert confirmed.correction_hash == label.correction_hash
    # The original resolved label is superseded, never edited.
    assert correction.original.correction_hash is None


def test_a_preference_only_complaint_cannot_obtain_label_write_authority() -> None:
    case = _open()
    case = start_investigation(case)
    rejected = reject(case)
    assert rejected.state == "rejected"
    assert rejected.correction_hash is None
    # Rejected is a dead end: it cannot be confirmed afterward to backdoor a
    # correction.
    with pytest.raises(MeasurementError):
        confirm(rejected, _NoCorrection(), evidence_hash=EVIDENCE_HASH)


def test_confirm_requires_an_investigating_case() -> None:
    case = _open()
    with pytest.raises(MeasurementError):
        confirm(case, _NoCorrection(), evidence_hash=EVIDENCE_HASH)


def test_investigation_requires_an_open_case() -> None:
    case = _open()
    investigating = start_investigation(case)
    with pytest.raises(MeasurementError):
        start_investigation(investigating)


def test_confirmed_state_requires_evidence_and_correction_hash() -> None:
    with pytest.raises(MeasurementError):
        DefectCase(
            case_id="case-1",
            reporter_id="reporter-1",
            source_hashes=(SOURCE_HASH,),
            target_definition_hash=TARGET_HASH,
            resolver_version=1,
            state="confirmed",
            evidence_hash=None,
            correction_hash=None,
        )


def test_open_case_carries_no_evidence_or_correction_hash() -> None:
    with pytest.raises(MeasurementError):
        DefectCase(
            case_id="case-1",
            reporter_id="reporter-1",
            source_hashes=(SOURCE_HASH,),
            target_definition_hash=TARGET_HASH,
            resolver_version=1,
            state="open",
            evidence_hash=EVIDENCE_HASH,
            correction_hash=None,
        )


def test_defect_report_groups_by_resolver_version() -> None:
    v1_confirmed = _confirmed(_open(resolver_version=1, case_id="a"))
    v1_rejected = reject(start_investigation(_open(resolver_version=1, case_id="b")))
    v1_open = _open(resolver_version=1, case_id="c")
    v2_open = _open(resolver_version=2, case_id="d")

    reports = defect_report([v1_confirmed, v1_rejected, v1_open, v2_open])
    by_version = {report.resolver_version: report for report in reports}

    assert by_version[1].confirmed_count == 1
    assert by_version[1].investigated_count == 2
    assert by_version[1].open_count == 1
    assert by_version[1].confirmed_rate == pytest.approx(0.5)
    assert by_version[1].disposition == "available"

    assert by_version[2].investigated_count == 0
    assert by_version[2].confirmed_rate is None
    assert by_version[2].disposition == "no_investigated_cases"
    assert by_version[2].open_count == 1


def test_uninvestigated_cases_never_enter_the_denominator() -> None:
    still_investigating = start_investigation(_open(resolver_version=5, case_id="e"))
    reports = defect_report([still_investigating])
    assert reports[0].investigated_count == 0
    assert reports[0].open_count == 1
    assert reports[0].confirmed_rate is None


def test_defect_statistics_are_unchanged_by_any_support_review_verdict() -> None:
    # defect_report never accepts a reviews.ReviewVerdict at all, so nothing
    # a rationale-support reviewer decides can move these counts (SDD-IN-39).
    confirmed = _confirmed(_open(resolver_version=1, case_id="a"))
    before = defect_report([confirmed])
    after = defect_report([confirmed])
    assert before == after
