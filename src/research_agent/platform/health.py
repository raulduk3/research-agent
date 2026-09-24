"""Health state machine (SDD-PL-05).

`ServiceHealth` tracks one service's `/health/ready` polling history through
the four states PL-05 and its TDD fix: `waiting` while it has never yet
answered ready, `healthy`, `failed` after three consecutive failed polls, and
the latched `operator_repair` state once its 10/30/90-second recovery
attempts are exhausted. `HealthMonitor.apply_poll` alone never turns a
still-loading service into `failed`; only `HealthMonitor.check_initial_load_bound`,
once the 15-minute initial-load window has actually elapsed, can, which is
what lets a test distinguish a deliberately slow initial load (stays
`waiting`) from a previously healthy service whose worker loop stalls (three
misses later, `failed`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_utc_instant,
)

POLL_INTERVAL_SECONDS: int = 30
FAILURE_THRESHOLD: int = 3
INITIAL_LOAD_BOUND_SECONDS: int = 15 * 60
RETRY_DELAYS_SECONDS: tuple[int, ...] = (10, 30, 90)

STATES: frozenset[str] = frozenset({"waiting", "healthy", "failed", "operator_repair"})
# Worst first: the overall state is the most severe state of any service.
_SEVERITY: tuple[str, ...] = ("operator_repair", "failed", "waiting", "healthy")


def _parse(instant: str) -> datetime:
    return datetime.strptime(instant, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def _elapsed_seconds(start: str, end: str) -> float:
    return (_parse(end) - _parse(start)).total_seconds()


@dataclass(frozen=True, slots=True)
class HealthPoll:
    """One `/health/ready` poll result."""

    ready: bool
    polled_at: str

    def __post_init__(self) -> None:
        validate_utc_instant(self.polled_at)


@dataclass(frozen=True, slots=True)
class ServiceHealth:
    """One service's current supervised health state."""

    service_role: str
    state: str
    consecutive_failures: int
    first_seen_at: str
    last_transition_at: str
    retry_attempts: int

    def __post_init__(self) -> None:
        validate_non_empty_string(self.service_role)
        if self.state not in STATES:
            raise ContractValidationError("state must be one of STATES")
        validate_non_negative_int(self.consecutive_failures)
        validate_non_negative_int(self.retry_attempts)
        validate_utc_instant(self.first_seen_at)
        validate_utc_instant(self.last_transition_at)


def initial_health(service_role: str, *, started_at: str) -> ServiceHealth:
    """The starting `waiting` state for a service that has just been started."""

    return ServiceHealth(
        service_role=service_role,
        state="waiting",
        consecutive_failures=0,
        first_seen_at=started_at,
        last_transition_at=started_at,
        retry_attempts=0,
    )


@dataclass(frozen=True, slots=True)
class HealthMonitor:
    """The supervisor's fixed polling, failure and recovery-delay parameters."""

    poll_interval_seconds: int = POLL_INTERVAL_SECONDS
    failure_threshold: int = FAILURE_THRESHOLD
    initial_load_bound_seconds: int = INITIAL_LOAD_BOUND_SECONDS
    retry_delays_seconds: tuple[int, ...] = RETRY_DELAYS_SECONDS

    def apply_poll(self, health: ServiceHealth, poll: HealthPoll) -> ServiceHealth:
        """Apply one poll result; a latched `operator_repair` state never changes."""

        if health.state == "operator_repair":
            return health
        if poll.ready:
            return replace(
                health,
                state="healthy",
                consecutive_failures=0,
                retry_attempts=0,
                last_transition_at=poll.polled_at,
            )
        failures = health.consecutive_failures + 1
        if failures < self.failure_threshold:
            return replace(
                health, consecutive_failures=failures, last_transition_at=poll.polled_at
            )
        if health.state == "waiting":
            # A still-loading service is not marked failed by polls alone;
            # only `check_initial_load_bound` can do that, once its time
            # bound elapses.
            return replace(
                health, consecutive_failures=failures, last_transition_at=poll.polled_at
            )
        return replace(
            health,
            state="failed",
            consecutive_failures=failures,
            last_transition_at=poll.polled_at,
        )

    def check_initial_load_bound(
        self, health: ServiceHealth, *, now: str
    ) -> ServiceHealth:
        """Fail a service still `waiting` once its initial-load bound elapses."""

        if health.state != "waiting":
            return health
        if (
            _elapsed_seconds(health.first_seen_at, now)
            > self.initial_load_bound_seconds
        ):
            return replace(health, state="failed", last_transition_at=now)
        return health

    def next_retry_delay(self, health: ServiceHealth) -> int | None:
        """The delay, in seconds, before the next recovery attempt, or None if exhausted."""

        if health.state != "failed":
            return None
        if health.retry_attempts >= len(self.retry_delays_seconds):
            return None
        return self.retry_delays_seconds[health.retry_attempts]

    def record_retry_attempt(self, health: ServiceHealth, *, now: str) -> ServiceHealth:
        """Record one exhausted recovery attempt, latching `operator_repair` after the last."""

        if health.state != "failed":
            raise ContractValidationError("a retry attempt requires a failed service")
        attempts = health.retry_attempts + 1
        if attempts >= len(self.retry_delays_seconds):
            return replace(
                health,
                state="operator_repair",
                retry_attempts=attempts,
                last_transition_at=now,
            )
        return replace(health, retry_attempts=attempts, last_transition_at=now)

    def report(
        self, services: Sequence[ServiceHealth], *, checked_at: str
    ) -> dict[str, object]:
        """The owner-facing health report: `{state, checked_at, checks[...]}`.

        The overall state is the most severe state of any service; with no
        service observed yet it is `waiting`, since nothing has answered ready.
        """

        validate_utc_instant(checked_at)
        overall = "waiting"
        if services:
            present = {health.state for health in services}
            overall = next(state for state in _SEVERITY if state in present)
        return {
            "state": overall,
            "checked_at": checked_at,
            "checks": [
                {
                    "name": health.service_role,
                    "state": health.state,
                    "detail": self._detail(health),
                }
                for health in services
            ],
        }

    def _detail(self, health: ServiceHealth) -> str:
        attempts = f"{health.retry_attempts} of {len(self.retry_delays_seconds)}"
        if health.state == "healthy":
            return "ready"
        if health.state == "waiting":
            return (
                f"not yet ready since {health.first_seen_at}; "
                f"{health.consecutive_failures} failed polls"
            )
        if health.state == "failed":
            return (
                f"{health.consecutive_failures} consecutive failed polls; "
                f"recovery attempts used {attempts}"
            )
        return f"recovery attempts exhausted ({attempts}); operator repair required"
