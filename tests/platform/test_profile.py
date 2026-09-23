"""The launch profile's per-run `run` section and its USD caps (#285)."""

from __future__ import annotations

import pytest

from research_agent.agents import budgets
from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.runs import ALLOWED_TOOLS, BUDGET_FIELDS
from research_agent.platform.profile import (
    BudgetGroup,
    DisabledCapabilities,
    EvaluationGroup,
    LaunchProfile,
    ModelGroup,
    PrivacyGroup,
    RecoveryGroup,
    RunGroup,
    RuntimeGroup,
    SourceGroup,
    StorageGroup,
)


def _profile(run: RunGroup | None = None) -> LaunchProfile:
    return LaunchProfile(
        profile_version="launch-v2",
        runtime=RuntimeGroup(python_version="3.12.12", uv_version="0.8.22"),
        storage=StorageGroup(
            postgres_version="17",
            backup_endpoint_bound=True,
            anchor_endpoint_bound=True,
        ),
        model=ModelGroup(
            agent_model_id="glm-5.3-flash",
            agent_provider="z.ai",
            embedding_model_revision="d556a88e332558790b210f7bdbe87da2fa94a8d8",
            agent_qualification_passed=True,
        ),
        source=SourceGroup(licensed_source_ids=frozenset({"arxiv"})),
        budget=BudgetGroup(
            paid_execution_enabled=True,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=True,
        ),
        evaluation=EvaluationGroup(replay_integrity_verified=True),
        privacy=PrivacyGroup(retention_years=2),
        recovery=RecoveryGroup(backup_verified=True),
        disabled_capabilities=DisabledCapabilities(capability_ids=frozenset()),
        **({} if run is None else {"run": run}),
    )


def test_run_section_launch_values_are_the_loops_enforced_ceilings() -> None:
    run = _profile().run
    assert run.model_calls == budgets.MODEL_CALLS_LIMIT
    assert run.tool_calls == budgets.TOOL_CALLS_LIMIT
    assert run.deep_reads == budgets.DEEP_READS_LIMIT
    assert run.images == budgets.IMAGES_LIMIT
    assert run.context_tokens == budgets.CONTEXT_TOKENS_LIMIT
    assert run.generation_tokens == budgets.GENERATION_TOKENS_LIMIT
    assert run.max_tokens_per_run == budgets.MAX_TOKENS_PER_RUN_LIMIT
    assert run.wall_time_seconds == budgets.WALL_TIME_SECONDS_LIMIT
    assert run.retries == budgets.RETRIES_LIMIT
    assert run.timeout_seconds == 120
    assert run.spend_micros == 10_000
    assert run.allowed_tools == ALLOWED_TOOLS


def test_run_budgets_are_exactly_the_run_record_fields() -> None:
    assert set(RunGroup().budgets()) == BUDGET_FIELDS


def test_run_section_round_trips_and_is_part_of_the_profile_hash() -> None:
    profile = _profile(RunGroup(tool_calls=10, allowed_tools=frozenset({"submit"})))
    restored = LaunchProfile.from_json(canonical_json(profile.to_dict()))
    assert restored.run == profile.run
    assert restored.compute_hash() == profile.compute_hash()
    assert profile.compute_hash() != _profile().compute_hash()


def test_from_json_rejects_a_profile_without_its_run_section() -> None:
    payload = _profile().to_dict()
    del payload["run"]
    with pytest.raises(ContractValidationError):
        LaunchProfile.from_json(canonical_json(payload))


@pytest.mark.parametrize("missing", ["spend_micros", "model_calls", "allowed_tools"])
def test_from_json_rejects_a_run_section_missing_a_field(missing: str) -> None:
    payload = _profile().to_dict()
    run = dict(payload["run"])  # type: ignore[call-overload]
    del run[missing]
    payload["run"] = run
    with pytest.raises(ContractValidationError):
        LaunchProfile.from_json(canonical_json(payload))


@pytest.mark.parametrize(
    "tools",
    [["submit", "submit"], ["submit", "browse"], []],
)
def test_from_json_rejects_inadmissible_allowed_tools(tools: list[str]) -> None:
    payload = _profile().to_dict()
    payload["run"] = {**payload["run"], "allowed_tools": tools}  # type: ignore[dict-item]
    with pytest.raises(ContractValidationError):
        LaunchProfile.from_json(canonical_json(payload))


@pytest.mark.parametrize(
    "overrides",
    [{"wall_time_seconds": 0}, {"spend_micros": -1}, {"model_calls": 0}],
)
def test_run_section_refuses_values_the_run_contract_refuses(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ContractValidationError):
        RunGroup(**overrides)  # type: ignore[arg-type]


def test_budget_caps_read_as_whole_microdollars() -> None:
    budget = BudgetGroup(
        paid_execution_enabled=True,
        daily_cap_usd="8",
        monthly_cap_usd="200.5",
        funded=True,
    )
    assert budget.daily_cap_micros == 8_000_000
    assert budget.monthly_cap_micros == 200_500_000
    with pytest.raises(ContractValidationError):
        _ = BudgetGroup(
            paid_execution_enabled=True,
            daily_cap_usd="0.0000001",
            monthly_cap_usd="200",
            funded=True,
        ).daily_cap_micros
