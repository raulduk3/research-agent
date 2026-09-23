import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.health import HealthMonitor, HealthPoll, initial_health

STARTED_AT = "2026-09-23T00:00:00.000000Z"


def _poll(ready: bool, at: str) -> HealthPoll:
    return HealthPoll(ready=ready, polled_at=at)


def test_a_previously_healthy_service_fails_after_three_consecutive_misses() -> None:
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    health = monitor.apply_poll(health, _poll(True, "2026-09-23T00:00:30.000000Z"))
    assert health.state == "healthy"
    for index in range(3):
        health = monitor.apply_poll(
            health, _poll(False, f"2026-09-23T00:0{index + 1}:00.000000Z")
        )
    assert health.state == "failed"


def test_a_stalled_worker_loop_does_not_fail_before_three_misses() -> None:
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    health = monitor.apply_poll(health, _poll(True, "2026-09-23T00:00:30.000000Z"))
    health = monitor.apply_poll(health, _poll(False, "2026-09-23T00:01:00.000000Z"))
    health = monitor.apply_poll(health, _poll(False, "2026-09-23T00:01:30.000000Z"))
    assert health.state == "healthy"


def test_a_deliberately_slow_initial_load_stays_waiting_not_failed() -> None:
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    for minute in range(1, 10):
        health = monitor.apply_poll(
            health, _poll(False, f"2026-09-23T00:{minute:02d}:00.000000Z")
        )
        assert health.state == "waiting"
    within_bound = monitor.check_initial_load_bound(
        health, now="2026-09-23T00:10:00.000000Z"
    )
    assert within_bound.state == "waiting"


def test_the_initial_load_bound_fails_a_service_still_waiting_past_fifteen_minutes() -> (
    None
):
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    health = monitor.apply_poll(health, _poll(False, "2026-09-23T00:01:00.000000Z"))
    expired = monitor.check_initial_load_bound(
        health, now="2026-09-23T00:16:00.000000Z"
    )
    assert expired.state == "failed"


def test_check_initial_load_bound_leaves_a_healthy_service_untouched() -> None:
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    health = monitor.apply_poll(health, _poll(True, "2026-09-23T00:00:30.000000Z"))
    unchanged = monitor.check_initial_load_bound(
        health, now="2026-09-23T01:00:00.000000Z"
    )
    assert unchanged.state == "healthy"


def test_recovery_delays_follow_ten_thirty_ninety_seconds_then_latch_operator_repair() -> (
    None
):
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    for index in range(3):
        health = monitor.apply_poll(
            health, _poll(False, f"2026-09-23T00:0{index + 1}:00.000000Z")
        )
    health = monitor.check_initial_load_bound(health, now="2026-09-23T00:20:00.000000Z")
    health = monitor.apply_poll(health, _poll(False, "2026-09-23T00:21:00.000000Z"))
    assert health.state == "failed"

    assert monitor.next_retry_delay(health) == 10
    health = monitor.record_retry_attempt(health, now="2026-09-23T00:21:10.000000Z")
    assert monitor.next_retry_delay(health) == 30
    health = monitor.record_retry_attempt(health, now="2026-09-23T00:21:40.000000Z")
    assert monitor.next_retry_delay(health) == 90
    health = monitor.record_retry_attempt(health, now="2026-09-23T00:23:10.000000Z")

    assert health.state == "operator_repair"
    assert monitor.next_retry_delay(health) is None


def test_operator_repair_is_latched_against_a_later_healthy_poll() -> None:
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    for index in range(3):
        health = monitor.apply_poll(
            health, _poll(False, f"2026-09-23T00:0{index + 1}:00.000000Z")
        )
    health = monitor.check_initial_load_bound(health, now="2026-09-23T00:20:00.000000Z")
    health = monitor.apply_poll(health, _poll(False, "2026-09-23T00:21:00.000000Z"))
    for _ in range(3):
        health = monitor.record_retry_attempt(health, now="2026-09-23T00:22:00.000000Z")
    assert health.state == "operator_repair"
    latched = monitor.apply_poll(health, _poll(True, "2026-09-23T00:30:00.000000Z"))
    assert latched.state == "operator_repair"


def test_record_retry_attempt_requires_a_failed_service() -> None:
    monitor = HealthMonitor()
    health = initial_health("models", started_at=STARTED_AT)
    with pytest.raises(ContractValidationError):
        monitor.record_retry_attempt(health, now=STARTED_AT)
