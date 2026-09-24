from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.disabled import reject_schema_evolution
from tests.evolution.genome_fixtures import PROFILE_HASH


def test_reject_schema_evolution_always_returns_disabled_by_profile() -> None:
    result = reject_schema_evolution(profile_hash=PROFILE_HASH)
    assert result.disposition == "disabled_by_profile"
    assert result.profile_hash == PROFILE_HASH


def test_reject_schema_evolution_rejects_a_missing_profile() -> None:
    with pytest.raises(ContractValidationError):
        reject_schema_evolution(profile_hash=None)


def test_reject_schema_evolution_rejects_an_empty_profile() -> None:
    with pytest.raises(ContractValidationError):
        reject_schema_evolution(profile_hash="")
