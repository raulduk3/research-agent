import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.preflight import (
    HostFloorRequirement,
    evaluate_floor,
    measure_host,
)

PROFILE_HASH = "0" * 64
NOW = "2026-09-22T00:00:00.000000Z"


def _requirement(**overrides: int) -> HostFloorRequirement:
    values = {
        "min_logical_cpus": 4,
        "min_ram_bytes": 8_000_000_000,
        "min_free_disk_bytes": 50_000_000_000,
        "min_accelerator_count": 1,
        "profile_hash": PROFILE_HASH,
    }
    values.update(overrides)
    return HostFloorRequirement(**values)


def test_evaluate_floor_passes_when_every_dimension_meets_the_minimum() -> None:
    measurement = measure_host(
        now=NOW,
        cpu_count=lambda: 8,
        ram_bytes=lambda: 16_000_000_000,
        free_disk_bytes=lambda: 100_000_000_000,
        accelerator_count=lambda: 1,
    )
    report = evaluate_floor(measurement, _requirement())
    assert report.passed
    assert report.shortfalls == ()


def test_evaluate_floor_reports_the_exact_shortfall_when_one_minimum_is_raised() -> (
    None
):
    measurement = measure_host(
        now=NOW,
        cpu_count=lambda: 8,
        ram_bytes=lambda: 16_000_000_000,
        free_disk_bytes=lambda: 100_000_000_000,
        accelerator_count=lambda: 1,
    )
    report = evaluate_floor(measurement, _requirement(min_logical_cpus=64))
    assert not report.passed
    assert any(item.startswith("logical_cpus:") for item in report.shortfalls)


def test_evaluate_floor_treats_an_unmeasured_value_as_a_shortfall_not_a_pass() -> None:
    measurement = measure_host(
        now=NOW,
        cpu_count=lambda: 8,
        ram_bytes=lambda: 16_000_000_000,
        free_disk_bytes=lambda: None,
        accelerator_count=lambda: 1,
    )
    report = evaluate_floor(measurement, _requirement())
    assert not report.passed
    assert "free_disk_bytes: unmeasured" in report.shortfalls


def test_report_hash_is_stable_for_identical_reports() -> None:
    measurement = measure_host(
        now=NOW,
        cpu_count=lambda: 8,
        ram_bytes=lambda: 16_000_000_000,
        free_disk_bytes=lambda: 100_000_000_000,
        accelerator_count=lambda: 1,
    )
    first = evaluate_floor(measurement, _requirement())
    second = evaluate_floor(measurement, _requirement())
    assert first.report_hash() == second.report_hash()


def test_host_floor_requirement_rejects_a_non_hash_profile_hash() -> None:
    with pytest.raises(ContractValidationError):
        _requirement(profile_hash="not-a-hash")
