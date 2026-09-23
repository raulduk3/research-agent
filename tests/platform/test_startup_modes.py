import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.platform.inventory import (
    ComponentInventory,
    ComponentRecord,
    ObservedComponent,
)
from research_agent.platform.preflight import (
    HostFloorReport,
    HostFloorRequirement,
    evaluate_floor,
    measure_host,
)
from research_agent.platform.profile import (
    BudgetGroup,
    DisabledCapabilities,
    EvaluationGroup,
    LaunchProfile,
    ModelGroup,
    PrivacyGroup,
    RecoveryGroup,
    RuntimeGroup,
    SourceGroup,
    StorageGroup,
)
from research_agent.platform.startup import WorkerSpec, launch_worker, start_mode

DIGEST = "a" * 64
PROJECT = "research-agent"
NOW = "2026-09-23T00:00:00.000000Z"
RUN_ID = "8b6a5f2e-5c1a-4b4b-9b3d-8e2f6a7c1d90"


def _profile(**overrides: object) -> LaunchProfile:
    values: dict[str, object] = {
        "profile_version": "launch-v2",
        "runtime": RuntimeGroup(python_version="3.12.12", uv_version="0.8.22"),
        "storage": StorageGroup(
            postgres_version="17",
            backup_endpoint_bound=True,
            anchor_endpoint_bound=True,
        ),
        "model": ModelGroup(
            agent_model_id="glm-5.3-flash",
            agent_provider="z.ai",
            embedding_model_revision="d556a88e332558790b210f7bdbe87da2fa94a8d8",
            agent_qualification_passed=True,
        ),
        "source": SourceGroup(licensed_source_ids=frozenset({"arxiv"})),
        "budget": BudgetGroup(
            paid_execution_enabled=True,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=True,
        ),
        "evaluation": EvaluationGroup(replay_integrity_verified=True),
        "privacy": PrivacyGroup(retention_years=2),
        "recovery": RecoveryGroup(backup_verified=True),
        "disabled_capabilities": DisabledCapabilities(capability_ids=frozenset()),
    }
    values.update(overrides)
    return LaunchProfile(**values)  # type: ignore[arg-type]


def _passing_floor() -> HostFloorReport:
    measurement = measure_host(
        now=NOW,
        cpu_count=lambda: 8,
        ram_bytes=lambda: 16_000_000_000,
        free_disk_bytes=lambda: 100_000_000_000,
        accelerator_count=lambda: 1,
    )
    requirement = HostFloorRequirement(
        min_logical_cpus=4,
        min_ram_bytes=8_000_000_000,
        min_free_disk_bytes=50_000_000_000,
        min_accelerator_count=1,
        profile_hash="0" * 64,
    )
    return evaluate_floor(measurement, requirement)


def _inventory() -> ComponentInventory:
    return ComponentInventory(
        components=(
            ComponentRecord(
                component_id="storage",
                role="storage",
                layers=frozenset({"infrastructure"}),
                image_digest=DIGEST,
                interface_ids=(),
                mode_membership=frozenset({"collection", "engineering", "study"}),
            ),
        )
    )


def test_start_mode_succeeds_when_every_gate_passes() -> None:
    outcome = start_mode(
        mode="collection",
        profile=_profile(),
        floor_report=_passing_floor(),
        inventory=_inventory(),
        observed=(ObservedComponent("storage", PROJECT),),
        compose_project=PROJECT,
    )
    assert outcome.started
    assert outcome.cycle_scheduling_enabled
    assert outcome.failed_gates == ()


def test_start_mode_reports_a_missing_component_as_a_failed_gate() -> None:
    outcome = start_mode(
        mode="collection",
        profile=_profile(),
        floor_report=_passing_floor(),
        inventory=_inventory(),
        observed=(),
        compose_project=PROJECT,
    )
    assert not outcome.started
    assert not outcome.cycle_scheduling_enabled
    assert any(gate.startswith("inventory_missing:") for gate in outcome.failed_gates)


def test_successful_collection_mode_never_implies_study_readiness() -> None:
    profile = _profile(
        budget=BudgetGroup(
            paid_execution_enabled=False,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=False,
        )
    )
    observed = (ObservedComponent("storage", PROJECT),)
    collection = start_mode(
        mode="collection",
        profile=profile,
        floor_report=_passing_floor(),
        inventory=_inventory(),
        observed=observed,
        compose_project=PROJECT,
    )
    study = start_mode(
        mode="study",
        profile=profile,
        floor_report=_passing_floor(),
        inventory=_inventory(),
        observed=observed,
        compose_project=PROJECT,
    )
    assert collection.started
    assert not study.started
    assert any(gate.startswith("profile:") for gate in study.failed_gates)


def test_start_mode_rejects_an_unknown_mode() -> None:
    with pytest.raises(ContractValidationError):
        start_mode(
            mode="production",
            profile=_profile(),
            floor_report=_passing_floor(),
            inventory=_inventory(),
            observed=(),
            compose_project=PROJECT,
        )


def test_worker_spec_rejects_a_mounted_docker_socket() -> None:
    with pytest.raises(ContractValidationError):
        WorkerSpec(
            run_id=RUN_ID,
            image_digest=DIGEST,
            orchestration_token="signed-token",
            docker_socket_mounted=True,
        )


def test_launch_worker_refuses_an_unauthenticated_request() -> None:
    spec = WorkerSpec(
        run_id=RUN_ID, image_digest=DIGEST, orchestration_token="signed-token"
    )
    with pytest.raises(ContractValidationError):
        launch_worker(spec, authenticated=False)


def test_launch_worker_admits_an_authenticated_predeclared_spec() -> None:
    spec = WorkerSpec(
        run_id=RUN_ID, image_digest=DIGEST, orchestration_token="signed-token"
    )
    assert launch_worker(spec, authenticated=True) is spec
