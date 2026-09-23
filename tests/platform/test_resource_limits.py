import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.resources import (
    ROLE_LIMITS,
    AppliedCgroup,
    LeaseState,
    ResourcePolicy,
)


def test_only_the_models_role_declares_an_accelerator() -> None:
    for role, limit in ROLE_LIMITS.items():
        if role == "models":
            assert limit.accelerator_count > 0
        else:
            assert limit.accelerator_count == 0


def test_cgroup_settings_derives_cpu_and_memory_from_the_role_table() -> None:
    settings = ResourcePolicy().cgroup_settings("storage")
    assert settings.cpu_quota_us == 100_000
    assert settings.memory_max_bytes == 2 * 1024**3
    assert not settings.accelerator_device_mounted


def test_cgroup_settings_declares_the_accelerator_for_models_alone() -> None:
    policy = ResourcePolicy()
    assert policy.cgroup_settings("models").accelerator_device_mounted
    assert not policy.cgroup_settings("ingest").accelerator_device_mounted


def test_cgroup_settings_rejects_an_undeclared_role() -> None:
    with pytest.raises(ContractValidationError):
        ResourcePolicy().cgroup_settings("nonexistent")


def test_verify_applied_passes_when_actual_matches_declared() -> None:
    policy = ResourcePolicy()
    declared = policy.cgroup_settings("scorer")
    applied = AppliedCgroup(
        cpu_quota_us=declared.cpu_quota_us,
        period_us=declared.period_us,
        memory_max_bytes=declared.memory_max_bytes,
        accelerator_device_mounted=declared.accelerator_device_mounted,
    )
    assert policy.verify_applied("scorer", applied) == ()


def test_verify_applied_reports_a_looser_memory_limit_actually_applied() -> None:
    applied = AppliedCgroup(
        cpu_quota_us=100_000,
        period_us=100_000,
        memory_max_bytes=999,
        accelerator_device_mounted=False,
    )
    assert "memory_max" in ResourcePolicy().verify_applied("scorer", applied)


def test_can_lease_enforces_at_most_two_concurrent_workers() -> None:
    policy = ResourcePolicy()
    state = LeaseState(active_worker_ids=frozenset({"run-1"}))
    assert policy.can_lease(state, "worker")
    state = LeaseState(active_worker_ids=frozenset({"run-1", "run-2"}))
    assert not policy.can_lease(state, "worker")


def test_can_lease_enforces_at_most_one_heavy_batch() -> None:
    policy = ResourcePolicy()
    state = LeaseState()
    assert policy.can_lease(state, "batch")
    state = LeaseState(active_batch_ids=frozenset({"batch-1"}))
    assert not policy.can_lease(state, "batch")


def test_can_lease_rejects_an_unleased_role() -> None:
    with pytest.raises(ContractValidationError):
        ResourcePolicy().can_lease(LeaseState(), "app")


def test_batch_pause_and_resume_thresholds() -> None:
    policy = ResourcePolicy()
    assert policy.batch_should_pause(49.0)
    assert not policy.batch_should_pause(47.0)
    assert policy.batch_should_resume(39.0)
    assert not policy.batch_should_resume(41.0)
