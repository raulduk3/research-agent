from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.snapshots.signals import (
    CapturedResponse,
    ProviderSignal,
    select_provider_signal,
)
from research_agent.storage.verification import PublicationCutoff

PROVIDER = "openalex"


def _capture(
    *,
    value: str = "42",
    observed_at: str = "2026-01-01T00:00:00.000000Z",
    published_at: str = "2026-01-02T00:00:00.000000Z",
    committed_ledger_sequence: int = 10,
) -> CapturedResponse:
    return CapturedResponse(
        provider_id=PROVIDER,
        capture_id="a" * 64,
        payload_hash="b" * 64,
        value=value,
        observed_at=observed_at,
        published_at=published_at,
        committed_ledger_sequence=committed_ledger_sequence,
    )


def test_a_response_captured_before_the_freeze_is_selected() -> None:
    cutoff = PublicationCutoff("2026-01-03T00:00:00.000000Z", 20)
    capture = _capture()
    signal = select_provider_signal((capture,), provider_id=PROVIDER, cutoff=cutoff)
    assert signal == ProviderSignal(
        PROVIDER,
        capture.capture_id,
        capture.payload_hash,
        capture.value,
        None,
        capture.observed_at,
    )


def test_a_response_captured_after_the_freeze_gives_no_value_despite_an_earlier_observed_date() -> (
    None
):
    cutoff = PublicationCutoff("2026-01-01T00:00:00.000000Z", 5)
    late_capture = _capture(
        observed_at="2025-01-01T00:00:00.000000Z",
        published_at="2026-01-05T00:00:00.000000Z",
        committed_ledger_sequence=15,
    )
    signal = select_provider_signal(
        (late_capture,), provider_id=PROVIDER, cutoff=cutoff
    )
    assert signal.value is None
    assert signal.unavailable_reason == "no_capture_before_snapshot_freeze"
    assert signal.capture_id is None


def test_replaying_a_later_snapshot_surfaces_the_newly_eligible_capture_alone() -> None:
    early_cutoff = PublicationCutoff("2026-01-01T00:00:00.000000Z", 5)
    later_cutoff = PublicationCutoff("2026-02-01T00:00:00.000000Z", 25)
    late_capture = _capture(
        value="99",
        published_at="2026-01-10T00:00:00.000000Z",
        committed_ledger_sequence=12,
    )

    before = select_provider_signal(
        (late_capture,), provider_id=PROVIDER, cutoff=early_cutoff
    )
    assert before.value is None

    after = select_provider_signal(
        (late_capture,), provider_id=PROVIDER, cutoff=later_cutoff
    )
    assert after.value == "99"
    assert after.capture_id == late_capture.capture_id


def test_the_most_recently_committed_eligible_capture_wins() -> None:
    cutoff = PublicationCutoff("2026-03-01T00:00:00.000000Z", 100)
    older = _capture(value="1", committed_ledger_sequence=3)
    newer = _capture(value="2", committed_ledger_sequence=8)
    signal = select_provider_signal((older, newer), provider_id=PROVIDER, cutoff=cutoff)
    assert signal.value == "2"


def test_selection_ignores_captures_from_another_provider() -> None:
    cutoff = PublicationCutoff("2026-03-01T00:00:00.000000Z", 100)
    other = CapturedResponse(
        provider_id="other-provider",
        capture_id="c" * 64,
        payload_hash="d" * 64,
        value="7",
        observed_at="2026-01-01T00:00:00.000000Z",
        published_at="2026-01-01T00:00:00.000000Z",
        committed_ledger_sequence=1,
    )
    signal = select_provider_signal((other,), provider_id=PROVIDER, cutoff=cutoff)
    assert signal.value is None


def test_provider_signal_rejects_an_available_value_missing_its_capture_fields() -> (
    None
):
    with pytest.raises(ContractValidationError):
        ProviderSignal(PROVIDER, None, None, "42", None, None)


def test_provider_signal_rejects_an_unavailable_value_carrying_capture_fields() -> None:
    with pytest.raises(ContractValidationError):
        ProviderSignal(PROVIDER, "a" * 64, "b" * 64, None, "some reason", None)
