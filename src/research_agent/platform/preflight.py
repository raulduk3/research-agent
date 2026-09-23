"""Operator preflight floor attestation (SDD-PL-10).

Before Compose starts application services, the operator CLI measures the
host's logical CPUs, physical RAM, persistent filesystem free bytes and
accelerator inventory, and compares each with the floor the active profile
states. The floor amendment before #74 has not yet fixed the measured
minima, so this module never hard-codes a number: the caller supplies the
`HostFloorRequirement` and this module only measures and compares. An
unmeasurable value is a shortfall, never a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_non_negative_int,
    validate_sha256,
    validate_utc_instant,
)


@dataclass(frozen=True, slots=True)
class HostFloorRequirement:
    """The stated minimum the active profile names; never invented here."""

    min_logical_cpus: int
    min_ram_bytes: int
    min_free_disk_bytes: int
    min_accelerator_count: int
    profile_hash: str

    def __post_init__(self) -> None:
        validate_non_negative_int(self.min_logical_cpus)
        validate_non_negative_int(self.min_ram_bytes)
        validate_non_negative_int(self.min_free_disk_bytes)
        validate_non_negative_int(self.min_accelerator_count)
        validate_sha256(self.profile_hash)


@dataclass(frozen=True, slots=True)
class HostMeasurement:
    """What the operator CLI actually measured on the host, or None if unknown."""

    logical_cpus: int | None
    ram_bytes: int | None
    free_disk_bytes: int | None
    accelerator_count: int | None
    measured_at: str

    def __post_init__(self) -> None:
        for value in (
            self.logical_cpus,
            self.ram_bytes,
            self.free_disk_bytes,
            self.accelerator_count,
        ):
            if value is not None:
                validate_non_negative_int(value)
        validate_utc_instant(self.measured_at)


@dataclass(frozen=True, slots=True)
class HostFloorReport:
    """A dated, hashed attestation of whether the host meets its stated floor."""

    measurement: HostMeasurement
    requirement: HostFloorRequirement
    shortfalls: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.shortfalls

    def to_dict(self) -> dict[str, object]:
        return {
            "measurement": {
                "logical_cpus": self.measurement.logical_cpus,
                "ram_bytes": self.measurement.ram_bytes,
                "free_disk_bytes": self.measurement.free_disk_bytes,
                "accelerator_count": self.measurement.accelerator_count,
                "measured_at": self.measurement.measured_at,
            },
            "requirement": {
                "min_logical_cpus": self.requirement.min_logical_cpus,
                "min_ram_bytes": self.requirement.min_ram_bytes,
                "min_free_disk_bytes": self.requirement.min_free_disk_bytes,
                "min_accelerator_count": self.requirement.min_accelerator_count,
                "profile_hash": self.requirement.profile_hash,
            },
            "shortfalls": list(self.shortfalls),
            "passed": self.passed,
        }

    def report_hash(self) -> str:
        return sha256_hex(canonical_json(self.to_dict()))


def measure_host(
    *,
    now: str,
    cpu_count: Callable[[], int | None],
    ram_bytes: Callable[[], int | None],
    free_disk_bytes: Callable[[], int | None],
    accelerator_count: Callable[[], int | None],
) -> HostMeasurement:
    """Measure the host through injected probes so a test never touches the real host."""

    validate_non_empty_string(now)
    return HostMeasurement(
        logical_cpus=cpu_count(),
        ram_bytes=ram_bytes(),
        free_disk_bytes=free_disk_bytes(),
        accelerator_count=accelerator_count(),
        measured_at=now,
    )


def evaluate_floor(
    measurement: HostMeasurement, requirement: HostFloorRequirement
) -> HostFloorReport:
    """Compare each measured dimension with its stated minimum; unknown is a shortfall."""

    shortfalls: list[str] = []
    for label, measured, minimum in (
        ("logical_cpus", measurement.logical_cpus, requirement.min_logical_cpus),
        ("ram_bytes", measurement.ram_bytes, requirement.min_ram_bytes),
        (
            "free_disk_bytes",
            measurement.free_disk_bytes,
            requirement.min_free_disk_bytes,
        ),
        (
            "accelerator_count",
            measurement.accelerator_count,
            requirement.min_accelerator_count,
        ),
    ):
        if measured is None:
            shortfalls.append(f"{label}: unmeasured")
        elif measured < minimum:
            shortfalls.append(f"{label}: measured {measured}, required {minimum}")
    return HostFloorReport(measurement, requirement, tuple(shortfalls))
