import pytest

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
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


def _ready_profile(**overrides: object) -> LaunchProfile:
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
        "source": SourceGroup(licensed_source_ids=frozenset({"arxiv", "openalex"})),
        "budget": BudgetGroup(
            paid_execution_enabled=True,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=True,
        ),
        "evaluation": EvaluationGroup(replay_integrity_verified=True),
        "privacy": PrivacyGroup(retention_years=2),
        "recovery": RecoveryGroup(backup_verified=True),
        "disabled_capabilities": DisabledCapabilities(
            capability_ids=frozenset({"encoder_fine_tuning"})
        ),
    }
    values.update(overrides)
    return LaunchProfile(**values)  # type: ignore[arg-type]


def test_collection_is_ready_with_licensed_sources_alone() -> None:
    profile = _ready_profile(
        evaluation=EvaluationGroup(replay_integrity_verified=False),
        model=ModelGroup(
            agent_model_id="glm-5.3-flash",
            agent_provider="z.ai",
            embedding_model_revision="d556a88e332558790b210f7bdbe87da2fa94a8d8",
            agent_qualification_passed=False,
        ),
        budget=BudgetGroup(
            paid_execution_enabled=False,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=False,
        ),
        recovery=RecoveryGroup(backup_verified=False),
    )
    assert profile.readiness("collection") == ()


def test_collection_is_refused_without_a_licensed_source() -> None:
    profile = _ready_profile(source=SourceGroup(licensed_source_ids=frozenset()))
    assert "licensed_source_access" in profile.readiness("collection")


def test_engineering_additionally_requires_replay_integrity() -> None:
    profile = _ready_profile(
        evaluation=EvaluationGroup(replay_integrity_verified=False)
    )
    assert profile.readiness("collection") == ()
    assert "replay_integrity" in profile.readiness("engineering")


def test_study_is_refused_for_an_unfunded_endpoint_even_when_qualified() -> None:
    profile = _ready_profile(
        budget=BudgetGroup(
            paid_execution_enabled=True,
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=False,
        )
    )
    assert profile.readiness("engineering") == ()
    unmet = profile.readiness("study")
    assert "funded_inference" in unmet


def test_study_is_ready_when_every_prerequisite_is_met() -> None:
    profile = _ready_profile()
    assert profile.readiness("study") == ()


def test_readiness_rejects_an_unknown_mode() -> None:
    with pytest.raises(ContractValidationError):
        _ready_profile().readiness("production")


def test_from_json_rejects_an_unknown_override_key() -> None:
    payload = _ready_profile().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ContractValidationError):
        LaunchProfile.from_json(canonical_json(payload))


@pytest.mark.parametrize(
    "missing_group",
    [
        "runtime",
        "storage",
        "model",
        "source",
        "budget",
        "evaluation",
        "privacy",
        "recovery",
        "disabled_capabilities",
    ],
)
def test_from_json_rejects_a_profile_missing_any_required_group(
    missing_group: str,
) -> None:
    payload = _ready_profile().to_dict()
    del payload[missing_group]
    with pytest.raises(ContractValidationError):
        LaunchProfile.from_json(canonical_json(payload))


def test_from_json_round_trips_a_complete_profile() -> None:
    profile = _ready_profile()
    restored = LaunchProfile.from_json(canonical_json(profile.to_dict()))
    assert restored.compute_hash() == profile.compute_hash()
