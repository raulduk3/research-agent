from dataclasses import replace
from uuid import uuid4

import pytest

from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.papers import (
    ExternalIdentifier,
    SourceAccess,
    SourceInterval,
    PaperObservation,
    PaperVersionRecord,
    normalize_identifier,
)


def test_external_identifiers_require_canonical_exact_identity() -> None:
    assert normalize_identifier("doi", "https://doi.org/10.1000/ABC") == "10.1000/abc"
    for value in (
        ExternalIdentifier("doi", "10.1000/abc"),
        ExternalIdentifier("arxiv", "2401.01234v2"),
        ExternalIdentifier("openalex", "W123"),
    ):
        assert ExternalIdentifier.from_json(value.to_canonical_json()) == value

    for scheme, value in (
        ("doi", "Title only"),
        ("arxiv", "2401.01234"),
        ("openalex", "123"),
    ):
        with pytest.raises(ContractValidationError):
            ExternalIdentifier(scheme, value)


def test_source_interval_preserves_uncertainty_as_a_half_open_range() -> None:
    interval = SourceInterval(
        "2026-01-01T00:00:00.000000Z", "2026-01-02T00:00:00.000000Z"
    )
    assert SourceInterval.from_json(interval.to_canonical_json()) == interval
    with pytest.raises(ContractValidationError):
        SourceInterval(interval.start, interval.start)


def test_source_access_separates_success_failure_and_capture_clocks() -> None:
    access = SourceAccess(
        1,
        (),
        ProducerVersion("e" * 64, "f" * 40, 1),
        "1" * 64,
        "2026-01-01T00:00:02.000000Z",
        "arxiv",
        "https://export.arxiv.org/api/query",
        "a" * 64,
        "arxiv-v1",
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01T00:00:01.000000Z",
        200,
        "b" * 64,
        "c" * 64,
        "arXiv-1.0",
        "d" * 64,
        None,
    )
    assert access.to_canonical_json()
    assert SourceAccess.from_json(access.to_canonical_json()) == access
    with pytest.raises(ContractValidationError):
        replace(access, retained_payload_hash=None)


def test_paper_version_and_observation_are_closed_and_time_safe() -> None:
    identifier = ExternalIdentifier("arxiv", "2401.01234v1")
    record = PaperVersionRecord(
        1,
        ("e" * 64,),
        ProducerVersion("f" * 64, "1" * 40, 1),
        "2" * 64,
        "2026-01-02T00:00:00.000000Z",
        str(uuid4()),
        str(uuid4()),
        (identifier,),
        True,
        "2026-01-01T00:00:00.000000Z",
        None,
        ("a" * 64,),
        ("b" * 64,),
        "Title",
        "Abstract",
        ("author",),
        "cs.AI",
        "c" * 64,
        "latex",
        "v1",
        3,
        ("cs.AI",),
        1,
    )
    assert PaperVersionRecord.from_json(record.to_canonical_json()) == record
    observation = PaperObservation(
        identifier,
        "v1",
        (identifier,),
        "d" * 64,
        "2026-01-01T00:00:00.000000Z",
        None,
        "2026-01-02T00:00:00.000000Z",
        "2026-01-02T00:00:01.000000Z",
        "d" * 64,
        "d" * 64,
        None,
    )
    assert PaperObservation.from_json(observation.to_canonical_json()) == observation

    body = canonical_loads(record.to_canonical_json())
    body["unexpected"] = True
    with pytest.raises(ContractValidationError):
        PaperVersionRecord.from_json(canonical_json(body))
    with pytest.raises(ContractValidationError):
        PaperObservation.from_json(canonical_json({"source": {}}))


def test_source_access_rejects_non_integer_http_status_and_unknown_wire_fields() -> (
    None
):
    access = SourceAccess(
        1,
        (),
        ProducerVersion("e" * 64, "f" * 40, 1),
        "1" * 64,
        "2026-01-01T00:00:02.000000Z",
        "openalex",
        "https://api.openalex.org/works",
        "a" * 64,
        "openalex-v1",
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01T00:00:01.000000Z",
        503,
        "b" * 64,
        "c" * 64,
        None,
        "d" * 64,
        "rejected",
    )
    # Failed captures may retain licensed error-response bytes for audit/replay.
    assert SourceAccess.from_json(access.to_canonical_json()) == access
    with pytest.raises(ContractValidationError):
        replace(access, http_status=True)
    body = canonical_loads(access.to_canonical_json())
    body["unexpected"] = None
    with pytest.raises(ContractValidationError):
        SourceAccess.from_json(canonical_json(body))

    invalid = canonical_loads(access.to_canonical_json())
    invalid["source"] = []
    with pytest.raises(ContractValidationError, match="field types"):
        SourceAccess.from_json(canonical_json(invalid))
