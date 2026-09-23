"""Engineering, per-head, three-head and prospective readiness, apart (SDD FT-24).

TDD-1.1.19: an empty registry still permits source capture and readable
paper cards; two qualified heads expose two probabilities and refuse a
complete three-head readiness claim; a failed head never blocks
engineering readiness.
"""

from __future__ import annotations

from hashlib import sha256

from research_agent.contracts import ProducerVersion
from research_agent.contracts.learning import TARGET_IDS
from research_agent.learning.readiness import ReadinessError, forecast_readiness
from research_agent.models.registry import (
    BundleManifest,
    BundleTargetEntry,
    ServingHandle,
)

TARGET_REGISTRY_HASH = sha256(b"readiness-registry").hexdigest()
REPRESENTATION_HASH = sha256(b"readiness-representation").hexdigest()
PRODUCER_VERSION = ProducerVersion(sha256(b"producer").hexdigest(), "a" * 40, 1)


def _handle(statuses: tuple[str, str, str]) -> ServingHandle:
    entries = tuple(
        BundleTargetEntry(
            target_id,
            sha256(target_id.encode()).hexdigest(),
            status,
            None
            if status == "unavailable"
            else sha256(f"{target_id}-artifact".encode()).hexdigest(),
            "never_fit" if status == "unavailable" else None,
        )
        for target_id, status in zip(TARGET_IDS, statuses, strict=True)
    )
    manifest = BundleManifest(
        TARGET_REGISTRY_HASH,
        REPRESENTATION_HASH,
        entries,
        PRODUCER_VERSION,
        "2026-01-01T00:00:00.000000Z",
    )
    return ServingHandle(1, sha256(manifest.to_canonical_json()).hexdigest(), manifest)


def test_empty_registry_still_permits_source_capture_and_paper_cards() -> None:
    report = forecast_readiness(
        engineering_ready=True,
        paper_cards_readable=True,
        jev_smoke_tested=True,
        handle=None,
        mature_sealed_predictions=False,
    )
    assert report.engineering_ready is True
    assert report.paper_cards_readable is True
    assert all(not target.qualified for target in report.targets)
    assert report.all_three_qualified is False


def test_two_qualified_heads_refuse_complete_three_head_readiness() -> None:
    handle = _handle(("qualified", "qualified", "unavailable"))
    report = forecast_readiness(
        engineering_ready=True,
        paper_cards_readable=True,
        jev_smoke_tested=True,
        handle=handle,
        mature_sealed_predictions=False,
    )
    assert report.qualified_target_ids() == (TARGET_IDS[0], TARGET_IDS[1])
    assert report.all_three_qualified is False
    assert report.mature_prospective_evaluation is False


def test_a_failed_head_never_blocks_engineering_readiness() -> None:
    handle = _handle(("unavailable", "qualified", "qualified"))
    report = forecast_readiness(
        engineering_ready=True,
        paper_cards_readable=True,
        jev_smoke_tested=False,
        handle=handle,
        mature_sealed_predictions=False,
    )
    assert report.engineering_ready is True
    unavailable = next(t for t in report.targets if not t.qualified)
    assert unavailable.reason == "never_fit"


def test_all_three_qualified_with_mature_predictions_yields_prospective_readiness() -> (
    None
):
    handle = _handle(("qualified", "qualified", "qualified"))
    report = forecast_readiness(
        engineering_ready=True,
        paper_cards_readable=True,
        jev_smoke_tested=True,
        handle=handle,
        mature_sealed_predictions=True,
    )
    assert report.all_three_qualified is True
    assert report.mature_prospective_evaluation is True


def test_all_three_qualified_without_mature_predictions_denies_prospective_benefit() -> (
    None
):
    handle = _handle(("qualified", "qualified", "qualified"))
    report = forecast_readiness(
        engineering_ready=True,
        paper_cards_readable=True,
        jev_smoke_tested=True,
        handle=handle,
        mature_sealed_predictions=False,
    )
    assert report.all_three_qualified is True
    assert report.mature_prospective_evaluation is False


def test_a_readiness_report_cannot_carry_prospective_benefit_without_all_three() -> (
    None
):
    import pytest

    from research_agent.learning.readiness import ForecastReadiness, TargetReadiness

    targets = (
        TargetReadiness(TARGET_IDS[0], True, None),
        TargetReadiness(TARGET_IDS[1], True, None),
        TargetReadiness(TARGET_IDS[2], False, "never_fit"),
    )
    with pytest.raises(ReadinessError):
        ForecastReadiness(True, True, True, targets, False, True)
